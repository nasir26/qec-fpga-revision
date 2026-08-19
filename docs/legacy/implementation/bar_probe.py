#!/usr/bin/env python3
"""
bar_probe.py — find the correct PCI resource file and byte offset for the
               shor_qec_kernel CU ap_return register on this exact machine.

Run as root so all BAR files are readable:
    sudo PYTHONPATH=/opt/xilinx/xrt/python \\
         LD_LIBRARY_PATH=/opt/xilinx/xrt/lib \\
         python3 bar_probe.py

What it does:
  1. Loads the xclbin on device 0 and fires a known probe shot
     (X error on q0 → expected result 0x00040001).
  2. Reads /proc/iomem and /sys/bus/pci/devices/*/resource to find the
     physical base addresses of every BAR on the device.
  3. Scans every resource file (resource0..resource5) at every plausible
     CU offset, looking for the expected probe value.
  4. Prints the exact file path + byte offset that works.
     That is the only information needed to fix shor_qec_host.py.
"""

import sys, os

# XRT path injection so this works under sudo
for p in ("/opt/xilinx/xrt/python",):
    if os.path.isdir(p) and p not in sys.path:
        sys.path.insert(0, p)
_lib = "/opt/xilinx/xrt/lib"
_cur = os.environ.get("LD_LIBRARY_PATH", "")
if _lib not in _cur:
    os.environ["LD_LIBRARY_PATH"] = _lib + (":" + _cur if _cur else "")

import mmap, struct, subprocess, argparse

ap = argparse.ArgumentParser()
ap.add_argument("--xclbin", default="shor_qec_kernel.xclbin")
ap.add_argument("--device", type=int, default=0)
args = ap.parse_args()

# ── known probe ──────────────────────────────────────────────────────────────
# X error on q0: pack_err(1,0)=1 → syndrome=0x01 → x_corr=0x001
# result = (0x01 << 18) | 0x001 = 0x00040001
PROBE_INPUT    = 1
PROBE_EXPECTED = 0x00040001

# ── XRT: load xclbin and fire probe shot ─────────────────────────────────────
try:
    import pyxrt as xrt
except ImportError:
    print("ERROR: pyxrt not found. Run: sudo PYTHONPATH=/opt/xilinx/xrt/python python3 bar_probe.py")
    sys.exit(1)

print("=" * 70)
print("Loading xclbin and firing probe shot …")
print("=" * 70)

device = xrt.device(args.device)
xclbin = xrt.xclbin(args.xclbin)
uuid   = device.load_xclbin(xclbin)

try:
    kernel = xrt.kernel(device, uuid, "shor_qec_kernel",
                        xrt.kernel.cu_access_mode.exclusive)
except AttributeError:
    kernel = xrt.kernel(device, uuid, "shor_qec_kernel")

run = xrt.run(kernel)
run.set_arg(0, PROBE_INPUT)
run.start()
state = run.wait()
print(f"  run.wait() state: {state}")
print(f"  probe input:    0x{PROBE_INPUT:08X}")
print(f"  expected result: 0x{PROBE_EXPECTED:08X}")
print()

# ── find PCI BDF for device 0 ────────────────────────────────────────────────
# xbutil examine gives us the BDF. We know from previous output it is 0000:01:00.1
# for device index 0. Confirm via xbutil.
print("=" * 70)
print("PCI device info")
print("=" * 70)
BDF_CANDIDATES = [
    "0000:01:00.1",
    "0000:21:00.1",
    "0000:41:00.1",
    "0000:81:00.1",
]
# Device 0 is the first card = 0000:01:00.1 (confirmed by previous xbutil output)
PRIMARY_BDF = "0000:01:00.1"

# ── read /sys/bus/pci/devices/<bdf>/resource for BAR base addresses ──────────
# Each line in 'resource': "start end flags"
# Line 0 = BAR0, line 1 = BAR1, ... line 10 = BAR5 (each BAR uses 2 lines: mem+prefetch)
# Actually the file has one line per possible BAR (0-5 = lines 0-5)
print(f"\nBAR base addresses for {PRIMARY_BDF}:")
bar_bases = {}
resource_file = f"/sys/bus/pci/devices/{PRIMARY_BDF}/resource"
try:
    with open(resource_file) as f:
        for i, line in enumerate(f):
            parts = line.strip().split()
            if len(parts) >= 2:
                start = int(parts[0], 16)
                end   = int(parts[1], 16)
                flags = int(parts[2], 16) if len(parts) > 2 else 0
                size  = (end - start + 1) if end > start else 0
                bar_bases[i] = start
                print(f"  BAR{i}: start=0x{start:016X}  end=0x{end:016X}  "
                      f"size=0x{size:X} ({size//1024}KB)  flags=0x{flags:X}")
except Exception as e:
    print(f"  could not read {resource_file}: {e}")

# ── xbutil dynamic-regions: CU base address (PCIe physical address) ──────────
print()
print("=" * 70)
print("CU base address from xbutil dynamic-regions")
print("=" * 70)
cu_phys_addr = None
try:
    out = subprocess.check_output(
        ["xbutil", "examine", "--device", PRIMARY_BDF, "--report", "dynamic-regions"],
        stderr=subprocess.STDOUT, timeout=15).decode(errors="replace")
    for line in out.splitlines():
        print(" ", line)
        # Parse "shor_qec_kernel:shor_qec_kernel_1  0x800000"
        if "shor_qec_kernel" in line and "0x" in line:
            parts = line.split()
            for p in parts:
                if p.startswith("0x") or p.startswith("0X"):
                    try:
                        cu_phys_addr = int(p, 16)
                    except ValueError:
                        pass
except Exception as e:
    print(f"  xbutil failed: {e}")

if cu_phys_addr is not None:
    print(f"\nParsed CU base address: 0x{cu_phys_addr:X}")

# ── scan every resource file for the probe value ─────────────────────────────
print()
print("=" * 70)
print("Scanning all resource files for probe value 0x00040001 …")
print("(firing a new probe shot before each scan attempt)")
print("=" * 70)

AP_OFFSETS_TO_TRY = [0x00, 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18, 0x1C,
                     0x20, 0x24, 0x28, 0x2C, 0x30]

found_results = []

for bdf in BDF_CANDIDATES:
    for res_num in range(6):
        res_path = f"/sys/bus/pci/devices/{bdf}/resource{res_num}"
        if not os.path.exists(res_path):
            continue
        try:
            size = os.path.getsize(res_path)
            if size == 0:
                continue
        except Exception:
            continue

        # Fire a fresh probe shot immediately before reading
        run2 = xrt.run(kernel)
        run2.set_arg(0, PROBE_INPUT)
        run2.start()
        run2.wait()

        try:
            with open(res_path, "rb") as f:
                file_size = os.fstat(f.fileno()).st_size
                if file_size < 4:
                    continue
                # Try reading at multiple offsets
                # 1. Small offsets (0x00 - 0x30): direct CU register map
                # 2. CU_BASE offset if file is large enough
                offsets_to_try = list(AP_OFFSETS_TO_TRY)
                if cu_phys_addr is not None:
                    # Try CU_BASE as a raw file offset (if file is large enough)
                    if file_size > cu_phys_addr + 0x20:
                        offsets_to_try += [cu_phys_addr + off
                                           for off in AP_OFFSETS_TO_TRY]
                    # Try CU_BASE relative to BAR base
                    bar_idx = res_num // 2 if res_num < 12 else res_num
                    bar_idx = res_num  # resource0=BAR0, resource2=BAR2, etc.
                    if bar_idx in bar_bases and bar_bases[bar_idx] > 0:
                        rel = cu_phys_addr - bar_bases[bar_idx]
                        if 0 < rel < file_size - 4:
                            offsets_to_try += [rel + off
                                               for off in AP_OFFSETS_TO_TRY]

                for off in offsets_to_try:
                    if off < 0 or off + 4 > file_size:
                        continue
                    # Page-align for mmap
                    page     = mmap.PAGESIZE
                    map_off  = (off // page) * page
                    off_in   = off - map_off
                    map_len  = off_in + 4
                    if map_off + map_len > file_size:
                        continue
                    try:
                        mm  = mmap.mmap(f.fileno(), map_len,
                                        mmap.MAP_SHARED, mmap.PROT_READ,
                                        offset=map_off)
                        raw = mm[off_in: off_in + 4]
                        val = struct.unpack("<I", raw)[0]
                        mm.close()
                        if val == PROBE_EXPECTED:
                            msg = (f"  *** FOUND *** {res_path} "
                                   f"file_offset=0x{off:X}  "
                                   f"value=0x{val:08X}  ✓")
                            print(msg)
                            found_results.append((res_path, off))
                        elif val != 0:
                            # Print non-zero values at plausible CU offsets
                            if off <= 0x30 or (cu_phys_addr and
                                               abs(off - cu_phys_addr) < 0x40):
                                print(f"  {res_path} @ 0x{off:X} → 0x{val:08X}")
                    except Exception:
                        pass
        except PermissionError:
            print(f"  {res_path}: PermissionError (run as root)")
        except Exception as e:
            print(f"  {res_path}: {e}")

# ── /proc/iomem scan for CU region ───────────────────────────────────────────
print()
print("=" * 70)
print("/proc/iomem — looking for CU region")
print("=" * 70)
try:
    with open("/proc/iomem") as f:
        for line in f:
            if any(kw in line.lower() for kw in
                   ["xilinx", "xdma", "shor", "0000:01", "alveo"]):
                print(" ", line.rstrip())
            # Also print entries near CU_BASE physical addr if known
            if cu_phys_addr:
                parts = line.split(":")
                if parts:
                    try:
                        rng = parts[0].strip().split("-")
                        if len(rng) == 2:
                            s = int(rng[0], 16)
                            e = int(rng[1], 16)
                            if s <= cu_phys_addr <= e:
                                print(f"  [CU_BASE 0x{cu_phys_addr:X} falls here] {line.rstrip()}")
                    except Exception:
                        pass
except Exception as e:
    print(f"  /proc/iomem: {e}")

# ── use xbutil read-register directly ────────────────────────────────────────
print()
print("=" * 70)
print("xbutil read-register attempts")
print("=" * 70)
for off in [0x00, 0x10, 0x18, 0x20]:
    for bdf in [PRIMARY_BDF]:
        cmd = ["xbutil", "read-register",
               "--device", bdf,
               "--core", "shor_qec_kernel:shor_qec_kernel_1",
               "--offset", hex(off)]
        try:
            # Fire probe shot first
            run3 = xrt.run(kernel)
            run3.set_arg(0, PROBE_INPUT)
            run3.start()
            run3.wait()
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                          timeout=10).decode(errors="replace")
            print(f"  {' '.join(cmd[-4:])}")
            for line in out.splitlines():
                print(f"    {line}")
        except subprocess.CalledProcessError as e:
            print(f"  offset 0x{off:02X}: xbutil error — "
                  f"{e.output.decode(errors='replace').strip()[:80]}")
        except Exception as e:
            print(f"  offset 0x{off:02X}: {e}")

# ── summary ───────────────────────────────────────────────────────────────────
print()
print("=" * 70)
print("SUMMARY")
print("=" * 70)
if found_results:
    print(f"  FOUND {len(found_results)} working location(s):")
    for path, off in found_results:
        print(f"    file : {path}")
        print(f"    offset: 0x{off:X}")
        print(f"  Use these two values in shor_qec_host.py.")
else:
    print("  No matching location found via mmap scan.")
    print("  Check xbutil read-register output above — that may have the answer.")
    print("  Also check /proc/iomem output for the CU physical address mapping.")