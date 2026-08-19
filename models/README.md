# Models

- `mirrors/` bit-exact software twins of each hardware decoder. Their only job is to be compared
  against hardware output, never to stand in for it.
- `reference/` Stim circuit definitions, PyMatching baselines, an independent union-find reference.
- `tests/` pytest suite: mirror versus hardware (requires card), mirror versus PyMatching
  (no card), exhaustive enumeration at d=3, and property tests over random Pauli frames.

The correctness argument changes with distance. At d=3 it is exhaustive enumeration over all
3^n single-block error patterns. At d=5 it is agreement with PyMatching under an identical
circuit-level noise model, with confidence intervals.

## Status

- `mirrors/steane_mirror.py`: bit-exact mirror of `rtl/steane713/src/steane_qec_kernel.cpp`,
  the reconstructed three-mode kernel (docs/BLOCKERS.md B-003; no original source exists in
  either archive). `tests/test_steane_mirror.py` reproduces the manuscript's claimed 21/21 x 3
  self-test (63/63 PASS against this mirror), plus a weight-1 cross-mode agreement check and a
  weight-2 census not present in the original manuscript. **This is a software-only result.** It
  validates that the reconstructed kernel's logic is internally consistent and matches the
  manuscript's description; it says nothing about hardware, and must not be cited as a
  `MEASURED-HW` or `MEASURED-SW` row for the *original* (missing) kernel in
  `docs/CLAIMS_LEDGER.md`.
  - Building this mirror surfaced a real defect in the manuscript's own description: main.tex
    L183's literal wording for the UF decoder ("count how many adjacent check nodes are active;
    if odd, include the qubit") does not correctly decode single-qubit errors on this Tanner
    graph — 4 of 7 qubits get spuriously included for a weight-1 syndrome. The fix used here
    follows main.tex L308's own resolution ("[UF] collapses to the same XOR-reduce for one growth
    round"), implemented as column-vs-syndrome equality. See the long comment in
    `steane_mirror.py::uf_decode` and `rtl/steane713/src/steane_qec_kernel.cpp::uf_decode`.
  - A second finding worth carrying into the manuscript rewrite: for this specific [7,4,3]
    Hamming code, every pair of columns XORs to a third column (`H_COL[i] ^ H_COL[j] == H_COL[k]`
    for some k, for every pair). That means a weight-2 error's syndrome is indistinguishable from
    a weight-1 error on qubit k at the *syndrome* level, and all three decoders (LUT, MWPM, UF)
    therefore alias to the *same* wrong single-qubit correction for every weight-2 X-only error
    (verified exhaustively: 21/21 pairs agree). This contradicts main.tex L479/L506, which claim
    the decoders "differ" in how they handle weight-2 syndromes. On this evidence they do not
    differ; they agree, on the wrong correction. Worth a ledger row and a manuscript fix once a
    hardware or full-mirror rerun confirms it against Y and Z errors too.
- `mirrors/shor_mirror.py`: not yet written. `host/python/shor_qec_host.py` already contains an
  embedded software decoder (the "Path S" fallback) that produced the 27/27 result in
  `evidence/runs/selftest.log`; extracting that into a standalone mirror module, rather than
  writing one from scratch, is the next step so E01's exhaustive 3^9 sweep has something to run
  against independent of the host driver's XRT plumbing.
