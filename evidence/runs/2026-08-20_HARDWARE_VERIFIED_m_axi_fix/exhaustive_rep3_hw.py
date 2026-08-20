#!/usr/bin/env python3
"""Exhaustive hardware test of the m_axi-fixed Rep-3 kernel: both valid
codewords (000, 111) against all 8 error masks (16 combinations, a complete
enumeration -- small enough that "self-test" and "exhaustive" coincide),
result read back via real xrt::bo, cross-checked against
models/mirrors/rep3_mirror.py. First hardware test this kernel has had.
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
sys.path.insert(0, "/home/cdac/Documents/qec_fpga/qec-fpga-revision/models/mirrors")
import pyxrt as xrt
import rep3_mirror

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/rep3/build_hw/rep3_qec_kernel_m_axi_fix.xclbin"

dev = xrt.device(0)
xb = xrt.xclbin(XCLBIN)
uuid = dev.load_xclbin(xb)
try:
    k = xrt.kernel(dev, uuid, "rep3_qec_kernel", xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    k = xrt.kernel(dev, uuid, "rep3_qec_kernel")
group_id = k.group_id(3)
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)
print(f"kernel ready, result_out group_id={group_id}")

total = 0
mismatches = 0
weight1_pass = 0
weight1_total = 0

for codeword_in in (0b000, 0b111):
    logical_in = 0 if codeword_in == 0b000 else 1
    for error_mask in range(8):
        r = xrt.run(k)
        r.set_arg(0, codeword_in)
        r.set_arg(1, error_mask)
        r.set_arg(2, logical_in)
        r.set_arg(3, bo)
        r.start()
        state = r.wait()
        bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)
        hw_result = int.from_bytes(bo.read(4, 0).tobytes(), byteorder="little")

        sw = rep3_mirror.rep3_qec_kernel(codeword_in, error_mask, logical_in)
        sw_packed = (sw["corrected"] | (sw["correction"] << 3) | (sw["syndrome"] << 6)
                     | (sw["corrected_logical"] << 8) | (sw["error_detected"] << 9)
                     | (sw["recovery_success"] << 10))

        total += 1
        ok = (hw_result == sw_packed)
        if not ok:
            mismatches += 1
            print(f"MISMATCH cw={codeword_in:03b} mask={error_mask:03b}: "
                  f"hw=0x{hw_result:08X} sw=0x{sw_packed:08X}")

        weight = bin(error_mask).count("1")
        if weight <= 1:
            weight1_total += 1
            recovery_success = (hw_result >> 10) & 1
            weight1_pass += recovery_success

        print(f"  cw={codeword_in:03b} mask={error_mask:03b}: state={state} "
              f"hw=0x{hw_result:08X} {'OK' if ok else 'MISMATCH'}")

print(f"\nDONE: {total} combinations, {total-mismatches}/{total} hardware-vs-software AGREE, "
      f"{mismatches} mismatches")
print(f"weight<=1 recovery (distance-3 guarantee): {weight1_pass}/{weight1_total}")
