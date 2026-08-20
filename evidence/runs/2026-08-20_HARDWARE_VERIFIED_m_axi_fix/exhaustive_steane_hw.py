#!/usr/bin/env python3
"""Exhaustive 3^7 = 2,187 hardware sweep against the m_axi-fixed Steane
kernel, all three decoder modes (6,561 total shots), cross-checked against
models/mirrors/steane_mirror.py -- the brief's E01 ask for Steane, closed.
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
sys.path.insert(0, "/home/cdac/Documents/qec_fpga/qec-fpga-revision/models/mirrors")
import pyxrt as xrt
import steane_mirror

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/steane713/build_hw/steane_qec_kernel_m_axi_fix.xclbin"
N_QUBITS = 7

dev = xrt.device(0)
xb = xrt.xclbin(XCLBIN)
uuid = dev.load_xclbin(xb)
try:
    k = xrt.kernel(dev, uuid, "steane_qec_kernel", xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    k = xrt.kernel(dev, uuid, "steane_qec_kernel")
group_id = k.group_id(1)
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)


def run_one(x_err, z_err, mode):
    err_in = (mode << 14) | (z_err << 7) | x_err
    r = xrt.run(k)
    r.set_arg(0, err_in)
    r.set_arg(1, bo)
    r.start()
    r.wait()
    bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)
    return int.from_bytes(bo.read(4, 0).tobytes(), byteorder="little")


total = 0
mismatches = 0
t0 = time.time()

for mode in (0, 1, 2):
    for pattern in range(3 ** N_QUBITS):
        x_err = 0
        z_err = 0
        p = pattern
        for q in range(N_QUBITS):
            digit = p % 3
            p //= 3
            if digit == 1:
                x_err |= (1 << q)
            elif digit == 2:
                z_err |= (1 << q)
        hw_result = run_one(x_err, z_err, mode)
        sw = steane_mirror.steane_qec_kernel(x_err, z_err, mode)
        sw_packed = (sw.x_corr | (sw.z_corr << 7) | (sw.s_z << 14) | (sw.s_x << 17)
                     | (sw.x_logical_err << 20) | (sw.z_logical_err << 21) | (mode << 22))
        total += 1
        if hw_result != sw_packed:
            mismatches += 1
            if mismatches <= 20:
                print(f"MISMATCH mode={mode} pattern={pattern} x_err={x_err:07b} "
                      f"z_err={z_err:07b} hw=0x{hw_result:08X} sw=0x{sw_packed:08X}")

elapsed = time.time() - t0
print(f"\nDONE: {total} (mode,pattern) combinations tested (3 modes x 3^7), "
      f"{total-mismatches}/{total} hardware-vs-software AGREE, {mismatches} mismatches, "
      f"{elapsed:.1f}s elapsed ({total/elapsed:.1f} shots/s)")
