#!/usr/bin/env python3
"""Rep-3 circuit-level, multi-round logical error rate, from
experiments/E05b_repetition_circuit_level/processed/circuit_level_processed.json.
Stim + PyMatching, SOFTWARE-ONLY (MEASURED-SW), not a hardware result and not
this project's own kernel decoder (uses PyMatching MWPM as an independent
cross-check decoder, not rep3_qec_kernel.cpp's LUT)."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA = REPO_ROOT / "experiments" / "E05b_repetition_circuit_level" / "processed" / "circuit_level_processed.json"
OUT = REPO_ROOT / "figures" / "out" / "fig_rep3_circuit_level.pdf"


def main():
    rows = json.loads(DATA.read_text())
    rounds_values = sorted(set(r["rounds"] for r in rows))

    fig, ax = plt.subplots(figsize=(5.5, 4.2))
    for rounds in rounds_values:
        pts = sorted([r for r in rows if r["rounds"] == rounds], key=lambda r: r["p"])
        p = np.array([r["p"] for r in pts])
        p_l = np.array([r["p_L"] for r in pts])
        lo = np.array([r["wilson_lo"] for r in pts])
        hi = np.array([r["wilson_hi"] for r in pts])
        ax.plot(p, p_l, "o-", label=f"{rounds} round{'s' if rounds != 1 else ''}", markersize=4)
        ax.fill_between(p, lo, hi, alpha=0.15)

    ax.plot([1e-3, 0.5], [1e-3, 0.5], "k:", lw=1, label="breakeven ($p_L=p$)")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("physical error rate $p$ (per-gate depolarising)")
    ax.set_ylabel("logical error rate $p_L$")
    ax.set_title("Rep-3 [[3,1,2]], circuit-level noise, Stim + PyMatching MWPM\n"
                  "$10^6$ shots/point, software-only (not this project's own decoder)", fontsize=8)
    ax.legend(fontsize=7)
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
