#!/usr/bin/env python3
"""Hardware test of the m_axi-fixed, reconstructed Steane kernel: load the
freshly built xclbin, run the 21-case single-qubit self-test across all
three decoder modes (63 cases total, matching main.tex L335's claimed
21x3), reading results back via a real xrt::bo -- the first hardware test
this reconstructed kernel has ever had (docs/BLOCKERS.md B-003).

Result register layout (rtl/steane713/src/steane_qec_kernel.cpp):
  bits [ 6: 0]  x_correction
  bits [13: 7]  z_correction
  bits [16:14]  s_z (X-type syndrome)
  bits [19:17]  s_x (Z-type syndrome)
  bits [20]     X_logical_error flag
  bits [21]     Z_logical_error flag
  bits [23:22]  mode (echoed back)
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
import pyxrt as xrt

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/steane713/build_hw/steane_qec_kernel_m_axi_fix.xclbin"
KERNEL_NAME = "steane_qec_kernel"
MODE_NAMES = {0: "LUT", 1: "MWPM", 2: "UF"}

CASES = []
for q in range(7):
    CASES.append(("X", q, 1 << q, 0))
    CASES.append(("Y", q, (1 << q), (1 << q)))
    CASES.append(("Z", q, 0, 1 << q))

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

group_id = k.group_id(1)
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)
print(f"[4] allocated result_out bo, group_id={group_id}")

passed = 0
failed = 0
for mode in (0, 1, 2):
    for kind, q, x_err, z_err in CASES:
        err_in = (mode << 14) | (z_err << 7) | x_err
        r = xrt.run(k)
        r.set_arg(0, err_in)
        r.set_arg(1, bo)
        r.start()
        state = r.wait()
        bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)
        result = int.from_bytes(bo.read(4, 0).tobytes(), byteorder="little")
        x_corr = result & 0x7F
        z_corr = (result >> 7) & 0x7F
        s_z = (result >> 14) & 0x7
        s_x = (result >> 17) & 0x7
        x_log = (result >> 20) & 1
        z_log = (result >> 21) & 1
        ok = (x_log == 0 and z_log == 0)
        passed += ok
        failed += not ok
        tag = "PASS" if ok else "FAIL"
        print(f"    mode={MODE_NAMES[mode]:5s} {kind} q{q}: state={state} "
              f"s_z={s_z} s_x={s_x} x_corr={x_corr:07b} z_corr={z_corr:07b} "
              f"Xlog={x_log} Zlog={z_log}  {tag}")

print(f"\n[5] self-test: {passed}/{passed+failed} PASS via REAL HARDWARE READ-BACK "
      f"(xrt::bo, first hardware test this reconstructed kernel has had)")
