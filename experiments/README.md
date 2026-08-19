# Experiments

One directory per experiment, self-contained: `run.sh`, `config.yaml`, `raw/`, `processed/`,
`plot.py`, `NOTES.md`.

**Hard rule.** `run.sh` must fail loudly if the hardware path is unavailable. It must never
fall back to a software decoder and continue. That silent fallback is exactly what produced
the errors in the rejected submission (see `evidence/runs/selftest.log`).

| ID | Purpose | Reviewer points |
|---|---|---|
| E01 | Exhaustive correctness on hardware | R1-Major-5, P0 |
| E02 | End-to-end latency distribution with tails | R1-Major-1, R1-Major-3, R2-2 |
| E03 | Throughput versus batch size, 1 microsecond crossover | R1-Major-3, R2-2 |
| E04 | Measured multi-CU scaling | R1-Major-3 |
| E05 | Repeated rounds with measurement error, backlog | R1-Major-1, R1-Major-5 |
| E06 | Surface code d=5 union-find (Phase 4) | R2-1 |
| E07 | Monte Carlo at 10^7 shots with confidence intervals | R1-Minor-4, R2-3 |
| E08 | Fair CPU and GPU baselines, literature table | R2-3 |
