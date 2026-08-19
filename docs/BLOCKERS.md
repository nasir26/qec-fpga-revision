# Blockers

Append-only. Each entry: what is blocked, why, what is needed, from whom, and the workaround in use.

## B-001: Hardware decode path inaccessible on the ORIGINAL capture machine (OPEN, priority zero, status UPDATED)
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

**Needed, in order of preference:**
1. Authorisation to attempt a self-test run against this host's live device using the existing
   `shor_qec_kernel.xclbin`, to see whether it loads at all under the shell/XRT version mismatch
   noted above. Read-only risk beyond normal device use; needs a go/no-go from the author before
   any run against shared hardware.
2. Authorisation to add a one-element `m_axi` output-buffer argument to the kernel (small HLS
   change) and rebuild, which removes the BAR4/path-A dependency entirely regardless of host.
   This is the manuscript's own recommendation (Section 11) and remains the structurally correct
   fix even though B-001's acute symptom may not reproduce here.
3. If this host's device turns out to be shared/production and unsuitable for repeated
   measurement runs (10^6-shot E02 sweeps, multi-CU E04 builds), confirmation of which machine is
   the intended measurement host, and access to it.
**From:** author, to confirm (1) is authorised and (3) is answered before any experiment runs.
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

## B-003: Missing Steane three-mode kernel source (PARTIALLY ADDRESSED — reconstruction written, unverified against hardware)
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

## B-005: No Steane or Rep-3 kernel was ever taken through v++ synthesis, as far as the archive shows (OPEN, priority zero)
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
