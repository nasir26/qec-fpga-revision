# qec-fpga-revision

Revision campaign for "FPGA-Based Real-Time Quantum Error Correction for Shor and Steane Codes"
(rejected, *The Journal of Supercomputing*, 18 Aug 2026, submission `e7d19f63-0e69-4714-a61d-f53b2885839f`).

Author: Nasir Ali, Embedded Systems Division, C-DAC Noida (NQM / MeitY).

## Current state

**A full draft manuscript exists and compiles, 2026-08-20** (`paper/main.tex` -> `paper/main.pdf`,
18 pages, built with `paper/build.sh`; see `docs/CLAIMS_LEDGER.md`, now past 100 rows). This is a
real, evidence-backed draft, not a finished submission: the title is provisional (ADR-001 not yet
signed off by the author), the bibliography style is a substitute for a missing proprietary
Springer Nature `.bst` file, `figures/out/fig3_error_curves.pdf`'s in-figure title text is below
the 8pt-at-final-size rule and needs a font-size fix, and **no result anywhere in the draft is a
hardware measurement** -- every latency/resource number is an HLS synthesis estimate and every
logical-error-rate curve is a software simulation, both stated explicitly in the abstract and
Section 6.4. Phase 1 (forensic audit) is complete; the bulk of Phase 3's software-reachable work
(real HLS synthesis for all three kernels, software-mirror correctness verification, phenomenological
and circuit-level Monte Carlo data, a literature comparison table, bibliography and Table 2/5
corrections) is done. What remains is fundamentally hardware-gated: see `docs/BLOCKERS.md` B-001.

**Not submission-ready yet.** Beyond the hardware gap: the GitHub repository this manuscript's
"Data availability" statement points to is currently private and needs to be made public (or
reviewer access arranged) before submission; the title needs the author's actual sign-off, not
just a provisional pick; and a full proofreading/formatting pass has not been done.

## The one rule

No number reaches the manuscript without a row in `docs/CLAIMS_LEDGER.md` carrying an
evidence path and a class tag: `MEASURED-HW`, `MEASURED-SW`, `HLS-ESTIMATE`, `POST-ROUTE`,
`ANALYTIC`, or `PROJECTED`. `PROJECTED` never appears in the abstract, title, conclusions,
or any results figure.

## Layout

| Path | Contents |
|---|---|
| `docs/legacy/` | The submitted manuscript and implementation archive. Read-only. Never edit. |
| `docs/CLAIMS_LEDGER.md` | Every quantitative claim, its evidence, its verdict. The spine of the effort. |
| `docs/SCOPE.md` | What the artifact demonstrates versus what the manuscript claimed. |
| `docs/BLOCKERS.md` | What is needed from the author or the environment. |
| `docs/DECISIONS.md` | Architectural decision records (title, venue, decoder choice). |
| `rtl/` | Kernel sources, one directory per code, with link configs. |
| `host/cpp/` | C++ XRT and OpenCL hosts. **The only path permitted to produce timing claims.** |
| `host/python/` | Convenience drivers and software mirrors. Never used for timing claims. |
| `models/` | Software mirrors, Stim and PyMatching references, correctness tests. |
| `experiments/` | One self-contained directory per experiment (E01 to E08). |
| `evidence/` | Append-only synthesis reports and run logs, checksummed in `MANIFEST.sha256`. |
| `figures/` | Figure sources in `src/`, generated vector PDFs in `out/`. |
| `paper/` | Rebuilt manuscript, split into `sections/`. |
| `response/` | Point-by-point reviewer response and change log. |

## Reproducing

```
make env-check      # verify Vitis 2023.2, XRT, platform xpfm, device visibility, permissions
make mirrors        # build software decoders and run the mirror test suite (no hardware)
make bitstreams     # synthesise and link all kernels (long)
make measure        # run experiments E01 to E08 against hardware
make figures        # regenerate every figure from experiments/*/processed/
make paper          # build the manuscript PDF
```

Each experiment is also runnable standalone: `cd experiments/E02_hw_latency_histogram && ./run.sh`.

## Conventions

- Every experiment records its RNG seed in `config.yaml`. Runs are reproducible or they do not count.
- `experiments/*/raw/` is written by tools only, never by hand.
- Figures are vector PDF, minimum 8 pt effective font at final column width.
- Prose in this repository does not use em dashes.
- Commit messages reference the reviewer point addressed, for example `fix(tab5): m = n-k throughout [R1-Major-6]`.
