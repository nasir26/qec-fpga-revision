#!/usr/bin/env python3
"""
benchmark_three_hardware.py
===========================

Unified CPU / GPU / FPGA benchmark for the C-DAC Indigenous Quantum Simulator.

Runs FOUR algorithm families on each available backend, all in complex128:

    GHZ  — H(0) + CX chain                       (n     gates)
    QFT  — full Quantum Fourier Transform        (~n²/2 gates)
    RQC  — Random Quantum Circuit, depth 20      (depth × ~3.5n gates)
    VQE  — Hardware-efficient ansatz, 3 layers   (layers × ~3n gates)

For each (algorithm, n_qubits) data point:
    1. Build ONE canonical gate list on the host. Random angles are sampled
       once per (algorithm, n) using a fixed seed and shared across all three
       backends, so the resulting statevectors are bit-comparable.
    2. Run on every available backend, time each, capture the final
       statevector.
    3. Compute fidelity F = |⟨ψ_ref | ψ_sim⟩|² against:
         - the analytic ideal state for GHZ and QFT|0⟩ (always available)
         - the CPU numpy reference for RQC and VQE (when n ≤ --max-cpu-qubits)
         - skipped if no reference can be built.

Outputs:
    - Console table per algorithm
    - {output}.json                       (full numerical results)
    - {output}_<algo>.png  (one per algo) (time + infidelity, 3 lines each)
    - {output}_summary.png                (4×2 grid covering all algorithms)

Backend gating:
    - CPU      : always available (numpy)
    - GPU      : requires `cudaq` (uses target 'nvidia' for FP64 statevector)
    - FPGA     : requires `fpga_simulator_version_5` import + a valid xclbin

Hardware targets in mind:
    - CPU      : whatever the host machine has
    - GPU      : NVIDIA RTX A4000 (16 GB VRAM, FP64 capable)
    - FPGA     : Xilinx Alveo U55C (16 GB HBM2, fpga_kernel_v05.cpp)

Up to 29 qubits is supported (8 GB statevector, fits in both 16 GB VRAM and
16 GB HBM2). 30 qubits would need exactly 16 GB which leaves no host headroom
for the gather buffer; pass --max-qubits 30 only on the FPGA path.

Usage:
    python benchmark_three_hardware.py \
        --xclbin /path/to/quantum_simulator_kernel_v05.xclbin \
        --max-qubits 29 --max-cpu-qubits 24 --trials 3

Author: Nasir Ali — C-DAC / NQM Qniverse
"""

from __future__ import annotations

import os
import sys
import time
import math
import json
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Callable

import numpy as np

# ─────────────────────────────────────────────────────────────────────────────
#  Optional backend imports
# ─────────────────────────────────────────────────────────────────────────────

try:
    import cudaq
    CUDAQ_OK = True
except ImportError:
    CUDAQ_OK = False

try:
    from fpga_simulator_version_5 import QuantumFPGACircuit  # v05 simulator
    FPGA_IMPORT_OK = True
except ImportError:
    FPGA_IMPORT_OK = False

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    PLOT_OK = True
except ImportError:
    PLOT_OK = False

logger = logging.getLogger(__name__)


# =============================================================================
#  Config — fixed across all backends so the comparison is meaningful
# =============================================================================

RQC_DEPTH    = 20
RQC_SEED     = 42
VQE_LAYERS   = 3
VQE_SEED     = 123
WARMUP_RUNS  = 1
DEFAULT_TRIALS = 3

# Hardware power model (used only for the energy column, not for ranking)
GPU_TDP_W      = 140.0
GPU_UTIL_FRAC  = 0.70
FPGA_AVG_W     = 40.0     # rough U55C kernel-active estimate
CPU_TDP_W      = 65.0     # rough single-socket numpy load


# =============================================================================
#  Angle generators — deterministic, shared across backends
# =============================================================================

def rqc_angles(n: int, depth: int = RQC_DEPTH,
               seed: int = RQC_SEED) -> List[float]:
    """3 angles per qubit per layer (rx, ry, rz). Same seed → same circuit."""
    rng = np.random.RandomState(seed)
    return rng.uniform(0.0, 2.0 * math.pi, depth * n * 3).astype(np.float64).tolist()


def vqe_angles(n: int, layers: int = VQE_LAYERS,
               seed: int = VQE_SEED) -> List[float]:
    """2 angles per qubit per layer (ry, rz)."""
    rng = np.random.RandomState(seed)
    return rng.uniform(0.0, math.pi, layers * n * 2).astype(np.float64).tolist()


# =============================================================================
#  Canonical gate-list builders (consumed by CPU and FPGA backends)
# =============================================================================
#  Format: list of (op_name, [qubits...], [params...] | None)
#  Qubit / parameter conventions match fpga_simulator_v05 KERNEL_GATE_OPS
#  and the CUDA-Q kernels below; this guarantees bit-comparable outputs.
# =============================================================================

def build_ghz_gates(n: int) -> List[Tuple]:
    gates: List[Tuple] = [("h", [0], None)]
    for q in range(n - 1):
        gates.append(("cx", [q, q + 1], None))
    return gates


def build_qft_gates(n: int, do_swaps: bool = True) -> List[Tuple]:
    """
    Standard QFT.  Phase angles use the Qiskit / FPGA convention:
        between control=k and target=j (k > j),  θ = π / 2^(k-j)
    which equals the CUDA-Q kernel angle  2π / 2^(k-j+1).
    """
    gates: List[Tuple] = []
    for j in range(n):
        gates.append(("h", [j], None))
        for k in range(j + 1, n):
            angle = math.pi / (2 ** (k - j))
            gates.append(("cp", [k, j], [angle]))
    if do_swaps:
        for q in range(n // 2):
            gates.append(("swap", [q, n - 1 - q], None))
    return gates


def build_rqc_gates(n: int, depth: int, angles: List[float]) -> List[Tuple]:
    """Same layer pattern as the CUDA-Q rqc_kernel below."""
    gates: List[Tuple] = []
    for d in range(depth):
        for i in range(n):
            base = (d * n + i) * 3
            gates.append(("rx", [i], [angles[base]]))
            gates.append(("ry", [i], [angles[base + 1]]))
            gates.append(("rz", [i], [angles[base + 2]]))
        for i in range(0, n - 1, 2):
            gates.append(("cx", [i, i + 1], None))
    return gates


def build_vqe_gates(n: int, layers: int, angles: List[float]) -> List[Tuple]:
    """Hardware-efficient ansatz: per layer, Ry/Rz on each qubit then CX ladder."""
    gates: List[Tuple] = []
    for L in range(layers):
        for i in range(n):
            base = (L * n + i) * 2
            gates.append(("ry", [i], [angles[base]]))
            gates.append(("rz", [i], [angles[base + 1]]))
        for i in range(n - 1):
            gates.append(("cx", [i, i + 1], None))
    return gates


# =============================================================================
#  CUDA-Q kernels — must be registered at module top level (not inside funcs)
# =============================================================================

if CUDAQ_OK:

    @cudaq.kernel
    def ghz_kernel(n: int):
        q = cudaq.qvector(n)
        h(q[0])
        for i in range(n - 1):
            cx(q[i], q[i + 1])

    @cudaq.kernel
    def qft_kernel(n: int):
        q = cudaq.qvector(n)
        for i in range(n):
            h(q[i])
            for j in range(i + 1, n):
                # cr1(θ) = diag(1, e^{iθ}) — matches FPGA `cp` and Qiskit CP
                # angle = π / 2^(j-i)  =  2π / 2^(j-i+1)
                angle = 2.0 * math.pi / (2 ** (j - i + 1))
                cr1(angle, q[j], q[i])
        for i in range(n // 2):
            swap(q[i], q[n - i - 1])

    @cudaq.kernel
    def rqc_kernel(n: int, depth: int, angles: List[float]):
        q = cudaq.qvector(n)
        for d in range(depth):
            for i in range(n):
                base = (d * n + i) * 3
                rx(angles[base],     q[i])
                ry(angles[base + 1], q[i])
                rz(angles[base + 2], q[i])
            for i in range(0, n - 1, 2):
                cx(q[i], q[i + 1])

    @cudaq.kernel
    def vqe_kernel(n: int, layers: int, angles: List[float]):
        q = cudaq.qvector(n)
        for L in range(layers):
            for i in range(n):
                base = (L * n + i) * 2
                ry(angles[base],     q[i])
                rz(angles[base + 1], q[i])
            for i in range(n - 1):
                cx(q[i], q[i + 1])


# =============================================================================
#  CPU reference simulator — numpy complex128
# =============================================================================
#  Implements the seven gate types our four algorithms use:
#      h, cx, cp, swap, rx, ry, rz
#  via einsum-equivalent tensordot reshapes.  Used both as a timing target
#  and as the gold-standard reference statevector for fidelity calculations.
# =============================================================================

class CPUSimulator:
    """Pure-numpy statevector simulator, complex128, gate-list driven."""

    name = "CPU (numpy fp64)"

    _H = np.array([[1, 1], [1, -1]], dtype=np.complex128) / math.sqrt(2.0)

    @staticmethod
    def _rx(theta: float) -> np.ndarray:
        c, s = math.cos(theta * 0.5), math.sin(theta * 0.5)
        return np.array([[c, -1j * s], [-1j * s, c]], dtype=np.complex128)

    @staticmethod
    def _ry(theta: float) -> np.ndarray:
        c, s = math.cos(theta * 0.5), math.sin(theta * 0.5)
        return np.array([[c, -s], [s, c]], dtype=np.complex128)

    @staticmethod
    def _rz(theta: float) -> np.ndarray:
        e_neg = np.exp(-0.5j * theta)
        e_pos = np.exp(+0.5j * theta)
        return np.diag([e_neg, e_pos]).astype(np.complex128)

    @staticmethod
    def _apply1(sv: np.ndarray, U: np.ndarray, k: int, n: int) -> np.ndarray:
        """
        Apply 2×2 unitary U to qubit k (LSB convention: qubit k ↔ bit k).

        numpy reshape((2,)*n) is C-order, so axis 0 of the reshaped array is
        the MOST-significant bit and axis (n-1) is the LEAST-significant bit.
        We therefore map qubit k → numpy axis (n-1-k).
        """
        ax = n - 1 - k
        sv = sv.reshape([2] * n)
        sv = np.tensordot(U, sv, axes=[[1], [ax]])
        sv = np.moveaxis(sv, 0, ax)
        return sv.reshape(-1)

    @staticmethod
    def _apply_cx(sv: np.ndarray, ctrl: int, tgt: int, n: int) -> np.ndarray:
        ctrl_ax = n - 1 - ctrl
        tgt_ax  = n - 1 - tgt
        sv = sv.reshape([2] * n)
        idx = [slice(None)] * n
        idx[ctrl_ax] = 1
        # Take a COPY of the ctrl=1 slice — flipping a view into the same
        # memory we then assign back to causes aliasing; copy avoids it.
        sub = sv[tuple(idx)].copy()
        # After integer-indexing axis ctrl_ax, the target axis position
        # shifts down by one if tgt_ax > ctrl_ax.
        tgt_in_sub = tgt_ax if tgt_ax < ctrl_ax else tgt_ax - 1
        sv[tuple(idx)] = np.flip(sub, axis=tgt_in_sub)
        return sv.reshape(-1)

    @staticmethod
    def _apply_cp(sv: np.ndarray, theta: float,
                  ctrl: int, tgt: int, n: int) -> np.ndarray:
        """Controlled-phase: diag(1, e^{iθ}) on tgt when ctrl=|1⟩."""
        ctrl_ax = n - 1 - ctrl
        tgt_ax  = n - 1 - tgt
        sv = sv.reshape([2] * n)
        idx = [slice(None)] * n
        idx[ctrl_ax] = 1
        idx[tgt_ax]  = 1
        sv[tuple(idx)] *= np.exp(1j * theta)
        return sv.reshape(-1)

    @staticmethod
    def _apply_swap(sv: np.ndarray, q0: int, q1: int, n: int) -> np.ndarray:
        a0 = n - 1 - q0
        a1 = n - 1 - q1
        sv = sv.reshape([2] * n).swapaxes(a0, a1)
        return sv.reshape(-1)

    def simulate(self, n: int, gates: List[Tuple]) -> Tuple[np.ndarray, float]:
        sv = np.zeros(2 ** n, dtype=np.complex128)
        sv[0] = 1.0
        t0 = time.perf_counter()
        for op, qs, params in gates:
            o = op.lower()
            if o == "h":
                sv = self._apply1(sv, self._H, qs[0], n)
            elif o in ("x",):
                X = np.array([[0, 1], [1, 0]], dtype=np.complex128)
                sv = self._apply1(sv, X, qs[0], n)
            elif o in ("rx",):
                sv = self._apply1(sv, self._rx(params[0]), qs[0], n)
            elif o in ("ry",):
                sv = self._apply1(sv, self._ry(params[0]), qs[0], n)
            elif o in ("rz",):
                sv = self._apply1(sv, self._rz(params[0]), qs[0], n)
            elif o in ("cx", "cnot"):
                sv = self._apply_cx(sv, qs[0], qs[1], n)
            elif o in ("cp", "cphase"):
                sv = self._apply_cp(sv, params[0], qs[0], qs[1], n)
            elif o == "swap":
                sv = self._apply_swap(sv, qs[0], qs[1], n)
            else:
                raise NotImplementedError(
                    f"CPU reference does not implement gate '{op}'. "
                    f"Add it to CPUSimulator.simulate() if your benchmark "
                    f"needs it."
                )
        elapsed = time.perf_counter() - t0
        return sv, elapsed


# =============================================================================
#  GPU backend wrapper (CUDA-Q)
# =============================================================================

class GPUBenchmark:
    """Thin wrapper that runs the CUDA-Q kernels and returns numpy state."""

    name = "GPU (CUDA-Q nvidia)"

    def __init__(self):
        if not CUDAQ_OK:
            raise RuntimeError("cudaq not importable")
        # 'nvidia-fp64' gives FP64 statevector to match the FPGA's complex128.
        # If unavailable on this install, fall back to 'nvidia' (FP32) and
        # warn — fidelity will be ~1e-7 instead of ~1e-14.
        self.target_used = "nvidia-fp64"
        try:
            cudaq.set_target("nvidia-fp64")
        except Exception:
            try:
                cudaq.set_target("nvidia", option="fp64")
                self.target_used = "nvidia (fp64 option)"
            except Exception:
                cudaq.set_target("nvidia")
                self.target_used = "nvidia (FP32 — fidelity will be limited)"
                logger.warning("CUDA-Q FP64 target unavailable; using FP32 nvidia")

    def simulate(self, algo: str, n: int,
                 angles: Optional[List[float]] = None
                 ) -> Tuple[np.ndarray, float]:
        t0 = time.perf_counter()
        if algo == "ghz":
            state = cudaq.get_state(ghz_kernel, n)
        elif algo == "qft":
            state = cudaq.get_state(qft_kernel, n)
        elif algo == "rqc":
            state = cudaq.get_state(rqc_kernel, n, RQC_DEPTH, angles)
        elif algo == "vqe":
            state = cudaq.get_state(vqe_kernel, n, VQE_LAYERS, angles)
        else:
            raise ValueError(f"Unknown algo {algo}")
        elapsed = time.perf_counter() - t0
        sv = np.array(state, dtype=np.complex128)
        return sv, elapsed


# =============================================================================
#  FPGA backend wrapper
# =============================================================================

class FPGABenchmark:
    """Wraps fpga_simulator_version_5.QuantumFPGACircuit for the unified loop."""

    name = "FPGA (Alveo U55C v05)"

    def __init__(self, xclbin_path: str, device_index: int = 0):
        if not FPGA_IMPORT_OK:
            raise RuntimeError("fpga_simulator_version_5 not importable")
        self.engine = QuantumFPGACircuit(xclbin_path, device_index=device_index)
        self.last_kernel_us = 0.0

    def simulate(self, n: int, gates: List[Tuple]) -> Tuple[np.ndarray, float]:
        t0 = time.perf_counter()
        result = self.engine.run_circuit(
            num_qubits=n,
            gates=gates,
            shots=0,            # we just want the statevector
            validate=False,
        )
        wall = time.perf_counter() - t0
        sv = np.asarray(result["statevector"], dtype=np.complex128)
        prof = result.get("profile")
        if prof is not None:
            self.last_kernel_us = float(getattr(prof, "xrt_kernel_us", 0.0))
        return sv, wall


# =============================================================================
#  Reference state for fidelity
# =============================================================================

def ideal_ghz(n: int) -> np.ndarray:
    sv = np.zeros(2 ** n, dtype=np.complex128)
    sv[0]  = 1.0 / math.sqrt(2.0)
    sv[-1] = 1.0 / math.sqrt(2.0)
    return sv


def ideal_qft_zero(n: int) -> np.ndarray:
    """QFT|0…0⟩ = (1/√N) Σ_k |k⟩"""
    N = 2 ** n
    return np.full(N, 1.0 / math.sqrt(N), dtype=np.complex128)


def fidelity(sv_test: np.ndarray, sv_ref: np.ndarray) -> float:
    """F = |⟨ref | test⟩|²"""
    if sv_test is None or sv_ref is None:
        return float("nan")
    if sv_test.shape != sv_ref.shape:
        return float("nan")
    return float(np.abs(np.vdot(sv_ref, sv_test)) ** 2)


# =============================================================================
#  Per-point benchmark routine
# =============================================================================

def time_callable(fn: Callable, trials: int) -> Tuple[float, float, np.ndarray]:
    """
    Run `fn` (WARMUP_RUNS + trials) times. Returns (median_seconds,
    std_seconds, last_returned_state).
    """
    times: List[float] = []
    state = None
    for t in range(WARMUP_RUNS + trials):
        sv, dt = fn()
        if t >= WARMUP_RUNS:
            times.append(dt)
            state = sv
    return float(np.median(times)), float(np.std(times)), state


def benchmark_point(
    algo: str,
    n: int,
    cpu: CPUSimulator,
    gpu: Optional[GPUBenchmark],
    fpga: Optional[FPGABenchmark],
    max_cpu_q: int,
    trials: int,
) -> Dict:
    """One row of the benchmark table for a given (algorithm, n_qubits)."""

    # ── Build the canonical gate list + matching CUDA-Q angles list ──────
    if algo == "ghz":
        gates  = build_ghz_gates(n)
        angles = None
    elif algo == "qft":
        gates  = build_qft_gates(n)
        angles = None
    elif algo == "rqc":
        angles = rqc_angles(n, RQC_DEPTH, RQC_SEED)
        gates  = build_rqc_gates(n, RQC_DEPTH, angles)
    elif algo == "vqe":
        angles = vqe_angles(n, VQE_LAYERS, VQE_SEED)
        gates  = build_vqe_gates(n, VQE_LAYERS, angles)
    else:
        raise ValueError(algo)

    rec: Dict = {
        "algo": algo,
        "num_qubits": n,
        "gate_count": len(gates),
        "sv_gb": (2 ** n * 16) / (1024 ** 3),
    }

    # ── CPU run (also serves as the fidelity reference for RQC/VQE) ──────
    cpu_sv: Optional[np.ndarray] = None
    if n <= max_cpu_q:
        try:
            cpu_med, cpu_std, cpu_sv = time_callable(
                lambda: cpu.simulate(n, gates), trials)
            rec["cpu_time_s"]     = cpu_med
            rec["cpu_time_std_s"] = cpu_std
        except Exception as e:
            logger.exception("CPU run failed")
            rec["cpu_error"] = str(e)
    else:
        rec["cpu_skip_reason"] = f"n>{max_cpu_q}"

    # ── Reference state for fidelity ─────────────────────────────────────
    if algo == "ghz":
        ref_state = ideal_ghz(n)
        rec["fidelity_ref"] = "analytic_ghz"
    elif algo == "qft":
        ref_state = ideal_qft_zero(n)
        rec["fidelity_ref"] = "analytic_qft0"
    else:
        ref_state = cpu_sv
        rec["fidelity_ref"] = "cpu_numpy" if cpu_sv is not None else "none"

    if cpu_sv is not None:
        rec["cpu_fidelity"] = fidelity(cpu_sv, ref_state)

    # ── GPU run ──────────────────────────────────────────────────────────
    if gpu is not None:
        try:
            gpu_med, gpu_std, gpu_sv = time_callable(
                lambda: gpu.simulate(algo, n, angles), trials)
            rec["gpu_time_s"]     = gpu_med
            rec["gpu_time_std_s"] = gpu_std
            if ref_state is not None:
                rec["gpu_fidelity"] = fidelity(gpu_sv, ref_state)
            rec["gpu_energy_j"] = gpu_med * GPU_TDP_W * GPU_UTIL_FRAC
        except Exception as e:
            logger.exception("GPU run failed")
            rec["gpu_error"] = str(e)

    # ── FPGA run ─────────────────────────────────────────────────────────
    if fpga is not None:
        try:
            fpga_med, fpga_std, fpga_sv = time_callable(
                lambda: fpga.simulate(n, gates), trials)
            rec["fpga_wall_s"]     = fpga_med
            rec["fpga_wall_std_s"] = fpga_std
            rec["fpga_kernel_us"]  = float(fpga.last_kernel_us)
            if ref_state is not None:
                rec["fpga_fidelity"] = fidelity(fpga_sv, ref_state)
            rec["fpga_energy_j"] = fpga_med * FPGA_AVG_W
        except Exception as e:
            logger.exception("FPGA run failed")
            rec["fpga_error"] = str(e)

    # ── Speedups (relative to CPU when both available) ───────────────────
    cpu_t = rec.get("cpu_time_s")
    if cpu_t and rec.get("gpu_time_s"):
        rec["gpu_speedup_vs_cpu"] = cpu_t / rec["gpu_time_s"]
    if cpu_t and rec.get("fpga_wall_s"):
        rec["fpga_speedup_vs_cpu"] = cpu_t / rec["fpga_wall_s"]

    return rec


# =============================================================================
#  Console table printing
# =============================================================================

def _fmt_time(t: Optional[float]) -> str:
    if t is None:
        return "    —    "
    if t >= 100:
        return f"{t:8.1f}s"
    if t >= 1.0:
        return f"{t:8.3f}s"
    if t >= 1e-3:
        return f"{t*1e3:7.2f}ms"
    return f"{t*1e6:7.1f}µs"


def _fmt_fid(f: Optional[float]) -> str:
    if f is None or (isinstance(f, float) and math.isnan(f)):
        return "      —     "
    return f"{f:.10f}"


def print_header(algo: str):
    print(f"\n  ── {algo.upper()}  "
          f"{'─' * (78 - 6 - len(algo))}")
    print(f"  {'Q':>3} │ {'Gates':>6} │ {'CPU':>10} │ {'GPU':>10} │ "
          f"{'FPGA':>10} │ {'F_CPU':>12} │ {'F_GPU':>12} │ {'F_FPGA':>12}")
    print(f"  {'─'*4}┼{'─'*8}┼{'─'*12}┼{'─'*12}┼{'─'*12}┼"
          f"{'─'*14}┼{'─'*14}┼{'─'*14}")


def print_row(rec: Dict):
    n  = rec["num_qubits"]
    gc = rec["gate_count"]
    print(
        f"  {n:>3} │ {gc:>6} │ "
        f"{_fmt_time(rec.get('cpu_time_s')):>10} │ "
        f"{_fmt_time(rec.get('gpu_time_s')):>10} │ "
        f"{_fmt_time(rec.get('fpga_wall_s')):>10} │ "
        f"{_fmt_fid(rec.get('cpu_fidelity')):>12} │ "
        f"{_fmt_fid(rec.get('gpu_fidelity')):>12} │ "
        f"{_fmt_fid(rec.get('fpga_fidelity')):>12}"
    )


# =============================================================================
#  Plotting
# =============================================================================

ALGO_TITLE = {
    "ghz": "GHZ State (n−1 CX chain)",
    "qft": "Quantum Fourier Transform",
    "rqc": f"Random Quantum Circuit (depth={RQC_DEPTH})",
    "vqe": f"VQE Hardware-Efficient Ansatz (layers={VQE_LAYERS})",
}

HW_STYLE = {
    "cpu":  dict(label="CPU (numpy fp64)",      color="#D32F2F", marker="o"),
    "gpu":  dict(label="GPU (CUDA-Q nvidia)",   color="#1565C0", marker="s"),
    "fpga": dict(label="FPGA (Alveo U55C v05)", color="#2E7D32", marker="^"),
}


def _series(records: List[Dict], time_key: str) -> Tuple[List[int], List[float]]:
    qs, ts = [], []
    for r in records:
        v = r.get(time_key)
        if v is not None and v > 0:
            qs.append(r["num_qubits"])
            ts.append(v)
    return qs, ts


def _fid_series(records: List[Dict], fid_key: str
                ) -> Tuple[List[int], List[float]]:
    """Returns (qubits, infidelity = max(1−F, eps)).  Eps avoids log(0)."""
    qs, infs = [], []
    for r in records:
        f = r.get(fid_key)
        if f is None or (isinstance(f, float) and math.isnan(f)):
            continue
        inf = max(1.0 - f, 1e-17)   # floor for log plot
        qs.append(r["num_qubits"])
        infs.append(inf)
    return qs, infs


def plot_per_algorithm(algo: str, records: List[Dict], output_path: str):
    if not PLOT_OK:
        return
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    fig.suptitle(f"{ALGO_TITLE[algo]}  —  CPU vs GPU vs FPGA",
                 fontsize=13, fontweight="bold")

    # --- Panel 1: execution time ---
    ax = axes[0]
    for hw, time_key in [("cpu", "cpu_time_s"),
                         ("gpu", "gpu_time_s"),
                         ("fpga", "fpga_wall_s")]:
        qs, ts = _series(records, time_key)
        if qs:
            ax.semilogy(qs, ts, marker=HW_STYLE[hw]["marker"], linestyle="-",
                        color=HW_STYLE[hw]["color"], linewidth=2,
                        markersize=6, label=HW_STYLE[hw]["label"])
    ax.set_xlabel("Number of qubits")
    ax.set_ylabel("Execution time (s)")
    ax.set_title("Execution time vs problem size")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=9, loc="upper left")

    # --- Panel 2: infidelity ---
    ax = axes[1]
    for hw, fid_key in [("cpu", "cpu_fidelity"),
                        ("gpu", "gpu_fidelity"),
                        ("fpga", "fpga_fidelity")]:
        qs, infs = _fid_series(records, fid_key)
        if qs:
            ax.semilogy(qs, infs, marker=HW_STYLE[hw]["marker"], linestyle="-",
                        color=HW_STYLE[hw]["color"], linewidth=2,
                        markersize=6, label=HW_STYLE[hw]["label"])
    ref = records[0].get("fidelity_ref", "?") if records else "?"
    ax.set_xlabel("Number of qubits")
    ax.set_ylabel(r"Infidelity  $1 - F$")
    ax.set_title(f"State fidelity vs reference  ({ref})")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=9, loc="lower right")

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  saved {output_path}")


def plot_summary(all_results: Dict[str, List[Dict]], output_path: str):
    """4×2 grid: rows = algorithms, columns = (time, infidelity)."""
    if not PLOT_OK:
        return
    algos = ["ghz", "qft", "rqc", "vqe"]
    fig, axes = plt.subplots(len(algos), 2, figsize=(13, 4.2 * len(algos)))
    fig.suptitle("Three-Hardware Quantum Simulator Benchmark  —  C-DAC NQM",
                 fontsize=14, fontweight="bold")

    for row, algo in enumerate(algos):
        recs = all_results.get(algo, [])
        # Time
        ax = axes[row, 0]
        for hw, time_key in [("cpu", "cpu_time_s"),
                             ("gpu", "gpu_time_s"),
                             ("fpga", "fpga_wall_s")]:
            qs, ts = _series(recs, time_key)
            if qs:
                ax.semilogy(qs, ts,
                            marker=HW_STYLE[hw]["marker"], linestyle="-",
                            color=HW_STYLE[hw]["color"], linewidth=2,
                            markersize=5, label=HW_STYLE[hw]["label"])
        ax.set_xlabel("Qubits")
        ax.set_ylabel("Time (s)")
        ax.set_title(f"{ALGO_TITLE[algo]}  —  execution time")
        ax.grid(True, which="both", alpha=0.3)
        if row == 0:
            ax.legend(fontsize=8, loc="upper left")

        # Infidelity
        ax = axes[row, 1]
        for hw, fid_key in [("cpu", "cpu_fidelity"),
                            ("gpu", "gpu_fidelity"),
                            ("fpga", "fpga_fidelity")]:
            qs, infs = _fid_series(recs, fid_key)
            if qs:
                ax.semilogy(qs, infs,
                            marker=HW_STYLE[hw]["marker"], linestyle="-",
                            color=HW_STYLE[hw]["color"], linewidth=2,
                            markersize=5, label=HW_STYLE[hw]["label"])
        ax.set_xlabel("Qubits")
        ax.set_ylabel(r"$1 - F$")
        ax.set_title(f"{ALGO_TITLE[algo]}  —  infidelity")
        ax.grid(True, which="both", alpha=0.3)

    plt.tight_layout()
    plt.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close()
    print(f"  saved {output_path}")


# =============================================================================
#  Main
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="CPU/GPU/FPGA quantum simulator benchmark (complex128)",
    )
    parser.add_argument("--xclbin", type=str, default=None,
                        help="Path to FPGA xclbin (skips FPGA if missing)")
    parser.add_argument("--max-qubits",     type=int, default=29)
    parser.add_argument("--min-qubits",     type=int, default=2)
    parser.add_argument("--max-cpu-qubits", type=int, default=24,
                        help="CPU is skipped above this qubit count")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--algos",  type=str, default="ghz,qft,rqc,vqe",
                        help="Comma-separated subset of {ghz,qft,rqc,vqe}")
    parser.add_argument("--cpu-only", action="store_true")
    parser.add_argument("--no-gpu",   action="store_true")
    parser.add_argument("--no-fpga",  action="store_true")
    parser.add_argument("--output",   type=str,
                        default="benchmark_three_hw")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(message)s")

    print("═" * 80)
    print("  THREE-HARDWARE QUANTUM SIMULATOR BENCHMARK")
    print("  CPU (numpy fp64)  │  GPU (CUDA-Q)  │  FPGA (Alveo U55C v05)")
    print("═" * 80)
    print(f"  Date         : {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"  Qubit range  : {args.min_qubits}–{args.max_qubits}")
    print(f"  CPU cap      : ≤{args.max_cpu_qubits}q")
    print(f"  Trials       : {args.trials} (+{WARMUP_RUNS} warmup)")
    print(f"  Algorithms   : {args.algos}")
    print(f"  Output stem  : {args.output}")

    # ── Backend setup ────────────────────────────────────────────────────
    cpu = CPUSimulator()

    gpu: Optional[GPUBenchmark] = None
    if not args.cpu_only and not args.no_gpu:
        if CUDAQ_OK:
            try:
                gpu = GPUBenchmark()
                print(f"  GPU backend  : ✓  cudaq target = {gpu.target_used}")
            except Exception as e:
                print(f"  GPU backend  : ✗  {e}")
        else:
            print("  GPU backend  : ✗  cudaq import failed")

    fpga: Optional[FPGABenchmark] = None
    if not args.cpu_only and not args.no_fpga:
        if not FPGA_IMPORT_OK:
            print("  FPGA backend : ✗  fpga_simulator_version_5 not importable")
        elif not args.xclbin:
            print("  FPGA backend : ✗  --xclbin not provided")
        elif not os.path.exists(args.xclbin):
            print(f"  FPGA backend : ✗  xclbin not found: {args.xclbin}")
        else:
            try:
                fpga = FPGABenchmark(args.xclbin)
                print(f"  FPGA backend : ✓  {args.xclbin}")
            except Exception as e:
                print(f"  FPGA backend : ✗  {e}")

    # Memory feasibility check
    sv_gb_max = (2 ** args.max_qubits * 16) / (1024 ** 3)
    print(f"  SV @ max-q   : {sv_gb_max:.2f} GB  (complex128)")
    print("═" * 80)

    # ── Sweep ────────────────────────────────────────────────────────────
    selected = [a.strip() for a in args.algos.split(",") if a.strip()]
    qubit_range = list(range(args.min_qubits, args.max_qubits + 1))
    all_results: Dict[str, List[Dict]] = {a: [] for a in selected}

    for algo in selected:
        print_header(algo)
        for n in qubit_range:
            try:
                rec = benchmark_point(algo, n, cpu, gpu, fpga,
                                      args.max_cpu_qubits, args.trials)
            except Exception as e:
                logger.exception(f"benchmark_point({algo},{n}) failed")
                rec = {"algo": algo, "num_qubits": n, "fatal_error": str(e),
                       "gate_count": 0}
            all_results[algo].append(rec)
            print_row(rec)

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "═" * 80)
    print("  SUMMARY")
    print("═" * 80)
    for algo in selected:
        recs = all_results[algo]
        gpu_speedups  = [r.get("gpu_speedup_vs_cpu") for r in recs
                         if r.get("gpu_speedup_vs_cpu")]
        fpga_speedups = [r.get("fpga_speedup_vs_cpu") for r in recs
                         if r.get("fpga_speedup_vs_cpu")]
        gpu_inf  = [1.0 - r.get("gpu_fidelity", 1.0)  for r in recs
                    if r.get("gpu_fidelity")  is not None]
        fpga_inf = [1.0 - r.get("fpga_fidelity", 1.0) for r in recs
                    if r.get("fpga_fidelity") is not None]
        print(f"  {algo.upper():4s}  "
              f"GPU avg×: {np.mean(gpu_speedups):>7.1f}  "
                  if gpu_speedups else f"  {algo.upper():4s}  GPU avg×:    —     "
              , end="")
        print(f"FPGA avg×: {np.mean(fpga_speedups):>7.1f}  "
                  if fpga_speedups else "FPGA avg×:    —     "
              , end="")
        print(f"max(1-F) GPU={max(gpu_inf):.2e}  "
                  if gpu_inf else "max(1-F) GPU=  —      "
              , end="")
        print(f"FPGA={max(fpga_inf):.2e}"
                  if fpga_inf else "FPGA=  —    ")

    # ── JSON export ──────────────────────────────────────────────────────
    out_json = f"{args.output}.json"
    with open(out_json, "w") as f:
        json.dump({
            "meta": {
                "date":             datetime.now().isoformat(),
                "min_qubits":       args.min_qubits,
                "max_qubits":       args.max_qubits,
                "max_cpu_qubits":   args.max_cpu_qubits,
                "trials":           args.trials,
                "rqc_depth":        RQC_DEPTH,
                "vqe_layers":       VQE_LAYERS,
                "rqc_seed":         RQC_SEED,
                "vqe_seed":         VQE_SEED,
                "cudaq_available":  CUDAQ_OK,
                "fpga_available":   fpga is not None,
                "fpga_xclbin":      args.xclbin,
            },
            "results": all_results,
        }, f, indent=2, default=str)
    print(f"\n  saved {out_json}")

    # ── Plots ────────────────────────────────────────────────────────────
    if PLOT_OK:
        for algo in selected:
            plot_per_algorithm(algo, all_results[algo],
                               f"{args.output}_{algo}.png")
        plot_summary(all_results, f"{args.output}_summary.png")
    else:
        print("  matplotlib not available — no PNGs written")

    print("\n" + "═" * 80)
    print("  BENCHMARK COMPLETE")
    print("═" * 80 + "\n")


if __name__ == "__main__":
    main()
