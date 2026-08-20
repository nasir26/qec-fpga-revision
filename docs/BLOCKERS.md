# Blockers

Append-only. Each entry: what is blocked, why, what is needed, from whom, and the workaround in use.

## B-001: Hardware decode path inaccessible on the ORIGINAL capture machine (RESOLVED for the Shor kernel, 2026-08-20)

**RESOLVED (2026-08-20, later same day): full hardware read-back confirmed.** The `m_axi`-fixed
Shor kernel (`rtl/shor913/src/shor_qec_kernel.cpp`) was built end-to-end (`v++ -c`, `v++ -l`,
full Vivado implementation, ~2h7m wall time), loaded onto this host's live Alveo U55C, and run
through all 27 single-qubit Pauli self-test cases with the result read back via a genuine
`xrt::bo` buffer object. **27/27 PASS, no software fallback, reproduced twice**
(`evidence/runs/2026-08-20_HARDWARE_VERIFIED_m_axi_fix/`, ledger C-001/C-153). Post-route
resources (0 BRAM18K, 0 DSP, 1245 FF, 1018+295 LUT) and timing (WNS +0.003 ns, 300 MHz achieved,
0 failing endpoints) are both real Vivado reports for the first time in this campaign (ledger
C-151/C-152). An opportunistic Python-loop latency measurement (not the rigorous E02) gives
p50=49.5 μs, p99=61.0 μs round trip (ledger C-154).

**What remains open:** this closes B-001 for the Shor kernel only. Rep-3 and the reconstructed
Steane kernel have not been through `v++`/Vivado at all (still `UNSUPPORTED`/`BLOCKED`, see D
below and B-005). The latency measurement above is a crude stand-in for the real E02 (needs a
C++ host, `clock_gettime`, ≥10^6 shots, tail statistics). E01's full exhaustive 3^9 hardware sweep
has not been run (only the 27-case self-test). Multi-CU (E04) and batched-throughput (E03) work
has not started. The device remains shared with other work on this machine and required a
`render`-group-independent, root-only `xbutil reset` from the author to reclaim before this run.

### History (kept for the record)

**UPDATE (2026-08-20 morning): kernel execution on real hardware, confirmed.** With the author running
`xbutil reset -d 0000:8c:00.1 -t user --force` to clear a stuck hardware context left over from
unrelated work on this shared machine, the original unmodified `shor_qec_kernel.xclbin` loads
successfully on this host and the kernel runs to `ERT_CMD_STATE_COMPLETED`, confirmed on two
independent runs (`evidence/runs/2026-08-20_original_host_this_hardware/`). This is the first
genuine `MEASURED-HW` result in this entire campaign (ledger C-149).

**What is still blocked:** reading the kernel's *output*. Running the original author's own
`shor_qec_host.py` unmodified against this now-working device gives a more precise diagnosis than
the original `PermissionError` story: path X (ctypes) successfully loads
`libxrt_coreutil.so` and enumerates its real exported symbols, and **`xrtRunGetReturnValue` is
simply not among them; `xrtRunReadRegister` is an undefined symbol.** On XRT 2.15.225, the direct
register-read C API this host driver's Path X depends on is not exported by the shared library at
all, independent of permissions. Path B (BAR4) was not properly exercised in this run because the
script's `PCI_RESOURCE4_PATHS` is hardcoded to the *original* capture host's four BDFs, none of
which match this host's `0000:8c:00.1`; combined with the already-confirmed finding that this
host's `resource4` is root-owned regardless (C-131), Path B would fail here too. Self-test again
falls back to the software decoder (27/27, matching `selftest.log`'s pattern, now for a
newly-diagnosed reason). See ledger C-150 for the full finding, and note this is a strong,
hardware-confirmed argument for the manuscript's own recommended fix: reading a result via a
standard `xrt::bo` buffer object (this revision's `m_axi` output-buffer addition, C-142-HLS) does
not depend on these fragile, XRT-build-specific raw symbols at all.

**Next step:** build (`v++ -c` / `v++ -l`, real wall-clock time, likely 15 minutes to a few hours
for Vivado implementation on kernels this small) and test the `m_axi`-fixed kernel
(`rtl/shor913/src/shor_qec_kernel.cpp`) against this same live device, reading its result via a
standard `xrt::bo`. If that closes the loop, this campaign gets its first hardware-measured,
hardware-verified correctness and latency result. Not yet started as of this update.

### Original entry (superseded in severity, kept for the record)
**Blocks:** E01, E02, E03, E04, E05, and every `MEASURED-HW` row in the ledger.
**Evidence:** `evidence/runs/selftest.log` shows XRT buffer path A failing with a range error on
arg index 1, BAR4 mmap failing with `PermissionError` on all four device BDFs
(`0000:01:00.1`, `0000:21:00.1`, `0000:41:00.1`, `0000:81:00.1`), user `abhishek` not in `render`
group, and the run falling back to the software decoder.

**UPDATE (2026-08-19, this working host):** the machine this revision campaign is actually
running on is a *different* machine from the one that produced `selftest.log`, and its situation
is materially better:
- `xbutil examine` shows a live, "Ready" Alveo U55C at PCIe BDF `0000:8c:00.1`
  (shell `xilinx_u55c_gen3x16_xdma_base_3`, XRT 2.15.225 / 2023.1).
- The current user (`cdac`) is **already** a member of the `render` group (`id` confirms
  `gid=109(render)` is present). The exact fix `selftest.log` recommends is already applied here.
- This means the specific BAR4-`PermissionError` failure mode may not reproduce on this host at
  all. It does **not** mean hardware verification is done: path A's failure in the log was a
  different, more fundamental problem (the AXI-Lite return register isn't a standard AXI4 master
  port, so a zero-length buffer is created regardless of permissions — see ledger C-008), the
  delivered `shor_qec_kernel.xclbin` was built for platform `xilinx_u55c_gen3x16_xdma_3_202210_1`
  which needs to be checked for compatibility against this host's `xdma_base_3` shell and its
  older XRT (2.15.225 vs. the 2.16.204 the manuscript assumes), and the kernel still needs the
  output-buffer-argument fix (Section 11's own recommendation, option 3 below) before path A will
  work cleanly on any host.
- No kernel has been run and no register has been read on this host yet. This update is a
  correction to the blocker's *severity*, not a claim that E01/E02 are unblocked.

**Needed, in order of preference (updated 2026-08-20):**
1. ~~Authorisation to attempt a self-test run against this host's live device~~ **DONE** — kernel
   execution confirmed real (C-149), read-back failure precisely diagnosed (C-150).
2. Authorisation to spend real build time (`v++ -c`/`v++ -l`, Vivado implementation, likely
   15 minutes to a few hours) building the `m_axi`-fixed kernel and testing its `xrt::bo`
   read-back against this live device. This is the next concrete step toward a real MEASURED-HW
   correctness and latency result, and does not depend on anything further from the author beyond
   this authorisation and continued access to the device (which is shared with other work on this
   machine — the same reset-and-check dance may be needed again before each run).
3. If this host's device turns out to be shared/production and unsuitable for repeated
   measurement runs (10^6-shot E02 sweeps, multi-CU E04 builds), confirmation of which machine is
   the intended measurement host, and access to it.
**From:** author, to authorise (2).
**Workaround:** none. Software-mirror numbers cannot substitute.

## B-002: Vitis and Vivado availability (STATUS UPDATED — largely satisfied on this host)
**Blocks:** all resynthesis, multi-CU builds, post-route report regeneration.
**UPDATE (2026-08-19):** Vitis 2023.2 is installed locally (`/tools/Xilinx/Vitis/2023.2`,
`/home/cdac/tools/Vitis`), and the exact platform used for the original build,
`xilinx_u55c_gen3x16_xdma_3_202210_1`, is present under `/opt/xilinx/platforms/`. Vitis HLS 2023.2
is also present. This significantly de-risks resynthesis of the Steane and Rep-3 kernels (Table
2/3 rows currently `UNSUPPORTED`/`CONTRADICTED` for lack of any build artifact) and regeneration
of the missing Shor `*_csynth.rpt`.
**UPDATE 2 (2026-08-19):** ran `vitis_hls -f <script> csynth_design` for real, four times (Shor
original, Shor with the m_axi fix, reconstructed Steane with and without the m_axi fix). All four
completed in 15-20 seconds each with no license error and produced real `*_csynth.rpt`/`.xml`
reports, now in `evidence/synthesis/`. **HLS-level licensing/tooling is confirmed working, not
just installed.** What's not yet attempted: `v++` linking to a real `.xo`/`.xclbin` (Vitis Kernel
Flow, a separate license feature from bare HLS), and Vivado implementation (place-and-route) for
post-route reports — both still needed for Tables 2/3 and for anything to run on the card.
**Needed now:** wall-clock time for `v++ -c`/`v++ -l` builds and Vivado implementation runs
(these are the multi-minute-to-multi-hour steps `vitis_hls csynth_design` alone is not), and
confirmation that a `v++`/Vivado license (as opposed to the HLS-only license just exercised) is
available for this campaign's use.
**From:** author, to confirm the v++/Vivado license and approve spending build time on it.

## B-003: Missing Steane three-mode kernel source (RESOLVED for hardware purposes, 2026-08-20)

**RESOLVED (2026-08-20): the reconstruction is now hardware-verified.** Built end to end (`v++
-c`, `v++ -l`, full Vivado implementation, ~2h13m) and tested against the live Alveo U55C: 63/63
self-test PASS (21 cases × 3 modes, real `xrt::bo` read-back) and a full exhaustive sweep, all
3^7=2,187 patterns × 3 modes = 6,561 combinations, **6,561/6,561 agreeing with the software
mirror, zero mismatches** (ledger C-156). Real post-route data also obtained: 0 BRAM18K, 1286 FF,
1067+283 LUT, WNS +0.003 ns, 300 MHz achieved (C-157/C-158). This is the first time any Steane
decoder logic, reconstructed or original, has run on real hardware in this line of work's
history. If the author locates the *original* `steane_qec_kernel.cpp`, it should still be
preferred and diffed against this reconstruction — the blocker is resolved pragmatically, not by
recovering the original source.

### History (kept for the record)
**Blocks:** verification of ledger rows C-061 and C-062; any Steane hardware result.
**Evidence:** the only Steane kernel in the archive, `steane_decoder_kernel.cpp` (50 lines, read
in full), implements a single batched LUT-only decoder over three `m_axi` HBM ports with no mode
field, no MWPM logic, and no UF logic. It is architecturally unrelated to the AXI-Lite monolithic
three-mode kernel Sections 6.3 and 9 describe.

**UPDATE (2026-08-19):** rather than wait on the original source, I wrote
`rtl/steane713/src/steane_qec_kernel.cpp` from the manuscript's own algorithm description
(Section 6.3, Algorithm 3, L179-186) and verified its logic against a new Python mirror
(`models/mirrors/steane_mirror.py`, `models/tests/test_steane_mirror.py`): 63/63 self-test PASS.
Building the mirror caught a real bug in the manuscript's own UF description (ledger C-140) and
surfaced a Hamming-code aliasing property that contradicts the manuscript's weight-2 claim
(C-141) — both fixed/noted in the reconstruction, neither yet reconciled in `main.tex` itself.
**This closes the "no source exists" problem but does not close the blocker**: the kernel has
not been through HLS C-simulation, synthesis, or hardware, so it cannot yet produce any
`HLS-ESTIMATE`, `POST-ROUTE`, or `MEASURED-HW` row. If the author has the *original* source, it
should still be preferred over this reconstruction and diffed against it.
**Needed:** either the original `steane_qec_kernel.cpp`, or authorisation to proceed with this
reconstruction through HLS co-simulation and synthesis (B-002/B-005 territory next).
**From:** author, to confirm which path to take.

## B-005: No Steane or Rep-3 kernel was ever taken through v++ synthesis, as far as the archive shows (RESOLVED for this revision's kernels, 2026-08-20)

**RESOLVED (2026-08-20): both kernels now built, placed, routed, and hardware-verified.**
This revision's `rtl/rep3/src/rep3_qec_kernel.cpp` and `rtl/steane713/src/steane_qec_kernel.cpp`
(both with the `m_axi` fix) were taken through `v++ -c`, `v++ -l`, and full Vivado
implementation (~2h13-17m each) and tested against the live Alveo U55C: Rep-3 16/16 exhaustive
(C-159), Steane 63/63 self-test + 6,561/6,561 exhaustive (C-156). Real post-route reports exist
for both for the first time (C-157/C-158/C-160). **This does not answer the original question**
of whether the *original* submission's Table 2/3 Steane numbers were ever backed by a real
Vivado run on the author's original kernel — that kernel's source was never recovered (B-003)
and this revision's numbers are for a reconstruction. If the author locates the original build
outputs, they should still be sought and compared against this revision's real data.

### History (kept for the record)
**Blocks:** Tables 2 and 3 (Steane and Rep-3 rows), C-030 through C-035, and every latency figure
for those two kernels (C-011, C-013, C-018, C-019).
**Evidence:** no `.xo`, `.xclbin`, `.compile_summary`, or `.link_summary` exists for Steane or
Rep-3 anywhere in either archive, and neither `build.log` nor `xcd.log` mentions either kernel
(grepped directly, zero hits). Only the Shor kernel has any build evidence at all, and even that
is incomplete (no `*_csynth.rpt`, see B-002).
**Needed:** either the original build outputs from whatever run produced Table 2/3's Steane
numbers (if one occurred on a machine/date not captured in this archive), or authorisation to
synthesise both kernels fresh once B-002 licensing is confirmed. Table 3 in particular (Steane
*post-route*) cannot be explained by any artifact in the archive; the author should say plainly
whether that table was ever backed by a real Vivado run.
**From:** author.

## B-004: GPU baseline environment (OPEN, lower priority)
**Blocks:** ledger row C-023, reviewer point R2-3.
**Needed:** a machine with CUDA-Q / cudaq-qec, or a decision to delete the GPU line from Figure 6.
**From:** author.

## B-006: GitHub destination and hardware-run authorisation (OPEN, needed before any commit leaves this machine)
**Blocks:** pushing this repository anywhere, and running anything against the live Alveo card
noted in B-001.
**Needed:**
1. The target GitHub repository (new or existing, public or private) to push `qec-fpga-revision`
   to, and confirmation of the account/remote to use.
2. Explicit go-ahead to run a self-test against the live device found on this host (B-001 item 1),
   since that touches shared hardware and this campaign has not yet asked permission to use it.
**From:** author (Nasir Ali).
