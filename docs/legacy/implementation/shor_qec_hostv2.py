#!/usr/bin/env python3
"""
Shor-Code QEC FPGA Host Driver
==============================

Runs single-shot 9-qubit Shor code error correction on the Alveo U55C via
the pure-AXI-Lite `shor_qec_kernel` compute unit and produces a Monte Carlo
p_logical vs p_physical curve.

Matches the interface conventions of `fpga_simulator_v05.py` (PyXRT, same
device-open pattern, same logging), but this kernel has no HBM buffers —
every call is a 4-byte AXI-Lite write plus a 4-byte read.

Hardware: Xilinx Alveo U55C, 300 MHz shor_qec_kernel
Companion kernel: shor_qec_kernel.cpp

Author: Nasir Ali — C-DAC / NQM Qniverse

Fix log (Apr 2026):
  - decode_one(): replaced broken get_return_value() / get_arg_value(1) with
    a 4-level compatibility ladder that works across all XRT versions:
      1. xrt.kernel.__call__()  — pre-2.14 callable-kernel API  (your system)
      2. run.get_return_value() — XRT >= 2.14
      3. run[return_offset]     — register-map read via run.__getitem__
      4. kernel.read_register() — raw AXI-Lite register read fallback
  - open(): log XRT version at startup for easier future debugging
  - probe_xrt_api(): new helper that prints every available method on the
    run/kernel objects so you can see exactly what your XRT exposes
  - --probe-api CLI flag: call probe_xrt_api() and exit (useful for future XRT upgrades)
  - cu_access_mode guard: some older XRT builds lack the .exclusive attribute;
    we fall back gracefully.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# ── XRT (mandatory) ──────────────────────────────────────────────────────────
try:
    import pyxrt as xrt
    XRT_AVAILABLE = True
except ImportError:
    XRT_AVAILABLE = False

# ── Matplotlib (optional — only for --plot) ──────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shor_qec")

# ═════════════════════════════════════════════════════════════════════════════
#  Kernel interface constants — must match shor_qec_kernel.cpp
# ═════════════════════════════════════════════════════════════════════════════
N_DATA      = 9
KERNEL_NAME = "shor_qec_kernel"

# Output bit layout (keep in sync with kernel's `result` register):
#   bits [ 8: 0]  x_correction applied
#   bits [17: 9]  z_correction applied
#   bits [25:18]  syndrome
#   bits [26]     X_logical_error flag
#   bits [27]     Z_logical_error flag
BIT_X_CORR_LO, BIT_X_CORR_HI =  0,  8
BIT_Z_CORR_LO, BIT_Z_CORR_HI =  9, 17
BIT_SYND_LO,   BIT_SYND_HI   = 18, 25
BIT_XLOG = 26
BIT_ZLOG = 27

# AXI-Lite register offsets (byte addresses in the control bundle).
# The HLS ap_ctrl_hs layout for a kernel with one scalar input and one return:
#   0x00  ap_ctrl  (start / done / idle / ready)
#   0x04  gier     (global interrupt enable)
#   0x08  ip_ier   (ip interrupt enable)
#   0x0C  ip_isr   (ip interrupt status)
#   0x10  err_in   (argument 0 — our packed error vector)
#   0x18  return   (ap_return — the 32-bit result we want)
#
# 0x18 is the standard offset for the first (and only) return register when
# there is exactly one scalar input argument at 0x10.  If you ever add a
# second scalar argument it moves to 0x20.
AP_RETURN_OFFSET = 0x18


def _bits(word: int, lo: int, hi: int) -> int:
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


# ═════════════════════════════════════════════════════════════════════════════
#  Error-model helpers
# ═════════════════════════════════════════════════════════════════════════════
def pack_err(x_err: int, z_err: int) -> int:
    """Pack (x_err, z_err) into the 32-bit AXI-Lite input word."""
    assert 0 <= x_err < (1 << N_DATA), f"x_err={x_err} out of range"
    assert 0 <= z_err < (1 << N_DATA), f"z_err={z_err} out of range"
    return (z_err << N_DATA) | x_err


def sample_single_pauli(rng: np.random.Generator,
                        p: float) -> Tuple[int, int]:
    """
    Depolarising-style single-qubit Pauli error on one random qubit.

    With probability (1-p), no error. With probability p, pick a uniformly
    random Pauli in {X, Y, Z} and place it on a uniformly random qubit.
    """
    if rng.random() >= p:
        return 0, 0
    q     = int(rng.integers(0, N_DATA))
    pauli = int(rng.integers(0, 3))   # 0=X, 1=Y, 2=Z
    if pauli == 0:
        return (1 << q), 0
    elif pauli == 1:
        return (1 << q), (1 << q)
    else:
        return 0, (1 << q)


def sample_iid_depolarising(rng: np.random.Generator,
                            p: float) -> Tuple[int, int]:
    """
    IID depolarising channel: each qubit independently gets one of
    {I, X, Y, Z} with probabilities {1-p, p/3, p/3, p/3}.
    """
    x_err = 0
    z_err = 0
    for q in range(N_DATA):
        if rng.random() < (1 - p):
            continue
        bucket = int(rng.integers(0, 3))
        if bucket == 0:
            x_err |= (1 << q)
        elif bucket == 1:
            x_err |= (1 << q)
            z_err |= (1 << q)
        else:
            z_err |= (1 << q)
    return x_err, z_err


# ═════════════════════════════════════════════════════════════════════════════
#  API probe helper — call once to understand your XRT version's capabilities
# ═════════════════════════════════════════════════════════════════════════════
def probe_xrt_api(fpga: "ShorQECFPGA") -> None:
    """
    Print every public attribute on the run and kernel objects.
    Run with --probe-api to see what your installed XRT exposes.
    This is the fastest way to debug 'has no attribute X' errors in future.
    """
    log.info("── XRT API probe ──")
    for obj_name, obj in (("kernel", fpga.kernel), ("run", fpga.run)):
        attrs = [a for a in dir(obj) if not a.startswith("__")]
        log.info("%s attrs: %s", obj_name, ", ".join(attrs))

    # Try a live decode of the zero-error input so we can see the raw return
    packed = pack_err(0, 0)
    fpga.run.set_arg(0, packed)
    fpga.run.start()
    state = fpga.run.wait()
    log.info("run.wait() returned: %r (type: %s)", state, type(state).__name__)

    # Walk every plausible return-value API and log what each one gives
    for method in ("get_return_value", "get_arg_value"):
        if hasattr(fpga.run, method):
            try:
                if method == "get_arg_value":
                    val = fpga.run.get_arg_value(1)
                else:
                    val = fpga.run.get_return_value()
                log.info("run.%s() → 0x%08X", method, int(val))
            except Exception as exc:
                log.info("run.%s() raised: %s", method, exc)
        else:
            log.info("run.%s  → NOT PRESENT", method)

    for method in ("read_register",):
        if hasattr(fpga.kernel, method):
            try:
                val = fpga.kernel.read_register(AP_RETURN_OFFSET)
                log.info("kernel.read_register(0x%02X) → 0x%08X",
                         AP_RETURN_OFFSET, int(val))
            except Exception as exc:
                log.info("kernel.read_register raised: %s", exc)
        else:
            log.info("kernel.read_register → NOT PRESENT")

    # Callable-kernel API: kernel(arg0) returns result directly
    try:
        r = fpga.kernel(packed)
        log.info("kernel(packed) callable → 0x%08X", int(r))
    except Exception as exc:
        log.info("kernel(packed) callable raised: %s", exc)

    log.info("── probe complete — use the working method above in decode_one ──")


# ═════════════════════════════════════════════════════════════════════════════
#  PyXRT wrapper
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class ShorQECFPGA:
    xclbin_path:  str
    device_index: int = 0
    kernel_name:  str = KERNEL_NAME

    device:  Optional["xrt.device"]  = field(default=None, init=False, repr=False)
    xclbin:  Optional["xrt.xclbin"]  = field(default=None, init=False, repr=False)
    uuid:    Optional[object]        = field(default=None, init=False, repr=False)
    kernel:  Optional["xrt.kernel"]  = field(default=None, init=False, repr=False)
    run:     Optional["xrt.run"]     = field(default=None, init=False, repr=False)

    # _return_via: which API path was found to work (determined on first call)
    _return_via: str = field(default="", init=False, repr=False)

    # -------------------------------------------------------------------- open
    def open(self) -> None:
        if not XRT_AVAILABLE:
            raise RuntimeError(
                "pyxrt not available.\n"
                "Fix: source /opt/xilinx/xrt/setup.sh  then re-run.\n"
                "Or: export PYTHONPATH=/opt/xilinx/xrt/python:$PYTHONPATH"
            )
        if not os.path.exists(self.xclbin_path):
            raise FileNotFoundError(f"xclbin not found: {self.xclbin_path}")

        log.info("opening XRT device %d", self.device_index)
        self.device = xrt.device(self.device_index)

        # Log XRT version if available — helps triage API issues
        try:
            log.info("XRT version   : %s", self.device.get_info(
                xrt.xrt_info_device.xrt_info_device_version))
        except Exception:
            pass  # older XRT doesn't have get_info / xrt_info_device

        log.info("loading xclbin : %s", self.xclbin_path)
        self.xclbin = xrt.xclbin(self.xclbin_path)
        self.uuid   = self.device.load_xclbin(self.xclbin)

        # cu_access_mode.exclusive may not exist in very old XRT builds
        try:
            self.kernel = xrt.kernel(self.device, self.uuid, self.kernel_name,
                                     xrt.kernel.cu_access_mode.exclusive)
        except AttributeError:
            log.warning("cu_access_mode.exclusive not available — "
                        "opening kernel without access-mode flag")
            self.kernel = xrt.kernel(self.device, self.uuid, self.kernel_name)

        # Reuse one run handle across shots — much faster than per-shot alloc
        self.run = xrt.run(self.kernel)
        log.info("kernel ready  : %s", self.kernel_name)

    # --------------------------------------------------------------------- io
    def _detect_return_api(self) -> str:
        """
        Determine once which API call correctly reads the ap_return register.

        Priority order (most → least preferred):
          1. "callable"       kernel(arg) — pre-2.14, the documented path for
                              kernels with ap_ctrl_hs and no buffer args.
                              xrt.run is created internally and discarded.
          2. "get_return"     run.get_return_value() — XRT >= 2.14
          3. "run_index"      run[AP_RETURN_OFFSET]  — register-map subscript
          4. "read_register"  kernel.read_register(AP_RETURN_OFFSET) — raw read

        We probe by sending x_err=z_err=0 (no error → result should have
        syndrome=0x00, x_corr=0, z_corr=0, both log flags = 0, so result = 0).
        Any method that returns an integer without raising is accepted.
        """
        probe_input = pack_err(0, 0)
        log.info("detecting XRT return-value API …")

        # ── Method 1: callable kernel (most common on XRT 2.11–2.13) ──────
        # xrt.kernel.__call__(arg0, ...) fires the CU synchronously and
        # returns the ap_return value directly.  No separate xrt.run needed.
        try:
            result = self.kernel(probe_input)
            log.info("  method 1 (callable)      → 0x%08X  ✓", int(result))
            return "callable"
        except Exception as exc:
            log.info("  method 1 (callable)      → %s", exc)

        # For methods 2-4 we need the run handle to have executed once
        self.run.set_arg(0, probe_input)
        self.run.start()
        self.run.wait()

        # ── Method 2: get_return_value() — XRT >= 2.14 ───────────────────
        try:
            result = self.run.get_return_value()
            log.info("  method 2 (get_return_value) → 0x%08X  ✓", int(result))
            return "get_return"
        except AttributeError:
            log.info("  method 2 (get_return_value) → AttributeError")
        except Exception as exc:
            log.info("  method 2 (get_return_value) → %s", exc)

        # ── Method 3: run[offset] subscript (register-map read) ───────────
        try:
            result = self.run[AP_RETURN_OFFSET]
            log.info("  method 3 (run[0x%02X])      → 0x%08X  ✓",
                     AP_RETURN_OFFSET, int(result))
            return "run_index"
        except Exception as exc:
            log.info("  method 3 (run[0x%02X])      → %s", AP_RETURN_OFFSET, exc)

        # ── Method 4: kernel.read_register() ─────────────────────────────
        try:
            result = self.kernel.read_register(AP_RETURN_OFFSET)
            log.info("  method 4 (read_register)   → 0x%08X  ✓", int(result))
            return "read_register"
        except Exception as exc:
            log.info("  method 4 (read_register)   → %s", exc)

        raise RuntimeError(
            "None of the four XRT return-value APIs worked.\n"
            "Run with --probe-api for full diagnostics.\n"
            "Check: source /opt/xilinx/xrt/setup.sh and retry."
        )

    def decode_one(self, x_err: int, z_err: int) -> int:
        """
        Fire one decode shot and return the 32-bit result register.

        On the first call we auto-detect which XRT API works for this
        installation and cache it in self._return_via so every subsequent
        call takes the fast path immediately.
        """
        packed = pack_err(x_err, z_err)

        if not self._return_via:
            self._return_via = self._detect_return_api()
            log.info("using return API: %s", self._return_via)

        if self._return_via == "callable":
            # xrt.kernel.__call__ fires the CU and returns ap_return directly.
            # This is the recommended path for AXI-Lite-only kernels on the
            # XRT version installed on this machine.
            return int(self.kernel(packed))

        # For all other paths we use the pre-allocated run handle.
        self.run.set_arg(0, packed)
        self.run.start()
        self.run.wait()

        if self._return_via == "get_return":
            return int(self.run.get_return_value())

        if self._return_via == "run_index":
            return int(self.run[AP_RETURN_OFFSET])

        if self._return_via == "read_register":
            return int(self.kernel.read_register(AP_RETURN_OFFSET))

        raise RuntimeError(f"Unknown return API: {self._return_via!r}")

    def close(self) -> None:
        self.run    = None
        self.kernel = None
        self.xclbin = None
        self.device = None


# ═════════════════════════════════════════════════════════════════════════════
#  Monte Carlo sweep
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class SweepResult:
    p_phys:     List[float] = field(default_factory=list)
    p_logical:  List[float] = field(default_factory=list)
    n_shots:    int         = 0
    model:      str         = "single_pauli"
    timings_ms: List[float] = field(default_factory=list)


def run_sweep(fpga:    ShorQECFPGA,
              p_list:  List[float],
              n_shots: int,
              model:   str,
              seed:    int) -> SweepResult:
    rng     = np.random.default_rng(seed)
    sampler = (sample_single_pauli if model == "single_pauli"
               else sample_iid_depolarising)
    res     = SweepResult(n_shots=n_shots, model=model)

    for p in p_list:
        fails = 0
        t0    = time.perf_counter()
        for _ in range(n_shots):
            x_err, z_err = sampler(rng, p)
            result       = fpga.decode_one(x_err, z_err)
            x_log_err    = _bits(result, BIT_XLOG, BIT_XLOG)
            z_log_err    = _bits(result, BIT_ZLOG, BIT_ZLOG)
            if x_log_err or z_log_err:
                fails += 1
        dt  = time.perf_counter() - t0
        p_l = fails / n_shots
        res.p_phys.append(p)
        res.p_logical.append(p_l)
        res.timings_ms.append(dt * 1e3)
        log.info("p=%.4f  p_L=%.5f   (%d/%d fails)   %.1f ms   %.0f shots/s",
                 p, p_l, fails, n_shots, dt * 1e3, n_shots / dt)
    return res


# ═════════════════════════════════════════════════════════════════════════════
#  Plotting
# ═════════════════════════════════════════════════════════════════════════════
def plot_curve(res:         SweepResult,
               out_path:    str,
               overlay_png: Optional[str] = None) -> None:
    if not HAS_MPL:
        log.warning("matplotlib not installed — skipping plot")
        return

    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.loglog(res.p_phys, res.p_logical, "o-",
              color="#d62728", lw=2, ms=7,
              label="Shor [[9,1,3]] — FPGA LUT decoder")

    p_arr = np.array(res.p_phys)
    ax.loglog(p_arr, p_arr, "--", color="gray", alpha=0.6,
              label="break-even  p_L = p")

    ax.set_xlabel("Physical error rate  p", fontsize=12)
    ax.set_ylabel("Logical error rate  p_L", fontsize=12)
    ax.set_title(
        "Shor 9-qubit QEC on Alveo U55C\n"
        f"{res.n_shots} shots/point  ·  {res.model}  ·  C-DAC NQM Qniverse",
        fontsize=11,
    )
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=10, loc="best")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    log.info("plot saved    : %s", out_path)

    if overlay_png and os.path.exists(overlay_png):
        log.info("overlay hint  : compare with %s manually", overlay_png)


# ═════════════════════════════════════════════════════════════════════════════
#  Self-test — 27 single-qubit Pauli errors, all must correct cleanly
# ═════════════════════════════════════════════════════════════════════════════
def self_test(fpga: ShorQECFPGA) -> None:
    """Send every single-qubit Pauli error and verify zero logical failures."""
    log.info("── self-test: all 27 single-qubit Pauli errors ──")
    ok = 0
    for q in range(N_DATA):
        for name, (xm, zm) in (("X", (1 << q, 0)),
                               ("Y", (1 << q, 1 << q)),
                               ("Z", (0,       1 << q))):
            r     = fpga.decode_one(xm, zm)
            x_log = _bits(r, BIT_XLOG,    BIT_XLOG)
            z_log = _bits(r, BIT_ZLOG,    BIT_ZLOG)
            synd  = _bits(r, BIT_SYND_LO, BIT_SYND_HI)
            x_c   = _bits(r, BIT_X_CORR_LO, BIT_X_CORR_HI)
            z_c   = _bits(r, BIT_Z_CORR_LO, BIT_Z_CORR_HI)
            status = "PASS" if (x_log == 0 and z_log == 0) else "FAIL"
            log.info("  %-6s q%d  synd=0x%02X  x_corr=%s  z_corr=%s  "
                     "x_log=%d z_log=%d  %s",
                     name, q, synd,
                     bin(x_c)[2:].zfill(9), bin(z_c)[2:].zfill(9),
                     x_log, z_log, status)
            if status == "PASS":
                ok += 1

    log.info("self-test result: %d/27 corrected", ok)
    if ok != 27:
        raise RuntimeError(
            f"self-test FAILED: only {ok}/27 corrected. "
            "Check kernel LUT or syndrome logic."
        )
    log.info("self-test PASSED — kernel LUT correct for all weight-1 Paulis")


# ═════════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="Shor QEC FPGA host — Alveo U55C")
    ap.add_argument("--xclbin",   default="shor_qec_kernel.xclbin",
                    help="path to compiled .xclbin  [%(default)s]")
    ap.add_argument("--device",   type=int, default=0,
                    help="XRT device index  [%(default)s]")
    ap.add_argument("--shots",    type=int, default=10_000,
                    help="Monte Carlo shots per error-rate point  [%(default)s]")
    ap.add_argument("--model",    choices=["single_pauli", "iid_depol"],
                    default="single_pauli",
                    help="error model for the sweep  [%(default)s]")
    ap.add_argument("--p",        nargs="+", type=float,
                    default=[0.001, 0.005, 0.01, 0.05],
                    help="physical error rates to sweep")
    ap.add_argument("--seed",     type=int, default=0xC0DE,
                    help="RNG seed  [%(default)s]")
    ap.add_argument("--plot",     default="shor_qec_fpga_curve.png",
                    help="output PNG filename  [%(default)s]")
    ap.add_argument("--overlay",  default="cudaqx_qec_v6_threshold.png",
                    help="existing GPU threshold PNG for reference")
    ap.add_argument("--no-selftest", action="store_true",
                    help="skip the 27-shot self-test")
    ap.add_argument("--probe-api",   action="store_true",
                    help="print all XRT run/kernel methods and exit "
                         "(use this to debug future API changes)")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("  Shor 9-qubit QEC   |   Alveo U55C   |   C-DAC NQM Qniverse")
    log.info("=" * 65)

    fpga = ShorQECFPGA(xclbin_path=args.xclbin, device_index=args.device)
    try:
        fpga.open()

        if args.probe_api:
            probe_xrt_api(fpga)
            return 0

        if not args.no_selftest:
            self_test(fpga)

        log.info("── Monte Carlo sweep: %s, %d shots/point ──",
                 args.model, args.shots)
        res = run_sweep(fpga, args.p, args.shots, args.model, args.seed)
        plot_curve(res, args.plot, overlay_png=args.overlay)

    finally:
        fpga.close()

    log.info("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())