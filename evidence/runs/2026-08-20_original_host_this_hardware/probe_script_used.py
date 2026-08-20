#!/usr/bin/env python3
"""Minimal, read-mostly probe of the ORIGINAL (unmodified) shor_qec_kernel.xclbin
against this host's live Alveo U55C. No new build -- uses the exact xclbin
shipped in docs/legacy/implementation/. Mirrors the path-A probe in
shor_qec_host.py but self-contained, and targets THIS host's device
(0000:8c:00.1), not the original capture host's four BDFs.

This is read-mostly, standard-use activity on the card (load a user-partition
xclbin, run one kernel invocation, attempt to read the result back). It does
not touch the shell/mgmt partition.
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
import pyxrt as xrt

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/docs/legacy/implementation/shor_qec_kernel.xclbin"
KERNEL_NAME = "shor_qec_kernel"
PROBE_INPUT = 1
PROBE_EXPECTED = 0x00040001

print(f"[1] xrt.device(0)")
dev = xrt.device(0)
print(f"    OK: {dev}")

print(f"[2] load_xclbin({XCLBIN})")
t0 = time.time()
xb = xrt.xclbin(XCLBIN)
uuid = dev.load_xclbin(xb)
print(f"    OK in {time.time()-t0:.2f}s, uuid={uuid}")

print(f"[3] xrt.kernel(dev, uuid, {KERNEL_NAME!r})")
try:
    k = xrt.kernel(dev, uuid, KERNEL_NAME, xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    k = xrt.kernel(dev, uuid, KERNEL_NAME)
print(f"    OK: {k}")

print(f"[4] run kernel with err_in={PROBE_INPUT} (X error on qubit 0)")
r = xrt.run(k)
r.set_arg(0, PROBE_INPUT)
r.start()
state = r.wait()
print(f"    kernel finished, state={state}")

print(f"[5] attempt to read return value via r.get_arg / xrt.bo path")
# ap_return is a scalar AXI-Lite register on this ORIGINAL kernel -- there is
# no m_axi output port to attach a buffer object to. This should fail or
# return something meaningless, exactly as selftest.log documents (path A:
# 'vector::_M_range_check' on the original capture host). Report whatever
# actually happens here, do not paper over it.
try:
    val = r.read_register(0x10)  # ap_return offset in the control bundle, best-effort guess
    print(f"    read_register(0x10) -> 0x{val:08X} (expected 0x{PROBE_EXPECTED:08X})")
except Exception as e:
    print(f"    read_register FAILED: {type(e).__name__}: {e}")

try:
    ret = r.return_value
    print(f"    r.return_value -> {ret}")
except Exception as e:
    print(f"    r.return_value FAILED: {type(e).__name__}: {e}")

print("[6] done -- this establishes whether the ORIGINAL xclbin even loads and runs on this host's shell/XRT version, independent of the readback question above.")
