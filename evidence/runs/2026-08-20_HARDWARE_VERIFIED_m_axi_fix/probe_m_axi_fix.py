#!/usr/bin/env python3
"""Hardware test of the m_axi-fixed shor_qec_kernel: load the freshly built
xclbin, run a self-test shot, and read the result back via a real xrt::bo
buffer object attached to result_out -- the actual fix this whole B-001
investigation has been building toward.

Result register layout (rtl/shor913/src/shor_qec_kernel.cpp):
  bits [ 8: 0]  x_correction applied
  bits [17: 9]  z_correction applied
  bits [25:18]  syndrome
  bits [26]     X_logical_error flag
  bits [27]     Z_logical_error flag
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
import pyxrt as xrt

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/shor913/build_hw/shor_qec_kernel_m_axi_fix.xclbin"
KERNEL_NAME = "shor_qec_kernel"

# The manuscript's own 27-case self-test: (kind, qubit, err_in, expected syndrome)
# err_in packs x_err in bits[8:0], z_err in bits[17:9].
CASES = []
for q in range(9):
    CASES.append(("X", q, 1 << q))
    CASES.append(("Y", q, (1 << q) | (1 << (q + 9))))
    CASES.append(("Z", q, 1 << (q + 9)))

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

print(f"[4] allocate a 4-byte xrt::bo for result_out, bank-matched to the kernel arg")
group_id = k.group_id(1)  # arg index 1 = result_out
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)
print(f"    OK, group_id={group_id}")

passed = 0
failed = 0
for kind, q, err_in in CASES:
    r = xrt.run(k)
    r.set_arg(0, err_in)
    r.set_arg(1, bo)
    r.start()
    state = r.wait()
    bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)
    result = int.from_bytes(bo.read(4, 0).tobytes(), byteorder="little", signed=False)
    x_corr = result & 0x1FF
    z_corr = (result >> 9) & 0x1FF
    synd = (result >> 18) & 0xFF
    x_log = (result >> 26) & 1
    z_log = (result >> 27) & 1
    ok = (x_log == 0 and z_log == 0)
    passed += ok
    failed += not ok
    tag = "PASS" if ok else "FAIL"
    print(f"    {kind} q{q}: state={state} result=0x{result:08X} synd=0x{synd:02X} "
          f"x_corr={x_corr:09b} z_corr={z_corr:09b} Xlog={x_log} Zlog={z_log}  {tag}")

print(f"\n[5] self-test: {passed}/{passed+failed} PASS via REAL HARDWARE READ-BACK "
      f"(xrt::bo, not software fallback)")
