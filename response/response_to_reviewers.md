# Response to Reviewers

Manuscript: *From Kernel Latency to Loop Latency: What an FPGA Distance-3 Quantum Error
Correction Decoder Actually Costs on a Commodity Accelerator Card* (provisional title, ADR-001,
awaiting final author sign-off)

Original submission: e7d19f63-0e69-4714-a61d-f53b2885839f, *The Journal of Supercomputing*

Status: draft, built from `docs/CLAIMS_LEDGER.md` (roughly 95 rows, most checked against a real
artifact rather than by inspection). Every claim below is sourced to a ledger row or a file in
this repository. Where work is genuinely unfinished, this letter says so rather than describing
it as done.

---

## Opening statement

The original submission presented software-decoder results and HLS synthesis estimates as
hardware-measured evidence of a real-time system; they were not, and we accept every reviewer's
finding on this point without qualification. Since submission, we rebuilt all three decoder
kernels with a working hardware read-back path and exhaustively verified them (Shor: 19,683 of
19,683 single-qubit-per-position patterns; Steane: 6,561 of 6,561 pattern/mode combinations;
Rep-3: the complete 16-combination input space) on a live Alveo U55C, with results read back
through a genuine AXI buffer object rather than the software fallback the original submission
silently used. The manuscript is reframed accordingly: it no longer claims real-time closed-loop
QEC, and instead reports a measured decoder-kernel cost, a first (still partial) look at what the
host interface actually costs on top of that, and a corrected scalability analysis, which we
believe is the honest and useful version of this contribution.

---

## Priority Zero: the software/hardware path finding

**Concern (self-identified, and partially caught by Reviewer 2).** The submitted `selftest.log`
shows the decode path used for every reported result was the software mirror, not the FPGA: line
24 reads `active decode path: sw`, and the file itself states the xclbin was loaded but never
exercised for the return value. The manuscript's 27/27 self-test, throughput figure, and Monte
Carlo shot counts were built on this log without disclosing this. Reviewer 2 partially detected
the consequence directly: "No hardware-measured wall-clock latency is reported; the 17-20ns
figures are HLS synthesis estimates only."

**Our response.** We treated this as the overriding priority, ahead of responding to individual
review points, per our own internal working rules (`CLAUDE_CODE_PROMPT.md` \S0.1-0.2). The root
cause turned out to be architectural, not a permissions problem: on the XRT build available to
us, the C API the original host driver's register-read path depends on
(`xrtRunGetReturnValue`/`xrtRunReadRegister`) is not exported by the shared library at all,
independent of privileges (ledger C-150). The manuscript's own Section 11 already identified the
correct fix (an AXI-master output-buffer argument, avoiding this code path entirely); we
implemented it, and it works. All three kernels were rebuilt with this fix, synthesised, placed,
routed, and tested against a live device:

- Shor: 27/27 self-test, then all $3^9=19{,}683$ single-qubit-per-position patterns, hardware
  result read back via a real `xrt::bo`, cross-checked bit-for-bit against an independent software
  mirror. 19,683/19,683 agree, zero mismatches.
- Steane (reconstructed kernel, see R1-Major-4 and the appendix): 63/63 self-test (21 cases x 3
  modes), then all $3^7=2{,}187$ patterns x 3 modes = 6,561 combinations. 6,561/6,561 agree, zero
  mismatches. First hardware test any Steane decoder logic in this line of work has ever had.
- Rep-3: the complete 16-combination input space (2 codewords x 8 error masks). 16/16 agree, zero
  mismatches.

**What is still not resolved.** Hardware-measured *latency* is not yet at the same standard as
hardware-measured *correctness*. We have one opportunistic, explicitly-labelled-as-crude Python
round-trip measurement (N=10,000 shots, p50 = 49.5 $\mu$s, p99 = 61.0 $\mu$s), not the rigorous
E02 measurement this campaign's own brief specifies (a C++ host with `clock_gettime`, $\ge 10^6$
shots, full percentile/tail reporting, and a latency-budget decomposition into host software,
PCIe, AXI-Lite register access, and kernel compute). This is the single largest remaining gap
before the manuscript's real-time-adjacent claims can be considered fully closed, and it is
stated plainly in \S\ref{sec:limitations} rather than left implicit.

**Changes made.** `rtl/{shor913,steane713,rep3}/src/*.cpp` (AXI-master output-buffer fix, all
three kernels); `paper/sections/results.tex` \S\ref{subsec:res-hardware} (exhaustive hardware
verification, reported with exact counts); `paper/sections/limitations.tex` (the still-crude E02
measurement stated as a gap, not a result).

**Evidence.** `docs/CLAIMS_LEDGER.md` C-001, C-149, C-150, C-153, C-154, C-155, C-156, C-159;
`evidence/runs/2026-08-20_HARDWARE_VERIFIED_m_axi_fix/`.

---

## Reviewer 1

### R1-Major-1: Real-time QEC claim overstated

**Reviewer's concern.** "Real-time QEC" denotes a closed control loop, syndrome extraction,
transfer, decode, Pauli-frame update, feedback, and repetition; the submitted artifact is a
host-driven decoder kernel with no feedback path, and the title and framing did not make that
distinction.

**Our response.** We agree without qualification and no longer claim real-time closed-loop QEC
anywhere in the manuscript. We did not build a feedback loop to a real or simulated quantum
processor, and we say so. Where we do have multi-round data (the repetition code, circuit-level
noise generated with Stim and decoded with PyMatching, not our own kernel), we state plainly that
it characterises the code's behaviour under repeated rounds and measurement error, not this
kernel's operation inside a real-time loop.

**Changes made.** Title reframed around measured kernel and interface cost rather than achieved
real-time operation (provisional, ADR-001, four candidate titles recorded, final choice pending
the author). Every instance of "real-time" audited; the closed-loop claim removed from the
abstract, introduction, and conclusions.
\S\ref{subsec:disc-thesis} ("The decoder is free; the interface is the problem") states the
paper's actual thesis explicitly. \S\ref{sec:limitations} lists closed-loop feedback as
unimplemented.

**Evidence.** `docs/DECISIONS.md` ADR-001; `paper/sections/introduction.tex`
\S\ref{subsec:scope}; `paper/sections/discussion.tex` \S\ref{subsec:disc-thesis};
`experiments/E05b_repetition_circuit_level/` (ledger C-148).

### R1-Major-2: Contribution reads as engineering effort, limited architectural insight

**Reviewer's concern.** The paper lacked a clear thesis distinguishing it from a routine HLS
implementation exercise.

**Our response.** Agreed. The genuinely interesting finding, that the decoder logic itself costs
almost nothing (single-digit nanoseconds, under 0.1% of the fabric) while the host interface costs
orders of magnitude more, was present but buried as a limitation in the original Section 11. We
promoted it to the paper's central thesis and backed it with a quantified comparison rather than
an assertion: the same kernel synthesised as AXI-Lite-only versus with the AXI-master
output-buffer fix costs 35 to 70x more pipeline depth for a working read-back path (an HLS-estimate
comparison; see R1-Major-3/R2-2 for the hardware-measured side, which is still partial).

**Changes made.** Contributions list rewritten (\S\ref{subsec:contributions}) around this finding
rather than an unsubstantiated priority claim (see R3-4/C-060, "first complete Vitis HLS
implementation," removed). New \S\ref{subsec:disc-thesis}.

**Evidence.** Ledger C-142-HLS, C-154; `paper/sections/discussion.tex`;
`paper/sections/introduction.tex` \S\ref{subsec:contributions}.

### R1-Major-3: Throughput comparison is misleading

**Reviewer's concern.** The $3\times10^8$/s per-CU and $6\times10^9$/s at 20 CUs figures were
presented as if achieved, and the comparison point (a single-threaded Python decoder) is not a
fair software baseline.

**Our response.** Agreed on both counts. The 20-CU/$6\times10^9$ figure was a resource-utilisation
extrapolation from a single, un-built configuration; we deleted it rather than replace it with
another unmeasured number, since no multi-CU build or measurement exists (E04 not yet run). We
have not yet replaced the weak single-threaded Python baseline with a fair compiled-C or
PyMatching comparison either; this remains open and is stated as such rather than left implicit.
What is complete: a literature comparison table situating this kernel's current (mostly
HLS-estimate) numbers honestly against real, hardware-measured decoder latencies from Riverlane
(both an FPGA and an ASIC design), Liyanage et al., Ryan-Anderson et al., and Google, none of
which this paper currently matches on closed-loop or fully measured end-to-end terms.

**Changes made.** The 20-CU/$6\times10^9$ figure removed from the abstract, throughput discussion,
and conclusions. Literature comparison table added. The $3\times10^8$/s II=1 rate is now labelled
explicitly as a kernel-level steady-state ceiling, never as achieved system throughput. Fair
CPU/GPU baselines and measured E03/E04 throughput remain open, stated in \S\ref{sec:limitations}.

**Evidence.** Ledger C-020, C-021, C-022, C-147; `response/literature_comparison.md`;
`paper/sections/limitations.tex`.

### R1-Major-4: MWPM and UF modes are not general decoders

**Reviewer's concern.** MWPM and union-find are presented alongside a LUT decoder as though they
were general decoding algorithms, when at this code and distance they may not meaningfully differ
from a lookup.

**Our response.** Correct, and reconstructing the missing Steane kernel (see the appendix) surfaced
the specific reason: for every pair of Steane data qubits, the XOR of their parity-check columns
equals a third column exactly, a property of this particular [7,4,3] Hamming code. Every weight-2
X-only error therefore aliases to the same syndrome as some weight-1 error, and LUT, MWPM, and UF
converge on the identical correction for it, not merely a similar one, as the original manuscript's
"the decoders differ in how they handle weight-2 syndromes" implied. We now state, at first
mention, that these are small-code decision circuits specialised to this code's Hamming structure,
not general graph decoders, and removed language implying scalable MWPM/UF support.

**Changes made.** \S\ref{subsec:disc-decoders} ("Why the three Steane decoder modes agree") states
the Hamming-aliasing finding explicitly, backed by an exhaustive weight-2 census. Scalability
language removed from \S\ref{sec:codes} and \S\ref{sec:discussion}.

**Evidence.** Ledger C-140, C-141 (`models/tests/test_steane_mirror.py::run_weight2_census`,
21 of 21 qubit pairs alias); `paper/sections/discussion.tex` \S\ref{subsec:disc-decoders}.

### R1-Major-5: Correctness verification necessary but insufficient

**Reviewer's concern.** A 27+21-case self-test does not constitute a "rigorous correctness proof"
(the original manuscript's own phrase) and does not cover measurement error or repeated rounds.

**Our response.** Agreed on the wording; "proof" is deleted and not replaced with an equivalent
overclaim (verification, not proof, over a stated input space). On coverage, we went substantially
beyond the original 48-case self-test: every single-qubit-per-position pattern for all three
codes, now run against real hardware and cross-checked bit-for-bit against an independently
written software mirror, with zero mismatches anywhere (see Priority Zero, above, for exact
counts). This still does not cover weight-$\ge$2 errors (a separate regime the code cannot
uniquely correct by construction, already characterised in the Monte Carlo data) or
measurement/syndrome-fault injection, which remain unperformed and are stated as such.

**Changes made.** "Rigorous correctness proof" deleted throughout.
\S\ref{subsec:res-hardware} reports exhaustive hardware verification with exact counts.
\S\ref{sec:limitations} states plainly that measurement-error and syndrome-fault-injection sweeps
were not performed.

**Evidence.** Ledger C-007 (delete), C-155, C-156, C-159;
`evidence/runs/2026-08-20_HARDWARE_VERIFIED_m_axi_fix/{exhaustive_shor_hw,exhaustive_steane_hw,exhaustive_rep3_hw}.py`
and logs.

### R1-Major-6: Syndrome-width definition and LUT scalability

**Reviewer's concern.** Table 5's $m$ values are not applied consistently: Steane is shown as
$m=3$ (one CSS half-syndrome, not the full syndrome) and BB$[[72,12,6]]$ is shown as $m=72$
(equal to $n$, not $n-k=60$).

**Our response.** Agreed; both values were simply wrong under a stated $m=n-k$ convention, which
the original manuscript never states explicitly. The table was rebuilt with that definition given
once, in the caption, and applied to every row without exception: Steane corrected to $m=6$ with
an explicit $m_X{=}3\mid m_Z{=}3$ CSS decomposition stated in the text, BB$[[72,12,6]]$ corrected
to $m=60$. The qualitative scalability conclusion (LUT decoding impractical past roughly
$m\approx16$) is unchanged by the correction, since it depends on the arithmetic of $2^m$ against
on-chip BRAM capacity, not on any single disputed row.

**Changes made.** Table~\ref{tab:lut-scaling} regenerated from `paper/tables/gen_table5.py` with
$m=n-k$ applied throughout; surface-code rows split into explicitly labelled rotated ($m=8$) and
unrotated ($m=16$) variants, since the original single row did not state which layout was meant.

**Evidence.** Ledger C-040 through C-049; `paper/tables/table5_lut_scaling.tex`;
`paper/tables/README.md`.

### R1-Minor-1: Title should be narrowed

See R1-Major-1. Provisional title in use pending the author's final choice among four options
recorded in `docs/DECISIONS.md` ADR-001.

### R1-Minor-2: Figure quality

**Reviewer's concern.** Small in-figure text, misaligned labels, dense explanatory text that
belongs in captions rather than the image.

**Our response.** One figure is fully corrected: Figure 3 (Monte Carlo logical error rates). Its
embedded text was measured directly, not judged by eye, at 2.6 to 4.8pt at final print size
(well under the 8pt rule), rebuilt, and reverified at a confirmed minimum of 8.72pt for every
span of text physically inside the figure. A duplicated caveat sentence that was baked into the
image as a title (already present, word for word, as the caption's first sentence) was removed
rather than resized. The remaining six figures (structure, pipeline, resource, syndrome-map,
throughput, and Tanner-graph diagrams) have not yet been redrawn in TikZ or checked against the
same rule; this remains open.

**Changes made.** `figures/src/fig3_error_curves.py` rewritten: figure dimensions, per-element
font sizes (including a specific fix for matplotlib's automatic $\sim$70%-scale shrinking of
mathtext subscripts and log-axis exponents, which left `$p_L$` and `$10^{-n}$` labels under 8pt
even after the main text was corrected), shortened legend text, and removal of the redundant
in-image caveat.

**Evidence.** `figures/out/fig3_error_curves.pdf`; verified directly against the compiled
`paper/main.pdf` (PyMuPDF span-size extraction, filtered to the figure's own bounding box, not
adjacent caption or body text): 0 spans under 8pt, minimum 8.72pt.

### R1-Minor-3: HLS estimate versus post-route results not distinguished

**Reviewer's concern.** The manuscript does not clearly separate HLS synthesis estimates from
post-route (post-implementation) figures.

**Our response.** Agreed, and this campaign's evidence discipline makes the distinction
load-bearing rather than cosmetic: three class tags (HLS-ESTIMATE, POST-ROUTE, MEASURED-HW) are
applied to every relevant claim in the ledger and now in the manuscript's own results tables and
prose. In several cases the two genuinely disagree in ways worth stating outright: all three
kernels show 0 post-route BRAM18K against non-zero HLS estimates, a repeatable pattern (LUTRAM
inference), not a one-off.

**Changes made.** \S\ref{subsec:res-real} (HLS-estimate results) and
\S\ref{subsec:res-hardware} (post-route and hardware-measured results) explicitly separated;
table captions state each column's evidence class.

**Evidence.** Ledger class-tag convention (file header); C-151, C-157, C-160.

### R1-Minor-4: Monte Carlo shot count inconsistent

**Reviewer's concern.** $10^5$ in the abstract, 200,000 in Section 9.6, and the only log in the
archive showing 10,000.

**Our response.** Agreed; none of the three original numbers was defensible (the archive's only
actual run covered 10,000 shots at 4 of the 9 claimed grid points, single-Pauli noise only, never
the IID-depolarising model the headline figures claim to use). We reran the sweep for real, at
$10^7$ shots per point, all 9 grid points, both noise models, for all three codes, and use that
one number everywhere.

**Changes made.** Abstract, \S\ref{subsec:meth-mc}, all figure captions, and conclusions now state
$10^7$ shots/point consistently, sourced to a single run.

**Evidence.** `experiments/E07b_montecarlo_software_mirror/` (raw and processed data, run log);
ledger C-100 through C-102, C-104 through C-108.

### R1-Minor-5: Table 2 versus Table 3 BRAM discrepancy

**Reviewer's concern.** Table 2 (HLS estimate) shows 2 BRAM18K for the Steane kernel; Table 3
(claimed post-route) shows 0, unexplained.

**Our response.** We could not locate any real Vivado implementation run behind the original
Table 3 for any kernel. We generated real post-route reports for all three kernels this time and
found the same pattern in every case: a nonzero HLS-estimated BRAM18K count becomes zero
post-route, because Vivado's implementation flow infers LUTRAM for buffers this small rather than
dedicated BRAM18K primitives. This is not a discrepancy we explain away qualitatively; it is a
now three-times-confirmed, real characteristic of this device's implementation tools, stated
plainly with the report data behind it.

**Changes made.** Table 3 rebuilt entirely from real post-route reports
(\S\ref{subsec:res-hardware}, `paper/tables/gen_table3.py`); text states the LUTRAM-inference
finding with all three kernels as corroborating evidence.

**Evidence.**
`evidence/synthesis/{shor,steane,rep3}_m_axi_fix_postroute_2026-08-20/impl_1_kernel_util_routed.rpt`;
ledger C-151, C-157, C-160.

### R1-Minor-6: Grammar and formatting

**Reviewer's concern.** Awkward line breaks, spacing, and dense captions throughout.

**Our response.** Not yet fully addressed as a dedicated task. Most prose was rewritten from
scratch during the structural split into `paper/sections/*.tex` (background, implementation,
results, discussion, and limitations as separate files rather than one dense document), which
removes much of the original density, but we have not performed a final, dedicated
line-by-line proofreading and typesetting pass. This remains open before submission.

**Changes made.** Structural rewrite only.

**Evidence.** `paper/sections/*.tex`; no dedicated grammar-pass log exists yet.

---

## Reviewer 2

### R2-1: Non-scalable methodology

**Reviewer's concern.** Distance-3, LUT-based decoding does not generalise; the resubmission
condition given was "distance-5+ iterative decoders with genuine hardware measurements and
comparison to existing work."

**Our response.** We have not attempted the distance-5 union-find track (recorded as Phase
4/ADR-004, currently open, awaiting the author's decision). The corrected scalability table
(R1-Major-6) now states precisely where LUT decoding stops working (roughly $m\approx16$) with
the syndrome-width convention fixed, a real, quantified version of the boundary the reviewer is
pointing at, but it remains an analytic ceiling, not a demonstrated d=5 result. We recommend to
the author that Phase 4 be attempted; ADR-004 records a two-to-four-week estimate and the
reasoning. This is a resourcing decision for the author, not something this response can resolve
on its own. The fallback framing, an explicitly-scoped distance-3 measurement and reference-design
paper, is already written into \S\ref{sec:limitations} and `docs/SCOPE.md` in case Phase 4 is not
pursued.

**Changes made.** Table 5 corrected (R1-Major-6); \S\ref{sec:limitations} states $d\ge5$ as
future work with the reason given, not a buried admission.

**Evidence.** `docs/DECISIONS.md` ADR-004; `docs/SCOPE.md`; `paper/tables/table5_lut_scaling.tex`.

### R2-2: Real-time claim unsupported

**Reviewer's concern.** No closed-loop, hardware-measured latency was reported; the 17 to 20ns
figures were HLS synthesis estimates only.

**Our response.** Confirmed correct by our own resynthesis, and worse than the reviewer could have
known from the archive alone: resynthesising the exact, unmodified committed kernel sources shows
the 17ns/20ns figures do not reproduce at all. The unmodified Shor kernel gives 1 cycle (3.33ns),
not 5 cycles (17ns); the unmodified Rep-3 kernel gives 0 cycles, not 3 cycles (10ns); no Steane
kernel existed in the archive to test in the first place. Since submission we obtained this
project's first real hardware-measured correctness results (see Priority Zero and R1-Major-5) and
one opportunistic, explicitly-labelled-as-crude Python round-trip latency measurement against the
live device (N=10,000, p50 49.5$\mu$s, p99 61.0$\mu$s), which is a real number where the original
had none, but is not the rigorous E02 measurement (C++ host, $10^6$ shots, full tail distribution,
latency-budget decomposition) this finding deserves.

**Changes made.** The closed-loop real-time framing is removed (R1-Major-1). The honest headline
finding, that measured host dispatch overhead ($\sim$50$\mu$s) dominates the kernel's own
HLS-estimated combinational latency ($\sim$3ns) by roughly four orders of magnitude, is stated in
\S\ref{subsec:disc-thesis} and \S\ref{sec:limitations} rather than buried. The rigorous E02
measurement has not been run and is named explicitly as the paper's most important remaining gap.

**Evidence.** Ledger C-010, C-012, C-019 (resynthesis contradicts the original latency figures);
C-154 (crude Python probe); C-015 (rigorous E02 not yet run).

### R2-3: Insufficient experimental validation

**Reviewer's concern.** No quantitative comparison with prior FPGA QEC work; weak or absent
baselines.

**Our response.** We built a literature comparison table against Das et al. (AFS), the corrected
Holmes et al. and Liyanage et al. citations (both of which carried wrong author lists or a wrong
technology description in the original bibliography, see R3-4), Ryan-Anderson et al., two
Riverlane decoders (FPGA and ASIC), and Google's 2024 below-threshold result. It shows plainly
that this manuscript's own row is currently the only one in the table without either a real
hardware-measured latency or a closed loop. We have not yet built a fair CPU baseline (compiled C
or PyMatching, rather than single-threaded Python) or obtained GPU access (CUDA-Q/cudaq-qec);
both remain open and are stated as open rather than answered with an unfair or fabricated number.

**Changes made.** Literature comparison table added (to become a manuscript table on
resubmission). Real $10^7$-shot Monte Carlo data with Wilson score intervals now backs every
logical-error-rate claim (R1-Minor-4).

**Evidence.** `response/literature_comparison.md`; ledger C-147; `docs/BLOCKERS.md` B-004 (GPU
access still needed).

### R2-4: Manuscript preparation

**Reviewer's concern.** Figures need redrawing from source; the structure is unbalanced toward
tutorial content; keywords are generic.

**Our response.** Keywords replaced: six specific terms (FPGA syndrome decoding, HLS
resource-latency tradeoff, host-interface latency, distance-3 stabilizer codes, decoder batching
threshold, AXI-Lite readback) in place of the original twelve generic ones. Structure rebalanced
into separate section files, with the stabilizer-formalism tutorial content moved out of the main
narrative into Appendix~\ref{app:formalism}, shifting the paper's weight toward measurement and
results as requested. Figure redrawing is complete only for Figure 3 (R1-Minor-2); the remaining
six figures have not been redrawn in TikZ, and this remains open.

**Changes made.** `\keywords{}` line, `paper/main.tex` line 53. `paper/sections/` split into
twelve files. Stabilizer-formalism content moved to Appendix~\ref{app:formalism}.

**Evidence.** `paper/main.tex` line 53; `paper/sections/` directory listing;
`paper/sections/appendix_reconstruction.tex`.

---

## Reviewer 3

### R3-1: Subsection granularity

**Reviewer's concern.** Many one-paragraph subsections throughout.

**Our response.** The section rewrite substantially increased the depth of most subsections as a
side effect of restructuring around measurement and results rather than tutorial exposition. We
have not performed a dedicated pass specifically counting and merging any remaining short
subsections, and cannot claim this point is fully closed.

**Changes made.** Structural rewrite (see R2-4).

**Evidence.** `paper/sections/*.tex`.

### R3-2: "against the self test oracle" should read "against a self-test oracle"

**Reviewer's concern.** Minor grammar: missing indefinite article and hyphenation.

**Our response.** The original sentence containing this exact phrase does not appear anywhere in
the rewritten manuscript; the surrounding text was rewritten as part of the Section 6
restructuring rather than edited in place, so the specific wording this point flags does not
recur. We have not separately re-audited every other sentence in the manuscript for the same
article/hyphenation pattern.

**Changes made.** Superseded by the section rewrite.

**Evidence.** A search for the original phrase across `paper/sections/` returns no matches.

### R3-3: Awkward $[[n,k,d]]$ sentence

**Reviewer's concern.** "Both the Shor and Steane codes have $[[n,k,d]] = [[9,1,3]]$ and
$[[7,1,3]]$ respectively" reads awkwardly.

**Our response.** Agreed, fixed exactly as suggested.

**Changes made.** Now reads: "The Shor code has parameters $[[9,1,3]]$; the Steane code has
$[[7,1,3]]$."

**Evidence.** `paper/sections/background.tex`, opening paragraph.

### R3-4: Reference [4] author list is wrong

**Reviewer's concern.** The bibliography entry for the Fowler et al. surface-code reference reads
"A. G. Fowler, M. Martinis, A. Fowler, and J. M. Martinis," which duplicates two names and drops
two real authors.

**Our response.** Fixed, and the fix triggered a full audit of the bibliography rather than a
single-entry patch, since a garbled entry this obviously wrong raised the question of what else
had not been checked. Corrected to Fowler, Mariantoni, Martinis, Cleland, Phys. Rev. A 86, 032324
(2012). The audit found and fixed three further real problems: `battistel2023real` cited a real,
correctly-entered paper (Battistel, Varbanov, Terhal, PRX Quantum 2, 030314, 2021) for a claim its
actual content does not support, the paper is about leakage reduction, not real-time decoding
latency (the citing sentence, not the bibliography entry, needed the fix; the entry itself needed
only an author-initial correction). `liyanage2023scalable` and `ristE2024scalable` shared an
identical, apparently fabricated-looking title with different authors, venues, and years;
`liyanage2023scalable`'s venue and author list were corrected (IEEE QCE 2023, pp. 916-927, not
"Proc. 29th IEEE HPCA" with a fifth author who does not appear on the real paper), while
`ristE2024scalable`'s actual intended title could not be determined and is flagged as unresolved
rather than guessed at. `holmes2020nisq+` was found to carry both a wrong author list and a wrong
description of the cited paper's technology (an SFQ superconducting hardware decoder, not an
FPGA union-find implementation as the citing text claimed).

**Changes made.** `paper/bib/references.bib` rebuilt from the manuscript's actual `\bibitem` list
(the file previously held the Springer template's unrelated placeholder examples). Four entries
corrected; one (`ristE2024scalable`) remains explicitly flagged as unresolved, pending the
author's real source, rather than silently left wrong or silently deleted.

**Evidence.** Ledger C-070, C-071, C-072, C-077, C-146; `response/change_log.md`.

---

## What remains open

For transparency, collected in one place rather than left scattered through the point-by-point
responses above:

1. **Rigorous E02 latency measurement** (C++ host, `clock_gettime`, $\ge10^6$ shots, full tail
   distribution, PCIe/AXI-Lite/host-software decomposition). The single most important remaining
   gap; only a crude, opportunistic Python-loop number exists (C-154).
2. **E03 batched throughput** and the batching-threshold crossover point.
3. **E04 measured multi-CU scaling.** The original 20-CU/$6\times10^9$ figure is deleted, not
   replaced, pending this.
4. **Fair CPU baseline** (compiled C, PyMatching) and **GPU baseline** (CUDA-Q/cudaq-qec, blocked
   on access, `docs/BLOCKERS.md` B-004).
5. **Distance-5 union-find track (Phase 4)**, an author go/no-go decision (ADR-004), gating
   which venues are realistic (ADR-002).
6. **Five of six remaining figures** not yet redrawn in TikZ or checked against the 8pt rule
   (only Figure 3 is confirmed compliant).
7. **A dedicated grammar and formatting proofreading pass** (R1-Minor-6, partially superseded by
   the structural rewrite but not independently verified).
8. **`ristE2024scalable`'s real bibliographic identity**, still unresolved.
9. **Title (ADR-001) and venue (ADR-002)**, both awaiting the author's final decision.

None of these gaps were papered over above; each is named in the specific reviewer point it
bears on as well as here.
