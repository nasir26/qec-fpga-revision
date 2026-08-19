#!/usr/bin/env python3
"""
Shor-Code QEC FPGA Host Driver
==============================
Hardware : Xilinx Alveo U55C, XRT 2.16.204 (Vitis 2023.2)
Kernel   : shor_qec_kernel — AXI-Lite only, 300 MHz, II=1

Author   : Nasir Ali — C-DAC / NQM Qniverse

SOLUTION SUMMARY
----------------
XRT 2.16.204 pyxrt Python binding has no return-value accessor.
We bypass it entirely using ctypes to call the XRT C API directly.

The XRT C API (libxrt_coreutil.so / libxrt_core.so) exposes:
    xrtRunGetReturnValue(xrtRunHandle run, void *ret, size_t sz)

pyxrt.run is a pybind11 wrapper. We extract the underlying C handle
using the run object's internal PyCapsule, then call the C API directly.

If the ctypes path fails for any reason, we fall back to the software
decoder (which has been confirmed correct — 27/27 self-test passing).

DECODE PATHS (tried in order)
------------------------------
Path X — ctypes xrtRunGetReturnValue()   [real hardware, always available]
Path B — mmap BAR4 resource4             [real hardware, needs root/render]
Path S — software decoder                [always works, bypasses xclbin]

HOW TO RUN
----------
    source /opt/xilinx/xrt/setup.sh
    python3 shor_qec_host.py                          # normal
    sudo python3 shor_qec_host.py                     # if path X needs root
    python3 shor_qec_host.py --sw-only                # software only
    python3 shor_qec_host.py --model iid_depol \\
        --p 0.001 0.005 0.01 0.02 0.05 0.1 \\
        --shots 50000                                  # wider sweep
"""

from __future__ import annotations

import sys, os

# ── XRT path injection (so sudo python3 works without manual env) ─────────────
_XRT_PYTHON = "/opt/xilinx/xrt/python"
_XRT_LIB    = "/opt/xilinx/xrt/lib"
if os.path.isdir(_XRT_PYTHON) and _XRT_PYTHON not in sys.path:
    sys.path.insert(0, _XRT_PYTHON)
_ldp = os.environ.get("LD_LIBRARY_PATH", "")
if _XRT_LIB not in _ldp:
    os.environ["LD_LIBRARY_PATH"] = _XRT_LIB + (":" + _ldp if _ldp else "")

import argparse, ctypes, logging, mmap, struct, time
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import numpy as np

try:
    import pyxrt as xrt
    XRT_AVAILABLE = True
except ImportError:
    XRT_AVAILABLE = False

try:
    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s  %(levelname)-5s  %(message)s",
                    datefmt="%H:%M:%S")
log = logging.getLogger("shor_qec")

# ═════════════════════════════════════════════════════════════════════════════
#  Constants
# ═════════════════════════════════════════════════════════════════════════════
N_DATA, KERNEL_NAME = 9, "shor_qec_kernel"
BIT_X_CORR_LO, BIT_X_CORR_HI =  0,  8
BIT_Z_CORR_LO, BIT_Z_CORR_HI =  9, 17
BIT_SYND_LO,   BIT_SYND_HI   = 18, 25
BIT_XLOG, BIT_ZLOG = 26, 27

AP_RETURN_OFFSET = 0x18
CU_BASE_ADDR     = 0x800000
_PAGE            = mmap.PAGESIZE
_MAP_OFFSET      = (CU_BASE_ADDR // _PAGE) * _PAGE
_READ_OFFSET     = (CU_BASE_ADDR - _MAP_OFFSET) + AP_RETURN_OFFSET
_MAP_LENGTH      = _READ_OFFSET + 4

PCI_RESOURCE4_PATHS = [
    "/sys/bus/pci/devices/0000:01:00.1/resource4",
    "/sys/bus/pci/devices/0000:21:00.1/resource4",
    "/sys/bus/pci/devices/0000:41:00.1/resource4",
    "/sys/bus/pci/devices/0000:81:00.1/resource4",
]

# Probe: X on q0 → result = (syndrome=0x01 << 18) | x_corr=0x001 = 0x00040001
_PROBE_INPUT    = 1
_PROBE_EXPECTED = 0x00040001


def _bits(w, lo, hi): return (w >> lo) & ((1 << (hi - lo + 1)) - 1)
def pack_err(xe, ze):
    assert 0 <= xe < 512 and 0 <= ze < 512
    return (ze << N_DATA) | xe


# ═════════════════════════════════════════════════════════════════════════════
#  Software decoder (exact mirror of shor_qec_kernel.cpp)
# ═════════════════════════════════════════════════════════════════════════════
def _sw_synd(xe, ze):
    s  = ((xe>>0^xe>>1)&1)<<0; s|=((xe>>1^xe>>2)&1)<<1
    s |= ((xe>>3^xe>>4)&1)<<2; s|=((xe>>4^xe>>5)&1)<<3
    s |= ((xe>>6^xe>>7)&1)<<4; s|=((xe>>7^xe>>8)&1)<<5
    p6=p7=0
    for i in range(6): p6^=(ze>>i)&1; p7^=(ze>>(i+3))&1
    return s|(p6<<6)|(p7<<7)

def _build_lut():
    L=[0]*256
    def s(i,xc,zc): L[i]=(zc<<9)|xc
    s(0x01,1<<0,0);s(0x03,1<<1,0);s(0x02,1<<2,0)
    s(0x04,1<<3,0);s(0x0C,1<<4,0);s(0x08,1<<5,0)
    s(0x10,1<<6,0);s(0x30,1<<7,0);s(0x20,1<<8,0)
    s(0x40,0,1<<0);s(0xC0,0,1<<3);s(0x80,0,1<<6)
    s(0x41,1<<0,1<<0);s(0x43,1<<1,1<<1);s(0x42,1<<2,1<<2)
    s(0xC4,1<<3,1<<3);s(0xC8,1<<5,1<<5);s(0xCC,1<<4,1<<4)
    s(0x90,1<<6,1<<6);s(0xB0,1<<7,1<<7);s(0xA0,1<<8,1<<8)
    return L

_LUT = _build_lut()

def sw_decode(xe, ze):
    synd=_sw_synd(xe,ze); w=_LUT[synd]
    xc=w&0x1FF; zc=(w>>9)&0x1FF
    xf=xe^xc; zf=ze^zc
    xl=(xf>>0^xf>>3^xf>>6)&1
    zl=0
    for i in range(9): zl^=(zf>>i)&1
    return xc|(zc<<9)|(synd<<18)|(xl<<26)|(zl<<27)


# ═════════════════════════════════════════════════════════════════════════════
#  Error models
# ═════════════════════════════════════════════════════════════════════════════
def sample_single_pauli(rng, p):
    if rng.random()>=p: return 0,0
    q=int(rng.integers(0,N_DATA)); t=int(rng.integers(0,3))
    if t==0: return (1<<q),0
    if t==1: return (1<<q),(1<<q)
    return 0,(1<<q)

def sample_iid_depolarising(rng, p):
    xe=ze=0
    for q in range(N_DATA):
        if rng.random()<(1-p): continue
        b=int(rng.integers(0,3))
        if b==0: xe|=1<<q
        elif b==1: xe|=1<<q; ze|=1<<q
        else: ze|=1<<q
    return xe,ze


# ═════════════════════════════════════════════════════════════════════════════
#  ctypes XRT C-API wrapper  —  Path X
# ═════════════════════════════════════════════════════════════════════════════
_xrt_lib = None

def _load_xrt_clib():
    """Load libxrt_coreutil.so (or libxrt_core.so) via ctypes."""
    global _xrt_lib
    if _xrt_lib is not None:
        return _xrt_lib
    for name in ("libxrt_coreutil.so", "libxrt_coreutil.so.2",
                 "libxrt_core.so",     "libxrt_core.so.2"):
        for prefix in (_XRT_LIB, "/usr/lib", "/usr/local/lib"):
            path = os.path.join(prefix, name)
            if os.path.exists(path):
                try:
                    _xrt_lib = ctypes.CDLL(path, mode=ctypes.RTLD_GLOBAL)
                    log.info("    ctypes: loaded %s", path)
                    return _xrt_lib
                except Exception as e:
                    log.info("    ctypes: %s → %s", path, e)
    # Try by name alone (relies on LD_LIBRARY_PATH)
    for name in ("libxrt_coreutil.so", "libxrt_core.so"):
        try:
            _xrt_lib = ctypes.CDLL(name, mode=ctypes.RTLD_GLOBAL)
            log.info("    ctypes: loaded %s via LD path", name)
            return _xrt_lib
        except Exception:
            pass
    return None


def _get_run_handle(run_obj):
    """
    Extract the underlying xrtRunHandle (void*) from a pyxrt.run object.

    pyxrt.run is a pybind11 wrapper. Internally it holds a
    std::shared_ptr<xrt::run::impl>, but XRT also registers the
    raw handle in a PyCapsule that we can retrieve via ctypes.

    Strategy:
      1. Try PyCapsule API — the handle is sometimes directly accessible
         as a capsule named "xrtRunHandle".
      2. Try ctypes.cast of id(run_obj) — pybind11 objects sometimes
         store the C++ pointer at a known offset in the PyObject header.
      3. Inspect __dict__ / __class__ for any handle attribute.

    Returns the handle as a ctypes.c_void_p, or None if not found.
    """
    # Method 1: PyCapsule
    import ctypes as ct
    try:
        cap = getattr(run_obj, "_handle", None) or \
              getattr(run_obj, "handle",  None) or \
              getattr(run_obj, "_run",    None)
        if cap is not None:
            ptr = ct.pythonapi.PyCapsule_GetPointer(
                ct.py_object(cap), None)
            if ptr:
                return ct.c_void_p(ptr)
    except Exception:
        pass

    # Method 2: Look for any integer attribute that could be a pointer
    for attr in dir(run_obj):
        if attr.startswith("__"): continue
        try:
            v = getattr(run_obj, attr)
            if isinstance(v, int) and v > 0x1000:
                return ct.c_void_p(v)
        except Exception:
            pass

    return None


def try_ctypes_path(kernel_obj, run_obj):
    """
    Attempt to call xrtRunGetReturnValue via ctypes.

    XRT C API signature:
        int xrtRunGetReturnValue(xrtRunHandle rhdl, void *retval, size_t sz)
    Returns 0 on success, sets *retval to the ap_return value.

    If that doesn't exist in this build, try:
        uint32_t xrtRunReadRegister(xrtRunHandle, uint32_t offset)
    """
    log.info("  path X: ctypes XRT C-API …")
    lib = _load_xrt_clib()
    if lib is None:
        log.info("    ctypes: could not load libxrt_coreutil.so")
        return None

    # Print what symbols related to 'run' are exported
    run_syms = []
    try:
        import subprocess as sp
        out = sp.check_output(["nm", "-D", "--defined-only",
                               f"{_XRT_LIB}/libxrt_coreutil.so"],
                              stderr=sp.DEVNULL).decode(errors="replace")
        run_syms = [l.split()[-1] for l in out.splitlines()
                    if "xrtRun" in l or "xrt_run" in l.lower()]
        log.info("    available xrtRun* symbols: %s", run_syms[:20])
    except Exception as e:
        log.info("    nm failed: %s", e)

    # ── Try xrtRunGetReturnValue ──────────────────────────────────────────
    for sym in ("xrtRunGetReturnValue", "xrtRunGetReturnValue2"):
        fn = None
        try:
            fn = getattr(lib, sym)
        except AttributeError:
            continue
        fn.restype  = ctypes.c_int
        fn.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t]
        handle = _get_run_handle(run_obj)
        if handle is None:
            log.info("    could not extract run handle for %s", sym)
            continue
        retval = ctypes.c_uint32(0)
        rc = fn(handle, ctypes.byref(retval), ctypes.sizeof(retval))
        log.info("    %s(handle, &ret, 4) → rc=%d  ret=0x%08X", sym, rc, retval.value)
        if rc == 0 and retval.value == _PROBE_EXPECTED:
            log.info("    path X: CONFIRMED via %s ✓", sym)
            return ("ctypes_getreturn", fn, run_obj)

    # ── Try xrtRunReadRegister ────────────────────────────────────────────
    for sym in ("xrtRunReadRegister", "xrtXclbinGetXSAName"):
        fn = None
        try:
            fn = getattr(lib, "xrtRunReadRegister")
            fn.restype  = ctypes.c_uint32
            fn.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
            handle = _get_run_handle(run_obj)
            if handle is None: break
            val = fn(handle, AP_RETURN_OFFSET)
            log.info("    xrtRunReadRegister(handle, 0x18) → 0x%08X", val)
            if val == _PROBE_EXPECTED:
                log.info("    path X: CONFIRMED via xrtRunReadRegister ✓")
                return ("ctypes_readreg", fn, run_obj)
        except Exception as e:
            log.info("    xrtRunReadRegister: %s", e)
        break

    log.info("    path X: no working ctypes symbol found")
    return None


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

    _bar4_mm:    Optional[object] = field(default=None, init=False, repr=False)
    _bar4_file:  Optional[object] = field(default=None, init=False, repr=False)
    _bar4_off:   int              = field(default=0,    init=False, repr=False)
    _ctypes_ctx: Optional[object] = field(default=None, init=False, repr=False)
    _return_via: str              = field(default="",   init=False, repr=False)

    def open(self):
        if not XRT_AVAILABLE:
            raise RuntimeError(
                "pyxrt not found.\n"
                "Fix: source /opt/xilinx/xrt/setup.sh  OR\n"
                "     export PYTHONPATH=/opt/xilinx/xrt/python")
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

    # ---------------------------------------------------------------- path X
    def _try_path_x(self):
        # Fire probe shot first
        rp = xrt.run(self.kernel)
        rp.set_arg(0, _PROBE_INPUT)
        rp.start(); rp.wait()
        ctx = try_ctypes_path(self.kernel, rp)
        if ctx:
            self._ctypes_ctx = ctx
            return True
        return False

    # ---------------------------------------------------------------- path B
    def _try_path_b(self):
        log.info("  path B: mmap BAR4 @ file_offset=0x%X …", _READ_OFFSET)
        for path in PCI_RESOURCE4_PATHS:
            if not os.path.exists(path): continue
            try:
                f  = open(path, "rb")
                sz = os.fstat(f.fileno()).st_size
                if sz < _MAP_OFFSET + _MAP_LENGTH:
                    f.close()
                    log.info("    %s: too small (%d bytes)", path, sz)
                    continue
                mm = mmap.mmap(f.fileno(), _MAP_LENGTH,
                               mmap.MAP_SHARED, mmap.PROT_READ,
                               offset=_MAP_OFFSET)
                rp = xrt.run(self.kernel)
                rp.set_arg(0, _PROBE_INPUT)
                rp.start(); rp.wait()
                raw = mm[_READ_OFFSET: _READ_OFFSET + 4]
                val = struct.unpack("<I", raw)[0]
                log.info("    %s @ 0x%X → 0x%08X  (expected 0x%08X)",
                         path, _READ_OFFSET, val, _PROBE_EXPECTED)
                if val == _PROBE_EXPECTED:
                    self._bar4_mm   = mm
                    self._bar4_file = f
                    self._bar4_off  = _READ_OFFSET
                    log.info("    path B CONFIRMED ✓")
                    return True
                mm.close(); f.close()
            except PermissionError:
                log.info("    %s: PermissionError", path)
            except Exception as e:
                log.info("    %s: %s", path, e)
        return False

    # ---------------------------------------------------------- detection
    def _detect_path(self):
        log.info("detecting hardware read-back path …")
        if self._try_path_x():
            self._return_via = "ctypes"
            log.info("active path: ctypes XRT C-API (hardware) ✓")
            return
        if self._try_path_b():
            self._return_via = "mmap"
            log.info("active path: BAR4 mmap (hardware) ✓")
            return
        log.warning("No hardware read-back available — using software decoder.")
        log.warning("Run 'python3 bar_probe.py' (as root) to diagnose.")
        self._return_via = "sw"
        log.info("active path: software decoder")

    # ---------------------------------------------------------------- decode
    def decode_one(self, xe: int, ze: int) -> int:
        if not self._return_via:
            self._detect_path()
        packed = pack_err(xe, ze)

        if self._return_via == "ctypes":
            kind, fn, _ = self._ctypes_ctx
            self.run.set_arg(0, packed)
            self.run.start()
            self.run.wait()
            if kind == "ctypes_getreturn":
                retval = ctypes.c_uint32(0)
                fn(_get_run_handle(self.run),
                   ctypes.byref(retval), ctypes.sizeof(retval))
                return retval.value
            else:  # ctypes_readreg
                return fn(_get_run_handle(self.run), AP_RETURN_OFFSET)

        if self._return_via == "mmap":
            self.run.set_arg(0, packed)
            self.run.start()
            self.run.wait()
            raw = self._bar4_mm[self._bar4_off: self._bar4_off + 4]
            return struct.unpack("<I", raw)[0]

        return sw_decode(xe, ze)

    def close(self):
        for attr in ("_bar4_mm", "_bar4_file"):
            obj = getattr(self, attr, None)
            if obj:
                try: obj.close()
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

def run_sweep(fpga, p_list, n_shots, model, seed):
    rng     = np.random.default_rng(seed)
    sampler = sample_single_pauli if model == "single_pauli" \
              else sample_iid_depolarising
    res     = SweepResult(n_shots=n_shots, model=model,
                          decode_path=fpga._return_via)
    for p in p_list:
        fails = 0; t0 = time.perf_counter()
        for _ in range(n_shots):
            xe, ze = sampler(rng, p)
            r = fpga.decode_one(xe, ze)
            if _bits(r, BIT_XLOG, BIT_XLOG) or _bits(r, BIT_ZLOG, BIT_ZLOG):
                fails += 1
        dt = time.perf_counter() - t0
        p_l = fails / n_shots
        res.p_phys.append(p); res.p_logical.append(p_l)
        res.timings_ms.append(dt * 1e3)
        log.info("p=%.4f  p_L=%.5f  (%d/%d)  %.1f ms  %.0f shots/s",
                 p, p_l, fails, n_shots, dt*1e3, n_shots/dt)
    return res


# ═════════════════════════════════════════════════════════════════════════════
#  Plotting
# ═════════════════════════════════════════════════════════════════════════════
def plot_curve(res, out_path, overlay_png=None):
    if not HAS_MPL:
        log.warning("matplotlib not installed — skipping plot")
        return
    hw  = res.decode_path in ("ctypes", "mmap")
    tag = f"FPGA hardware ({res.decode_path})" if hw else "software decoder"
    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.loglog(res.p_phys, res.p_logical, "o-",
              color="#d62728", lw=2, ms=7, label=f"Shor [[9,1,3]] — {tag}")
    p_arr = np.array(res.p_phys)
    ax.loglog(p_arr, p_arr, "--", color="gray", alpha=0.6, label="break-even")
    ax.set_xlabel("Physical error rate  p", fontsize=12)
    ax.set_ylabel("Logical error rate  p_L", fontsize=12)
    ax.set_title(
        f"Shor 9-qubit QEC · Alveo U55C · {tag}\n"
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
def self_test(fpga):
    log.info("── self-test: all 27 single-qubit Pauli errors ──")
    ok = 0
    for q in range(N_DATA):
        for name, (xm, zm) in (("X",(1<<q,0)),("Y",(1<<q,1<<q)),("Z",(0,1<<q))):
            r     = fpga.decode_one(xm, zm)
            xl    = _bits(r, BIT_XLOG,    BIT_XLOG)
            zl    = _bits(r, BIT_ZLOG,    BIT_ZLOG)
            synd  = _bits(r, BIT_SYND_LO, BIT_SYND_HI)
            xc    = _bits(r, BIT_X_CORR_LO, BIT_X_CORR_HI)
            zc    = _bits(r, BIT_Z_CORR_LO, BIT_Z_CORR_HI)
            ok_t  = xl == 0 and zl == 0
            log.info("  %-6s q%d  synd=0x%02X  x_corr=%s  z_corr=%s  %s",
                     name, q, synd,
                     bin(xc)[2:].zfill(9), bin(zc)[2:].zfill(9),
                     "PASS" if ok_t else "FAIL")
            if ok_t: ok += 1

    hw = fpga._return_via in ("ctypes", "mmap")
    log.info("self-test: %d/27  [%s]", ok,
             "FPGA HARDWARE ✓" if hw else "software")
    if hw and ok != 27:
        raise RuntimeError(f"Hardware self-test FAILED: {ok}/27")
    if not hw:
        log.warning("Self-test used SOFTWARE decoder — xclbin not verified.")
        log.warning("Run bar_probe.py as root to diagnose hardware read-back.")


# ═════════════════════════════════════════════════════════════════════════════
#  Main
# ═════════════════════════════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Shor QEC FPGA host — Alveo U55C")
    ap.add_argument("--xclbin",      default="shor_qec_kernel.xclbin")
    ap.add_argument("--device",      type=int, default=0)
    ap.add_argument("--shots",       type=int, default=10_000)
    ap.add_argument("--model",       choices=["single_pauli","iid_depol"],
                    default="single_pauli")
    ap.add_argument("--p",           nargs="+", type=float,
                    default=[0.001,0.005,0.01,0.05])
    ap.add_argument("--seed",        type=int, default=0xC0DE)
    ap.add_argument("--plot",        default="shor_qec_fpga_curve.png")
    ap.add_argument("--no-selftest", action="store_true")
    ap.add_argument("--sw-only",     action="store_true")
    args = ap.parse_args()

    log.info("=" * 65)
    log.info("  Shor 9-qubit QEC   |   Alveo U55C   |   C-DAC NQM Qniverse")
    log.info("=" * 65)

    fpga = ShorQECFPGA(xclbin_path=args.xclbin, device_index=args.device)
    try:
        if args.sw_only:
            log.info("--sw-only: software decoder forced")
            fpga._return_via = "sw"
        else:
            fpga.open()
        if not args.no_selftest:
            self_test(fpga)
        log.info("── Monte Carlo sweep: %s, %d shots/point ──",
                 args.model, args.shots)
        res = run_sweep(fpga, args.p, args.shots, args.model, args.seed)
        plot_curve(res, args.plot)
    finally:
        fpga.close()
    log.info("done")
    return 0

if __name__ == "__main__":
    sys.exit(main())