"""Self-test for models/mirrors/steane_mirror.py, the reconstructed Steane
kernel mirror (docs/BLOCKERS.md B-003). Reproduces the manuscript's claimed
21/21-per-mode self-test (main.tex L335, Algorithm 3) against the Python
mirror ONLY -- this is not a hardware result and must not be logged as one
in docs/CLAIMS_LEDGER.md. Also runs an exhaustive weight-1 cross-check
across all three modes (main.tex L500-509's "statistically identical for
weight-1" claim, checked here as an exact equality claim, not a statistical
one) and an exhaustive weight-2 agreement census.
"""

import itertools
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mirrors"))
from steane_mirror import steane_qec_kernel, MODE_NAMES  # noqa: E402

N_DATA = 7


def run_self_test():
    total = 0
    failed = 0
    for mode in (0, 1, 2):
        for q in range(N_DATA):
            for kind in ("X", "Y", "Z"):
                x_err = (1 << q) if kind in ("X", "Y") else 0
                z_err = (1 << q) if kind in ("Y", "Z") else 0
                r = steane_qec_kernel(x_err, z_err, mode)
                total += 1
                ok = (r.x_logical_err == 0 and r.z_logical_err == 0)
                if not ok:
                    failed += 1
                    print(f"FAIL mode={MODE_NAMES[mode]} {kind} q{q}: "
                          f"x_corr={r.x_corr:07b} z_corr={r.z_corr:07b} "
                          f"Xlog={r.x_logical_err} Zlog={r.z_logical_err}")
    print(f"self-test: {total - failed}/{total} PASS "
          f"({'all modes agree with the manuscript-claimed 21/21 x 3' if failed == 0 else 'MISMATCH'})")
    return failed == 0


def run_weight1_cross_mode_check():
    mismatches = 0
    checked = 0
    for q in range(N_DATA):
        for x_err, z_err in [(1 << q, 0), (0, 1 << q), (1 << q, 1 << q)]:
            checked += 1
            results = {m: steane_qec_kernel(x_err, z_err, m) for m in (0, 1, 2)}
            corrections = {(r.x_corr, r.z_corr) for r in results.values()}
            if len(corrections) != 1:
                mismatches += 1
                print(f"CROSS-MODE MISMATCH x_err={x_err:07b} z_err={z_err:07b}: "
                      + ", ".join(f"{MODE_NAMES[m]}={results[m].x_corr:07b}/{results[m].z_corr:07b}"
                                  for m in (0, 1, 2)))
    print(f"weight-1 cross-mode agreement: {checked - mismatches}/{checked} identical across LUT/MWPM/UF")
    return mismatches == 0


def run_weight2_census():
    agree = 0
    disagree = 0
    for i, j in itertools.combinations(range(N_DATA), 2):
        x_err = (1 << i) | (1 << j)
        results = {m: steane_qec_kernel(x_err, 0, m) for m in (0, 1, 2)}
        corrections = {r.x_corr for r in results.values()}
        if len(corrections) == 1:
            agree += 1
        else:
            disagree += 1
    print(f"weight-2 X-error census: {agree} of {agree + disagree} qubit pairs "
          f"give identical correction across all three modes, {disagree} differ")


if __name__ == "__main__":
    ok1 = run_self_test()
    ok2 = run_weight1_cross_mode_check()
    run_weight2_census()
    sys.exit(0 if (ok1 and ok2) else 1)
