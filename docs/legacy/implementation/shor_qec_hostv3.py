#!/usr/bin/env python3
"""
Shor-Code QEC FPGA Host Driver
==============================
Hardware : Xilinx Alveo U55C, XRT 2.16.204 (Vitis 2023.2 branch)
Kernel   : shor_qec_kernel — AXI-Lite only, 300 MHz, II=1

Author   : Nasir Ali — C-DAC / NQM Qniverse

Fix history
-----------
v1  original — used get_return_value() / get_arg_value(1): both missing in
    XRT 2.16 pyxrt binding.

v2  four-method probe ladder — callable/get_return/run[]/read_register:
    all missing. kernel(arg) returns pyxrt.run, not int.

v3  (this file) — definitive fix for XRT 2.16.204 pyxrt binding.

Root cause — confirmed by xrt_probe2.py output
----------------------------------------------
XRT 2.16 pyxrt exposes exactly 5 methods on pyxrt.run:
    add_callback, set_arg, start, state, wait
There is NO Python-level return-value accessor anywhere in this binding.

set_arg() accepts ONLY:
    run.set_arg(idx, int)        ← scalar input
    run.set_arg(idx, xrt::bo)    ← buffer object

xbutil examine --report dynamic-regions confirmed:
    shor_qec_kernel:shor_qec_kernel_1   Base Address  0x800000

ap_return sits at CU_base + 0x18 = 0x800018 inside BAR4 (resource4).
resource4 requires 'render' group membership or sudo.

SOLUTION — three decode paths, tried in order:
  Path A (preferred, no sudo):
    Allocate a 4-byte xrt.bo using xrt.XCL_BO_FLAGS_NONE (top-level
    constant — NOT pyxrt.bo.flags which doesn't exist in this version).
    Bind it to arg index 1 via run.set_arg(1, bo).
    After wait(), sync BO FROM_DEVICE and unpack 4 bytes.

  Path B (needs 'render' group):
    mmap BAR4 resource4 at page-aligned offset covering CU_BASE (0x800000).
    Read 4 bytes at CU_BASE + 0x18 after each wait().
    To unlock: sudo usermod -aG render abhishek  (then re-login)

  Path C (always works, bypasses xclbin):
    Pure-Python reimplementation of shor_qec_kernel.cpp.
    Correct results but does NOT exercise the real FPGA bitstream.
    Use --sw-only flag to force this path for CI / no-hardware environments.
"""

from __future__ import annotations

import argparse
import logging
import mmap
import os
import struct
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

# ── XRT ──────────────────────────────────────────────────────────────────────
try:
    import pyxrt as xrt
    XRT_AVAILABLE = True
except ImportError:
    XRT_AVAILABLE = False

# ── Matplotlib ───────────────────────────────────────────────────────────────
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-5s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("shor_qec")

# ═════════════════════════════════════════════════════════════════════════════
#  Kernel interface constants
# ═════════════════════════════════════════════════════════════════════════════
N_DATA      = 9
KERNEL_NAME = "shor_qec_kernel"

BIT_X_CORR_LO, BIT_X_CORR_HI =  0,  8
BIT_Z_CORR_LO, BIT_Z_CORR_HI =  9, 17
BIT_SYND_LO,   BIT_SYND_HI   = 18, 25
BIT_XLOG = 26
BIT_ZLOG = 27

# ap_return byte offset inside the CU register map (ap_ctrl_hs, 1 scalar input)
AP_RETURN_OFFSET = 0x18

# CU base address — from: xbutil examine --report dynamic-regions
# shor_qec_kernel:shor_qec_kernel_1  Base Address: 0x800000
CU_BASE_ADDR = 0x800000

# All four U55C user-PF sysfs paths on this machine
PCI_RESOURCE4_PATHS = [
    "/sys/bus/pci/devices/0000:01:00.1/resource4",
    "/sys/bus/pci/devices/0000:21:00.1/resource4",
    "/sys/bus/pci/devices/0000:41:00.1/resource4",
    "/sys/bus/pci/devices/0000:81:00.1/resource4",
]


def _bits(word: int, lo: int, hi: int) -> int:
    return (word >> lo) & ((1 << (hi - lo + 1)) - 1)


def pack_err(x_err: int, z_err: int) -> int:
    assert 0 <= x_err < (1 << N_DATA)
    assert 0 <= z_err < (1 << N_DATA)
    return (z_err << N_DATA) | x_err


# ═════════════════════════════════════════════════════════════════════════════
#  Software-only decoder — identical logic to shor_qec_kernel.cpp
# ═════════════════════════════════════════════════════════════════════════════
def _sw_syndrome(xe: int, ze: int) -> int:
    s  = ((xe >> 0 ^ xe >> 1) & 1) << 0   # S0 = Z0Z1
    s |= ((xe >> 1 ^ xe >> 2) & 1) << 1   # S1 = Z1Z2
    s |= ((xe >> 3 ^ xe >> 4) & 1) << 2   # S2 = Z3Z4
    s |= ((xe >> 4 ^ xe >> 5) & 1) << 3   # S3 = Z4Z5
    s |= ((xe >> 6 ^ xe >> 7) & 1) << 4   # S4 = Z6Z7
    s |= ((xe >> 7 ^ xe >> 8) & 1) << 5   # S5 = Z7Z8
    p6 = p7 = 0
    for i in range(6):
        p6 ^= (ze >> i) & 1
        p7 ^= (ze >> (i + 3)) & 1
    s |= p6 << 6   # S6 = X0..X5
    s |= p7 << 7   # S7 = X3..X8
    return s


def _build_sw_lut() -> list:
    lut = [0] * 256
    def s(idx, xc, zc): lut[idx] = (zc << 9) | xc
    # X errors
    s(0x01,1<<0,0); s(0x03,1<<1,0); s(0x02,1<<2,0)
    s(0x04,1<<3,0); s(0x0C,1<<4,0); s(0x08,1<<5,0)
    s(0x10,1<<6,0); s(0x30,1<<7,0); s(0x20,1<<8,0)
    # Z errors (block degenerate)
    s(0x40,0,1<<0); s(0xC0,0,1<<3); s(0x80,0,1<<6)
    # Y errors
    s(0x41,1<<0,1<<0); s(0x43,1<<1,1<<1); s(0x42,1<<2,1<<2)
    s(0xC4,1<<3,1<<3); s(0xC8,1<<5,1<<5); s(0xCC,1<<4,1<<4)
    s(0x90,1<<6,1<<6); s(0xB0,1<<7,1<<7); s(0xA0,1<<8,1<<8)
    return lut


_SW_LUT = _build_sw_lut()


def sw_decode(x_err: int, z_err: int) -> int:
    """Pure-Python decode — mirrors shor_qec_kernel.cpp exactly."""
    synd  = _sw_syndrome(x_err, z_err)
    word  = _SW_LUT[synd]
    xc    = word & 0x1FF
    zc    = (word >> 9) & 0x1FF
    xfix  = x_err ^ xc
    zfix  = z_err ^ zc
    xl    = (xfix >> 0 ^ xfix >> 3 ^ xfix >> 6) & 1
    zl    = 0
    for i in range(9): zl ^= (zfix >> i) & 1
    return xc | (zc << 9) | (synd << 18) | (xl << 26) | (zl << 27)


# ═════════════════════════════════════════════════════════════════════════════
#  Error models
# ═════════════════════════════════════════════════════════════════════════════
def sample_single_pauli(rng: np.random.Generator, p: float) -> Tuple[int, int]:
    if rng.random() >= p:
        return 0, 0
    q = int(rng.integers(0, N_DATA))
    t = int(rng.integers(0, 3))
    if t == 0: return (1 << q), 0
    if t == 1: return (1 << q), (1 << q)
    return 0, (1 << q)


def sample_iid_depolarising(rng: np.random.Generator, p: float) -> Tuple[int, int]:
    xe = ze = 0
    for q in range(N_DATA):
        if rng.random() < (1 - p): continue
        b = int(rng.integers(0, 3))
        if b == 0:   xe |= 1 << q
        elif b == 1: xe |= 1 << q; ze |= 1 << q
        else:        ze |= 1 << q
    return xe, ze


# ═════════════════════════════════════════════════════════════════════════════
#  PyXRT wrapper
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class ShorQECFPGA:
    xclbin_path:  str
    device_index: int = 0
    kernel_name:  str = KERNEL_NAME

    device:  Optional[object] = field(default=None, init=False, repr=False)
    xclbin:  Optional[object] = field(default=None, init=False, repr=False)
    uuid:    Optional[object] = field(default=None, init=False, repr=False)
    kernel:  Optional[object] = field(default=None, init=False, repr=False)
    run:     Optional[object] = field(default=None, init=False, repr=False)

    _result_bo:  Optional[object] = field(default=None, init=False, repr=False)
    _bar4_mm:    Optional[object] = field(default=None, init=False, repr=False)
    _bar4_file:  Optional[object] = field(default=None, init=False, repr=False)
    _bar4_off:   int              = field(default=0,    init=False, repr=False)
    _return_via: str              = field(default="",   init=False, repr=False)

    # ------------------------------------------------------------------ open
    def open(self) -> None:
        if not XRT_AVAILABLE:
            raise RuntimeError(
                "pyxrt not available.\n"
                "Fix: source /opt/xilinx/xrt/setup.sh"
            )
        if not os.path.exists(self.xclbin_path):
            raise FileNotFoundError(self.xclbin_path)

        log.info("opening XRT device %d", self.device_index)
        self.device = xrt.device(self.device_index)

        log.info("loading xclbin : %s", self.xclbin_path)
        self.xclbin = xrt.xclbin(self.xclbin_path)
        self.uuid   = self.device.load_xclbin(self.xclbin)

        try:
            self.kernel = xrt.kernel(self.device, self.uuid, self.kernel_name,
                                     xrt.kernel.cu_access_mode.exclusive)
        except AttributeError:
            self.kernel = xrt.kernel(self.device, self.uuid, self.kernel_name)

        self.run = xrt.run(self.kernel)
        log.info("kernel ready  : %s", self.kernel_name)

    # ---------------------------------------------------------- path detection
    # Known-correct probe input: X error on q0
    #   x_err=1, z_err=0  →  syndrome=0x01  →  x_corr=0x001  z_corr=0
    #   result = (0x01 << 18) | 0x001 = 0x00040001
    _PROBE_PACKED   = 1          # pack_err(1, 0)
    _PROBE_EXPECTED = 0x00040001

    def _try_path_a(self) -> bool:
        """
        Path A — xrt.bo bound to arg 1 as the ap_return output slot.

        XRT 2.16 set_arg() signature (confirmed by probe):
            set_arg(int, int)      ← scalar input only
            set_arg(int, xrt::bo)  ← buffer output

        The correct BO flag in this version is the TOP-LEVEL constant
        xrt.XCL_BO_FLAGS_NONE, NOT xrt.bo.flags.XCL_BO_FLAGS_NONE
        (that nested path doesn't exist here).

        kernel.group_id(1) returns the memory bank group for arg 1.
        For an AXI-Lite-only kernel this is always group 0, but we
        ask the kernel object so the code is version-proof.
        """
        log.info("  path A: xrt.bo output buffer at arg index 1 …")
        try:
            grp = self.kernel.group_id(1)
            bo  = xrt.bo(self.device, 4, xrt.XCL_BO_FLAGS_NONE, grp)

            r = xrt.run(self.kernel)
            r.set_arg(0, self._PROBE_PACKED)
            r.set_arg(1, bo)
            r.start()
            r.wait()
            bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE)
            raw = bo.read(4, 0)
            val = struct.unpack("<I", bytes(raw))[0]
            log.info("    probe → 0x%08X  (expected 0x%08X)", val, self._PROBE_EXPECTED)

            if val == self._PROBE_EXPECTED:
                self._result_bo = bo
                # Pre-bind the BO to the reusable run handle
                self.run.set_arg(1, self._result_bo)
                log.info("    path A: CONFIRMED ✓")
                return True
            log.info("    path A: result mismatch — skipping")
            return False
        except Exception as e:
            log.info("    path A failed: %s", e)
            return False

    def _try_path_b(self) -> bool:
        """
        Path B — direct MMIO of CU register space via mmap of BAR4.

        CU base 0x800000 confirmed by:
            xbutil examine --device 0000:01:00.1 --report dynamic-regions

        mmap requires page-aligned offset, so we align down to 4 KiB
        and store the remainder offset for the actual register read.

        Needs user in 'render' group:
            sudo usermod -aG render abhishek
            (log out and back in for group change to take effect)
        """
        log.info("  path B: BAR4 mmap @ CU_BASE=0x%X + 0x18 …", CU_BASE_ADDR)
        page    = mmap.PAGESIZE
        map_off = (CU_BASE_ADDR // page) * page
        off_in  = (CU_BASE_ADDR - map_off) + AP_RETURN_OFFSET

        for path in PCI_RESOURCE4_PATHS:
            if not os.path.exists(path):
                continue
            try:
                f  = open(path, "rb")
                mm = mmap.mmap(f.fileno(), off_in + 4,
                               mmap.MAP_SHARED, mmap.PROT_READ,
                               offset=map_off)

                # Fire a probe shot so hardware writes a known result
                rp = xrt.run(self.kernel)
                rp.set_arg(0, self._PROBE_PACKED)
                rp.start()
                rp.wait()

                raw = mm[off_in: off_in + 4]
                val = struct.unpack("<I", raw)[0]
                log.info("    %s @ off=0x%X → 0x%08X  (expected 0x%08X)",
                         path, off_in, val, self._PROBE_EXPECTED)

                if val == self._PROBE_EXPECTED:
                    self._bar4_mm   = mm
                    self._bar4_file = f
                    self._bar4_off  = off_in
                    log.info("    path B: CONFIRMED ✓  using %s", path)
                    return True
                log.info("    path B: result mismatch at %s", path)
                mm.close(); f.close()
            except PermissionError:
                log.info("    %s: PermissionError", path)
                log.info("    Fix: sudo usermod -aG render %s  (then re-login)",
                         os.environ.get("USER", "abhishek"))
            except Exception as e:
                log.info("    %s: %s", path, e)
        return False

    def _try_path_c(self) -> bool:
        """Path C — software-only decoder. Always succeeds."""
        log.warning("  path C: software decoder active — xclbin NOT exercised")
        log.warning("  To use real hardware, run ONE of:")
        log.warning("    sudo usermod -aG render %s  (then re-login)",
                    os.environ.get("USER", "abhishek"))
        log.warning("    OR: sudo python3 shor_qec_host.py ...")
        return True

    def _detect_path(self) -> None:
        log.info("detecting decode path for XRT 2.16.204 …")
        if self._try_path_a():
            self._return_via = "bo"
        elif self._try_path_b():
            self._return_via = "mmap"
        else:
            self._try_path_c()
            self._return_via = "sw"
        log.info("active decode path: %s", self._return_via)

    # ---------------------------------------------------------------- decode
    def decode_one(self, x_err: int, z_err: int) -> int:
        """Fire one decode and return the 32-bit result register."""
        if not self._return_via:
            self._detect_path()

        packed = pack_err(x_err, z_err)

        if self._return_via == "bo":
            self.run.set_arg(0, packed)
            # arg 1 already bound to self._result_bo from detection
            self.run.start()
            self.run.wait()
            self._result_bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE)
            raw = self._result_bo.read(4, 0)
            return struct.unpack("<I", bytes(raw))[0]

        if self._return_via == "mmap":
            self.run.set_arg(0, packed)
            self.run.start()
            self.run.wait()
            raw = self._bar4_mm[self._bar4_off: self._bar4_off + 4]
            return struct.unpack("<I", raw)[0]

        # "sw" path
        return sw_decode(x_err, z_err)

    def close(self) -> None:
        if self._bar4_mm:
            try: self._bar4_mm.close()
            except Exception: pass
        if self._bar4_file:
            try: self._bar4_file.close()
            except Exception: pass
        self.run = self.kernel = self.xclbin = self.device = None


# ═════════════════════════════════════════════════════════════════════════════
#  Monte Carlo sweep
# ═════════════════════════════════════════════════════════════════════════════
@dataclass
class SweepResult:
    p_phys:      List[float] = field(default_factory=list)
    p_logical:   List[float] = field(default_factory=list)
    n_shots:     int         = 0
    model:       str         = "single_pauli"
    timings_ms:  List[float] = field(default_factory=list)
    decode_path: str         = ""


def run_sweep(fpga: ShorQECFPGA, p_list: List[float],
              n_shots: int, model: str, seed: int) -> SweepResult:
    rng     = np.random.default_rng(seed)
    sampler = (sample_single_pauli if model == "single_pauli"
               else sample_iid_depolarising)
    res     = SweepResult(n_shots=n_shots, model=model,
                          decode_path=fpga._return_via)
    for p in p_list:
        fails = 0
        t0    = time.perf_counter()
        for _ in range(n_shots):
            xe, ze = sampler(rng, p)
            r      = fpga.decode_one(xe, ze)
            if _bits(r, BIT_XLOG, BIT_XLOG) or _bits(r, BIT_ZLOG, BIT_ZLOG):
                fails += 1
        dt  = time.perf_counter() - t0
        p_l = fails / n_shots
        res.p_phys.append(p)
        res.p_logical.append(p_l)
        res.timings_ms.append(dt * 1e3)
        log.info("p=%.4f  p_L=%.5f   (%d/%d)   %.1f ms   %.0f shots/s",
                 p, p_l, fails, n_shots, dt * 1e3, n_shots / dt)
    return res


# ═════════════════════════════════════════════════════════════════════════════
#  Plotting
# ═════════════════════════════════════════════════════════════════════════════
def plot_curve(res: SweepResult, out_path: str,
               overlay_png: Optional[str] = None) -> None:
    if not HAS_MPL:
        log.warning("matplotlib not installed — skipping plot")
        return
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.loglog(res.p_phys, res.p_logical, "o-",
              color="#d62728", lw=2, ms=7,
              label=f"Shor [[9,1,3]] — {res.decode_path} decoder")
    p_arr = np.array(res.p_phys)
    ax.loglog(p_arr, p_arr, "--", color="gray", alpha=0.6,
              label="break-even  p_L = p")
    ax.set_xlabel("Physical error rate  p", fontsize=12)
    ax.set_ylabel("Logical error rate  p_L", fontsize=12)
    ax.set_title(
        f"Shor 9-qubit QEC · Alveo U55C · {res.decode_path}\n"
        f"{res.n_shots} shots/point · {res.model} · C-DAC NQM Qniverse",
        fontsize=11)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=10)
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    log.info("plot saved: %s", out_path)


# ═════════════════════════════════════════════════════════════════════════════
#  Self-test
# ═════════════════════════════════════════════════════════════════════════════
def self_test(fpga: ShorQECFPGA) -> None:
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
            xc    = _bits(r, BIT_X_CORR_LO, BIT_X_CORR_HI)
            zc    = _bits(r, BIT_Z_CORR_LO, BIT_Z_CORR_HI)
            status = "PASS" if (x_log == 0 and z_log == 0) else "FAIL"
            log.info("  %-6s q%d  synd=0x%02X  x_corr=%s  z_corr=%s  %s",
                     name, q, synd,
                     bin(xc)[2:].zfill(9), bin(zc)[2:].zfill(9), status)
            if status == "PASS":
                ok += 1

    log.info("self-test: %d/27", ok)
    if fpga._return_via == "sw":
        log.warning("NOTE: self-test ran against SOFTWARE decoder, not the xclbin.")
        log.warning("To verify real hardware: sudo usermod -aG render %s",
                    os.environ.get("USER", "abhishek"))
    elif ok != 27:
        raise RuntimeError(f"self-test FAILED: {ok}/27 — check kernel LUT")
    else:
        log.info("self-test PASSED — kernel LUT verified on hardware ✓")


# ═════════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════════
def main() -> int:
    ap = argparse.ArgumentParser(description="Shor QEC FPGA host — Alveo U55C")
    ap.add_argument("--xclbin",      default="shor_qec_kernel.xclbin")
    ap.add_argument("--device",      type=int, default=0)
    ap.add_argument("--shots",       type=int, default=10_000)
    ap.add_argument("--model",       choices=["single_pauli", "iid_depol"],
                    default="single_pauli")
    ap.add_argument("--p",           nargs="+", type=float,
                    default=[0.001, 0.005, 0.01, 0.05])
    ap.add_argument("--seed",        type=int, default=0xC0DE)
    ap.add_argument("--plot",        default="shor_qec_fpga_curve.png")
    ap.add_argument("--overlay",     default="cudaqx_qec_v6_threshold.png")
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--sw-only",     action="store_true",
                    help="force software decoder (no FPGA access needed)")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("  Shor 9-qubit QEC   |   Alveo U55C   |   C-DAC NQM Qniverse")
    log.info("=" * 65)

    fpga = ShorQECFPGA(xclbin_path=args.xclbin, device_index=args.device)
    try:
        if args.sw_only:
            log.info("--sw-only: skipping FPGA open, using software decoder")
            fpga._return_via = "sw"
        else:
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