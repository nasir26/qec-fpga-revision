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



# This figure is included at \includegraphics[width=\textwidth] in
# paper/sections/results.tex. Measured directly from the compiled main.pdf
# (PyMuPDF span sizes on the page carrying this figure, sn-jnl single-column
# \textwidth): a matplotlib legend set at fontsize=7 on the OLD figsize=(13,4)
# rendered at 2.57pt on the page, i.e. an inclusion scale of ~0.367 (this is
# an empirical fact about this document class, not a guess -- 344pt printed
# width / 936pt native width at the old figsize matches it). At that scale,
# every unset-fontsize element (titles, tick labels, at rcParams defaults)
# came out at 3.9-4.8pt, far under the journal's 8pt-at-final-size rule; only
# the LaTeX-set caption text (10pt/8pt) was compliant.
#
# Fix: shrink the native figure (less aggressive downscaling needed to reach
# the same printed width) AND set every text element's fontsize explicitly,
# sized for a >=9.5pt effective floor with headroom over the empirically
# measured ~0.53 scale factor at this new figsize (344pt / (9in*72pt/in)).
FIGSIZE = (9.5, 5.2)
TITLE_FONTSIZE = 18
LABEL_FONTSIZE = 17
LEGEND_FONTSIZE = 17
TICK_LABELSIZE = 17
# The "software-mirror, not hardware-measured" caveat is already the bolded
# first sentence of the LaTeX caption (paper/sections/results.tex) -- no need
# to also cram it into the image as a suptitle, which is what was colliding
# with the panel titles.


def main():
    points = load()
    fig, axes = plt.subplots(1, 3, figsize=FIGSIZE)

    # --- Panel 1: Rep-3, IID bit-flip ---
    ax = axes[0]
    p, p_l, lo, hi = series(points, "rep3", "iid_bitflip")
    ax.plot(p, p_l, "o-", label="measured", color="C0")
    ax.fill_between(p, lo, hi, alpha=0.25, color="C0", label="95% CI")
    p_analytic = np.linspace(min(p), max(p), 200)
    ax.plot(p_analytic, 3 * p_analytic**2 - 2 * p_analytic**3, "--", color="k",
             label="analytic")
    ax.set_title("Rep-3 [[3,1,2]]", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("physical error rate $p$", fontsize=LABEL_FONTSIZE)
    ax.set_ylabel("logical error rate $p_L$", fontsize=LABEL_FONTSIZE)
    ax.legend(fontsize=LEGEND_FONTSIZE, loc="upper left")
    ax.tick_params(axis="both", labelsize=TICK_LABELSIZE)
    ax.grid(alpha=0.3)

    # --- Panel 2: Shor, both models ---
    ax = axes[1]
    p, p_l, lo, hi = series(points, "shor", "single_pauli")
    floor = 0.5 / 1e7
    p_l_floor = np.where(p_l == 0, floor, p_l)
    ax.plot(p, p_l_floor, "s-", label="single-Pauli", color="C2")
    p, p_l, lo, hi = series(points, "shor", "iid_depolarising")
    ax.plot(p, p_l, "o-", label="IID-depol.", color="C1")
    ax.fill_between(p, lo, hi, alpha=0.25, color="C1")
    ax.axhline(0.015, ls=":", color="gray", lw=1, label="prior claim")
    ax.set_yscale("log")
    ax.set_title("Shor [[9,1,3]]", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("physical error rate $p$", fontsize=LABEL_FONTSIZE)
    ax.legend(fontsize=LEGEND_FONTSIZE, loc="upper left")
    ax.tick_params(axis="both", labelsize=TICK_LABELSIZE)
    ax.grid(alpha=0.3)

    # --- Panel 3: Steane, 3 modes ---
    ax = axes[2]
    colors = {"LUT": "C0", "MWPM": "C3", "UF": "C4"}
    for mode in ("LUT", "MWPM", "UF"):
        p, p_l, lo, hi = series(points, f"steane_{mode}", "iid_depolarising")
        ax.plot(p, p_l, "o-", label=f"{mode}", color=colors[mode], markersize=5)
        ax.fill_between(p, lo, hi, alpha=0.15, color=colors[mode])
    ax.set_title("Steane [[7,1,3]]", fontsize=TITLE_FONTSIZE)
    ax.set_xlabel("physical error rate $p$", fontsize=LABEL_FONTSIZE)
    ax.legend(fontsize=LEGEND_FONTSIZE, loc="upper left")
    ax.tick_params(axis="both", labelsize=TICK_LABELSIZE)
    ax.grid(alpha=0.3)

    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
