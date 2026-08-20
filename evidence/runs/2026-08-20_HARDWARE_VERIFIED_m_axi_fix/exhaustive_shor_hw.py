#!/usr/bin/env python3
"""Exhaustive 3^9 = 19,683 single-Pauli-per-qubit hardware sweep against the
already-loaded, m_axi-fixed Shor kernel -- upgrades E01 from a 27-case
self-test to genuine exhaustive verification, per the brief's E01 ask.

Per qubit, one of {I, X, Z} (matching the brief's 3^9 = 19,683 convention;
Y is representable but this sweep follows the brief's literal count). Cross-
checked against models/mirrors/shor_mirror.py's exact logic per shot.
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
sys.path.insert(0, "/home/cdac/Documents/qec_fpga/qec-fpga-revision/models/mirrors")
import pyxrt as xrt
import shor_mirror

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/shor913/build_hw/shor_qec_kernel_m_axi_fix.xclbin"
N_QUBITS = 9

dev = xrt.device(0)
xb = xrt.xclbin(XCLBIN)
uuid = dev.load_xclbin(xb)
try:
    k = xrt.kernel(dev, uuid, "shor_qec_kernel", xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    k = xrt.kernel(dev, uuid, "shor_qec_kernel")
group_id = k.group_id(1)
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)


def run_one(x_err, z_err):
    err_in = (z_err << 9) | x_err
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
last_print = t0

# 3^9 = 19,683 patterns: each qubit independently in {I, X, Z} (brief's convention)
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
    hw_result = run_one(x_err, z_err)
    sw = shor_mirror.shor_qec_kernel(x_err, z_err)
    sw_packed = (sw["x_corr"] | (sw["z_corr"] << 9) | (sw["syndrome"] << 18)
                 | (sw["x_logical_err"] << 26) | (sw["z_logical_err"] << 27))
    total += 1
    if hw_result != sw_packed:
        mismatches += 1
        if mismatches <= 20:
            print(f"MISMATCH pattern={pattern} x_err={x_err:09b} z_err={z_err:09b} "
                  f"hw=0x{hw_result:08X} sw=0x{sw_packed:08X}")
    now = time.time()
    if now - last_print > 10:
        print(f"  progress: {total}/{3**N_QUBITS} ({100*total/3**N_QUBITS:.1f}%), "
              f"{mismatches} mismatches so far, {total/(now-t0):.1f} shots/s")
        last_print = now

elapsed = time.time() - t0
print(f"\nDONE: {total} patterns tested, {total-mismatches}/{total} hardware-vs-software "
      f"AGREE, {mismatches} mismatches, {elapsed:.1f}s elapsed ({total/elapsed:.1f} shots/s)")
