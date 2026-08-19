# #!/usr/bin/env python3
# """
# xrt_probe.py — deep-inspect every attribute on pyxrt.run and pyxrt.kernel
# for the exact XRT build installed on this machine.

# Run:
#     source /opt/xilinx/xrt/setup.sh
#     python3 xrt_probe.py --xclbin shor_qec_kernel.xclbin

# What it does:
#   1. Opens the device and loads the xclbin (same as the host driver).
#   2. Dumps EVERY non-dunder attribute on xrt.kernel and xrt.run — name,
#      type, and whether it is callable.
#   3. Fires the kernel with err_in=0 (no error) via three calling patterns
#      and tries every plausible return-value accessor on the run object that
#      comes back, printing the raw value of each.
#   4. Prints the xbutil examine output so we can see the XRT version string.

# This is a one-shot diagnostic — nothing is changed, nothing is written.
# Paste the full output as context for the next fix iteration.
# """

# import os, sys, subprocess, argparse, importlib

# # ── args ────────────────────────────────────────────────────────────────────
# ap = argparse.ArgumentParser()
# ap.add_argument("--xclbin", default="shor_qec_kernel.xclbin")
# ap.add_argument("--device", type=int, default=0)
# args = ap.parse_args()

# # ── XRT version banner ───────────────────────────────────────────────────────
# print("=" * 70)
# print("XRT version info")
# print("=" * 70)
# for cmd in (["xbutil",  "examine"],
#             ["xbmgmt",  "examine"],
#             ["/opt/xilinx/xrt/bin/xbutil", "examine"]):
#     try:
#         out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
#                                       timeout=10).decode(errors="replace")
#         # Print only the first 30 lines — the version string is always near top
#         for line in out.splitlines()[:30]:
#             print(line)
#         break
#     except Exception as e:
#         print(f"  {cmd[0]} failed: {e}")

# print()

# # ── import pyxrt ─────────────────────────────────────────────────────────────
# print("=" * 70)
# print("pyxrt import")
# print("=" * 70)
# try:
#     import pyxrt as xrt
#     print(f"  import OK   module file: {xrt.__file__}")
#     print(f"  dir(pyxrt): {[a for a in dir(xrt) if not a.startswith('__')]}")
# except ImportError as e:
#     print(f"  FAILED: {e}")
#     print("  Fix: source /opt/xilinx/xrt/setup.sh")
#     sys.exit(1)

# print()

# # ── open device + load xclbin ────────────────────────────────────────────────
# print("=" * 70)
# print("device / xclbin open")
# print("=" * 70)
# if not os.path.exists(args.xclbin):
#     print(f"  xclbin not found: {args.xclbin}")
#     sys.exit(1)

# device = xrt.device(args.device)
# print(f"  device opened: index {args.device}")

# # Try to print device info
# for info_attr in ("xrt_info_device_version", "xrt_info_device_name",
#                   "xrt_info_device_kdma"):
#     try:
#         enum_val = getattr(xrt.xrt_info_device, info_attr)
#         val = device.get_info(enum_val)
#         print(f"  device.get_info({info_attr}) = {val}")
#     except Exception as e:
#         print(f"  device.get_info({info_attr}) → {e}")

# xclbin = xrt.xclbin(args.xclbin)
# uuid   = device.load_xclbin(xclbin)
# print(f"  xclbin loaded   uuid: {uuid}")

# print()

# # ── kernel object inspection ─────────────────────────────────────────────────
# print("=" * 70)
# print("xrt.kernel attributes")
# print("=" * 70)

# KERNEL_NAME = "shor_qec_kernel"
# try:
#     kernel = xrt.kernel(device, uuid, KERNEL_NAME,
#                         xrt.kernel.cu_access_mode.exclusive)
#     print("  opened with cu_access_mode.exclusive")
# except AttributeError:
#     kernel = xrt.kernel(device, uuid, KERNEL_NAME)
#     print("  opened without cu_access_mode (not available)")
# except Exception as e:
#     print(f"  kernel open failed: {e}")
#     sys.exit(1)

# print(f"  type: {type(kernel)}")
# for attr in sorted(dir(kernel)):
#     if attr.startswith("__"):
#         continue
#     val = getattr(kernel, attr, "<err>")
#     print(f"  kernel.{attr:<30s}  callable={callable(val)}  type={type(val).__name__}")

# print()

# # ── run object inspection ────────────────────────────────────────────────────
# print("=" * 70)
# print("xrt.run attributes")
# print("=" * 70)

# run = xrt.run(kernel)
# print(f"  type: {type(run)}")
# for attr in sorted(dir(run)):
#     if attr.startswith("__"):
#         continue
#     val = getattr(run, attr, "<err>")
#     print(f"  run.{attr:<34s}  callable={callable(val)}  type={type(val).__name__}")

# print()

# # ── fire the kernel and try every return-value accessor ─────────────────────
# print("=" * 70)
# print("return-value accessor experiments  (err_in=0, expect result=0)")
# print("=" * 70)

# PACKED_ZERO = 0   # x_err=0, z_err=0 → syndrome=0 → result=0

# # ── Pattern A: kernel(arg) → run_obj; run_obj.wait(); read from run_obj ──────
# print("\n-- Pattern A: r = kernel(arg)  then r.wait() then read from r --")
# try:
#     r = kernel(PACKED_ZERO)
#     print(f"  kernel(0) returned type: {type(r).__name__}  value: {r!r}")

#     if hasattr(r, "wait"):
#         state = r.wait()
#         print(f"  r.wait() → {state!r}  type: {type(state).__name__}")

#     # Now try every accessor on r
#     for attr in sorted(dir(r)):
#         if attr.startswith("__"):
#             continue
#         v = getattr(r, attr, None)
#         if callable(v):
#             # Try calling it with 0, 1, or no arguments
#             for call_args in ((), (0,), (1,)):
#                 try:
#                     result = v(*call_args)
#                     print(f"  r.{attr}({', '.join(map(str,call_args))}) → {result!r}  "
#                           f"type={type(result).__name__}")
#                     break
#                 except TypeError:
#                     continue
#                 except Exception as e2:
#                     print(f"  r.{attr}({', '.join(map(str,call_args))}) raised: {e2}")
#                     break
#         else:
#             print(f"  r.{attr} = {v!r}")

# except Exception as e:
#     print(f"  Pattern A failed: {e}")

# # ── Pattern B: run.set_arg / start / wait then accessors ─────────────────────
# print("\n-- Pattern B: run.set_arg(0,val); run.start(); run.wait() --")
# try:
#     run2 = xrt.run(kernel)
#     run2.set_arg(0, PACKED_ZERO)
#     run2.start()
#     state2 = run2.wait()
#     print(f"  run2.wait() → {state2!r}  type: {type(state2).__name__}")

#     # Try all likely result accessors
#     accessors = [
#         ("get_return_value",  lambda r: r.get_return_value()),
#         ("get_arg_value(0)",  lambda r: r.get_arg_value(0)),
#         ("get_arg_value(1)",  lambda r: r.get_arg_value(1)),
#         ("get_arg_value(2)",  lambda r: r.get_arg_value(2)),
#         ("[0x10]",            lambda r: r[0x10]),
#         ("[0x18]",            lambda r: r[0x18]),
#         ("[0x20]",            lambda r: r[0x20]),
#     ]
#     for label, fn in accessors:
#         try:
#             val = fn(run2)
#             print(f"  run2.{label:<25s} → 0x{int(val):08X}  ({int(val)})")
#         except Exception as e:
#             print(f"  run2.{label:<25s} → {e}")

# except Exception as e:
#     print(f"  Pattern B failed: {e}")

# # ── Pattern C: kernel.read_register at various offsets ───────────────────────
# print("\n-- Pattern C: kernel.read_register(offset) --")
# if hasattr(kernel, "read_register"):
#     for off in (0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C, 0x20, 0x24):
#         try:
#             val = kernel.read_register(off)
#             print(f"  kernel.read_register(0x{off:02X}) → 0x{int(val):08X}")
#         except Exception as e:
#             print(f"  kernel.read_register(0x{off:02X}) → {e}")
# else:
#     print("  kernel.read_register not available")

# # ── Pattern D: cu_offset / offset accessor on kernel ─────────────────────────
# print("\n-- Pattern D: kernel[offset] or kernel.offset() --")
# for off in (0x18, 0x10, 0x00):
#     try:
#         val = kernel[off]
#         print(f"  kernel[0x{off:02X}] → 0x{int(val):08X}")
#     except Exception as e:
#         print(f"  kernel[0x{off:02X}] → {e}")

# print()
# print("=" * 70)
# print("probe complete — paste this output to identify the correct API")
# print("=" * 70)


#!/usr/bin/env python3
"""
xrt_probe2.py — find ap_return in XRT 2.16 pyxrt binding

XRT 2.16 pyxrt.run has only: add_callback, set_arg, start, state, wait
The ap_return register IS written by hardware but pyxrt doesn't expose a
direct getter. The trick in this binding version is:

  Option 1: xrt.bo scalar readback
    - Allocate a host-accessible xrt.bo of 4 bytes
    - Pass its device address as a second kernel arg (won't work — AXI-Lite only)

  Option 2: run.set_arg with the return slot index
    - For ap_ctrl_hs with one input scalar, the return slot is arg index 1
    - set_arg(1, ctypes_array) before start() — hardware writes into it
    - read it back after wait() from the ctypes buffer

  Option 3: direct MMIO via mmap of the CU BAR
    - /sys/bus/pci/devices/0000:01:00.1/resource2  (BAR2 = CU register space)
    - mmap offset=CU_BASE, read 4 bytes at offset 0x18

  Option 4: xbutil / xbmgmt register read via subprocess

Run: python3 xrt_probe2.py --xclbin shor_qec_kernel.xclbin
"""
import os, sys, struct, mmap, subprocess, ctypes, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--xclbin", default="shor_qec_kernel.xclbin")
ap.add_argument("--device", type=int, default=0)
args = ap.parse_args()

import pyxrt as xrt

device = xrt.device(args.device)
xclbin = xrt.xclbin(args.xclbin)
uuid   = device.load_xclbin(xclbin)

try:
    kernel = xrt.kernel(device, uuid, "shor_qec_kernel",
                        xrt.kernel.cu_access_mode.exclusive)
except Exception:
    kernel = xrt.kernel(device, uuid, "shor_qec_kernel")

PACKED_ZERO = 0  # x_err=0 z_err=0  →  syndrome=0  →  result=0x00000000
PACKED_X0   = 1  # X error on q0    →  syndrome=0x01 → x_corr=0x001, result=0x00040001
# result for X on q0:
#   x_corr[8:0] = 0b000000001 = 0x001
#   z_corr[17:9]= 0
#   syndrome[25:18] = 0x01 → bits 18..25 = 0x01 << 18 = 0x00040000
#   x_log=0, z_log=0
#   result = 0x00040001
EXPECTED_X0 = 0x00040001

print("=" * 70)
print("Option 2a: set_arg(1, buf) — write result into a ctypes buffer")
print("=" * 70)
# Try passing a ctypes c_uint32 array as arg index 1 (the ap_return slot)
# XRT may write the result into it if it maps to the ap_return register.
for arg_idx in (1, 2, 3):
    try:
        buf = (ctypes.c_uint32 * 1)(0xDEADBEEF)
        run = xrt.run(kernel)
        run.set_arg(0, PACKED_X0)
        run.set_arg(arg_idx, buf)
        run.start()
        run.wait()
        val = buf[0]
        print(f"  set_arg({arg_idx}, buf) → buf[0] = 0x{val:08X}  "
              f"{'CORRECT' if val == EXPECTED_X0 else 'wrong (expected 0x{:08X})'.format(EXPECTED_X0)}")
    except Exception as e:
        print(f"  set_arg({arg_idx}, buf) → {e}")

print()
print("=" * 70)
print("Option 2b: xrt.bo scalar buffer as output arg")
print("=" * 70)
# Some XRT versions allow a 4-byte BO mapped as the return slot
for arg_idx in (1, 2):
    try:
        bo = xrt.bo(device, 4, xrt.bo.flags.XCL_BO_FLAGS_NONE,
                    kernel.group_id(arg_idx))
        run = xrt.run(kernel)
        run.set_arg(0, PACKED_X0)
        run.set_arg(arg_idx, bo)
        run.start()
        run.wait()
        bo.sync(xrt.xclBOSyncDirection.XCL_BO_SYNC_BO_FROM_DEVICE)
        raw = bo.read(4, 0)
        val = struct.unpack("<I", raw)[0]
        print(f"  bo arg_idx={arg_idx}  bo.read() → 0x{val:08X}  "
              f"{'CORRECT' if val == EXPECTED_X0 else 'wrong'}")
    except Exception as e:
        print(f"  bo arg_idx={arg_idx} → {e}")

print()
print("=" * 70)
print("Option 3: direct MMIO via /sys PCI BAR mmap")
print("=" * 70)
# Find the CU BAR resource file. For Alveo U55C xdma the CU registers
# live in BAR2 (resource2) of the user PF (the .1 device).
# We read 64 bytes from offset 0 to find the CU base, then read 0x18.
pci_devs = [
    "/sys/bus/pci/devices/0000:01:00.1",
    "/sys/bus/pci/devices/0000:21:00.1",
    "/sys/bus/pci/devices/0000:41:00.1",
    "/sys/bus/pci/devices/0000:81:00.1",
]
for dev_path in pci_devs:
    for resource in ("resource2", "resource4"):
        res_path = f"{dev_path}/{resource}"
        if not os.path.exists(res_path):
            continue
        try:
            size = os.path.getsize(res_path)
            if size < 0x100000:
                print(f"  {res_path}: too small ({size} bytes), skipping")
                continue
            with open(res_path, "r+b") as f:
                # CU register map typically starts at 0x0 in BAR2 for Alveo
                # The ap_return offset is 0x18 for a single-input kernel
                mm = mmap.mmap(f.fileno(), 0x40, offset=0)
                raw = mm[0x18:0x22]
                val = struct.unpack("<I", raw[:4])[0]
                mm.close()
                print(f"  {res_path} @ offset 0x18 → 0x{val:08X}")
        except PermissionError:
            print(f"  {res_path}: PermissionError (need sudo or group membership)")
        except Exception as e:
            print(f"  {res_path}: {e}")

print()
print("=" * 70)
print("Option 4: xbutil read-register (if available in this XRT version)")
print("=" * 70)
# xbutil examine --report dynamic-regions shows CU base addresses
# Then: xbutil  --device 0000:01:00.1 read-register --offset 0x18
for bdf in ("0000:01:00.1",):
    for cmd in (
        ["xbutil", "read-register", "--device", bdf, "--core", "shor_qec_kernel_1", "--offset", "0x18"],
        ["xbutil", "examine", "--device", bdf, "--report", "dynamic-regions"],
    ):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                          timeout=10).decode(errors="replace")
            print(f"  cmd: {' '.join(cmd)}")
            for line in out.splitlines():
                print(f"    {line}")
            print()
        except Exception as e:
            print(f"  {' '.join(cmd[:3])} → {e}")

print()
print("=" * 70)
print("Option 5: add_callback — does it pass the result?")
print("=" * 70)
try:
    result_holder = [None]
    def cb(run_handle, state):
        result_holder[0] = state
        print(f"  callback called: state={state!r}  type={type(state).__name__}")
        # Check all attrs on run_handle inside callback
        for attr in sorted(dir(run_handle)):
            if attr.startswith("__"):
                continue
            try:
                v = getattr(run_handle, attr)
                if callable(v):
                    pass
                else:
                    print(f"    run_handle.{attr} = {v!r}")
            except Exception:
                pass

    run3 = xrt.run(kernel)
    run3.set_arg(0, PACKED_X0)
    run3.add_callback(xrt.ert_cmd_state.ERT_CMD_STATE_COMPLETED, cb)
    run3.start()
    run3.wait()
    import time; time.sleep(0.1)
    print(f"  result_holder = {result_holder[0]!r}")
except Exception as e:
    print(f"  callback approach: {e}")

print()
print("=" * 70)
print("Summary: run attributes in full")
print("=" * 70)
run_final = xrt.run(kernel)
for attr in sorted(dir(run_final)):
    if attr.startswith("__"):
        continue
    v = getattr(run_final, attr, None)
    print(f"  run.{attr} = {v!r}")

print()
print("probe2 complete")