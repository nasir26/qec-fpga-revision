#!/usr/bin/env python3
"""Monte Carlo logical error rate sweep against the SOFTWARE MIRRORS ONLY.

THIS IS NOT experiments/E07_montecarlo_1e7 (the real, hardware-measured
experiment the brief and docs/CLAIMS_LEDGER.md C-100/C-102 call for). That
experiment is still BLOCKED on docs/BLOCKERS.md B-001 and stays that way
until it runs against real hardware. This script exists to:

  1. Give the manuscript rewrite real, traceable logical-error-rate numbers
     where it currently has none at all (ledger C-100 through C-108 are all
     UNSUPPORTED -- no run of any kind, at any shot count, exists in either
     archive, for either noise model, for any code but a 4-point single-Pauli
     sweep on Shor).
  2. Rehearse the analysis pipeline (Wilson intervals, the paired
     two-proportion z-test for "LUT/MWPM/UF are statistically identical")
     before spending real hardware time on it.

Every number this script produces belongs in the ledger tagged MEASURED-SW,
never MEASURED-HW, and never silently substituted for the real E07 result.

Uses the software mirrors in models/mirrors/ (rep3_mirror.py, shor_mirror.py,
steane_mirror.py), which are themselves verified against the actual HLS
kernel sources (see models/README.md). Fully vectorised with numpy: for each
code, a lookup table of (x_err, z_err) -> logical-fail is precomputed once by
exhaustive enumeration (small enough to be exact, not sampled), then Monte
Carlo shots are generated as numpy arrays and the failure lookup is a single
vectorised fancy-index operation. This is what makes 10^7 shots/point
tractable in pure Python without a hardware accelerator.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "models" / "mirrors"))

import rep3_mirror  # noqa: E402
import shor_mirror  # noqa: E402
import steane_mirror  # noqa: E402

SEED = 0xC0DE7  # matches main.tex L357's stated seed, for continuity
N_SHOTS = 10_000_000
P_GRID = [1e-3, 5e-3, 1e-2, 2e-2, 5e-2, 0.10, 0.15, 0.18, 0.20]

OUT_RAW = Path(__file__).parent / "raw"
OUT_PROCESSED = Path(__file__).parent / "processed"


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    """Wilson score interval for a binomial proportion. Returns (p_hat, lo, hi)."""
    if n == 0:
        return 0.0, 0.0, 0.0
    p_hat = k / n
    denom = 1 + z * z / n
    centre = (p_hat + z * z / (2 * n)) / denom
    half = (z / denom) * np.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))
    return p_hat, max(0.0, centre - half), min(1.0, centre + half)


def two_proportion_z_test(k1: int, n1: int, k2: int, n2: int) -> float:
    """Two-sided two-proportion z-test. Returns the p-value."""
    from math import erfc, sqrt
    p1, p2 = k1 / n1, k2 / n2
    p_pool = (k1 + k2) / (n1 + n2)
    se = sqrt(p_pool * (1 - p_pool) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0 if p1 == p2 else 0.0
    z = (p1 - p2) / se
    return erfc(abs(z) / sqrt(2))  # two-sided p-value


# ---------------------------------------------------------------------------
#  Precomputed logical-failure lookup tables (exact, exhaustive, not sampled)
# ---------------------------------------------------------------------------

def build_shor_fail_table() -> np.ndarray:
    """shape (512, 512) bool, True = logical failure."""
    table = np.zeros((512, 512), dtype=bool)
    for x in range(512):
        for z in range(512):
            r = shor_mirror.shor_qec_kernel(x, z)
            table[x, z] = (r["x_logical_err"] != 0) or (r["z_logical_err"] != 0)
    return table


def build_steane_fail_tables() -> dict[str, np.ndarray]:
    """One (128, 128) bool table per mode."""
    tables = {}
    for mode, name in ((0, "LUT"), (1, "MWPM"), (2, "UF")):
        t = np.zeros((128, 128), dtype=bool)
        for x in range(128):
            for z in range(128):
                r = steane_mirror.steane_qec_kernel(x, z, mode)
                t[x, z] = (r.x_logical_err != 0) or (r.z_logical_err != 0)
        tables[name] = t
    return tables


def build_rep3_fail_table() -> np.ndarray:
    """shape (8,) bool, indexed by error_mask, for codeword_in=0b000 (by
    symmetry the 0b111 codeword gives the identical failure pattern)."""
    table = np.zeros(8, dtype=bool)
    for e in range(8):
        r = rep3_mirror.rep3_qec_kernel(0b000, e, 0)
        table[e] = (r["recovery_success"] == 0)
    return table


# ---------------------------------------------------------------------------
#  Vectorised shot generation
# ---------------------------------------------------------------------------

def sample_single_pauli(rng: np.random.Generator, n_shots: int, n_qubits: int, p: float):
    """main.tex L329: w.p. p, one uniformly random qubit gets a uniformly
    random Pauli in {X,Y,Z}; w.p. 1-p, no error."""
    x_err = np.zeros(n_shots, dtype=np.int64)
    z_err = np.zeros(n_shots, dtype=np.int64)
    has_error = rng.random(n_shots) < p
    n_err = int(has_error.sum())
    if n_err:
        qubits = rng.integers(0, n_qubits, size=n_err)
        kinds = rng.integers(0, 3, size=n_err)  # 0=X, 1=Y, 2=Z
        bit = np.int64(1) << qubits
        x_bit = np.where(kinds != 2, bit, 0)
        z_bit = np.where(kinds != 0, bit, 0)
        x_err[has_error] = x_bit
        z_err[has_error] = z_bit
    return x_err, z_err


def sample_iid_depolarising(rng: np.random.Generator, n_shots: int, n_qubits: int, p: float):
    """main.tex L330: each qubit independently gets a depolarising error
    w.p. p, uniform over {X,Y,Z} conditioned on an error occurring."""
    errs = rng.random((n_shots, n_qubits)) < p          # (n_shots, n_qubits)
    kinds = rng.integers(0, 3, size=(n_shots, n_qubits))  # 0=X,1=Y,2=Z
    bits = (np.int64(1) << np.arange(n_qubits, dtype=np.int64))[None, :]
    x_mask = errs & (kinds != 2)
    z_mask = errs & (kinds != 0)
    x_err = (x_mask * bits).sum(axis=1)
    z_err = (z_mask * bits).sum(axis=1)
    return x_err, z_err


def sample_iid_bitflip(rng: np.random.Generator, n_shots: int, n_qubits: int, p: float):
    """Fig 3 caption (main.tex L470): "IID bit-flip noise" for the Rep-3
    panel -- each qubit independently flips (X only) w.p. p. Rep-3 has no
    notion of a Z/phase error at all (main.tex L140: "protects against a
    single X error and has no protection against Z errors"), so this is
    deliberately a different, simpler model than the general depolarising
    model used for Shor/Steane, not a special case of it."""
    errs = rng.random((n_shots, n_qubits)) < p
    bits = (np.int64(1) << np.arange(n_qubits, dtype=np.int64))[None, :]
    return (errs * bits).sum(axis=1)  # this is directly the 3-bit error_mask


def run_sweep(name: str, n_qubits: int, fail_table_lookup, model: str, rng: np.random.Generator):
    rows = []
    for p in P_GRID:
        if model == "single_pauli":
            x_err, z_err = sample_single_pauli(rng, N_SHOTS, n_qubits, p)
        elif model == "iid_depolarising":
            x_err, z_err = sample_iid_depolarising(rng, N_SHOTS, n_qubits, p)
        elif model == "iid_bitflip":
            x_err = sample_iid_bitflip(rng, N_SHOTS, n_qubits, p)
            z_err = None
        else:
            raise ValueError(model)
        fails = fail_table_lookup(x_err, z_err)
        k = int(fails.sum())
        p_hat, lo, hi = wilson_interval(k, N_SHOTS)
        rows.append({"code": name, "model": model, "p": p, "n_shots": N_SHOTS,
                      "n_fail": k, "p_L": p_hat, "wilson_lo": lo, "wilson_hi": hi})
        print(f"  {name:8s} {model:17s} p={p:<8g} n_fail={k:>8d}/{N_SHOTS} "
              f"p_L={p_hat:.3e} [{lo:.3e},{hi:.3e}]")
    return rows


def main():
    OUT_RAW.mkdir(exist_ok=True)
    OUT_PROCESSED.mkdir(exist_ok=True)
    rng = np.random.default_rng(SEED)
    t_start = time.time()

    print("Building exact failure-lookup tables (exhaustive enumeration, not sampled)...")
    shor_table = build_shor_fail_table()
    steane_tables = build_steane_fail_tables()
    rep3_table = build_rep3_fail_table()
    print(f"  done in {time.time()-t_start:.1f}s")

    all_rows = []

    print("\n=== iid_bitflip (Rep-3 only, main.tex Fig 3 left panel's actual model) ===")
    all_rows += run_sweep("rep3", 3, lambda x, z: rep3_table[x], "iid_bitflip", rng)

    for model in ("single_pauli", "iid_depolarising"):
        print(f"\n=== {model} ===")
        all_rows += run_sweep("shor", 9, lambda x, z: shor_table[x, z], model, rng)
        for mode_name, table in steane_tables.items():
            all_rows += run_sweep(f"steane_{mode_name}", 7,
                                   lambda x, z, t=table: t[x, z], model, rng)

    # Save raw per-point results
    raw_path = OUT_RAW / "montecarlo_raw.json"
    raw_path.write_text(json.dumps(all_rows, indent=2))
    print(f"\nwrote {raw_path} ({len(all_rows)} rows)")

    # Statistical test: are Steane LUT/MWPM/UF "statistically identical"? (main.tex L479, ledger C-108)
    print("\n=== Steane LUT vs MWPM vs UF, two-proportion z-test, iid_depolarising ===")
    by_key = {(r["code"], r["model"], r["p"]): r for r in all_rows}
    z_test_rows = []
    for p in P_GRID:
        lut = by_key[("steane_LUT", "iid_depolarising", p)]
        mwpm = by_key[("steane_MWPM", "iid_depolarising", p)]
        uf = by_key[("steane_UF", "iid_depolarising", p)]
        pval_lut_mwpm = two_proportion_z_test(lut["n_fail"], N_SHOTS, mwpm["n_fail"], N_SHOTS)
        pval_lut_uf = two_proportion_z_test(lut["n_fail"], N_SHOTS, uf["n_fail"], N_SHOTS)
        pval_mwpm_uf = two_proportion_z_test(mwpm["n_fail"], N_SHOTS, uf["n_fail"], N_SHOTS)
        row = {"p": p, "pval_LUT_vs_MWPM": pval_lut_mwpm, "pval_LUT_vs_UF": pval_lut_uf,
               "pval_MWPM_vs_UF": pval_mwpm_uf}
        z_test_rows.append(row)
        print(f"  p={p:<8g} LUT-vs-MWPM p={pval_lut_mwpm:.4f}  "
              f"LUT-vs-UF p={pval_lut_uf:.4f}  MWPM-vs-UF p={pval_mwpm_uf:.4f}")

    processed_path = OUT_PROCESSED / "montecarlo_processed.json"
    processed_path.write_text(json.dumps({"points": all_rows, "z_tests": z_test_rows}, indent=2))
    print(f"\nwrote {processed_path}")
    print(f"\ntotal wall time: {time.time()-t_start:.1f}s")


if __name__ == "__main__":
    main()
