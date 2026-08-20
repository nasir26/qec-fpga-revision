#!/usr/bin/env python3
"""Crude, honest Python-loop round-trip latency measurement against the real
m_axi-fixed kernel on hardware. NOT the real E02 (that needs a C++ host with
clock_gettime and >=10^6 shots for a proper tail distribution). This is a
quick, single-process, best-effort measurement taken opportunistically while
hardware access is live, dominated by Python/XRT dispatch overhead, not the
kernel's own cycle-level latency. Report it as exactly that: an upper bound
on host-to-FPGA round trip, Python path, N=10,000 shots, wall-clock only.
"""
import sys
import time

sys.path.insert(0, "/opt/xilinx/xrt/python")
import pyxrt as xrt

XCLBIN = "/home/cdac/Documents/qec_fpga/qec-fpga-revision/rtl/shor913/build_hw/shor_qec_kernel_m_axi_fix.xclbin"
N = 10_000

dev = xrt.device(0)
xb = xrt.xclbin(XCLBIN)
uuid = dev.load_xclbin(xb)
try:
    k = xrt.kernel(dev, uuid, "shor_qec_kernel", xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    k = xrt.kernel(dev, uuid, "shor_qec_kernel")
group_id = k.group_id(1)
bo = xrt.bo(dev, 4, xrt.bo.normal, group_id)

# warm up
for _ in range(100):
    r = xrt.run(k)
    r.set_arg(0, 1)
    r.set_arg(1, bo)
    r.start()
    r.wait()
    bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)

times_ns = []
for i in range(N):
    t0 = time.perf_counter_ns()
    r = xrt.run(k)
    r.set_arg(0, (i % 511) + 1)
    r.set_arg(1, bo)
    r.start()
    r.wait()
    bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE, 4, 0)
    _ = bo.read(4, 0)
    t1 = time.perf_counter_ns()
    times_ns.append(t1 - t0)

times_ns.sort()
n = len(times_ns)
def pct(p):
    return times_ns[min(n - 1, int(n * p))]

print(f"N={n} shots, Python/pyxrt round trip (set_arg x2 + start + wait + sync + read)")
print(f"  min    = {times_ns[0]/1000:.1f} us")
print(f"  p50    = {pct(0.50)/1000:.1f} us")
print(f"  p90    = {pct(0.90)/1000:.1f} us")
print(f"  p99    = {pct(0.99)/1000:.1f} us")
print(f"  p99.9  = {pct(0.999)/1000:.1f} us")
print(f"  max    = {times_ns[-1]/1000:.1f} us")
print(f"  mean   = {sum(times_ns)/n/1000:.1f} us")
