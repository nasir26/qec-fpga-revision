# Architectural Decision Records

Format: context, options, decision, consequences. One ADR per decision. Never delete an ADR;
supersede it with a later one.

---

## ADR-001: Manuscript title (OPEN, awaiting author)

**Context.** Three reviewers and the author independently concluded that
"FPGA-Based Real-Time Quantum Error Correction for Shor and Steane Codes" overstates the work.
"Real-time QEC" denotes a closed control loop including syndrome extraction, transfer, decode,
Pauli-frame update, feedback signalling, and repetition. The artifact is a host-driven decoder
kernel with no feedback path.

**Options.**
1. *Sub-Cycle Syndrome Decoding for Distance-3 Stabilizer Codes on the Alveo U55C: an Open, Measured HLS Reference Design*
2. *Hardware Decoder Kernels for the Shor and Steane Codes: Synthesis, Measurement, and the Host-Interface Latency Wall*
3. *From Kernel Latency to Loop Latency: What an FPGA Distance-3 QEC Decoder Actually Costs on a Commodity Accelerator Card*
4. *A Measured Characterisation of FPGA Syndrome Decoders for Distance-3 CSS Codes, and the Batching Threshold for Real-Time Operation*

**Recommendation.** Option 3 if Phase 4 is skipped, option 4 if the batching study is the
centrepiece, option 1 if the paper is submitted as an artifact and reference design.
The commented-out title already in `main.tex` line 37 is closer to honest than the submitted one
and is worth reading before deciding.

**Consequence.** The framing pivot follows the title: the thesis becomes "the decoder is free,
the interface is the problem, and here is where the wall sits", which is a real and useful
engineering result currently buried in Section 11.

---

## ADR-002: Resubmission venue (OPEN, awaiting author)

**Context.** *The Journal of Supercomputing* is a poor fit; this is a control-stack and
reconfigurable-computing contribution, not a supercomputing one.

**Candidates.** IEEE TQE, ACM TRETS, ACM JETC, *Quantum Science and Technology*, FCCM, FPL,
IEEE QCE.

**Dependency.** If Phase 4 (distance-5 union-find with measured hardware) is executed, the
stronger venues open. If not, TRETS or FCCM with a strong artifact is the realistic target.

---

## ADR-003: Timing measurement path (DECIDED)

**Decision.** All publishable latency and throughput numbers come from the C++ host under
`host/cpp/`. Python drivers under `host/python/` are for convenience and for the software
mirror only, and their timings never enter the manuscript except as an explicitly labelled
comparison point in the latency-budget figure.

**Rationale.** Python dispatch overhead is the dominant term in the prior submission's numbers
and conflating it with hardware latency is what produced the central error under review.

---

## ADR-004: Phase 4 (distance-5 union-find track) recommendation (OPEN, awaiting author)

**Context.** Reviewer 2's resubmission condition is explicit: "distance-5+ iterative decoders
with genuine hardware measurements and comparison to existing work would constitute a meaningful
contribution." The brief scopes Phase 4 as optional-but-decisive: a rotated d=5 surface code
(24 stabilizers, 25 data qubits) with a hand-written or HLS union-find decoder, multi-round
decoding with measurement errors, and PyMatching/Stim cross-validation.

**Recommendation: attempt it, but sequence it after E01/E02 close the P0 finding, and treat it
as a hard go/no-go decision at a fixed checkpoint rather than an open-ended effort.**

**Reasoning.**
1. Without Phase 4, the realistic ceiling for this paper is a d=3 measurement/reference-design
   study (TRETS, FCCM, JETC-tier). With a measured d=5 UF decoder and a PyMatching-validated
   logical-error-rate curve, the paper opens TQE/QCE/QST-tier venues, which is a materially
   different outcome for the author, not a marginal improvement.
2. The scalability finding this campaign will produce regardless of Phase 4 (Table 5, corrected:
   LUT decoding is viable to about $m\approx16$, i.e. through the Shor/Steane/d=3-surface class
   and no further) is itself an argument *for* attempting Phase 4: it is precisely the boundary
   Reviewer 2 says is the only regime with practical value, and the current codebase (monolithic
   AXI-Lite HLS kernels, a working host toolchain, Vitis 2023.2 confirmed installed on this host)
   is a reasonable starting point for a UF kernel, not a green-field effort.
3. It is real engineering risk, not a formality. A distance-5 rotated-surface UF decoder in HLS
   with multi-round, measurement-error decoding is a genuinely harder design than anything in the
   current archive (none of whose kernels handle repeated rounds or persistent state). Holmes et
   al. and Liyanage et al. (see ledger C-072, now bibliographically corrected) establish the
   peeling step parallelises on FPGA, which de-risks the algorithm choice but not the schedule.

**Time estimate.** Two to four weeks of engineering time, contingent on:
- Union-find HLS/RTL implementation and verification against a software UF reference and
  PyMatching on identical Stim circuits: 1 to 2 weeks.
- Multi-round driver with a persistent Pauli-frame register and a synthetic (Stim-generated,
  explicitly labelled as simulated) syndrome source: 3 to 5 days.
- Synthesis, timing closure, and hardware measurement (latency per round, backlog behaviour) on
  the device this host already has access to: 3 to 5 days, assuming B-002 licensing is confirmed
  and no timing-closure surprises at d=5 (24-bit syndrome logic is meaningfully larger than the
  8-bit Shor kernel and may need pipelining work the current kernels don't require).
- Contingency for a d=7 extension (brief Section 5, "if the fabric and the calendar allow"):
  add one to two more weeks; treat as a stretch goal, not part of the base estimate.

**Decision point.** Recommend committing to Phase 4 only after E01 (exhaustive hardware
verification) and E02 (measured latency distribution) land, per the brief's own suggested order
of execution (Section 11: "decision point with the author on Phase 4, end of week 3"). If the
author declines or the two-to-four-week budget isn't available, `docs/SCOPE.md` already states
the fallback framing plainly: reposition as a d=3 measurement and reference-design paper and
target TRETS/FCCM, with d≥5 stated as future work and a reason given (not a buried admission).

**Consequence.** ADR-002 (venue) is gated on this decision.
