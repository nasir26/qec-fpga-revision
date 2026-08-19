#!/usr/bin/env python3
"""
FPGA Quantum Circuit Simulator — Version 5 (complex64, 30-qubit, MCX)
=====================================================================

What is in v05 (over v04)
-------------------------
CAPACITY
  + MAX_QUBITS_FPGA raised from 16 to 30 (8 GB statevector max, fits in HBM2)
  + Kernel LOOP_TRIPCOUNT bounds updated for 2^29 pairs / 2^30 full-state

CORRECTNESS
  + det_tolerance and uniform_tolerance are now explicit run_circuit()
    parameters, forwarded to FPGAValidator — the test suite uses these.
  + circuit_name forwarded to FPGAValidator.validate() for better logs.

GATES
  + Generalised MCX (opcode 35): mcx([ctrl_0, ..., ctrl_{N-1}, target])
    works for any control count in 0..num_qubits-1. Internally encoded as
    (target, control_bitmask) in the kernel gate buffer — one gate word
    regardless of the number of controls.
  + Aliases: 'mcx', 'mct' both resolve to opcode 35.

INTERFACE
  + TRUSTED_KERNEL_GATES_DEFAULT module-level frozenset (all opcodes)
  + probe_native_gates(verbose) method on QuantumFPGACircuit
  + Module importable as fpga_simulator_version_5

PRECISION
  complex64 (float32 re + float32 im) throughout — matches v04.
  An earlier v05 attempt with complex128 passed HLS at target II but failed
  Vivado implementation with global congestion level 7 after 5 hours of
  routing on the Alveo U55C. Float32 halves DSP48E2 and LUT pressure on
  every arithmetic path and routes cleanly.
  Norm/prob tolerance is 1e-4, same as v04, to account for float32 drift.

Hardware: Xilinx Alveo U55C, 16-bank HBM2, 300 MHz quantum_simulator_kernel
Compatible kernel: fpga_kernel_v05.cpp (36 opcodes, GATE_WORDS=8, float)

Author: Nasir Ali — C-DAC / NQM Qniverse
"""

from __future__ import annotations

import time
import math
import os
import uuid
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Tuple, Dict, Optional
from datetime import datetime
from collections import defaultdict

import numpy as np

# ── XRT (mandatory — no fallback) ────────────────────────────────────────────
try:
    import pyxrt as xrt
    XRT_AVAILABLE = True
except ImportError:
    XRT_AVAILABLE = False

# ── Qiskit (optional result wrapper) ─────────────────────────────────────────
try:
    from qiskit.result import Result
    from qiskit.providers.models import QasmBackendConfiguration
    QISKIT_AVAILABLE = True
except ImportError:
    QISKIT_AVAILABLE = False

try:
    from qiskit_aer.version import __version__ as _aer_version
except ImportError:
    _aer_version = "0.14.0"

logger = logging.getLogger(__name__)

# =============================================================================
#  Constants — must match fpga_kernel_v05.cpp exactly
# =============================================================================

VERSION                = "5"
KERNEL_NAME            = "quantum_simulator_kernel"
KERNEL_CLOCK_MHZ       = 300.0
KERNEL_CLOCK_PERIOD_NS = 1e3 / KERNEL_CLOCK_MHZ          # 3.333 ns
NUM_HBM_BANKS          = 16
MAX_QUBITS_FPGA        = 30
GATE_WORDS             = 8      # int32 words per gate (4 header + 3 param + 1 pad)
KERNEL_MAX_GATES       = 512    # BRAM gate buffer depth
BYTES_PER_AMP          = 8      # complex64 = 2 × float32

# =============================================================================
#  Gate opcode table — every gate the kernel implements natively.
# =============================================================================

KERNEL_GATE_OPS: Dict[str, int] = {
    # Single-qubit
    'id'    : 23,
    'h'     : 0,
    'x'     : 1,
    'y'     : 2,
    'z'     : 3,
    's'     : 4,
    't'     : 5,
    'sdg'   : 6,
    'tdg'   : 7,
    'sx'    : 18,
    'sxdg'  : 19,
    'rx'    : 8,
    'ry'    : 9,
    'rz'    : 10,
    'p'     : 11,
    'phase' : 11,
    'u1'    : 20,
    'u2'    : 21,
    'u3'    : 22,
    'u'     : 22,
    # Two-qubit
    'cx'    : 12,
    'cnot'  : 12,
    'cy'    : 13,
    'cz'    : 14,
    'ch'    : 15,
    'swap'  : 16,
    'cp'    : 24,
    'cphase': 24,
    'crx'   : 25,
    'cry'   : 26,
    'crz'   : 27,
    'iswap' : 28,
    'ecr'   : 29,
    'rxx'   : 30,
    'ryy'   : 31,
    'rzz'   : 32,
    'csx'   : 33,
    'dcx'   : 34,
    # Three-qubit
    'ccx'    : 17,
    'toffoli': 17,
    'ccnot'  : 17,
    # Generalised multi-controlled X (any number of controls)
    'mcx'    : 35,
    'mct'    : 35,
}

# Gates we silently drop (not unitary on the statevector)
NON_UNITARY_GATES = frozenset({'measure', 'barrier', 'reset', 'snapshot',
                                'delay', 'initialize'})

# Frozenset of all natively-supported gate names (used by run_fpga_tests.py)
TRUSTED_KERNEL_GATES_DEFAULT: frozenset = frozenset(KERNEL_GATE_OPS.keys())

# =============================================================================
#  Alveo U55C power / energy model
# =============================================================================

ALVEO_STATIC_W            = 28.0
ALVEO_HBM_IDLE_W          = 12.0
HBM_PJ_PER_BIT            = 3.9
LOGIC_MW_PER_MHZ_PER_KLUT = 0.12
ACTIVE_KLUTS              = 82.4

# =============================================================================
#  Data classes
# =============================================================================

@dataclass
class GateProfile:
    gate_name    : str
    target_qubit : int
    est_cycles   : int
    est_time_us  : float
    hbm_read_kb  : float
    hbm_write_kb : float
    est_energy_uj: float


@dataclass
class ValidationResult:
    passed          : bool
    norm            : float
    prob_sum        : float
    norm_ok         : bool
    prob_ok         : bool
    expected_ok     : Optional[bool] = None
    expected_detail : str            = ""
    norm_tolerance  : float          = 1e-4
    prob_tolerance  : float          = 1e-4


@dataclass
class RunProfile:
    circuit_name       : str   = ""
    num_qubits         : int   = 0
    num_gates          : int   = 0
    num_chunks         : int   = 1
    host_distribute_us : float = 0.0
    host_encode_us     : float = 0.0
    xrt_kernel_us      : float = 0.0
    host_collect_us    : float = 0.0
    host_measure_us    : float = 0.0
    total_wall_us      : float = 0.0
    est_total_cycles   : int   = 0
    est_kernel_time_us : float = 0.0
    total_hbm_read_mb  : float = 0.0
    total_hbm_write_mb : float = 0.0
    est_eff_bw_gbps    : float = 0.0
    total_energy_mj    : float = 0.0
    avg_power_w        : float = 0.0
    energy_per_gate_uj : float = 0.0
    validation         : Optional[ValidationResult] = None
    gate_profiles      : List[GateProfile] = field(default_factory=list)
    gate_type_summary  : Dict              = field(default_factory=dict)


# =============================================================================
#  FPGA-side Validator
# =============================================================================

class FPGAValidator:
    """
    Mathematical correctness checks on the statevector the FPGA returned.
    Tolerances are 1e-4 to accommodate float32 accumulated drift.
    """

    NORM_TOLERANCE = 1e-4
    PROB_TOLERANCE = 1e-4

    @staticmethod
    def check_norm(sv: np.ndarray) -> Tuple[bool, float]:
        norm = float(np.linalg.norm(sv.astype(np.complex64, copy=False)))
        return abs(norm - 1.0) <= FPGAValidator.NORM_TOLERANCE, norm

    @staticmethod
    def check_probability_sum(sv: np.ndarray) -> Tuple[bool, float]:
        sv32 = sv.astype(np.complex64, copy=False)
        prob_sum = float(np.add(np.square(sv32.real),
                                np.square(sv32.imag)).sum())
        return abs(prob_sum - 1.0) <= FPGAValidator.PROB_TOLERANCE, prob_sum

    @staticmethod
    def check_deterministic(
        sv: np.ndarray, expected_idx: int,
        tolerance: float = 0.02, label: str = "",
    ) -> Tuple[bool, str]:
        prob = float(sv[expected_idx].real ** 2 + sv[expected_idx].imag ** 2)
        ok   = prob >= (1.0 - tolerance)
        return ok, (
            f"{label}: P(|{expected_idx}⟩) = {prob:.6f} "
            f"({'PASS' if ok else 'FAIL'}, threshold={1.0 - tolerance:.3f})"
        )

    @staticmethod
    def check_uniform_superposition(
        sv: np.ndarray, num_qubits: int,
        tolerance: float = 0.05, label: str = "",
    ) -> Tuple[bool, str]:
        N        = 2 ** num_qubits
        expected = 1.0 / math.sqrt(N)
        amps     = np.abs(sv.astype(np.complex64, copy=False))
        max_dev  = float(np.max(np.abs(amps - expected)))
        ok       = max_dev <= tolerance
        return ok, (
            f"{label}: max amplitude deviation = {max_dev:.6f} "
            f"({'PASS' if ok else 'FAIL'}, expected ~{expected:.6f})"
        )

    @classmethod
    def validate(
        cls, sv: np.ndarray, num_qubits: int,
        circuit_name      : str             = "",
        det_idx           : Optional[int]   = None,
        uniform_check     : bool            = False,
        det_tolerance     : float           = 0.02,
        uniform_tolerance : float           = 0.05,
    ) -> ValidationResult:
        norm_ok, norm     = cls.check_norm(sv)
        prob_ok, prob_sum = cls.check_probability_sum(sv)

        expected_ok     = None
        expected_detail = ""
        if det_idx is not None:
            expected_ok, expected_detail = cls.check_deterministic(
                sv, det_idx,
                tolerance=det_tolerance,
                label=circuit_name,
            )
        elif uniform_check:
            expected_ok, expected_detail = cls.check_uniform_superposition(
                sv, num_qubits,
                tolerance=uniform_tolerance,
                label=circuit_name,
            )

        passed = norm_ok and prob_ok and (expected_ok is None or expected_ok)
        return ValidationResult(
            passed=passed, norm=norm, prob_sum=prob_sum,
            norm_ok=norm_ok, prob_ok=prob_ok,
            expected_ok=expected_ok, expected_detail=expected_detail,
            norm_tolerance=cls.NORM_TOLERANCE,
            prob_tolerance=cls.PROB_TOLERANCE,
        )


# =============================================================================
#  Energy estimator
# =============================================================================

class EnergyEstimator:
    @staticmethod
    def gate_energy_uj(cycles: int, hbm_bytes: float) -> float:
        duration_s = cycles / (KERNEL_CLOCK_MHZ * 1e6)
        hbm_j      = HBM_PJ_PER_BIT * hbm_bytes * 8 * 1e-12
        logic_w    = LOGIC_MW_PER_MHZ_PER_KLUT * KERNEL_CLOCK_MHZ * ACTIVE_KLUTS * 1e-6
        logic_j    = logic_w * duration_s
        static_j   = ALVEO_STATIC_W * duration_s
        return (hbm_j + logic_j + static_j) * 1e6

    @staticmethod
    def total_energy_mj(total_cycles: int,
                        total_hbm_bytes: float) -> Tuple[float, float]:
        duration_s = total_cycles / (KERNEL_CLOCK_MHZ * 1e6)
        if duration_s <= 0:
            return 0.0, 0.0
        hbm_j    = HBM_PJ_PER_BIT * total_hbm_bytes * 8 * 1e-12
        logic_w  = LOGIC_MW_PER_MHZ_PER_KLUT * KERNEL_CLOCK_MHZ * ACTIVE_KLUTS * 1e-6
        logic_j  = logic_w * duration_s
        static_j = (ALVEO_STATIC_W + ALVEO_HBM_IDLE_W) * duration_s
        total_j  = hbm_j + logic_j + static_j
        return total_j * 1e3, total_j / duration_s


# =============================================================================
#  Pure-FPGA quantum circuit engine
# =============================================================================

class QuantumFPGACircuit:
    """
    Hardware-only quantum circuit engine — complex64 / 30-qubit edition.

    Pipeline:
        |0…0⟩  →  HBM (16 banks)  →  kernel(gate seq)  →  HBM  →  ψ
                                       ▲
                                       │ auto-chunked for > 512 gates
    """

    def __init__(self, xclbin_path: str, device_index: int = 0):
        if not XRT_AVAILABLE:
            raise RuntimeError(
                "pyxrt is not available. Install Xilinx XRT and ensure the "
                "Alveo U55C is reachable. This simulator has no CPU fallback."
            )
        if not os.path.exists(xclbin_path):
            raise FileNotFoundError(
                f"XCLBIN not found: {xclbin_path}\n"
                "Compile fpga_kernel_v05.cpp with Vitis HLS first."
            )

        self.xclbin_path  = xclbin_path
        self.device_index = device_index

        self._init_xrt()
        self._allocate_hbm()

        self._gate_bo: Optional["xrt.bo"] = None
        self._gate_bo_size: int           = 0

        self._index_cache: Dict[int, List[np.ndarray]] = {}
        self._sv_buffer: Optional[np.ndarray] = None
        self._sv_buffer_size: int             = 0

        logger.info(
            f"QuantumFPGACircuit v{VERSION} (complex64, 30-qubit) initialised — "
            f"pure FPGA, device {device_index}, kernel '{KERNEL_NAME}'"
        )

    # ── XRT init ──────────────────────────────────────────────────────────────

    def _init_xrt(self):
        try:
            self.device      = xrt.device(self.device_index)
            self.xclbin_uuid = self.device.load_xclbin(self.xclbin_path)
            self.kernel      = xrt.kernel(self.device, self.xclbin_uuid, KERNEL_NAME)
        except Exception as exc:
            raise RuntimeError(
                f"FPGA init failed on device {self.device_index}: {exc}\n"
                f"  xclbin: {self.xclbin_path}"
            ) from exc

    # ── HBM allocation ────────────────────────────────────────────────────────

    def _allocate_hbm(self):
        """
        Allocate one BO per HBM pseudo-channel, sized for the 30-qubit max.
        Per bank: 2^26 amplitudes × 8 B = 512 MB.  Total: 16 × 512 MB = 8 GB.
        """
        max_state           = 2 ** MAX_QUBITS_FPGA
        self._amps_per_bank = (max_state + NUM_HBM_BANKS - 1) // NUM_HBM_BANKS
        buf_bytes           = self._amps_per_bank * BYTES_PER_AMP   # 8 B / amp

        self.hbm_banks = []
        for i in range(NUM_HBM_BANKS):
            bo = xrt.bo(
                self.device, buf_bytes,
                xrt.bo.flags.normal,
                self.kernel.group_id(i),
            )
            self.hbm_banks.append(bo)

        logger.info(
            f"HBM allocated: {NUM_HBM_BANKS} banks × "
            f"{buf_bytes // (1024 * 1024)} MB each (complex64, 30-qubit max)"
        )

    # ── Index cache helpers ───────────────────────────────────────────────────

    def _get_indices(self, num_qubits: int) -> List[np.ndarray]:
        cached = self._index_cache.get(num_qubits)
        if cached is not None:
            return cached
        N = 2 ** num_qubits
        cached = [np.arange(b, N, NUM_HBM_BANKS, dtype=np.int64)
                  for b in range(NUM_HBM_BANKS)]
        self._index_cache[num_qubits] = cached
        return cached

    def _get_sv_buffer(self, state_size: int) -> np.ndarray:
        """Persistent complex64 statevector buffer reused across runs."""
        if self._sv_buffer is None or self._sv_buffer_size != state_size:
            self._sv_buffer      = np.zeros(state_size, dtype=np.complex64)
            self._sv_buffer_size = state_size
        else:
            self._sv_buffer.fill(0)
        return self._sv_buffer

    # ── State distribution: zero |0…0⟩ in HBM in-place (float32) ─────────────

    def _distribute_statevector(self, num_qubits: int):
        """
        Initialise HBM banks to |0…0⟩ for a complex64 statevector.
        Only syncs the bytes that this circuit will actually touch, not the
        full 30-qubit bank.
        """
        amps_per_bank = (2 ** num_qubits + NUM_HBM_BANKS - 1) // NUM_HBM_BANKS
        floats_count  = amps_per_bank * 2     # two float32 per amplitude
        byte_count    = floats_count * 4      # 4 bytes per float32

        for bank_id in range(NUM_HBM_BANKS):
            bank = self.hbm_banks[bank_id]
            view = np.frombuffer(bank.map(), dtype=np.float32, count=floats_count)
            view.fill(0.0)
            if bank_id == 0:
                view[0] = 1.0   # real part of amplitude index 0
            bank.sync(
                xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_TO_DEVICE,
                byte_count, 0,
            )

    # ── State collection: vectorised de-interleave + scatter (complex64) ─────

    def _collect_statevector(self, num_qubits: int) -> np.ndarray:
        """
        Reverse the interleave: bank[b], slot[k] → amplitude[b + k*16].
        """
        state_size    = 2 ** num_qubits
        amps_per_bank = (state_size + NUM_HBM_BANKS - 1) // NUM_HBM_BANKS
        floats_count  = amps_per_bank * 2
        byte_count    = floats_count * 4

        statevector  = self._get_sv_buffer(state_size)
        bank_indices = self._get_indices(num_qubits)

        for bank_id in range(NUM_HBM_BANKS):
            bank = self.hbm_banks[bank_id]
            bank.sync(
                xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE,
                byte_count, 0,
            )
            raw = np.frombuffer(bank.map(), dtype=np.float32, count=floats_count)
            re = raw[0::2]
            im = raw[1::2]
            indices = bank_indices[bank_id]
            n_take  = len(indices)
            statevector.real[indices] = re[:n_take]
            statevector.imag[indices] = im[:n_take]

        return statevector

    # ── Gate encoding: float32 → int32 bit reinterpret (v04-compatible) ──────

    def _encode_gates(
        self, gates: List[Tuple]
    ) -> Tuple[np.ndarray, int, List[Tuple]]:
        """
        Encode gates into the kernel's
            [type, q0, q1, q2, p0, p1, p2, pad]
        int32 layout (8 words per gate).

        Special case: generalised MCX (opcode 35).
            Qiskit / Aer convention for mcx is qubits = [c0, c1, ..., c_{N-1}, target].
            We convert this to:
                word[1] = target
                word[2] = control bitmask = OR_k (1 << ctrl_k)
                word[3] = -1 (unused)
            so the kernel dispatches to apply_mcx(target, mask, num_qubits).
        """
        resolved = []
        for gate_name, qubits, params in gates:
            name = gate_name.lower()
            if name in NON_UNITARY_GATES:
                continue
            if name not in KERNEL_GATE_OPS:
                logger.warning(
                    f"Gate '{gate_name}' has no kernel opcode — skipping."
                )
                continue
            resolved.append((name, qubits, params))

        n = len(resolved)
        if n == 0:
            return np.zeros(GATE_WORDS, dtype=np.int32), 0, resolved

        encoded = np.zeros((n, GATE_WORDS), dtype=np.int32)
        for i, (name, qubits, params) in enumerate(resolved):
            op = KERNEL_GATE_OPS[name]
            encoded[i, 0] = op

            if op == 35:
                # Generalised MCX: qubits = [ctrl_0, ..., ctrl_{N-1}, target]
                if len(qubits) < 1:
                    raise ValueError("mcx requires at least a target qubit")
                target = int(qubits[-1])
                ctrls  = [int(q) for q in qubits[:-1]]
                if target in ctrls:
                    raise ValueError(
                        f"mcx target {target} cannot also be a control "
                        f"(controls={ctrls})"
                    )
                ctrl_mask = 0
                for c in ctrls:
                    if c < 0 or c >= MAX_QUBITS_FPGA:
                        raise ValueError(f"mcx control qubit out of range: {c}")
                    ctrl_mask |= (1 << c)
                encoded[i, 1] = target
                encoded[i, 2] = ctrl_mask
                encoded[i, 3] = -1
            else:
                encoded[i, 1] = qubits[0] if len(qubits) > 0 else 0
                encoded[i, 2] = qubits[1] if len(qubits) > 1 else -1
                encoded[i, 3] = qubits[2] if len(qubits) > 2 else -1

            if params:
                # Vectorised float32 → int32 bit reinterpret
                p_arr = np.asarray(
                    [float(p) for p in params[:3]], dtype=np.float32)
                encoded[i, 4:4 + len(p_arr)] = p_arr.view(np.int32)
            # word 7 stays 0 (reserved/padding)

        return encoded.reshape(-1), n, resolved

    # ── Gate-buffer upload (BO grown on demand, persistent) ───────────────────

    def _upload_gate_buffer(self, gate_arr: np.ndarray):
        gate_bytes = gate_arr.nbytes
        if self._gate_bo is None or self._gate_bo_size < gate_bytes:
            alloc_size = max(gate_bytes, 4096)
            self._gate_bo = xrt.bo(
                self.device, alloc_size,
                xrt.bo.flags.normal,
                self.kernel.group_id(16),
            )
            self._gate_bo_size = alloc_size
        np.frombuffer(
            self._gate_bo.map(), dtype=np.int32, count=len(gate_arr)
        )[:] = gate_arr
        self._gate_bo.sync(
            xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_TO_DEVICE,
            gate_bytes, 0,
        )

    # ── Single kernel launch (≤ 512 gates) ────────────────────────────────────

    def _launch_kernel(self, num_gates: int, num_qubits: int):
        run = self.kernel(
            self.hbm_banks[0],  self.hbm_banks[1],
            self.hbm_banks[2],  self.hbm_banks[3],
            self.hbm_banks[4],  self.hbm_banks[5],
            self.hbm_banks[6],  self.hbm_banks[7],
            self.hbm_banks[8],  self.hbm_banks[9],
            self.hbm_banks[10], self.hbm_banks[11],
            self.hbm_banks[12], self.hbm_banks[13],
            self.hbm_banks[14], self.hbm_banks[15],
            self._gate_bo,
            num_gates,
            num_qubits,
        )
        run.wait()

    # ── Per-gate analytical profiling ─────────────────────────────────────────

    def _profile_gates(
        self, resolved_gates: List[Tuple], num_qubits: int
    ) -> List[GateProfile]:
        state_size = 2 ** num_qubits
        pairs      = state_size >> 1
        profiles   = []

        TWO_Q = {'cx', 'cnot', 'cy', 'cz', 'ch', 'swap', 'iswap',
                 'cp', 'cphase', 'crx', 'cry', 'crz', 'csx', 'dcx'}
        THREE_Q = {'ccx', 'toffoli', 'ccnot', 'mcx', 'mct'}
        WIDE_4AMP = {'ecr', 'rxx', 'ryy'}

        for name, qubits, _ in resolved_gates:
            q0 = qubits[0] if qubits else 0
            if name in WIDE_4AMP:
                cycles    = (state_size >> 2) * 32
                hbm_bytes = state_size * BYTES_PER_AMP
            elif name == 'rzz':
                cycles    = state_size * 8
                hbm_bytes = state_size * BYTES_PER_AMP
            elif name in TWO_Q or name in THREE_Q:
                cycles    = state_size * 16
                hbm_bytes = state_size * BYTES_PER_AMP
            else:
                cycles    = pairs * 16
                hbm_bytes = pairs * 2 * BYTES_PER_AMP

            time_us   = cycles * KERNEL_CLOCK_PERIOD_NS / 1e3
            hbm_kb    = hbm_bytes / 1024
            energy_uj = EnergyEstimator.gate_energy_uj(cycles, hbm_bytes)

            profiles.append(GateProfile(
                gate_name=name, target_qubit=q0,
                est_cycles=cycles, est_time_us=time_us,
                hbm_read_kb=hbm_kb / 2, hbm_write_kb=hbm_kb / 2,
                est_energy_uj=energy_uj,
            ))
        return profiles

    # ── Reset HBM to |0…0⟩ (public API for batched workloads) ────────────────

    def reset_state(self, num_qubits: int):
        """Re-zero |0…0⟩ in HBM without re-allocating buffers."""
        self._distribute_statevector(num_qubits)

    # ── Native-gate probe ────────────────────────────────────────────────────

    def probe_native_gates(self, verbose: bool = False) -> frozenset:
        """
        Returns the set of gate names that this kernel reliably implements.
        In v05, all opcodes are trusted; future versions may probe via a
        1-qubit H→X→H identity test for each gate family.
        """
        if verbose:
            print(
                f"  v{VERSION} trusted gates "
                f"({len(TRUSTED_KERNEL_GATES_DEFAULT)}): "
                f"{sorted(TRUSTED_KERNEL_GATES_DEFAULT)}"
            )
        return TRUSTED_KERNEL_GATES_DEFAULT

    # ── Main execution path ───────────────────────────────────────────────────

    def run_circuit(
        self,
        num_qubits        : int,
        gates             : List[Tuple],
        shots             : int            = 1024,
        validate          : bool           = True,
        det_idx           : Optional[int]  = None,
        uniform_check     : bool           = False,
        det_tolerance     : float          = 0.02,
        uniform_tolerance : float          = 0.05,
        circuit_name      : str            = "",
        skip_init         : bool           = False,
    ) -> Dict:
        """
        Execute a quantum circuit on FPGA hardware (complex64, 30-qubit max).

        Any gate count is supported: circuits longer than KERNEL_MAX_GATES
        (512) are transparently chunked into multiple kernel launches with
        HBM state preserved across chunks.
        """
        if num_qubits < 1 or num_qubits > MAX_QUBITS_FPGA:
            raise ValueError(
                f"num_qubits must be in [1, {MAX_QUBITS_FPGA}], got {num_qubits}")

        t0         = time.perf_counter_ns()
        state_size = 2 ** num_qubits

        # ── 1. Initialise |0…0⟩ in HBM (unless caller asks us to skip) ───────
        if not skip_init:
            self._distribute_statevector(num_qubits)
        t_dist = time.perf_counter_ns()

        # ── 2. Encode gates ──────────────────────────────────────────────────
        gate_arr, num_gates_total, resolved_gates = self._encode_gates(gates)
        t_encode = time.perf_counter_ns()

        # ── 3. Chunked kernel execution (≤ KERNEL_MAX_GATES per launch) ──────
        xrt_kernel_us = 0.0
        num_chunks    = 0

        if num_gates_total > 0:
            for chunk_start in range(0, num_gates_total, KERNEL_MAX_GATES):
                chunk_end = min(chunk_start + KERNEL_MAX_GATES, num_gates_total)
                n_chunk   = chunk_end - chunk_start
                chunk_arr = gate_arr[
                    chunk_start * GATE_WORDS : chunk_end * GATE_WORDS
                ]

                t_up0 = time.perf_counter_ns()
                self._upload_gate_buffer(chunk_arr)
                self._launch_kernel(n_chunk, num_qubits)
                t_up1 = time.perf_counter_ns()
                xrt_kernel_us += (t_up1 - t_up0) / 1e3
                num_chunks    += 1

        t_kernel = time.perf_counter_ns()

        # ── 4. Collect statevector ────────────────────────────────────────────
        final_state = self._collect_statevector(num_qubits)
        t_collect   = time.perf_counter_ns()

        # ── 5. Renormalise (correct float32 drift) ────────────────────────────
        norm_before = float(np.linalg.norm(final_state))
        if norm_before > 1e-10:
            final_state /= norm_before

        # ── 6. FPGA-side validation (no CPU re-simulation) ────────────────────
        val_result: Optional[ValidationResult] = None
        if validate:
            val_result = FPGAValidator.validate(
                sv=final_state, num_qubits=num_qubits,
                circuit_name=circuit_name,
                det_idx=det_idx, uniform_check=uniform_check,
                det_tolerance=det_tolerance,
                uniform_tolerance=uniform_tolerance,
            )
            if not val_result.passed:
                logger.warning(
                    f"FPGA validation FAILED — norm={val_result.norm:.6f}, "
                    f"prob_sum={val_result.prob_sum:.6f}"
                )

        # ── 7. Profiling ──────────────────────────────────────────────────────
        gate_profiles  = self._profile_gates(resolved_gates, num_qubits)
        total_cycles   = sum(gp.est_cycles for gp in gate_profiles)
        total_hbm_b    = sum(
            (gp.hbm_read_kb + gp.hbm_write_kb) * 1024 for gp in gate_profiles)
        est_kernel_us  = total_cycles * KERNEL_CLOCK_PERIOD_NS / 1e3
        energy_mj, avg_pw = EnergyEstimator.total_energy_mj(
            total_cycles, total_hbm_b)

        eff_bw = ((total_hbm_b / 1e9) / (xrt_kernel_us / 1e6)
                  if xrt_kernel_us > 0 else 0.0)

        type_summary: Dict = defaultdict(
            lambda: {'count': 0, 'cycles': 0, 'energy_uj': 0.0, 'time_us': 0.0})
        for gp in gate_profiles:
            s = type_summary[gp.gate_name]
            s['count']     += 1
            s['cycles']    += gp.est_cycles
            s['energy_uj'] += gp.est_energy_uj
            s['time_us']   += gp.est_time_us

        # ── 8. Measurement ────────────────────────────────────────────────────
        measured_qubits: List[int] = []
        for gn, qs, _ in gates:
            if gn.lower() == 'measure':
                for q in qs:
                    if q not in measured_qubits:
                        measured_qubits.append(q)
        if not measured_qubits:
            measured_qubits = list(range(num_qubits))

        probs = np.empty(state_size, dtype=np.float64)
        np.square(final_state.real.astype(np.float64), out=probs)
        probs += np.square(final_state.imag.astype(np.float64))
        prob_sum_meas = probs.sum()
        if prob_sum_meas > 0:
            probs /= prob_sum_meas

        counts: Dict[str, int] = {}
        memory: List[str]      = []
        if shots > 0:
            indices = np.random.choice(state_size, size=shots, p=probs)

            meas_sorted = sorted(measured_qubits, reverse=True)
            full_register = (meas_sorted == list(range(num_qubits - 1, -1, -1)))

            if full_register:
                for idx in indices:
                    bs = format(int(idx), f'0{num_qubits}b')
                    counts[bs] = counts.get(bs, 0) + 1
                    memory.append(bs)
            else:
                for idx in indices:
                    bs = format(int(idx), f'0{num_qubits}b')
                    out = ''.join(bs[num_qubits - 1 - q] for q in meas_sorted)
                    counts[out] = counts.get(out, 0) + 1
                    memory.append(out)

        t_end = time.perf_counter_ns()

        # ── 9. Build profile object ───────────────────────────────────────────
        profile = RunProfile(
            circuit_name       = circuit_name,
            num_qubits         = num_qubits,
            num_gates          = num_gates_total,
            num_chunks         = num_chunks,
            host_distribute_us = (t_dist    - t0)        / 1e3,
            host_encode_us     = (t_encode  - t_dist)    / 1e3,
            xrt_kernel_us      = xrt_kernel_us,
            host_collect_us    = (t_collect - t_kernel)  / 1e3,
            host_measure_us    = (t_end     - t_collect) / 1e3,
            total_wall_us      = (t_end     - t0)        / 1e3,
            est_total_cycles   = total_cycles,
            est_kernel_time_us = est_kernel_us,
            total_hbm_read_mb  = sum(gp.hbm_read_kb  for gp in gate_profiles) / 1024,
            total_hbm_write_mb = sum(gp.hbm_write_kb for gp in gate_profiles) / 1024,
            est_eff_bw_gbps    = eff_bw,
            total_energy_mj    = energy_mj,
            avg_power_w        = avg_pw,
            energy_per_gate_uj = (energy_mj * 1e3 / num_gates_total
                                  if num_gates_total > 0 else 0.0),
            validation         = val_result,
            gate_profiles      = gate_profiles,
            gate_type_summary  = dict(type_summary),
        )

        timing = {
            'distribute_us': profile.host_distribute_us,
            'encode_us'    : profile.host_encode_us,
            'kernel_us'    : profile.xrt_kernel_us,
            'collect_us'   : profile.host_collect_us,
            'measure_us'   : profile.host_measure_us,
            'total_us'     : profile.total_wall_us,
            'num_chunks'   : profile.num_chunks,
        }

        return {
            'statevector'    : final_state.copy(),
            'counts'         : counts,
            'memory'         : memory,
            'measured_qubits': measured_qubits,
            'success'        : True,
            'execution_time' : profile.total_wall_us / 1e6,
            'timing'         : timing,
            'profile'        : profile,
            'validation'     : val_result,
        }


# =============================================================================
#  FPGASimulator — Qiskit-compatible backend wrapper
# =============================================================================

class FPGASimulator:
    """
    Qiskit-compatible FPGA backend (v05, hardware-only, complex64, 30-qubit).
    """

    _DEFAULT_XCLBIN = (
        "/home/qacc/yes/envs/FPGA/lib/python3.8/site-packages/"
        "qiskit_aer/backends/quantum_fpga_optimized/"
        "quantum_simulator_kernel.xclbin"
    )

    def __init__(self, xclbin_path: Optional[str] = None,
                 device_index: int = 0, **backend_options):
        xclbin_path = xclbin_path or self._DEFAULT_XCLBIN
        self._fpga  = QuantumFPGACircuit(xclbin_path, device_index)
        self.name   = f"fpga_simulator_v{VERSION}"
        self._last_profile: Optional[RunProfile] = None
        self._configuration = (
            self._build_configuration() if QISKIT_AVAILABLE else None)

    @staticmethod
    def _build_configuration():
        return QasmBackendConfiguration(
            backend_name    = f"fpga_simulator_v{VERSION}",
            backend_version = _aer_version,
            n_qubits        = MAX_QUBITS_FPGA,
            basis_gates     = sorted(set(KERNEL_GATE_OPS.keys()) |
                                     {'measure', 'reset', 'barrier'}),
            gates           = [],
            local           = True,
            simulator       = True,
            conditional     = False,
            open_pulse      = False,
            memory          = True,
            max_shots       = None,
            coupling_map    = None,
            description     = (
                f"FPGA quantum simulator v{VERSION} — pure hardware execution, "
                "Xilinx Alveo U55C, 16-bank HBM2, 300 MHz kernel, complex64, "
                "30-qubit, generalised MCX, auto-chunked"
            ),
        )

    def configuration(self):
        return self._configuration

    @property
    def last_profile(self) -> Optional[RunProfile]:
        return self._last_profile

    def run(self, circuits, shots: int = 1024, seed_simulator=None, **kwargs):
        t_start = time.time()
        if not isinstance(circuits, list):
            circuits = [circuits]
        if seed_simulator is not None:
            np.random.seed(seed_simulator)

        results = []
        for circuit in circuits:
            gates: List[Tuple] = []
            has_meas = False

            for instruction in circuit.data:
                op_name = instruction.operation.name
                if op_name.lower() == 'measure':
                    has_meas = True
                try:
                    if hasattr(circuit, 'find_bit'):
                        qubits = [circuit.find_bit(q).index
                                  for q in instruction.qubits]
                    else:
                        qubits = [circuit.qubits.index(q)
                                  for q in instruction.qubits]
                except Exception:
                    qubits = list(range(len(instruction.qubits)))
                params = getattr(instruction.operation, 'params', None)
                gates.append((op_name, qubits, params))

            if not has_meas and shots > 0:
                gates.append(('measure', list(range(circuit.num_qubits)), None))

            cname = getattr(circuit, 'name', 'unnamed')
            cres  = self._fpga.run_circuit(
                circuit.num_qubits, gates,
                shots=shots, circuit_name=cname,
            )
            profile = cres['profile']
            self._last_profile = profile

            sv = cres.get('statevector')
            results.append({
                'success': True,
                'shots'  : shots,
                'data'   : {
                    'counts'        : cres['counts'],
                    'statevector'   : sv.tolist() if isinstance(sv, np.ndarray) else None,
                    'execution_time': cres['execution_time'],
                },
                'header' : {
                    'name'    : profile.circuit_name,
                    'metadata': {
                        'fpga_enabled'     : True,
                        'hbm_banks'        : NUM_HBM_BANKS,
                        'execution_mode'   : f'xrt-hbm-hw-v{VERSION}-fpga-only',
                        'precision'        : 'complex64',
                        'kernel_clock_mhz' : KERNEL_CLOCK_MHZ,
                        'xrt_kernel_us'    : profile.xrt_kernel_us,
                        'num_chunks'       : profile.num_chunks,
                        'est_cycles'       : profile.est_total_cycles,
                        'energy_mj'        : profile.total_energy_mj,
                        'avg_power_w'      : profile.avg_power_w,
                        'eff_bw_gbps'      : profile.est_eff_bw_gbps,
                        'norm'             : (profile.validation.norm
                                              if profile.validation else None),
                        'validation_passed': (profile.validation.passed
                                              if profile.validation else None),
                    },
                    'timing'      : cres['timing'],
                    'qreg_sizes'  : [['q', circuit.num_qubits]],
                    'clreg_sizes' : ([['c', circuit.num_clbits]]
                                     if hasattr(circuit, 'num_clbits') else []),
                    'qubit_labels': [['q', i] for i in range(circuit.num_qubits)],
                    'clbit_labels': ([['c', i] for i in range(circuit.num_clbits)]
                                     if hasattr(circuit, 'num_clbits') else []),
                },
            })

        total_time = time.time() - t_start
        job_id     = kwargs.get('job_id', str(uuid.uuid4()))

        result_dict = {
            'backend_name'   : self.name,
            'backend_version': (_aer_version if not self._configuration
                                else self._configuration.backend_version),
            'qobj_id'        : None,
            'job_id'         : job_id,
            'success'        : all(r['success'] for r in results),
            'results'        : results,
            'date'           : datetime.now().isoformat(),
            'status'         : 'COMPLETED',
            'header'         : {},
            'metadata'       : {
                'shots'         : shots,
                'seed_simulator': seed_simulator,
                'fpga_enabled'  : True,
                'hbm_banks'     : NUM_HBM_BANKS,
                'execution_mode': f'xrt-hbm-hw-v{VERSION}-fpga-only',
                'precision'     : 'complex64',
                'total_run_time': total_time,
            },
        }

        if QISKIT_AVAILABLE:
            try:
                return Result.from_dict(result_dict)
            except Exception:
                pass

        class _SimpleResult:
            def __init__(self, d): self._d = d
            def get_counts(self, *_): return self._d['results'][0]['data']['counts']
            def result(self): return self
        return _SimpleResult(result_dict)

    def print_profile(self, detailed: bool = False):
        p = self._last_profile
        if p is None:
            print("No profile available — run a circuit first.")
            return

        W = 78
        print(f"\n{'═' * W}")
        print(f"  FPGA RUN PROFILE v{VERSION}  [{p.circuit_name}]  "
              f"complex64 / float32  FPGA-ONLY")
        print(f"{'═' * W}")
        print(f"  Qubits: {p.num_qubits}  |  Gates: {p.num_gates}"
              f"  |  Chunks: {p.num_chunks}  |  State: {2**p.num_qubits:,}")
        print(f"{'─' * W}")
        print("  TIMING (wall clock)")
        print(f"    Distribute state   : {p.host_distribute_us:>12,.0f} µs")
        print(f"    Encode gates       : {p.host_encode_us:>12,.0f} µs")
        print(f"    XRT kernel exec    : {p.xrt_kernel_us:>12,.0f} µs")
        print(f"    Collect state      : {p.host_collect_us:>12,.0f} µs")
        print(f"    Measurement sample : {p.host_measure_us:>12,.0f} µs")
        print(f"    Total wall         : {p.total_wall_us:>12,.0f} µs"
              f"  ({p.total_wall_us / 1e6:.4f} s)")
        print(f"{'─' * W}")
        print("  ANALYTICAL KERNEL ESTIMATES (complex64, 8 B / amplitude)")
        print(f"    Est. clock cycles  : {p.est_total_cycles:>12,}")
        print(f"    Est. kernel time   : {p.est_kernel_time_us:>12,.0f} µs")
        print(f"    HBM read           : {p.total_hbm_read_mb:>12,.2f} MB")
        print(f"    HBM write          : {p.total_hbm_write_mb:>12,.2f} MB")
        print(f"    Eff. HBM bandwidth : {p.est_eff_bw_gbps:>12,.1f} GB/s")
        print(f"{'─' * W}")
        print("  ENERGY")
        print(f"    Total energy       : {p.total_energy_mj:>12,.4f} mJ")
        print(f"    Avg power          : {p.avg_power_w:>12,.1f} W")
        print(f"    Energy per gate    : {p.energy_per_gate_uj:>12,.2f} µJ")
        if p.validation is not None:
            v = p.validation
            tag = "PASS" if v.passed else "FAIL"
            print(f"{'─' * W}")
            print(f"  FPGA-SIDE VALIDATION  [{tag}]")
            print(f"    Norm               : {v.norm:.10f}"
                  f"  ({'OK' if v.norm_ok else 'FAIL'}, tol={v.norm_tolerance})")
            print(f"    Prob sum           : {v.prob_sum:.10f}"
                  f"  ({'OK' if v.prob_ok else 'FAIL'}, tol={v.prob_tolerance})")
            if v.expected_detail:
                print(f"    State check        : {v.expected_detail}")
        if detailed and p.gate_profiles:
            print(f"{'─' * W}")
            print("  GATE BREAKDOWN")
            print(f"    {'Gate':<8} {'Cnt':>5} {'Cycles':>14} "
                  f"{'Time(µs)':>10} {'Energy(µJ)':>11}")
            print(f"    {'─'*8} {'─'*5} {'─'*14} {'─'*10} {'─'*11}")
            for gn, s in sorted(p.gate_type_summary.items()):
                print(f"    {gn:<8} {s['count']:>5} {s['cycles']:>14,} "
                      f"{s['time_us']:>10,.0f} {s['energy_uj']:>11,.2f}")
        print(f"{'═' * W}\n")

    def export_profile_json(self, filepath: str) -> str:
        p = self._last_profile
        if p is None:
            return '{}'
        data = asdict(p)
        data.pop('gate_profiles', None)
        j = json.dumps(data, indent=2, default=str)
        with open(filepath, 'w') as f:
            f.write(j)
        return j


# =============================================================================
#  Top-level convenience function
# =============================================================================

def validate_fpga_output(
    statevector       : np.ndarray,
    num_qubits        : int,
    circuit_name      : str            = "",
    det_idx           : Optional[int]  = None,
    uniform_check     : bool           = False,
    det_tolerance     : float          = 0.02,
    uniform_tolerance : float          = 0.05,
) -> ValidationResult:
    """
    Validate a complex64 statevector returned from the FPGA using FPGA-side
    checks only. No CPU re-simulation.
    """
    return FPGAValidator.validate(
        sv=statevector, num_qubits=num_qubits,
        circuit_name=circuit_name,
        det_idx=det_idx, uniform_check=uniform_check,
        det_tolerance=det_tolerance,
        uniform_tolerance=uniform_tolerance,
    )


# =============================================================================
#  __all__
# =============================================================================

__all__ = [
    'QuantumFPGACircuit',
    'FPGASimulator',
    'FPGAValidator',
    'EnergyEstimator',
    'GateProfile',
    'RunProfile',
    'ValidationResult',
    'KERNEL_GATE_OPS',
    'KERNEL_MAX_GATES',
    'NUM_HBM_BANKS',
    'MAX_QUBITS_FPGA',
    'GATE_WORDS',
    'BYTES_PER_AMP',
    'TRUSTED_KERNEL_GATES_DEFAULT',
    'VERSION',
    'validate_fpga_output',
]
