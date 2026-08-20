#!/usr/bin/env python3
"""Regenerates fig3_error_curves as a vector PDF from real Monte Carlo data.

Source: experiments/E07b_montecarlo_software_mirror/processed/montecarlo_processed.json
SOFTWARE-MIRROR data (see that experiment's README): not a hardware measurement.
10^7 shots/point, Wilson 95% CI shown as shaded bands.
"""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "experiments" / "E07b_montecarlo_software_mirror" / "processed" / "montecarlo_processed.json"
OUT = REPO_ROOT / "figures" / "out" / "fig3_error_curves.pdf"


def load():
    d = json.loads(DATA.read_text())
    return d["points"]


def series(points, code, model):
    rows = [r for r in points if r["code"] == code and r["model"] == model]
    rows.sort(key=lambda r: r["p"])
    p = np.array([r["p"] for r in rows])
    p_l = np.array([r["p_L"] for r in rows])
    lo = np.array([r["wilson_lo"] for r in rows])
    hi = np.array([r["wilson_hi"] for r in rows])
    return p, p_l, lo, hi


def main():
    points = load()
    fig, axes = plt.subplots(1, 3, figsize=(13, 4))

    # --- Panel 1: Rep-3, IID bit-flip ---
    ax = axes[0]
    p, p_l, lo, hi = series(points, "rep3", "iid_bitflip")
    ax.plot(p, p_l, "o-", label="measured (software mirror, $10^7$ shots)", color="C0")
    ax.fill_between(p, lo, hi, alpha=0.25, color="C0", label="Wilson 95% CI")
    p_analytic = np.linspace(min(p), max(p), 200)
    ax.plot(p_analytic, 3 * p_analytic**2 - 2 * p_analytic**3, "--", color="k",
             label=r"analytic $p_L=3p^2-2p^3$")
    ax.set_title("Rep-3 [[3,1,2]], IID bit-flip")
    ax.set_xlabel("physical error rate $p$")
    ax.set_ylabel("logical error rate $p_L$")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    # --- Panel 2: Shor, both models ---
    ax = axes[1]
    p, p_l, lo, hi = series(points, "shor", "single_pauli")
    floor = 0.5 / 1e7
    p_l_floor = np.where(p_l == 0, floor, p_l)
    ax.plot(p, p_l_floor, "s-", label="single-Pauli (shown at shot-noise floor)", color="C2")
    p, p_l, lo, hi = series(points, "shor", "iid_depolarising")
    ax.plot(p, p_l, "o-", label="IID-depolarising (measured)", color="C1")
    ax.fill_between(p, lo, hi, alpha=0.25, color="C1")
    ax.axhline(0.015, ls=":", color="gray", lw=1,
               label="manuscript's claimed value at p=0.10 (0.015)")
    ax.set_yscale("log")
    ax.set_title("Shor [[9,1,3]]")
    ax.set_xlabel("physical error rate $p$")
    ax.legend(fontsize=6.5)
    ax.grid(alpha=0.3)

    # --- Panel 3: Steane, 3 modes ---
    ax = axes[2]
    colors = {"LUT": "C0", "MWPM": "C3", "UF": "C4"}
    for mode in ("LUT", "MWPM", "UF"):
        p, p_l, lo, hi = series(points, f"steane_{mode}", "iid_depolarising")
        ax.plot(p, p_l, "o-", label=f"{mode}", color=colors[mode], markersize=4)
        ax.fill_between(p, lo, hi, alpha=0.15, color=colors[mode])
    ax.set_title("Steane [[7,1,3]], IID-depolarising\n(3 decoder modes, real z-test in caption)")
    ax.set_xlabel("physical error rate $p$")
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3)

    fig.suptitle("Monte Carlo logical error rates, $10^7$ shots/point, software mirrors "
                  "(NOT hardware-measured -- see docs/BLOCKERS.md B-001)", fontsize=9)
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
