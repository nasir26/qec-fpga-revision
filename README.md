# qec-fpga-revision

Revision campaign for "FPGA-Based Real-Time Quantum Error Correction for Shor and Steane Codes"
(rejected, *The Journal of Supercomputing*, 18 Aug 2026, submission `e7d19f63-0e69-4714-a61d-f53b2885839f`).

Author: Nasir Ali, Embedded Systems Division, C-DAC Noida (NQM / MeitY).

## Current state

**Phase 1 (forensic audit) complete, 2026-08-19.** Repository scaffolded, original submission
archived read-only and checksummed under `docs/legacy/`, `docs/CLAIMS_LEDGER.md` populated to
86 rows against every table cell and figure caption in `main.tex`, `docs/SCOPE.md` and
`docs/BLOCKERS.md` finalised, `docs/DECISIONS.md` carries a Phase 4 recommendation (ADR-004).
See `docs/PROVABLE_FACTS.md` for the one-page summary. **Awaiting author go-ahead before Phase 2.**

**Nothing in this repository is submission-ready.** The prior submission's central hardware
claims are not currently backed by hardware logs in the archive (see `docs/SCOPE.md`). Of the
three kernels the manuscript describes, only one (Shor) has any synthesis evidence at all in the
delivered archive, and none has a confirmed hardware read-back.

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
