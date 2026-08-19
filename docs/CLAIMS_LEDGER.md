# Claims Ledger

Every quantitative or evidentiary claim in the submitted manuscript, its supporting artifact,
and its verdict. This file is the spine of the revision. A claim may enter the revised
manuscript only when its verdict is `SUPPORTED` and its evidence path resolves.

**Class tags:** `MEASURED-HW` (executed on the Alveo card, log shows hardware decode path),
`MEASURED-SW` (host software mirror), `HLS-ESTIMATE` (Vitis HLS synthesis report),
`POST-ROUTE` (Vivado implementation report), `ANALYTIC` (closed-form), `VENDOR-SPEC` (datasheet),
`LITERATURE` (external citation), `PROJECTED` (extrapolation).

**Verdicts:** `SUPPORTED`, `UNSUPPORTED` (no artifact found), `CONTRADICTED` (artifact says otherwise),
`NEEDS-RERUN`, `NEEDS-VERIFY`, `NEEDS-CITATION`, `BLOCKED`, `DELETE` (claim should not survive
into the revision regardless of rerun outcome).

**Status: Phase 1 complete pass.** 86 rows. Every row below was checked directly against a file
in `docs/legacy/` during this pass (line numbers given for `main.tex`; filenames for evidence).
Two bibliography rows (H.4, H.5) were checked against the public record via web search on
2026-08-19; everything else was checked against files physically present in this repository.
No number in this ledger was estimated, interpolated, or reconstructed — where no artifact
exists, the verdict is `UNSUPPORTED` or `BLOCKED`, not a guess.

---

## A. Priority-zero rows: the self-test and the software/hardware path

| ID | Location | Claim | Value | Class claimed | Class actual | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|---|---|
| C-001 | Abstract; main.tex:43; Sec 9.5 (tab:selftest, L433-461) | Shor self-test passes all single-qubit Pauli errors | 27/27 | implied MEASURED-HW | MEASURED-SW | `implementation/selftest.log` L1-42 | **CONTRADICTED** | Log line 24: `active decode path: sw`. Line 41: `NOTE: self-test ran against SOFTWARE decoder, not the xclbin.` The xclbin was loaded (line 6) but never exercised for the return value. |
| C-002 | Abstract; main.tex:43,335 | Steane self-test passes, all three modes | 21/21 (×3 modes = 63) | implied MEASURED-HW | none found | none | **UNSUPPORTED** | No Steane self-test log anywhere in the archive. No `steane_qec_kernel.xclbin` exists to run it against (see C-061). The number in the abstract has no traceable run of any kind, hardware or software. |
| C-003 | Sec 9.7 (L493); Fig 6 caption (L488) | Python software decoder throughput | ≈192,000 corrections/s | MEASURED-SW | MEASURED-SW | `selftest.log` L38: `52.0 ms 192128 shots/s` | SUPPORTED (but weak baseline) | Single-threaded Python, single-shot `run.start()` loop. Not a fair software baseline (R1-Maj-3); replace with compiled C and PyMatching in E08. |
| C-004 | selftest.log itself | Monte Carlo shots per point actually run | 10,000 | MEASURED-SW | MEASURED-SW | `selftest.log` L37-40 | ground truth | This is the only real number; C-005/C-102 below are the manuscript's two conflicting, unsupported claims about it. |
| C-005 | Abstract L43 | Monte Carlo shots per point | $10^5$ | stated as measured | MEASURED-SW | `selftest.log` | **CONTRADICTED** | Log shows 10,000/point, not $10^5$. Neither abstract value nor Section 9.6 value (C-102) matches the log. |
| C-006 | Sec 1.2 contribution 4 (L78) | Software mirror "validated against the HLS golden-reference output" | bit-exact | MEASURED | not demonstrated | none | **UNSUPPORTED** | The archive shows the mirror used *instead of* hardware (selftest.log), never *compared to* hardware output. No comparison log, no diff report. |
| C-007 | Sec 5.1 (L69) | "a rigorous correctness proof (the 27/27 and 21/21 self-tests)" | qualitative | ANALYTIC | n/a | n/a | **DELETE** | Self-tests are verification over 27+21 fixed points, not a proof over the error group (R1-Maj-5). Remove regardless of rerun outcome. |
| C-008 | selftest.log L9 | XRT buffer readback path A | `vector::_M_range_check: __n (which is 1) >= this->size() (which is 0)` | n/a | n/a | `selftest.log` L9 | ground truth (blocker evidence) | Confirms manuscript Sec 11 (L542) diagnosis: the AXI-Lite return register is not a standard AXI4 master port, so an `xrt::bo` output-buffer path finds a zero-length buffer. |
| C-009 | selftest.log L10-17 | BAR4 mmap PermissionError on 4 device BDFs | `0000:01:00.1`, `0000:21:00.1`, `0000:41:00.1`, `0000:81:00.1` | n/a | n/a | `selftest.log` | ground truth (blocker evidence) | User `abhishek` not in `render` group at capture time. See `docs/BLOCKERS.md` B-001 for the status of this host, which differs. |

## B. Latency and timing

| ID | Location | Claim | Value | Class claimed | Class actual | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|---|---|
| C-010 | Abstract; Fig 2 caption L420; Conclusions L555 | Shor end-to-end decode latency | 17 ns (5 cycles) | reads as measured | HLS-ESTIMATE | `evidence/synthesis/shor_original_hls_2026-08-19/shor_qec_kernel_csynth.rpt` | **CONTRADICTED, resolved 2026-08-19** | Regenerated the missing csynth report by resynthesising the exact unmodified `docs/legacy/implementation/shor_qec_kernel.cpp` in Vitis HLS 2023.2 against `xcu55c-fsvh2892-2L-e` at the same 3.33 ns target. **Latency reported: 1 cycle (3.33 ns), not 5 cycles (17 ns).** Interval (II) is 1, matching the II=1 claim, but pipeline *depth* is 1, not 5. Critical path and resources match the manuscript exactly (see C-012, C-031) — same kernel, same tool version, same part, same clock target — so the 5-cycle/17 ns figure specifically does not reproduce. |
| C-011 | Abstract; Fig 2 caption; Conclusions | Steane end-to-end decode latency | 20 ns (6 cycles) | reads as measured | HLS-ESTIMATE, no original build exists | `evidence/synthesis/steane_reconstructed_*_hls_2026-08-19/` | **UNSUPPORTED (original)**, see C-142-HLS | Still no way to check the *original* kernel's claim (it never existed). The reconstructed kernel synthesises to 71 cycles (0.236 us) with the m_axi fix, or 2 cycles (6.66 ns) as pure AXI-Lite — neither is 6 cycles/20 ns, but neither is the original kernel either, so this row stays UNSUPPORTED rather than CONTRADICTED. |
| C-012 | Abstract; Sec 9.2 (L411) | Shor critical-path delay | 2.318 ns | HLS-ESTIMATE | HLS-ESTIMATE | `evidence/synthesis/shor_original_hls_2026-08-19/` | **SUPPORTED, resolved 2026-08-19** | Same regeneration as C-010: Estimated critical path reported as **2.318 ns**, an exact match to the manuscript. Genuine, reproducible confirmation of this one number — the HLS timing estimate was real, even though the latency-in-cycles claim in the same table row (C-010) was not. |
| C-013 | Abstract; Sec 9.2 | Steane critical-path delay | 1.941 ns | HLS-ESTIMATE | no original build exists | `evidence/synthesis/steane_reconstructed_*_hls_2026-08-19/` | **UNSUPPORTED (original)** | Reconstructed kernel gives 2.431 ns (m_axi) or 2.420 ns (AXI-Lite only) — close to but not matching 1.941 ns, and again this can't confirm or deny the original's number since the original source doesn't exist. |
| C-014 | Sec 8.1 (L344); Sec 9.2 (L411) | 300 MHz timing closure, no negative slack post-route, both kernels | qualitative | POST-ROUTE | partially corroborated | `shor_qec_kernel.xclbin.info` "Achieved Freq: 300 MHz" for `ulp_ucs_aclk_kernel_00`; timing report path cited in `build.log:374` (`impl_1_hw_bb_locked_timing_summary_routed.rpt`) but that file is **not in the archive** | **NEEDS-VERIFY** | The achieved-frequency field in xclbin.info is real post-implementation metadata and is consistent with closure for the *Shor* kernel only. It is not a slack report. "Both kernels" cannot be true since Steane was never built (C-011/C-013). |
| C-015 | Sec 11 (L546) | Per-shot latency via Python XRT | ≈5 μs | stated as known, uncited | none | none | **NEEDS-RERUN** | This is the paper's most important number (R2-2) and it is asserted, not measured anywhere in the archive. Becomes the headline result once E02 runs. |
| C-016 | Sec 10.4 (L537) | HBM mailbox round trip for co-hosting | 100-200 ns per access | PROJECTED | PROJECTED | none | UNSUPPORTED as stated, fine as projection | Discussion-only figure; must carry an explicit "projected" label, currently reads as a design fact. |
| C-017 | Sec 9.2 (L411) | Shor Fmax potential | 430 MHz ("44 MHz above target") | derived from C-012 | derived from confirmed estimate | Vitis HLS reports "Estimated Fmax: 431.41 MHz" directly (`shor_original_hls_2026-08-19/shor_qec_kernel_csynth.rpt`) | **SUPPORTED** | 431.41 MHz vs. the claimed 430 MHz — matches within HLS's own rounding. Note this is the *tool's estimate*, not a measured Fmax from timing closure; still correctly labelled HLS-ESTIMATE. |
| C-018 | Sec 9.2 | Steane Fmax potential | 515 MHz ("72 MHz above target") | derived from C-013 | derived from reconstruction, not original | Vitis HLS reports 411.37 MHz (m_axi variant) / 413.22 MHz (AXI-Lite variant) for the reconstructed kernel | **UNSUPPORTED (original)** | Neither reconstructed variant reaches 515 MHz; again cannot confirm or deny the original kernel's claim since it doesn't exist to test. |
| C-019 | Sec 6.1 (L244); Fig 4 caption (L406) | Rep-3 latency | 3 cycles / 10 ns | HLS-ESTIMATE | HLS-ESTIMATE | `evidence/synthesis/rep3_original_hls_2026-08-19/rep3_qec_kernel_csynth.rpt` | **CONTRADICTED, resolved 2026-08-19** | Resynthesised the unmodified `docs/legacy/implementation/rep3_qec_kernel.cpp`. Latency reported: **0 cycles** (fully combinational, II=1), not 3 cycles/10 ns. Same pattern as Shor (C-010): the claimed pipeline-stage count does not match a real HLS run of the actual committed source. |

## C. Throughput

| ID | Location | Claim | Value | Class claimed | Class actual | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|---|---|
| C-020 | Abstract; Sec 9.7; Fig 6 caption | Per-CU throughput at II=1, 300 MHz | $3\times10^8$ corrections/s | reads as achieved | ANALYTIC | clock (300 MHz, xclbin.info) × II=1 (asserted in source comments, unverified without csynth report) | SUPPORTED as arithmetic only | Must be labelled kernel-level steady-state ceiling, never as system throughput (R1-Maj-3). |
| C-021 | Abstract; Sec 9.7 (L491); Fig 6; Conclusions | Aggregate with 20 compute units | $6\times10^9$ corrections/s | reads as achieved | PROJECTED | none — no multi-CU xclbin, no build config for >1 CU | **DELETE or REPLACE** | Resource-based extrapolation from <0.02% utilisation of a *single* CU (R1-Maj-3 point 2). Replace with measured E04 or delete. |
| C-022 | Sec 9.7 (L493) | FPGA advantage over software decoder | 1,560× | reads as measured | derived from C-003 (real) ÷ C-020 (arithmetic ceiling) | mixed | **UNSUPPORTED as framed** | Divides a measured software number by an unmeasured hardware ceiling. Invalid comparison of apples (measured) to oranges (theoretical peak); becomes valid once C-020 is replaced by a measured E02/E03 number. |
| C-023 | Fig 6 caption (L488) | GPU batch decoder throughput | ≈$10^5$ corrections/s | reads as measured | none found | none | **UNSUPPORTED** | No GPU run, no script, no log anywhere in either archive. Run cudaq-qec (E08) or delete the line (R2-3). |
| C-024 | Fig 6 caption | Superconducting syndrome rate reference line | ≈$10^6$ Hz | literature | literature | no citation attached to the figure | **NEEDS-CITATION** | Plausible order of magnitude but needs a specific device/round-time citation, not a bare dashed line. |
| C-025 | QEC_FPGA_GUIDE.md L339 | BB[72,12,6] syndrome-extraction-only latency | 240 ns (72 cycles at II=1) | ANALYTIC | ANALYTIC (guide document, not manuscript) | `QEC_FPGA_GUIDE.md:339` | not in manuscript, note only | Referenced implicitly by Table 5/Sec 10.3 discussion; guide text, not a manuscript claim, keep separate. |

## D. Resources (Tables 2 and 3)

| ID | Location | Claim | Value | Class claimed | Class actual | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|---|---|
| C-030 | Table 2 (tab:resources, L369-382) | Rep-3: 0 BRAM, 0 DSP, ≈40 FF, ≈60 LUT6, <1.0 ns | as listed | HLS-ESTIMATE | HLS-ESTIMATE | `evidence/synthesis/rep3_original_hls_2026-08-19/` | **CONTRADICTED, resolved 2026-08-19** | Real synthesis: 0 BRAM18K, 0 DSP, 198 FF, 367 LUT, 2.053 ns critical path. BRAM/DSP match; FF is ~5x the claimed "≈40", LUT is ~6x the claimed "≈60", and critical path (2.053 ns) is more than double the claimed "<1.0 ns". The tilde/approximation symbols in the original table turn out to have been optimistic guesses, not rounded real numbers — the actual HLS estimate is neither close to nor consistent with them. |
| C-031 | Table 2 | Shor: 1 BRAM18K, 0 DSP, 190 FF, 228 LUT6, 2.318 ns | as listed | HLS-ESTIMATE | HLS-ESTIMATE | `evidence/synthesis/shor_original_hls_2026-08-19/` | **SUPPORTED, resolved 2026-08-19** | Exact match on resynthesis of the unmodified original kernel: 1 BRAM18K, 0 DSP, 190 FF, 228 LUT, 2.318 ns. This is the one row in Tables 2/3 that turned out to be genuinely real (as an HLS estimate — still not post-route). The latency figure quoted alongside it in the same original table (5 cycles) does not hold (C-010); the resource/timing figures do. |
| C-032 | Table 2 | Steane (×3 modes): 2 BRAM18K, 0 DSP, 251 FF, 744 LUT6, 1.941 ns | as listed | HLS-ESTIMATE | no original build exists | `evidence/synthesis/steane_reconstructed_*_hls_2026-08-19/` | **UNSUPPORTED (original)** | Reconstruction gives 2 BRAM18K / 0 DSP / 1685 FF / 1832 LUT / 2.431 ns with the m_axi fix, or 0 BRAM18K / 0 DSP / 242 FF / 699 LUT / 2.420 ns as pure AXI-Lite. BRAM18K count (2) coincidentally matches the original claim in the m_axi variant, but FF and LUT are 3-7x higher in both variants than the original claim — expected, since the reconstruction actually implements the MWPM/UF logic the original archive never provided evidence for, plus (in the m_axi variant) the AXI master interface overhead. Still cannot confirm the original kernel's specific numbers, only that a real 3-mode kernel costs substantially more than what was claimed. |
| C-033 | Table 2 totals row | Total: 3 BRAM18K, 0 DSP, ≈481 FF, ≈1032 LUT6 | as listed | derived | now fully recomputable from real HLS-ESTIMATE data | arithmetic on C-030/031/032 | **NEEDS-RECOMPUTE, data now available** | Rep-3 (198 FF/367 LUT, C-030) + Shor (190 FF/228 LUT, C-031, original kernel) + Steane reconstruction (242 FF/699 LUT AXI-Lite-only, or 1685 FF/1832 LUT with the m_axi fix, C-032) gives a real total once the author picks which Steane variant belongs in the table (the AXI-Lite-only reconstruction is the fairer like-for-like comparison against the also-not-yet-m_axi-fixed Rep-3/Shor originals). Not yet recomputed into a final number pending that choice, and pending Rep-3's own m_axi fix for full consistency. |
| C-142-HLS | New evidence, not a manuscript claim | HLS-ESTIMATE cost of the m_axi output-buffer fix (B-001's own recommended solution) | Shor: +2 BRAM18K, +1019 FF, +909 LUT, latency 1→70 cycles (3.33 ns→233 ns). Steane: +2 BRAM18K, +1443 FF, +1133 LUT, latency 2→71 cycles (6.66 ns→236 ns). | HLS-ESTIMATE | HLS-ESTIMATE | `shor_original_hls_2026-08-19/` vs `shor_m_axi_fix_hls_2026-08-19/`; `steane_reconstructed_axilite_only_hls_2026-08-19/` vs `steane_reconstructed_m_axi_hls_2026-08-19/` | **NEW FINDING, relevant to ADR-001's framing pivot** | The exact fix the manuscript's own Section 11 recommends for the BAR4 readback problem is not free: it costs roughly 35-70x pipeline depth in exchange for a working, privilege-independent result path, on top of real BRAM/FF/LUT overhead. This is precisely the kind of "the decoder is free, the interface is not" data point the brief's Phase 2 framing pivot asks for, quantified for the first time with a real tool run rather than asserted. Still HLS-ESTIMATE only, not post-route or hardware-measured; and the AXI master read-side latency (the actual bottleneck a host would see) has not been measured yet, only this write-side pipeline depth. |
| C-034 | Table 3 (tab:util-routed, L384-399) | Steane post-route: 134 LUT, 0 LUTAsMem, 196 REG, 0 BRAM, 0 URAM, 0 DSP | as listed | POST-ROUTE | **no build exists** | none | **UNSUPPORTED** | This is the sharpest contradiction in the manuscript: Table 3 presents post-route (i.e. post-*bitstream*) numbers for a kernel that, per every log and file in the archive, was never taken through synthesis at all. Either a Steane build happened on a machine/run not captured in what was delivered, or this table is fabricated from the Table 2 numbers by hand. Author must locate the real Vivado run or the table must be removed. |
| C-035 | Table 2/3, R1-Min-5 | BRAM 2 → 0 discrepancy between Table 2 and Table 3 for Steane | "explain in the text" | qualitative | **cannot be explained, both tables ungrounded** | n/a | **BLOCKED** | The LUTRAM-inference explanation offered informally is plausible engineering folklore but cannot be verified because neither underlying report exists. Requires an actual Steane build before this cell means anything. |
| C-036 | Abstract; Conclusions L557 | Total footprint under 0.02% of U55C fabric | <0.02% | derived | derived from C-030/031/032 | from Table 1 device totals (real, VENDOR-SPEC, see C-090) ÷ Table 2 (mostly ungrounded) | **NEEDS-RECOMPUTE** | Numerically the *conclusion* ("negligible") will almost certainly survive once real numbers exist, since even 10x the claimed LUT count is still <1% of the device. But the specific "<0.02%" figure must be recomputed from real data, not asserted. |

## E. Scalability table (Table 5 / tab:lut-scaling)

Manuscript definition check (R1-Maj-6): the text never states $m = n-k$ explicitly; it should,
once, at the top of the table caption, and every row below must be recomputed against it.

**FIXED, 2026-08-19:** `paper/tables/gen_table5.py` regenerates this table from
`paper/tables/table5_scalability_data.yaml` with $m=n-k$ applied to every row, the Steane
$m_X\mid m_Z$ decomposition explicit, and the surface-code rows split into labelled rotated/
unrotated variants. Output committed at `paper/tables/table5_lut_scaling.tex`. This is pure
arithmetic on (n, k); it needed no hardware and no author decision to fix. See
`paper/tables/README.md` for the cross-check against Table 2's Shor BRAM count. The individual
row verdicts below are retained as the audit trail for that fix.

| ID | Location | Claim | Value as printed | Correct value ($m=n-k$) | Verdict | Note |
|---|---|---|---|---|---|---|
| C-040 | Table 5 row 1 | Rep-3 [[3,1,2]] syndrome width | m=2 | 2 | SUPPORTED | $n-k = 3-1 = 2$. Correct as printed. |
| C-041 | Table 5 row 2 | Steane [[7,1,3]] syndrome width | m=3 | **6** | **CONTRADICTED** | $n-k = 7-1 = 6$. The printed 3 is one CSS half-syndrome ($H_X$ or $H_Z$ alone, each 3 bits). If the decoder genuinely runs two independent 3-bit LUTs, the table needs an explicit `m_X | m_Z = 3 | 3` column and the text at L179-184 must say so (R1-Maj-6). |
| C-042 | Table 5 row 3 | Shor [[9,1,3]] syndrome width | m=8 | 8 | SUPPORTED | $n-k = 9-1 = 8$. Correct, and matches the 8-bit syndrome described in Sec 4 (L123, L164). |
| C-043 | Table 5 row 4 | Surface d=3 syndrome width | m=8 | 8 (rotated) or 16 (unrotated) | **NEEDS-CLARIFY** | Consistent only with the *rotated* surface code. Text never states which layout is meant; must state it once. |
| C-044 | Table 5 row 5 | Surface d=5 syndrome width | m=24 | 24 (rotated, $n=25,k=1\Rightarrow n-k=24$) | SUPPORTED (as a projection) | Internally consistent with the rotated-code convention implied by row 4; still purely a projection, no d=5 artifact exists (see Phase 4). |
| C-045 | Table 5 row 6 | BB[72,12,6] syndrome width | m=72 | **60** | **CONTRADICTED** | $n-k = 72-12 = 60$. The printed value equals $n$, not $n-k$; this inflates the LUT-entry column ($2^{72}$ vs the correct $2^{60}$, both still "infeasible" so the *qualitative* conclusion is unaffected, but the number is simply wrong). |
| C-046 | Table 5 row 5, LUT entries | Surface d=5 LUT entries | 16,777,216 ($=2^{24}$) | consistent with C-044 | SUPPORTED (arithmetic) | Correct given m=24. |
| C-047 | Table 5 row 6, LUT entries | BB[72,12,6] LUT entries | $2^{72}$ | should be $2^{60}$ per C-045 | **CONTRADICTED** | Follows from C-045; recompute. |
| C-048 | Sec 10.3 (L516) | BB[72,12,6] BP decoder resource estimate | ≈40 BRAM18K, ≈200 DSP48 | PROJECTED (`QEC_FPGA_GUIDE.md` L343-353, "rough budget... estimate") | SUPPORTED as a labelled projection | Must never appear as a measured or synthesised number; the source document itself calls it a rough budget. |
| C-049 | Sec 10.3 discussion | "beyond $m\approx16$ the LUT becomes impractical" | qualitative threshold | ANALYTIC (arithmetic: $2^{16}=65{,}536$ entries $\times$ correction width, vs. 4,032 BRAM18K on the device) | SUPPORTED | The qualitative scaling-ceiling claim is sound math and does not depend on the disputed m values above; it is the paper's genuinely defensible scalability finding once the specific table cells are fixed. |

## F. Logical error rates and Monte Carlo methodology

| ID | Location | Claim | Value | Class | Evidence | Verdict | Note |
|---|---|---|---|---|---|---|---|
| C-100 | Sec 7.3 (L357), Monte Carlo protocol | Shots per point | 200,000 | MEASURED-SW | none matching | **UNSUPPORTED** | No 200k-shot log or data file anywhere in either archive. |
| C-101 | Sec 7.3 (L357) | Physical error-rate grid | 9 points, $\{10^{-3},5\times10^{-3},10^{-2},2\times10^{-2},5\times10^{-2},0.10,0.15,0.18,0.20\}$ | MEASURED-SW | actual log has 4 points: `selftest.log` L37-40, only $p\in\{0.001,0.005,0.01,0.05\}$ | **CONTRADICTED** | The only Monte Carlo run in the archive covers 4 of the 9 claimed grid points, at 10,000 shots each, under `single_pauli` only — never `IID-depolarising`, which is what Table/Fig 3's headline numbers (below) claim to use. |
| C-102 | Fig 3 caption (L470); Sec 7.3 | Monte Carlo shots per point (second, conflicting instance) | 200,000 | MEASURED-SW | see C-100/C-004, no independent log | **CONTRADICTED**, duplicate of C-005/C-100 | R1-Min-4: abstract says $10^5$, here says 200,000, log says 10,000. Three different numbers for one experiment; pick the sourced one (10,000) or rerun at a stated, logged value and use it everywhere. |
| C-103 | Fig 3 caption, Rep-3 panel | $p_L = 3p^2-2p^3$ overlay, and $p_L\approx2.7\times10^{-2}$ at $p=0.10$ | analytic + one data point | ANALYTIC + MEASURED-SW, only the ANALYTIC part verified | arithmetic: $3(0.1)^2-2(0.1)^3=0.028$ | analytic part SUPPORTED; data point **UNSUPPORTED** | The closed-form curve is correct arithmetic (0.028 ≈ "approximately $2.7\times10^{-2}$"). The underlying simulated data point has no logged run behind it (rep3 was never exercised in selftest.log). |
| C-104 | Fig 3 caption, Shor panel | Single-Pauli logical error rate | 0 (at shot-noise floor) | MEASURED-SW, consistent with self-test not an MC sweep | `selftest.log` shows 27/27 single-Pauli PASS, not a Monte Carlo run | plausible but **UNSUPPORTED as an MC claim** | Self-test at $p=1$ (always inject) passing is not the same experiment as a $p$-swept Monte Carlo curve. |
| C-105 | Fig 3 caption, Shor panel | IID-depolarising logical rate | ≈$1.5\times10^{-2}$ at $p=0.10$ | MEASURED-SW | none found | **UNSUPPORTED** | No IID-depolarising run of any kind is present in the archive; `noise.py` implements the model but no output log uses it. |
| C-106 | Sec 7.6 (L477); Conclusions L557 | Shor below-threshold up to $p=0.08$ | threshold value | MEASURED-SW | none found | **UNSUPPORTED** | Log shows only $p\in\{0.001,...,0.05\}$ tested; 0.08 was never a tested point. |
| C-107 | Conclusions L557 | Steane below-threshold up to $p=0.10$ | threshold value | MEASURED-SW | none found | **UNSUPPORTED** | No Steane MC run exists at all. |
| C-108 | Fig 3 caption, Steane panel; Abstract | LUT/MWPM/UF curves "statistically identical" for $p\le0.10$ | qualitative | claimed statistical, no test performed | none | **UNSUPPORTED** | No paired bootstrap, no two-proportion z-test, no p-values, and (per C-107) no underlying data at all. Either run the test (E07) and report p-values, or delete the statistical claim (R1-Min-4/R2-3). |
| C-109 | Sec 11 (L544) | Logical error rate floor at 200k shots | ≈$2.5\times10^{-6}$ | ANALYTIC | arithmetic: $0.5/200{,}000 = 2.5\times10^{-6}$ | SUPPORTED as arithmetic, contingent | Correct formula for a shot-noise floor; only meaningful once C-100 (200,000 shots) is actually run. |
| C-110 | Sec 11 (L544) | 10^7 shots feasible on FPGA in ~33 ms | derived | ANALYTIC, derived from C-020 (arithmetic ceiling, not measured) | arithmetic: $10^7 / 3\times10^8 \approx 33$ ms | SUPPORTED as arithmetic on an unmeasured rate | Correct math on the II=1 ceiling; will need restating once a *measured* batched rate (E03) exists, since the real number will be slower than the II=1 ceiling. |

## G. Architecture and priority claims

| ID | Location | Claim | Class | Verdict | Note |
|---|---|---|---|---|---|
| C-060 | Sec 1.2 contribution 1 (L75) | "The first complete Vitis HLS implementations of the Shor and Steane QEC decoders targeting the Alveo U55C" | priority | **NEEDS-SEARCH, likely DELETE** | Unsubstantiated priority claim; no search performed for this ledger. Drop unless a literature search turns up nothing, in which case reframe around reproducibility instead of "first." |
| C-061 | Sec 1.2 contribution 3 (L77); Sec 6.3 (L285-308); Sec 1 item 3 (L62) | Three runtime-selectable Steane decoder modes (LUT/MWPM/UF) in one kernel, selected by a 2-bit AXI-Lite mode field | implementation | **ARTIFACT MISSING** | No `steane_qec_kernel.cpp` exists anywhere in either archive. The only Steane kernel present, `steane_decoder_kernel.cpp` (50 lines), implements a single LUT-only batched decoder with no mode field, no MWPM, no UF (verified by reading the full 50-line file: it has exactly one `local_lut[64]` lookup path). |
| C-062 | Sec 6.3, Sec 9.1 (L500-508) | MWPM and UF modes described as decoder architectures | implementation | REFRAME (R1-Maj-4) | Text at L500-508 already half-admits these collapse to the Hamming bijection; move that admission to first mention (Sec 3.3, L179-184) and state plainly these are small-code specialised decision circuits, not general graph decoders. Moot for hardware claims until C-061 is resolved. |
| C-063 | Sec 1 (L65); Sec 5.3 (L231-237); Abstract | "All three kernels operate exclusively over the AXI-Lite control bus, no HBM required" | architecture | **CONTRADICTED** | `steane_decoder_kernel.cpp` L6-16 declares three `m_axi` gmem-bundle pointer arguments (`syndromes`, `decoder_lut`, `instructions`) plus `s_axilite` only for scalar control — this is an HBM/DDR streaming kernel, not AXI-Lite-only. `host_decoder.cpp` L317-331 opens three `cl::Buffer` objects (OpenCL device buffers), which only exist for `m_axi` kernels. Confirmed by direct source read, not inference. |
| C-064 | Sec 11 (L546) | "The current driver executes one shot per kernel invocation" (batching not implemented) | status | **CONTRADICTED** | `steane_decoder_kernel.cpp` already batches 64 syndromes per 512-bit AXI beat with an outer `num_chunks` loop, and `host_decoder.cpp` already has `std::chrono::steady_clock` timing wired around a multi-chunk OpenCL dispatch (L342, L382-383). The batched path exists in prototype form; Section 11 describes it as future work. Reconcile: either finish and use this kernel for E03, or explain why it was abandoned. |
| C-065 | Sec 5.2 (L223-229) | Monolithic architecture chosen because HBM round trip (~100 ns/hop) would "inflate decode latency by a factor of ten" | architectural argument | SUPPORTED as reasoning, contingent on C-010 | The argument is internally consistent (100 ns vs. an unverified 17 ns baseline) but its numerical force depends on C-010 being real. |
| C-066 | Sec 5.3 (L237) | "Both kernels met timing at 300 MHz in the same Vivado implementation run" | qualitative | **CONTRADICTED** | Cannot be true: there is no Vivado implementation run for the Steane kernel anywhere in the archive (see D section). At most one kernel (Shor) has any implementation evidence. |

## H. Bibliography audit (19 entries, `main.tex` L579-638)

| ID | Entry (bibkey) | Problem | Verdict | Note |
|---|---|---|---|---|
| C-070 | `fowler2012surface` (ref [4], L590-591) | Author list garbled: "A. G. Fowler, M. Martinis, A. Fowler, and J. M. Martinis" | **FIX** (R3-4) | Well-established real paper: Fowler, Mariantoni, Martinis, Cleland, "Surface codes: Towards practical large-scale quantum computation," Phys. Rev. A 86, 032324 (2012). Current entry duplicates "Martinis"/"Fowler" as if there were two of each and drops Mariantoni and Cleland entirely. |
| C-071 | `battistel2023real` (L617-618) | Bibliography entry vs. in-text citation mismatch | **FIX (in-text citation, not the entry)** | Verified via web search 2026-08-19: the entry (Battistel, Varbanov, Terhal, "Hardware-efficient leakage-reduction scheme for quantum error correction with superconducting transmon qubits," PRX Quantum 2, 030314, 2021) is an **accurate** citation of a real paper. The defect is that L92 cites it as having "revisited" real-time decoding latency requirements — that paper is about leakage reduction, not decoding latency. Fix the sentence at L92, not the bibliography entry. Also: entry gives author as "B. Battistel"; the real first author's initial is F. (Francesco Battistel) — minor initial fix needed. |
| C-072 | `ristE2024scalable` (L620-621) vs. `liyanage2023scalable` (L605-606) | Two bibliography entries carry the **identical title** "Scalable quantum error correction for surface codes using FPGA" with different authors, venues, and years | **FIX, both entries wrong** | Verified via web search 2026-08-19: the real paper with this exact title is Liyanage, Wu, Deters, Zhong, IEEE QCE 2023, pp. 916-927 (**not** "Proc. 29th IEEE HPCA" as `liyanage2023scalable` states, and **not** including a fifth author "A. Javadi-Abhari" as the entry states). `ristE2024scalable`, attributed to Riste, Egger, Ganzhorn, Fuhrer, Müller, Filipp, Eichler, npj Quantum Information 8, 39 (2022), appears to be a distinct, real Riste-et-al. publication that has been given the wrong title (copy-pasted from the Liyanage entry). Both entries need correction: fix `liyanage2023scalable`'s venue and author list, and find `ristE2024scalable`'s actual title. |
| C-073 | All 19 entries | No DOIs anywhere in the bibliography | **AUDIT/FIX** | Confirmed by direct read of L579-638: zero `doi` fields. Add throughout per R1/R2 general manuscript-quality concerns. |
| C-074 | `shor1995scheme` (L581-582) | Shor, Phys. Rev. A 52, R2493 (1995) | SUPPORTED | Matches well-known publication record; not independently re-verified via web this pass but internally consistent and uncontested by any reviewer. |
| C-075 | `steane1996error` (L584-585) | Steane, Phys. Rev. Lett. 77, 793 (1996) | SUPPORTED | Same basis as C-074. |
| C-076 | `das2022afs` (L599-600) | Das et al., "AFS," Proc. 28th IEEE HPCA, 2022, pp. 692-705 | SUPPORTED | Matches well-known publication record; not independently re-verified via web this pass. |
| C-077 | `holmes2020nisq+` (L602-603) | Holmes, Johri, Guerreschi, Clarke, Matsuura, "NISQ+," Proc. 47th ISCA, 2020, pp. 556-569 | SUPPORTED | Matches well-known publication record; not independently re-verified via web this pass. |
| C-078 | Remaining 10 entries (`gottesman1997stabilizer`, `terhal2015qec`, `preskill2018quantum`, `riesebos2017pauli`, `almudever2017engineering`, `ryan2021realization`, `mahmud2020scaling`, `aaronson2004improved`, `qiskit2024`, `xilinx2023vitis`, `xilinx2023xrt`) | Not checked against the public record in this pass | **NEEDS-VERIFY-EXTERNAL** | No internal red flags found by inspection (no title collisions, no obviously wrong venue), but "no red flag on inspection" is not the same as "verified." Full DOI-level pass required before resubmission per the brief's explicit instruction to check all 19. |

## I. Platform specification (Table 1, tab:alveo)

| ID | Location | Claim | Value | Class | Verdict | Note |
|---|---|---|---|---|---|---|
| C-090 | Table 1 (L201-221) | XCVU55C device specs: 1,730k logic cells, 1,303,680 LUT6, 2,607,360 FF, 9,024 DSP, 4,032 BRAM18K, 960 URAM, 16 GB HBM2 / ~460 GB/s, PCIe Gen3×16 | as listed | VENDOR-SPEC | **NEEDS-CITATION** | These are Xilinx datasheet figures (DS962/product selection guide), plausible and internally consistent with the utilisation percentages computed elsewhere in the paper (e.g. Table 3's "User Budget" column matches Table 1's LUT/DSP/BRAM/URAM figures exactly, which is a good consistency check), but the manuscript cites no datasheet reference for Table 1 itself. Add a citation to the U55C product brief. |
| C-091 | Table 1 | "Kernel clock (AXI-Lite) 300 MHz (this work)" | 300 MHz | design choice, not vendor spec | SUPPORTED | Corroborated by `shor_qec_kernel.xclbin.info` (`ulp_ucs_aclk_kernel_00`, Achieved Freq 300 MHz) and `shor_link.cfg` (`freqHz=300000000`), for the Shor kernel only. |

## J. Host-interface and self-test-oracle claims

| ID | Location | Claim | Class | Verdict | Note |
|---|---|---|---|---|---|
| C-120 | Sec 6.1 (L317-323) | Three-path (X/B/S) return-value detection sequence in the Python host driver | implementation description | SUPPORTED | Matches the actual behaviour logged in `selftest.log` (path A attempted, path B/BAR4 attempted, path C/software fallback used) modulo naming: the manuscript calls the paths "X / B / S," the log calls them "A / B / C." Cosmetic naming mismatch to fix, not a substantive one. |
| C-121 | Sec 6.1 (L323) | "In the experimental runs reported below, Path X was confirmed on the Alveo U55C... with the ctypes extraction succeeding" | MEASURED-HW | **CONTRADICTED** | Directly contradicted by the only log in the archive: `selftest.log` L9 shows path A/X *failing* (`vector::_M_range_check`), not succeeding, and line 24 confirms the software path was active. This sentence describes a run that is not the one in evidence. |
| C-122 | Sec 3.4 (L335) | "All 27 Shor tests and all $21\times3=63$ Steane mode-tests pass" | MEASURED | **CONTRADICTED / UNSUPPORTED** | Shor: contradicted (ran in software, C-001). Steane: unsupported, no log exists (C-002). |

## K. Newly discovered facts not derivable from the manuscript text alone

| ID | Finding | Evidence | Relevance |
|---|---|---|---|
| C-130 | This working host (`/home/cdac/Documents/qec_fpga`, not the machine that produced `selftest.log`) has a live, XRT-visible Alveo U55C at PCIe BDF `0000:8c:00.1`, shell `xilinx_u55c_gen3x16_xdma_base_3`, device status "Ready." | `xbutil examine` output, captured 2026-08-19 | Directly changes B-001's severity; see `docs/BLOCKERS.md`. |
| C-131 | The current OS user (`cdac`) is already a member of the `render` group on this host. | `id` / `getent group render` | The specific permission fix `selftest.log` recommends (`usermod -aG render`) already applies here; it was a per-host problem on the original capture machine, not a structural one. |
| C-132 | XRT installed here is version 2.15.225 (2023.1), branch 2023.1. The manuscript (L342) and `selftest.log` both reference XRT 2.16.204 (2023.2). | `xbutil examine` header | Version mismatch between this host and the one described in the manuscript; the delivered `shor_qec_kernel.xclbin` was built against the `xilinx_u55c_gen3x16_xdma_3_202210_1` platform (`xclbin.info`), while this host's live shell is `xilinx_u55c_gen3x16_xdma_base_3` — compatibility must be checked before attempting to load it, not assumed. |
| C-133 | Vitis 2023.2 and the exact platform `xilinx_u55c_gen3x16_xdma_3_202210_1` used to build the original xclbin are both installed locally (`/opt/xilinx/platforms/`, `/tools/Xilinx/Vitis/2023.2`). | filesystem inspection | B-002 (tool availability) is largely already satisfied on this host; only wall-clock build time and a rebuild decision remain open. |

## L. Reconstruction work (Phase 2/3, in progress — see docs/BLOCKERS.md B-003, B-005)

These rows are software-only findings from building and self-testing a reconstruction of the
missing Steane three-mode kernel. They are new defects/findings discovered during this campaign,
not present in the original manuscript's claim set, and are logged here so they survive into the
manuscript rewrite and are not silently fixed and forgotten.

| ID | Finding | Evidence | Verdict | Note |
|---|---|---|---|---|
| C-140 | main.tex L183's literal description of the UF decoder ("qubit q counts how many of its adjacent check nodes are active; if the count is odd, qubit q is included") does not correctly decode single-qubit Pauli errors on the Steane Tanner graph. | `models/tests/test_steane_mirror.py`, first run: 9/63 self-test failures, all in UF mode, all with the same signature (4 of 7 qubits spuriously flagged for a weight-1 input) | **CONTRADICTED (manuscript text is internally wrong)** | Resolved using main.tex L308's own follow-up sentence ("collapses to the same XOR-reduce for one growth round"), implemented as column-vs-syndrome equality. Fixed version passes 63/63. The manuscript prose at L183 needs correction regardless of whose kernel eventually ships — this is not an artifact-missing problem, it is a description-is-wrong problem. |
| C-141 | For every pair of Steane data qubits (i,j), `H_COL[i] XOR H_COL[j]` equals some third column `H_COL[k]` exactly (a property of this specific [7,4,3] Hamming code). Consequence: every weight-2 X-only error is syndrome-indistinguishable from a weight-1 error on qubit k, and LUT, MWPM, and UF all alias to the same (wrong) single-qubit correction for it. | `models/tests/test_steane_mirror.py::run_weight2_census`: 21/21 qubit pairs give identical correction across all three modes | **CONTRADICTS main.tex L479, L506** | Those lines claim the three decoders "differ" in how they handle weight-2 syndromes. On this reconstruction's evidence they do not differ, they agree — on an incorrect correction. This is a defensible, testable claim to carry into the rewrite (Sec 9.1/10.1), but should be re-confirmed against a from-source kernel or HLS co-simulation before it's asserted as a hardware fact, and Y/Z weight-2 cases haven't been checked yet either. |
| C-142 | `rtl/shor913/src/shor_qec_kernel.cpp` modified to add a one-element `m_axi` output-buffer argument (`result_out`), implementing the manuscript's own Section 11 fix for the BAR4/ap_return readback failure (C-008, C-009). `rtl/steane713/src/steane_qec_kernel.cpp` written from scratch (B-003) with the same output-buffer convention, implementing the LUT/MWPM/UF architecture main.tex Sections 6.3/9.1 describe. | `rtl/shor913/src/shor_qec_kernel.cpp`, `rtl/steane713/src/steane_qec_kernel.cpp` | **NOT YET SYNTHESISED OR HARDWARE-TESTED** | Logic-level only: verified against `models/mirrors/steane_mirror.py` (C-140/C-141) for Steane; the Shor decode logic is unchanged from the original so should reproduce the original 27/27 truth table, but this has not been re-run through HLS C-simulation. No `*_csynth.rpt`, no `.xo`, no `.xclbin` exists for either revised kernel yet. Do not cite these as hardware or even HLS-estimate results until a real build exists. |

---

## Verdict tally (89 rows, A-L)

- `CONTRADICTED`: 19
- `UNSUPPORTED`: 22
- `NEEDS-RERUN` / `NEEDS-VERIFY` / `NEEDS-VERIFY-EXTERNAL` / `NEEDS-CITATION` / `NEEDS-CLARIFY` / `NEEDS-RECOMPUTE` / `NEEDS-SEARCH`: 21
- `SUPPORTED` (as arithmetic, as a labelled projection, or independently corroborated): 17
- `DELETE`: 2
- `BLOCKED`: 1
- `NOT YET SYNTHESISED OR HARDWARE-TESTED` (Phase 2/3 reconstruction work, section L): 1
- ground truth / ADR / not-a-manuscript-claim rows: 6

Roughly three in four rows do not currently support the manuscript claim they were extracted
from. The failure mode is not "wrong numbers" so much as "numbers whose only real backing is a
single Shor-kernel run against the software decoder" being used to support claims about three
kernels, two of which (Steane, Rep-3) were never synthesised at all as far as this archive shows.

Section L is new work product from this campaign, not from the original archive: a reconstructed
Steane kernel (docs/BLOCKERS.md B-003) whose logic has been software-verified against a Python
mirror and which surfaced two genuine defects in the manuscript's own prose (C-140, C-141) along
the way. Neither reconstructed kernel has been synthesised or run on hardware yet.
