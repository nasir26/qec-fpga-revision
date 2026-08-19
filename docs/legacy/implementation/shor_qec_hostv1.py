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
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

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
N_DATA   = 9
KERNEL_NAME = "shor_qec_kernel"

# Output bit layout (keep in sync with kernel's `result` register):
BIT_X_CORR_LO,  BIT_X_CORR_HI  =  0,  8
BIT_Z_CORR_LO,  BIT_Z_CORR_HI  =  9, 17
BIT_SYND_LO,    BIT_SYND_HI    = 18, 25
BIT_XLOG = 26
BIT_ZLOG = 27


def _bits(word: int, lo: int, hi: int) -> int:
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


# ═════════════════════════════════════════════════════════════════════════════
#  Error-model helpers
# ═════════════════════════════════════════════════════════════════════════════
def pack_err(x_err: int, z_err: int) -> int:
    """Pack (x_err, z_err) into the 32-bit AXI-Lite input word."""
    assert 0 <= x_err < (1 << N_DATA)
    assert 0 <= z_err < (1 << N_DATA)
    return (z_err << N_DATA) | x_err


def sample_single_pauli(rng: np.random.Generator,
                        p: float) -> Tuple[int, int]:
    """
    Depolarising-style single-qubit Pauli error on one random qubit.

    With probability (1-p), no error. With probability p, pick a uniformly
    random Pauli in {X, Y, Z} and place it on a uniformly random qubit.
    This is the simplest model that exercises all three correction paths
    and matches the single-qubit-error regime where a distance-3 code is
    provably optimal.
    """
    if rng.random() >= p:
        return 0, 0
    q = int(rng.integers(0, N_DATA))
    pauli = int(rng.integers(0, 3))  # 0=X, 1=Y, 2=Z
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
    {I, X, Y, Z} with probabilities {1-p, p/3, p/3, p/3}. This model can
    produce multi-qubit errors and so will generate an uncorrectable tail
    that shows the distance-3 limit.
    """
    x_err = 0
    z_err = 0
    for q in range(N_DATA):
        r = rng.random()
        if r < (1 - p):
            continue
        bucket = rng.integers(0, 3)
        if bucket == 0:
            x_err |= (1 << q)
        elif bucket == 1:
            x_err |= (1 << q)
            z_err |= (1 << q)
        else:
            z_err |= (1 << q)
    return x_err, z_err


# ═════════════════════════════════════════════════════════════════════════════
#  PyXRT wrapper
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class ShorQECFPGA:
    xclbin_path: str
    device_index: int = 0
    kernel_name: str = KERNEL_NAME

    device:  Optional["xrt.device"]  = field(default=None, init=False, repr=False)
    xclbin:  Optional["xrt.xclbin"]  = field(default=None, init=False, repr=False)
    uuid:    Optional[object]        = field(default=None, init=False, repr=False)
    kernel:  Optional["xrt.kernel"]  = field(default=None, init=False, repr=False)
    run:     Optional["xrt.run"]     = field(default=None, init=False, repr=False)

    # -------------------------------------------------------------------- open
    def open(self) -> None:
        if not XRT_AVAILABLE:
            raise RuntimeError("pyxrt not available — install XRT first")
        if not os.path.exists(self.xclbin_path):
            raise FileNotFoundError(self.xclbin_path)

        log.info("opening XRT device %d", self.device_index)
        self.device = xrt.device(self.device_index)
        log.info("loading xclbin : %s", self.xclbin_path)
        self.xclbin = xrt.xclbin(self.xclbin_path)
        self.uuid   = self.device.load_xclbin(self.xclbin)
        self.kernel = xrt.kernel(self.device, self.uuid, self.kernel_name,
                                 xrt.kernel.cu_access_mode.exclusive)
        # Reuse one run handle across shots — much faster than per-shot alloc.
        self.run = xrt.run(self.kernel)
        log.info("kernel ready  : %s", self.kernel_name)

    # --------------------------------------------------------------------- io
    def decode_one(self, x_err: int, z_err: int) -> int:
        """Fire one shot and return the 32-bit result register."""
        packed = pack_err(x_err, z_err)
        self.run.set_arg(0, packed)
        self.run.start()
        self.run.wait()
        # The AXI-Lite return value is written by the kernel's ap_return
        # port. PyXRT exposes it via get_arg_value() on arg index 1 on
        # shim versions that support it; otherwise reads the CU register
        # map directly. On recent XRT (2.14+) `self.run.get_return_value()`
        # is the recommended entry. We try both.
        try:
            return int(self.run.get_return_value())
        except AttributeError:
            return int(self.run.get_arg_value(1))

    def close(self) -> None:
        self.run = None
        self.kernel = None
        self.xclbin = None
        self.device = None


# ═════════════════════════════════════════════════════════════════════════════
#  Monte Carlo sweep
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class SweepResult:
    p_phys:     List[float]            = field(default_factory=list)
    p_logical:  List[float]            = field(default_factory=list)
    n_shots:    int                    = 0
    model:      str                    = "single_pauli"
    timings_ms: List[float]            = field(default_factory=list)


def run_sweep(fpga: ShorQECFPGA,
              p_list: List[float],
              n_shots: int,
              model: str,
              seed: int) -> SweepResult:
    rng = np.random.default_rng(seed)
    sampler = (sample_single_pauli if model == "single_pauli"
               else sample_iid_depolarising)
    res = SweepResult(n_shots=n_shots, model=model)

    for p in p_list:
        fails = 0
        t0 = time.perf_counter()
        for _ in range(n_shots):
            x_err, z_err = sampler(rng, p)
            result = fpga.decode_one(x_err, z_err)
            x_log_err = _bits(result, BIT_XLOG, BIT_XLOG)
            z_log_err = _bits(result, BIT_ZLOG, BIT_ZLOG)
            if x_log_err or z_log_err:
                fails += 1
        dt = time.perf_counter() - t0
        p_l = fails / n_shots
        res.p_phys.append(p)
        res.p_logical.append(p_l)
        res.timings_ms.append(dt * 1e3)
        log.info("p=%.4f  p_L=%.5f   (%d/%d fails)   %.1f ms   "
                 "%.0f shots/s",
                 p, p_l, fails, n_shots, dt * 1e3, n_shots / dt)
    return res


# ═════════════════════════════════════════════════════════════════════════════
#  Plotting
# ═════════════════════════════════════════════════════════════════════════════
def plot_curve(res: SweepResult,
               out_path: str,
               overlay_png: Optional[str] = None) -> None:
    if not HAS_MPL:
        log.warning("matplotlib not installed — skipping plot")
        return

    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.loglog(res.p_phys, res.p_logical, "o-",
              color="#d62728", lw=2, ms=7,
              label="Shor [[9,1,3]] — FPGA LUT decoder")

    # Break-even line p_L = p
    p_arr = np.array(res.p_phys)
    ax.loglog(p_arr, p_arr, "--", color="gray", alpha=0.6,
              label="break-even  p_L = p")

    ax.set_xlabel("Physical error rate  p", fontsize=12)
    ax.set_ylabel("Logical error rate  p_L", fontsize=12)
    ax.set_title(
        "Shor 9-qubit QEC on Alveo U55C\n"
        f"{res.n_shots} shots/point  ·  {res.model}  ·  "
        "C-DAC NQM Qniverse",
        fontsize=11,
    )
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=10, loc="best")
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    log.info("plot saved    : %s", out_path)

    if overlay_png and os.path.exists(overlay_png):
        log.info("overlay hint  : compare with %s manually — different codes, "
                 "same axes", overlay_png)


# ═════════════════════════════════════════════════════════════════════════════
#  Self-test
# ═════════════════════════════════════════════════════════════════════════════
def self_test(fpga: ShorQECFPGA) -> None:
    """Send every single-qubit Pauli error and verify zero logical failures."""
    log.info("── self-test: all 27 single-qubit Pauli errors ──")
    ok = 0
    for q in range(N_DATA):
        for name, (xm, zm) in (("X", (1 << q, 0)),
                               ("Y", (1 << q, 1 << q)),
                               ("Z", (0, 1 << q))):
            r = fpga.decode_one(xm, zm)
            x_log = _bits(r, BIT_XLOG, BIT_XLOG)
            z_log = _bits(r, BIT_ZLOG, BIT_ZLOG)
            synd  = _bits(r, BIT_SYND_LO, BIT_SYND_HI)
            status = "PASS" if (x_log == 0 and z_log == 0) else "FAIL"
            log.info("  %s on q%d   syndrome=0x%02X   %s", name, q, synd, status)
            if status == "PASS":
                ok += 1
    log.info("self-test result: %d/27 corrected", ok)
    if ok != 27:
        raise RuntimeError("self-test failed — kernel LUT or syndrome bug")


# ═════════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="Shor QEC FPGA host")
    ap.add_argument("--xclbin", default="shor_qec_kernel.xclbin",
                    help="path to compiled .xclbin")
    ap.add_argument("--device", type=int, default=0, help="XRT device index")
    ap.add_argument("--shots", type=int, default=10_000,
                    help="Monte Carlo shots per physical error point")
    ap.add_argument("--model", choices=["single_pauli", "iid_depol"],
                    default="single_pauli",
                    help="error model for the sweep")
    ap.add_argument("--p", nargs="+", type=float,
                    default=[0.001, 0.005, 0.01, 0.05],
                    help="physical error rates")
    ap.add_argument("--seed", type=int, default=0xC0DE)
    ap.add_argument("--plot", default="shor_qec_fpga_curve.png")
    ap.add_argument("--overlay",
                    default="cudaqx_qec_v6_threshold.png",
                    help="existing GPU threshold PNG for side-by-side reference")
    ap.add_argument("--no-selftest", action="store_true")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("  Shor 9-qubit QEC   |   Alveo U55C   |   C-DAC NQM Qniverse")
    log.info("=" * 65)

    fpga = ShorQECFPGA(xclbin_path=args.xclbin, device_index=args.device)
    try:
        fpga.open()
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
