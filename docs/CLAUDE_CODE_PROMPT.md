# Claude Code Mission Brief: Rebuild and Re-anchor the FPGA QEC Paper

**Project:** FPGA-based QEC decoders on Xilinx Alveo U55C (rep-3, Shor [[9,1,3]], Steane [[7,1,3]])
**Status:** Rejected by *The Journal of Supercomputing* (Submission e7d19f63-0e69-4714-a61d-f53b2885839f), 18 Aug 2026, three reviewers.
**Author:** Nasir Ali, C-DAC Noida, Embedded Systems Division (NQM / MeitY).
**Your role:** engineering lead for the revision campaign. You own the repository, the measurement harness, the manuscript rebuild, and the reviewer response letter.

---

## 0. Read this before you touch anything

### 0.1 The finding that outranks the reviewers

`selftest.log` in the supplied archive ends with:

```
WARNING  NOTE: self-test ran against SOFTWARE decoder, not the xclbin.
WARNING    path C: software decoder active — xclbin NOT exercised
INFO     active decode path: sw
INFO   ── Monte Carlo sweep: single_pauli, 10000 shots/point ──
```

The manuscript presents the 27/27 Shor self-test, the 21/21 Steane self-test, and the throughput figure (192,000 corrections/s attributed to "the Python software decoder ... as measured in selftest.log") as evidence of a working FPGA system. The only log in the archive shows the hardware path failing (BAR4 `PermissionError` on all four devices, XRT buffer path A raising a range error), the software mirror taking over, and 10,000 shots per point, not the 200,000 stated in Section 9.6 or the 10^5 stated in the abstract.

**Therefore: Priority Zero is not "address reviewer comments". Priority Zero is to establish, with logs, exactly which claims in the manuscript are backed by hardware execution and which are backed by the software mirror or by HLS estimates.** Reviewer 2 partially detected this ("No hardware-measured wall-clock latency is reported; the 17-20ns figures are HLS synthesis estimates only"). A resubmission that does not fix this at the root will fail again, and worse, a resubmission that repeats hardware claims without hardware logs is a research-integrity exposure for the author and for C-DAC.

Every task below is downstream of this. Do not carry any number forward into the revised manuscript unless it has a traceable artifact in `evidence/`.

### 0.2 Working rules, non-negotiable

1. **No number without provenance.** Every figure, table cell, and abstract claim maps to a row in `docs/CLAIMS_LEDGER.md` with: claim text, value, source artifact path, generating command, date, and a class tag of `MEASURED-HW`, `MEASURED-SW`, `HLS-ESTIMATE`, `POST-ROUTE`, `ANALYTIC`, or `PROJECTED`.
2. **Never fabricate, interpolate, or "reconstruct" experimental data.** If hardware is unavailable, the ledger records `BLOCKED` and the manuscript claim is deleted or downgraded, not estimated.
3. **`PROJECTED` numbers never appear in the abstract, the title, the conclusions, or any figure axis presented as a result.** They live in a clearly labelled discussion subsection.
4. **Regenerate, do not retouch.** Every figure must be produced by a committed script from a committed data file. No hand-edited images, no AI-generated diagrams (Reviewer 2 flagged both).
5. **Small commits, honest messages.** One logical change per commit. Reference the reviewer point being addressed, for example `fix(tab5): define m as n-k consistently [R1-Major-6]`.
6. **When you are blocked, stop and report.** Write the blocker into `docs/BLOCKERS.md` with what you need from the author (hardware access, `render` group membership, a Vitis licence, wall-clock time on the card) and move to the next independent task. Do not paper over a blocker with a plausible-looking substitute.
7. **Do not use em dashes in any prose you write** (manuscript, README, response letter). Use commas, semicolons, colons, or parentheses. En dashes in numeric ranges and hyphenated proper names are fine.

### 0.3 What you have been given

Two archives:

**`qec_fpga.zip`** (manuscript):
`main.tex` (640 lines, the submitted paper), `sn-article.tex`, `sn-jnl.cls`, `sn-bibliography.bib`, `sn-article.pdf`, `user-manual.pdf`, and seven PNG figures (`fig1_shor_structure`, `fig2_pipeline`, `fig3_error_curves`, `fig4_resources`, `fig5_syndrome_map`, `fig6_throughput`, `fig7_tanner`).

**`qec_fpga_files-*.zip`** (implementation):
- Kernels: `shor_qec_kernel.cpp` (238 lines, AXI-Lite monolithic, 256-entry static LUT), `rep3_qec_kernel.cpp` (158 lines), `steane_decoder_kernel.cpp` (50 lines), `fpga_kernel_v05.cpp` (973 lines, the statevector simulator, out of scope but referenced).
- Hosts: `shor_qec_host.py` (589 lines) plus v1/v2/v3 variants, `host_decoder.cpp` (419 lines, OpenCL C++ host with `chrono` and OpenCL profiling already wired), `steane_fpga_qec.py` (611 lines), `noise.py` (393 lines).
- Build: `Makefile`, `build_shor.sh`, `shor_link.cfg`, `rep3_link.cfg`, `v05_link.cfg`.
- Artifacts: `shor_qec_kernel.xclbin` (43 MB), `.xo`, `.xclbin.info`, `.link_summary`, `.compile_summary`, `build.log`, `xcd.log`, `selftest.log`, `lut_table.txt`.
- Data: `ibm_boston_calibrations_2026-04-13T06_47_34Z.csv`.
- Docs: `QEC_FPGA_GUIDE.md` (457 lines).
- Probes: `bar_probe.py`, `xrt_probe.py`, `benchmark_three_hardware.py`.

**Known gaps you must confirm in Phase 1:**
- There is no `steane_qec_kernel.cpp` implementing the three runtime-selectable decoder modes (LUT / MWPM / UF) that Sections 6.3 and 9 describe. The only Steane kernel present is a 64-way unrolled batch LUT decoder over a 512-bit HBM `m_axi` interface, which is a *different architecture* from the AXI-Lite monolith the paper describes. Locate the real source or record it as missing.
- `host_decoder.cpp` uses `m_axi` buffers and OpenCL profiling. This is the batched path the paper's Section 11 says does not exist yet. Establish which of these two stories is true.
- Table 2 reports Steane at 2 BRAM18K (HLS) and Table 3 reports 0 BRAM (post-route). Reviewer 1 Minor 5 asks why. Find the actual reports.

---

## 1. Target repository layout

Build this tree at `~/work/qec-fpga-revision/`. Every directory gets a `README.md` explaining what lives there and how to regenerate it.

```
qec-fpga-revision/
├── README.md                      # project state, how to reproduce everything, one page
├── Makefile                       # top-level: make bitstreams | measure | figures | paper | all
├── .gitignore                     # xclbin, xo, build dirs, *.jou, *.log from tools
├── environment/
│   ├── vitis-2023.2.md            # exact tool versions, platform xpfm path, XRT version
│   ├── host-machine.md            # CPU, RAM, OS, PCIe slot, device BDF, driver, group perms
│   └── requirements.txt           # python deps, pinned (numpy, matplotlib, stim, pymatching, scipy)
│
├── rtl/                           # kernel sources, one dir per kernel
│   ├── rep3/
│   ├── shor913/
│   ├── steane713/                 # must contain the real 3-mode kernel, or a rebuild of it
│   └── surface_d5/                # NEW, Phase 4
│       ├── src/
│       ├── cfg/                   # link.cfg, connectivity, clock constraints
│       └── README.md
│
├── host/
│   ├── cpp/                       # C++ XRT/OpenCL hosts, the ONLY path used for timing claims
│   │   ├── src/
│   │   ├── include/
│   │   └── CMakeLists.txt
│   ├── python/                    # convenience + software mirrors, NEVER used for timing claims
│   └── README.md                  # states explicitly which path produces publishable timing
│
├── models/                        # software mirrors and reference decoders
│   ├── mirrors/                   # bit-exact software twin of each hardware decoder
│   ├── reference/                 # stim circuits, pymatching baselines, UF reference impl
│   └── tests/                     # pytest: mirror vs hardware, mirror vs pymatching
│
├── experiments/                   # one directory per experiment, each self-contained
│   ├── E01_single_pauli_exhaustive/
│   ├── E02_hw_latency_histogram/
│   ├── E03_batched_throughput_scan/
│   ├── E04_multi_cu_scaling/
│   ├── E05_repeated_rounds_meas_error/
│   ├── E06_surface_d5_uf/
│   ├── E07_montecarlo_1e7/
│   └── E08_baseline_cpu_gpu/
│       ├── run.sh                 # the exact command, no hidden flags
│       ├── config.yaml            # every parameter, including RNG seed
│       ├── raw/                   # untouched tool output, logs, csv
│       ├── processed/             # derived csv/json only
│       ├── plot.py                # produces the figure from processed/
│       └── NOTES.md               # what was run, when, on what, what surprised you
│
├── evidence/                      # immutable, append-only proof for the claims ledger
│   ├── synthesis/                 # *_csynth.rpt, vivado utilization, timing summary
│   ├── runs/                      # timestamped hardware run logs
│   └── MANIFEST.sha256            # checksum every evidence file
│
├── figures/
│   ├── src/                       # tikz/matplotlib/drawio sources, no binaries here
│   ├── out/                       # generated PDF (vector) for the manuscript
│   └── README.md                  # figure -> generating script -> data file mapping
│
├── paper/
│   ├── main.tex                   # the rebuilt manuscript
│   ├── sections/                  # one file per section, \input from main.tex
│   ├── tables/                    # generated .tex tables, produced by scripts from processed data
│   ├── bib/references.bib
│   ├── figures -> ../figures/out  # symlink
│   └── build.sh
│
├── response/
│   ├── response_to_reviewers.md   # point-by-point, the source of truth
│   ├── response_to_reviewers.tex  # formatted for submission
│   └── change_log.md              # every manuscript change, mapped to reviewer point
│
└── docs/
    ├── CLAIMS_LEDGER.md           # the spine of this whole effort
    ├── BLOCKERS.md
    ├── DECISIONS.md               # architectural decision records, one per decision
    ├── SCOPE.md                   # what this paper claims and, explicitly, what it does not
    └── legacy/                    # the original submitted files, read-only, for diffing
```

**Rules for the tree:** `docs/legacy/` is never edited. `evidence/` is append-only and checksummed. Anything in `experiments/*/raw/` is never edited by hand. If a file does not have an obvious home, it does not belong in the repo.

---

## 2. Phase 1: Forensic audit (do this first, it gates everything)

**Goal:** know exactly what is true.

1. Ingest both archives into `docs/legacy/`, checksum them, commit as the baseline.
2. Build `docs/CLAIMS_LEDGER.md`. Extract *every* quantitative claim from `main.tex`: abstract, contributions list, Tables 1 through 5, all seven figure captions, Sections 9, 10, 11, and the conclusions. Expect roughly 60 to 90 rows. Columns:
   `ID | Location | Claim | Value | Class | Evidence path | Reproducing command | Verdict`
   Verdict is one of `SUPPORTED`, `UNSUPPORTED`, `CONTRADICTED`, `NEEDS-RERUN`.
3. Grep the entire implementation archive for the evidence. Specifically resolve:
   - 17 ns and 20 ns latency: is there a `*_csynth.rpt` giving cycle counts, and is there *any* wall-clock hardware measurement anywhere? (Expect: HLS only. Mark `HLS-ESTIMATE`.)
   - 2.318 ns and 1.941 ns critical path: from which report?
   - 300 MHz timing closure: from `build.log` / `link_summary` / Vivado timing summary, or asserted?
   - Table 2 vs Table 3 BRAM discrepancy: find both reports and explain in one sentence.
   - 27/27 and 21/21: which decode path produced them? (`selftest.log` says software.)
   - 192,000 corrections/s: software mirror on host CPU, single-threaded Python. Confirm and note that this is *not* a fair software baseline.
   - 200,000 shots per point: find the log. If absent, the correct value is 10,000 and both the abstract and Section 9.6 are wrong in the same direction.
   - The 20-compute-unit and 6e9 corrections/s claim: confirm it is arithmetic, not an implementation.
4. Write `docs/SCOPE.md`: a blunt two-column list, "what the artifact demonstrates" versus "what the manuscript claimed". This becomes the skeleton of the response letter.
5. Report to the author before proceeding. Do not start Phase 2 until the ledger is reviewed.

---

## 3. Phase 2: The title and framing problem

The author has independently concluded the title is not justifiable. Reviewer 1 (Minor 1), Reviewer 1 (Major 1), and Reviewer 2 (point 2) all converge on the same thing: "Real-Time Quantum Error Correction" describes a closed control loop, and this artifact is a host-driven decoder kernel.

Produce `docs/DECISIONS.md` entry ADR-001 with the title options and a recommendation. Candidates to evaluate:

- *Sub-Cycle Syndrome Decoding for Distance-3 Stabilizer Codes on the Alveo U55C: an Open, Measured HLS Reference Design*
- *Hardware Decoder Kernels for the Shor and Steane Codes: Synthesis, Measurement, and the Host-Interface Latency Wall*
- *From Kernel Latency to Loop Latency: What an FPGA Distance-3 QEC Decoder Actually Costs on a Commodity Accelerator Card*
- *A Measured Characterisation of FPGA Syndrome Decoders for Distance-3 CSS Codes, and the Batching Threshold for Real-Time Operation*

The framing pivot to recommend: **the paper's honest and genuinely interesting result is that the decoder is free and the interface is not.** The kernel costs 17 ns and 0.02% of the fabric; the host path costs about 5 microseconds and is the entire problem. That is a real, publishable, and useful engineering finding, and it is exactly what a control-stack engineer needs to know. Sections 9.7 and 11 currently bury it as a limitation. Promote it to the thesis. A paper that says "we measured where the wall is, and here is the batching threshold at which it moves" survives review; a paper that says "we achieved real-time QEC" does not.

Apply the same discipline to keywords (Reviewer 2 point 4: currently generic). Replace the twelve-term list with six specific terms.

---

## 4. Phase 3: Hardware measurement campaign (the core new work)

This directly answers R1-Major-1, R1-Major-3, R1-Major-5, R2-2, R2-3.

### E01: Exhaustive correctness, on hardware
- Resolve the BAR4 permission blocker first. Options in order of preference: (a) add the user to the `render` group and re-login; (b) add a one-element `m_axi` output buffer argument to the kernel so the result returns over a standard AXI master port, which the manuscript's own Section 11 already identifies as the clean fix; (c) run the C++ XRT host, which does not depend on the `/sys/bus/pci/.../resource4` mmap path at all. **Prefer (b) plus (c).** It is a small kernel change and it removes the entire class of failure.
- Rerun 27/27 and 21/21 against the loaded xclbin, with the log showing `active decode path: hw`.
- Extend beyond single-Pauli: all 3^9 = 19,683 Shor error patterns and all 3^7 = 2,187 Steane patterns, comparing hardware output to the software mirror bit-for-bit. Report agreement rate and enumerate every disagreement. This upgrades "sanity check" to "exhaustive verification over the input space", which is a real answer to R1-Major-5.
- Add measurement-error and syndrome-fault injection as a separate exhaustive sweep, and report where the decoder is correct-by-construction versus where it fails. R1-Major-5 asks for exactly this.

### E02: End-to-end latency, measured, with tails
Reviewers do not want a mean. They want a distribution.
- Instrument the C++ host with `clock_gettime(CLOCK_MONOTONIC_RAW)` around: register write, kernel execute, register read, and the full round trip. Use OpenCL profiling counters where available for the kernel-only interval.
- 10^6 single-shot invocations minimum. Emit a full histogram, and report p50, p90, p99, p99.9, p99.99, and max. Real-time is a worst-case property, which is precisely R1-Major-3's third point.
- Produce the same distribution for: Python PyXRT path, C++ XRT native API path, C++ OpenCL path, and (if you can) a pinned, isolated-core, `SCHED_FIFO` variant. The spread across these four is itself a result worth publishing.
- Decompose the latency budget into a stacked bar: host software, PCIe round trip, AXI-Lite register access, kernel compute. Reviewer 1 explicitly asks where the time goes.

### E03: Batched throughput
Section 11 promises this and the archive may already contain it (`steane_decoder_kernel.cpp` processes 64 syndromes per 512-bit beat over `m_axi`).
- Implement or finish the batched interface for all three kernels. Sweep batch size from 1 to 2^20 in powers of two.
- Plot measured corrections/s against batch size, with the II=1 ceiling as a horizontal asymptote and the per-invocation overhead as the low-batch regime.
- **Report the crossover batch size at which the amortised per-syndrome latency drops below 1 microsecond.** Frame it clearly: batching buys throughput and costs loop latency, so a real QEC loop cannot use large batches. This is the honest reconciliation of R1-Major-3 and it is a genuinely useful engineering number.
- Report measured throughput next to the II=1 kernel-level rate, and label them differently everywhere. Never again present 3e8 corrections/s without the measured number beside it.

### E04: Multi-CU scaling, measured not extrapolated
R1-Major-3 point 2 rejects the 20-CU extrapolation outright.
- Build actual xclbins with 1, 2, 4, 8 compute units. Report post-route utilisation, achieved Fmax, routing congestion, and *measured* aggregate throughput at each point.
- If scaling is sublinear (it will be, because AXI-Lite control and host dispatch serialise), that is the result. Say so. Delete the 6e9 figure entirely unless you have measured it.
- If 20 CUs will not close timing or route, report the failure. A negative result honestly reported is worth more here than the extrapolation.

### E05: Repeated rounds with measurement error
R1-Major-1 says the loop must include syndrome extraction, transfer, decode, Pauli-frame update, feedback, and repeat.
- Implement a Pauli-frame update path in the kernel (an XOR into a persistent frame register) and a multi-round driver.
- Measure sustained round rate over 10^4 to 10^6 rounds. Report backlog behaviour: does the decoder keep up when syndromes arrive at 1 MHz, and what happens in the tail?
- This is the single highest-value experiment for converting "decoder kernel" into "loop component with measured behaviour". Even a synthetic syndrome source (from Stim) rather than a real QPU makes the claim defensible, as long as you say plainly that the syndrome source is simulated.

### E08: Fair baselines
R2-3 says there is no quantitative comparison with prior work.
- CPU baseline: not a Python loop. Use a compiled C decoder, single core and multicore, plus PyMatching for the surface-code cases. The current 192,000/s Python number makes the FPGA look good by comparing against a strawman, and a reviewer who notices will not be gentle.
- GPU baseline: if CUDA-Q / cudaq-qec is available, run it and report properly, including per-invocation overhead at small batch. If not available, delete the GPU line from the throughput figure rather than citing "roughly 10^5" with no source.
- Literature comparison table: Das et al. (AFS), Liyanage et al., Holmes et al. (NISQ+), Riste et al., plus recent Riverlane and Google real-time decoder results. Columns: code and distance, platform, decoder algorithm, reported latency, whether measured or estimated, whether a closed loop. Your row goes in the same table with the same honesty applied. This one table does more for the paper than any other single addition.

---

## 5. Phase 4: The scaling track (optional in scope, decisive in impact)

Reviewer 2 states the resubmission condition explicitly: "distance-5+ iterative decoders with genuine hardware measurements and comparison to existing work would constitute a meaningful contribution."

Recommend to the author that this is worth doing, and scope it as:

- **Rotated surface code, d=5** (24 stabilizers, 25 data qubits), with a **union-find decoder** in HLS or hand-written RTL. UF is the right choice: it is near-linear, hardware-friendly, and Holmes et al. already established the peeling step parallelises.
- Multi-round decoding over a space-time graph, with measurement errors, over d rounds. This is the regime where the LUT approach dies (which the paper already admits) and where FPGA work has value (which Reviewer 2 correctly says is the only regime that matters).
- Verify against PyMatching and Stim: same circuit-level noise model, same shots, logical error rate curves overlaid with confidence intervals. Agreement with PyMatching is your correctness argument at d=5, replacing the exhaustive-enumeration argument that only works at d=3.
- Measure latency per round and its tail, and report the backlog threshold.
- Extend to d=7 if the fabric and the calendar allow, so the scaling trend has three points rather than two.

If the author decides against this track, that is a legitimate call. In that case the paper must be repositioned as a measurement and reference-design paper and submitted somewhere that fits (see Section 8), and `docs/SCOPE.md` must say plainly that d>=5 is future work with a stated reason.

---

## 6. Phase 5: Statistics, tables, and figures

### Monte Carlo (R2-3, R1-Minor-4)
- Run 10^7 shots per point as the reviewer asks. On the batched path this is minutes, not a research programme.
- Every logical error rate gets a Wilson score interval, plotted. No point may be reported without its uncertainty.
- Where the LUT / MWPM / UF curves are claimed to be "statistically identical", back it with an actual test (paired bootstrap or a two-proportion z-test per point) and report the p-values. Otherwise delete the claim.
- Fix the shot count everywhere: abstract, Section 9.6, all captions, conclusions. One number, sourced from the run log.
- Add circuit-level depolarising noise (Stim-generated) alongside the current phenomenological models. R1-Major-5 and the limitations section both point here.

### Table 5, the syndrome-width table (R1-Major-6)
Rebuild it with a stated definition at the top of the caption: **m is the number of independent stabilizer generators, m = n - k**, for every row, no exceptions.
- Steane [[7,1,3]]: m = 6, not 3. If the decoder uses two independent 3-bit LUTs for the X and Z halves, add an explicit column `m_X | m_Z` and state the CSS decomposition in the text.
- BB [[72,12,6]]: m = 60, not 72.
- Surface d=3: state whether you mean the rotated (m = 8) or unrotated (m = 16) code.
- Recompute every LUT-entry and BRAM column from the corrected m. The scalability argument gets *stronger* with correct numbers, not weaker.

### Tables 2 and 3 (R1-Minor-5)
Add a note distinguishing HLS post-synthesis estimate from Vivado post-route actual, and explain the BRAM 2 to 0 change (almost certainly LUTRAM inference for the 8-entry Steane table during implementation). Verify against the reports, do not guess.

### Figures (R1-Minor-2, R2-4)
Regenerate all seven, plus the new ones. Requirements:
- Vector PDF only. No PNG in the final manuscript.
- Minimum 8 pt effective font at final column width. Check by measuring the rendered PDF, not by eye.
- No AI-generated schematics. Redraw `fig1_shor_structure`, `fig2_pipeline`, and `fig7_tanner` in TikZ or draw.io with clean, checked labels. Reviewer 2 saw text overflow and label misalignment, which reads as carelessness and colours the whole review.
- Move dense in-figure explanatory text into the caption or the body.
- Every figure script lives in `figures/src/` and reads only from `experiments/*/processed/`.

New figures the revision needs: latency histogram with tail markers (E02), latency budget decomposition (E02), throughput versus batch size with the 1 microsecond crossover marked (E03), measured multi-CU scaling (E04), and, if Phase 4 runs, d=5 logical error rate versus PyMatching (E06).

### HLS versus post-route separation (R1-Minor-3)
Introduce a single convention and apply it everywhere, including captions: superscript or a tag column marking `[HLS]`, `[route]`, `[measured]`. Add one short subsection in the methodology defining the three and stating which claims rest on which.

---

## 7. Phase 6: Manuscript rebuild

Do not edit `main.tex` in place. Split into `paper/sections/*.tex` and rebuild.

**Structural surgery (R2-4, R3-1):**
- Sections 2 to 4 (related work, stabilizer formalism, the three codes) are disproportionate to Section 6 (implementation). Compress the tutorial content hard. The stabilizer-as-Boolean-logic exposition is good writing but it belongs in two pages, not the current spread, and the parts worth keeping should move to an appendix. The saved space goes to measurement results.
- Merge the many one-paragraph subsections (R3-1). A subsection needs at least half a page to justify itself.
- The new centre of gravity is the measurement section. Aim for roughly: 15% background, 25% implementation, 45% measurement and results, 15% discussion and limitations.

**Specific line edits requested by Reviewer 3:**
- Page 3: "against the self test oracle" becomes "against a self-test oracle" (R3-2).
- Page 4: "Both the Shor and Steane codes have [[n,k,d]] = [[9,1,3]] and [[7,1,3]] respectively" becomes "The Shor code has parameters [[9,1,3]]; the Steane code has [[7,1,3]]" (R3-3).
- Reference [4] author list is wrong (R3-4). The current entry reads "A. G. Fowler, M. Martinis, A. Fowler, and J. M. Martinis", which is garbled. Correct to Fowler, Mariantoni, Martinis, Cleland, Phys. Rev. A 86, 032324 (2012). **Then audit the entire bibliography, because this is not the only broken entry:**
  - `battistel2023real` is keyed and cited as a real-time decoding analysis but the entry's title, authors, journal, and year describe a leakage-reduction paper. One of the two is wrong.
  - `ristE2024scalable` carries the same title as `liyanage2023scalable` ("Scalable quantum error correction for surface codes using FPGA") with different authors, venue, and year. At least one is misattributed.
  - Verify every one of the nineteen entries against the actual publication record: authors, title, venue, volume, pages, year, DOI. Add DOIs throughout.
- Grammar and formatting pass (R1-Minor-6): awkward line breaks, spacing, dense captions.

**Claims discipline throughout:**
- Delete "rigorous correctness proof" (Section 5.1). Self-tests are verification, not proof. R1-Major-5 names this directly.
- Rewrite the Steane MWPM and UF description to state up front that these are **small-code specialised decision circuits** exploiting the Hamming structure, not general graph decoders (R1-Major-4). The paper already half-admits this in Section 10.1; move that admission forward to where the modes are introduced, and remove any implication of scalable MWPM/UF support.
- Rewrite the contributions list (Section 1.2). Drop "first complete Vitis HLS implementations" unless you can substantiate priority with a search. Replace with what is actually defensible: an open, measured, reproducible reference design; a decomposed latency budget for the host-FPGA path; a measured batching threshold; a corrected scalability analysis.
- Every remaining instance of "real-time" gets audited. Either it is qualified (real-time-capable kernel, sub-round decode latency) or it is deleted.

---

## 8. Venue reassessment

Add `docs/DECISIONS.md` ADR-002. *The Journal of Supercomputing* was arguably the wrong venue: this is a QEC control-stack and reconfigurable-computing contribution, not a supercomputing one. Evaluate and recommend among: IEEE TQE, ACM TRETS, ACM JETC, *Quantum Science and Technology*, FCCM or FPL (conference, with a strong artifact), IEEE QCE. Weigh against whether Phase 4 is executed, since d=5 with measured hardware opens the stronger venues and a d=3 measurement study fits TRETS or FCCM better.

---

## 9. Phase 7: Response to reviewers

`response/response_to_reviewers.md`, point by point, in reviewer order, every point answered. Format per point:

```
### R1-Major-3: The throughput comparison is misleading
**Reviewer's concern:** [one-sentence restatement, fairly]
**Our response:** [what we did]
**Changes made:** [Section, Table, Figure references in the revised manuscript]
**Evidence:** [experiments/E03_.../ , figure N]
```

Tone: concede what is correct without hedging. Reviewer 1 Major 1 and 3, Reviewer 2 points 1 and 2 are all correct and should be conceded plainly and early, because a response letter that concedes cleanly and then shows measured data is far more persuasive than one that argues. Where you disagree, disagree with data, once, briefly.

Maintain `response/change_log.md` in parallel: every manuscript edit, mapped to the reviewer point that motivated it. This is what you check against at the end to prove no point was silently dropped.

---

## 10. Complete reviewer checklist (acceptance criteria)

Nothing ships until every row is `DONE` with an evidence path.

| ID | Point | Required outcome |
|---|---|---|
| R1-Maj-1 | Real-time claim overstated | Title and abstract reframed; loop components enumerated with which are implemented and which are not; E05 multi-round measurement present or the claim removed |
| R1-Maj-2 | Limited architectural insight | Contributions rewritten around measurement and reproducibility; latency-wall finding promoted to thesis; ADR documenting the monolithic choice with measured justification |
| R1-Maj-3 | Misleading throughput | Measured end-to-end throughput reported alongside II=1 rate, distinctly labelled; 20-CU extrapolation deleted or replaced by measured E04; worst-case latency reported, not just peak throughput |
| R1-Maj-4 | MWPM/UF not general | Explicit statement at first mention that these are small-code specialised circuits; all scalability implications removed |
| R1-Maj-5 | Verification insufficient | Exhaustive 3^n enumeration on hardware; measurement-error and repeated-round tests; "rigorous correctness proof" deleted |
| R1-Maj-6 | Syndrome-width definition | Table 5 rebuilt with m = n - k stated and applied; Steane 6, BB 60; CSS half-syndrome decomposition explained |
| R1-Min-1 | Title | New title selected via ADR-001 |
| R1-Min-2 | Figure quality | All figures vector, >=8 pt, redrawn, in-figure text moved to captions |
| R1-Min-3 | HLS vs post-route | Tagging convention introduced and applied throughout; methodology subsection defining the three classes |
| R1-Min-4 | Shot count inconsistent | Single sourced value everywhere, traced to a run log |
| R1-Min-5 | Table 2 vs 3 BRAM | Discrepancy explained from the actual reports |
| R1-Min-6 | Grammar and formatting | Full proofread pass; line breaks and spacing fixed |
| R2-1 | Non-scalable method | Phase 4 d=5 UF decoder, or explicit repositioning as a d=3 measurement study with the scalability ceiling as a stated finding rather than a buried admission |
| R2-2 | Real-time unsupported | E02 hardware-measured latency distribution with tails; the ~5 microsecond host overhead moved from a limitation to a headline finding with the batching threshold quantified |
| R2-3 | Insufficient validation | Literature comparison table; fair CPU and GPU baselines; 10^7 shots with confidence intervals |
| R2-4 | Manuscript preparation | Figures redrawn from source; structure rebalanced; keywords narrowed |
| R3-1 | Subsection granularity | Short subsections merged |
| R3-2 | "a self-test oracle" | Fixed |
| R3-3 | Awkward [[n,k,d]] sentence | Fixed |
| R3-4 | Reference [4] | Fixed, plus full bibliography audit including battistel2023real and ristE2024scalable |
| **P0** | **Software-path claims** | **Every hardware claim re-established on hardware, or removed. `selftest.log` superseded by a log showing `active decode path: hw`** |

---

## 11. Suggested order of execution

1. Phase 1 forensic audit, then stop and report. (Days 1 to 3.)
2. Unblock the hardware path: kernel output-buffer argument plus C++ host. Rerun the self-tests on hardware. (Days 3 to 6.)
3. E01 exhaustive verification, E02 latency distribution. These two alone convert the paper from unsupported to supported. (Week 2.)
4. E03 batching, E04 multi-CU, E08 baselines. (Week 3.)
5. Decision point with the author on Phase 4 (d=5). (End of week 3.)
6. E05 repeated rounds, E07 statistics, table and bibliography corrections in parallel. (Week 4.)
7. Phase 4 if approved. (Weeks 5 to 8.)
8. Manuscript rebuild, figures, response letter. (Weeks 8 to 10.)

Report progress at the end of each phase against `docs/CLAIMS_LEDGER.md`, not against a task list. The ledger going from mostly `UNSUPPORTED` to entirely `SUPPORTED` is the actual definition of done.

---

## 12. What I want you to say back to me first

Before writing any code, produce:
1. The Phase 1 ledger, with the verdict column filled in.
2. A one-page statement of what the artifact provably does, based only on files in the archive.
3. `docs/BLOCKERS.md`, listing exactly what you need from me (card access, permissions, tool licences, wall-clock time).
4. Your recommendation on Phase 4, with a time estimate.

Then wait for my go-ahead.
