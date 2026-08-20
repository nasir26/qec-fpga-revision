#!/usr/bin/env python3
"""Circuit-level, multi-round Monte Carlo for the Rep-3 code, using Stim
(circuit generation + exact sampling) and PyMatching (MWPM decoding).

Addresses two reviewer points at once that nothing else in this campaign
has touched yet:
  - R1-Maj-5 / R1-Maj-1: "circuit-level noise" and "repeated QEC rounds
    with measurement errors" -- everything else in this repo (including
    experiments/E07b_montecarlo_software_mirror) is PHENOMENOLOGICAL,
    single-shot, perfect-measurement noise. This is genuinely different:
    real gate-level depolarising noise, real measurement error, and a
    real multi-round space-time decoding graph.

Scope, stated plainly: this covers ONLY the Rep-3 [[3,1,2]] code. Stim has
a built-in `repetition_code:memory` circuit generator; Shor [[9,1,3]] and
Steane [[7,1,3]] do not have off-the-shelf Stim generators and would need
custom circuit construction (qubit layout, CNOT schedule, stabilizer
measurement circuits) -- a real, separate piece of engineering, not
attempted in this pass. This experiment is additive evidence, not a
replacement for models/mirrors/-based phenomenological sweeps.

This is SOFTWARE-ONLY (Stim simulation + PyMatching decoding), MEASURED-SW
class, and uses PyMatching's general MWPM decoder, NOT this project's own
rep3_qec_kernel.cpp LUT decoder -- so it is a different decoder on the same
code, useful as an independent correctness cross-check and as real
circuit-level data, but it does not test this project's own kernel logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pymatching
import stim

SEED = 0xC0DE7
N_SHOTS = 1_000_000
DISTANCE = 3
ROUNDS_GRID = [1, 3, 10, 50]
P_GRID = [0.001, 0.003, 0.01, 0.03, 0.05, 0.08, 0.10]

OUT_RAW = Path(__file__).parent / "raw"
OUT_PROCESSED = Path(__file__).parent / "processed"


def wilson_interval(k: int, n: int, z: float = 1.96):
    if n == 0:
        return 0.0, 0.0, 0.0
    p_hat = k / n
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    half = (z / denom) * np.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    return p_hat, max(0.0, centre - half), min(1.0, centre + half)


def run_point(p: float, rounds: int, n_shots: int, seed: int):
    circuit = stim.Circuit.generated(
        "repetition_code:memory",
        distance=DISTANCE,
        rounds=rounds,
        after_clifford_depolarization=p,
        before_round_data_depolarization=p,
        before_measure_flip_probability=p,
        after_reset_flip_probability=p,
    )
    dem = circuit.detector_error_model(decompose_errors=True)
    matcher = pymatching.Matching.from_detector_error_model(dem)

    sampler = circuit.compile_detector_sampler(seed=seed)
    detection_events, observable_flips = sampler.sample(n_shots, separate_observables=True)

    predictions = matcher.decode_batch(detection_events)
    n_fail = int(np.sum(predictions.flatten() != observable_flips.flatten()))
    return n_fail


def main():
    OUT_RAW.mkdir(exist_ok=True)
    OUT_PROCESSED.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)

    rows = []
    print(f"Rep-3 [[3,1,2]] circuit-level, Stim + PyMatching MWPM, {N_SHOTS:,} shots/point")
    for rounds in ROUNDS_GRID:
        for p in P_GRID:
            seed = int(rng.integers(0, 2**31))
            n_fail = run_point(p, rounds, N_SHOTS, seed)
            p_hat, lo, hi = wilson_interval(n_fail, N_SHOTS)
            rows.append({"code": "rep3", "distance": DISTANCE, "rounds": rounds, "p": p,
                         "n_shots": N_SHOTS, "n_fail": n_fail, "p_L": p_hat,
                         "wilson_lo": lo, "wilson_hi": hi, "decoder": "pymatching_mwpm"})
            print(f"  rounds={rounds:3d} p={p:<8g} n_fail={n_fail:>7d}/{N_SHOTS} "
                  f"p_L={p_hat:.4e} [{lo:.4e},{hi:.4e}]")

    raw_path = OUT_RAW / "circuit_level_raw.json"
    raw_path.write_text(json.dumps(rows, indent=2))
    print(f"\nwrote {raw_path} ({len(rows)} rows)")

    processed_path = OUT_PROCESSED / "circuit_level_processed.json"
    processed_path.write_text(json.dumps(rows, indent=2))
    print(f"wrote {processed_path}")


if __name__ == "__main__":
    main()
