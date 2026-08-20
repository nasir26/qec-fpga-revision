# E07b: Monte Carlo, software mirrors only

**Status: RUN, 2026-08-19/20.** This is NOT `experiments/E07_montecarlo_1e7`, the real
hardware-measured experiment the brief and `docs/CLAIMS_LEDGER.md` C-100 call for — that stays
`BLOCKED` on `docs/BLOCKERS.md` B-001 until it runs against real hardware. This is a
software-mirror-only rehearsal, run because the manuscript currently has zero traceable Monte
Carlo data at any shot count for five of its eight (code, model) combinations, and one is
genuinely useful to have even before hardware access resolves.

## What was run

`run_montecarlo.py`, seed `0xC0DE7` (matching main.tex L357), `N_SHOTS = 10,000,000` per point,
the same 9-point physical-error-rate grid the manuscript states (main.tex L357). Vectorised with
numpy against exact, exhaustively-precomputed failure-lookup tables (not sampled decoding — the
decode outcome for every possible input is known in advance from `models/mirrors/`, so only the
random error injection is sampled). Full run: 81 (code, model, p) points, wall time 117.6 s.

- Rep-3: **IID bit-flip** only (main.tex Fig 3 caption says "IID bit-flip noise" for this panel,
  a different, simpler model than the general depolarising model used for Shor/Steane — Rep-3 has
  no notion of a Z error at all, so it cannot use the same sampler).
- Shor: single-Pauli and IID-depolarising, both, per main.tex L327-331.
- Steane: IID-depolarising, all three modes (LUT/MWPM/UF), per main.tex L479.

## Findings

1. **Rep-3 matches the manuscript closely.** Measured $p_L$ at $p=0.10$: **0.02801**
   (Wilson 95% CI [0.02790, 0.02811]). Manuscript claims "approximately $2.7\times10^{-2}$"
   (main.tex L475) and the analytic curve $p_L=3p^2-2p^3=0.028$. All three agree. This is a real
   cross-validation of one of the manuscript's few claims that turns out to hold up.

2. **Shor single-Pauli: exactly zero failures at every grid point, 10^7 shots each**, consistent
   with the manuscript's claim (main.tex L477: "the logical error rate is zero... at all tested
   values of p"). Confirmed, not just asserted.

3. **Shor IID-depolarising: measured $p_L(0.10) = 0.1513$, CI [0.1511, 0.1516]. The manuscript
   claims $\approx1.5\times10^{-2}$ (main.tex L477) — a factor of ten lower.** The confidence
   interval is four orders of magnitude tighter than the gap between measured and claimed, so this
   is not sampling noise. It is also internally consistent with the weight-stratified exhaustive
   characterisation already in `models/mirrors/shor_mirror.py`'s test suite (weight-2 events are
   only 34.3% correctable, and at $p=0.10$ roughly a fifth of shots have weight $\ge2$ errors under
   the depolarising model — the arithmetic works out to a double-digit-percent failure rate, not
   1.5%). See ledger C-144.

4. **Steane's "statistically identical" claim (main.tex L479, L508) is now backed by a real test,
   not an assertion, and it holds up.** Two-proportion z-tests, all three pairwise comparisons
   (LUT-vs-MWPM, LUT-vs-UF, MWPM-vs-UF), at all 9 grid points (27 tests total): 26 of 27 give
   $p>0.05$; one (LUT-vs-MWPM at $p=0.05$) gives $p=0.0475$, marginally under the threshold. With
   27 simultaneous comparisons at $\alpha=0.05$, roughly 1.35 false positives are expected by
   chance alone (multiple-comparisons effect), and the actual measured rates at that point
   (LUT 0.03446, MWPM 0.03430) differ in the fourth decimal place — not a substantively different
   curve. The qualitative claim holds; report the real p-values in the rewrite rather than the
   bare word "identical".

## Claims this experiment resolves

`docs/CLAIMS_LEDGER.md`: C-104, C-105, C-106, C-107, C-108, and new rows C-144/C-145 for the two
headline findings above. All tagged `MEASURED-SW`, none `MEASURED-HW`. See the ledger for the
full mapping.

## What this does NOT resolve

C-100/C-102 (200,000-shot figure — this ran at 10,000,000, a different number, on purpose, per
the reviewers' own request, not a reproduction of the original's stated protocol). C-106/C-107
(below-threshold claims at specific p values — the curves above answer this differently than the
manuscript states; see C-144). Anything `MEASURED-HW`.
