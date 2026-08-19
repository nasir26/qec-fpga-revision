# rtl/surface_d5

Phase 4. Rotated surface code, d=5, union-find decoder over the space-time graph with
measurement errors, d rounds per decode window.

Empty until the author approves Phase 4 (see docs/DECISIONS.md and the mission brief Section 5).
This is the track Reviewer 2 named as the condition for a meaningful contribution:
"distance-5+ iterative decoders with genuine hardware measurements and comparison to existing work".

## Design notes to settle before writing code
- Union-find versus BP+OSD: UF preferred for hardware (near-linear, peeling parallelises).
- Space-time graph construction: d rounds, measurement error edges, boundary handling.
- Fixed-point versus integer weights.
- Correctness argument at d=5 is agreement with PyMatching under identical circuit-level noise,
  not exhaustive enumeration.
- Latency target: per-round decode under the syndrome round time, with the tail reported.
