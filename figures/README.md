# Figures

Sources in `src/`, generated vector PDFs in `out/`. No binaries in `src/`. No hand editing.

**Requirements** (R1-Minor-2, R2-4):
- Vector PDF only in the manuscript. No PNG.
- Minimum 8 pt effective font at final column width, verified by measuring the rendered PDF.
- No AI-generated schematics. Redraw in TikZ or draw.io with checked labels.
- Dense in-figure explanatory text moves to the caption or the body.

## Mapping

| Figure | Source script | Input data | Status |
|---|---|---|---|
| fig1 Shor structure | src/fig1_shor_structure.tex | none (schematic) | REDRAW, was flagged for text overflow |
| fig2 pipeline | src/fig2_pipeline.tex | none (schematic) | REDRAW |
| fig3 error curves | src/fig3_error_curves.py | experiments/E07b_montecarlo_software_mirror/processed/ | **DONE (2026-08-19), software-mirror data.** Real 10^7-shot Wilson-interval curves; see that experiment's NOTES.md for the headline finding (Shor's IID-depolarising rate is ~10x the manuscript's claim). Source data is `MEASURED-SW`, not `MEASURED-HW` — swap to `experiments/E07_montecarlo_1e7/processed/` once hardware data exists (docs/BLOCKERS.md B-001), and the caption/label in `fig3_error_curves.py` must be updated when that happens. |
| fig4 resources | src/fig4_resources.py | evidence/synthesis/ | REGENERATE from verified reports |
| fig5 syndrome map | src/fig5_syndrome_map.py | rtl/shor913/src (LUT) | REGENERATE |
| fig6 throughput | src/fig6_throughput.py | E03, E04, E08 | REBUILD, current version mixes measured and analytic on one axis |
| fig7 Tanner graph | src/fig7_tanner.tex | none (schematic) | REDRAW |
| NEW latency histogram | src/fig8_latency_hist.py | E02 | TODO |
| NEW latency budget | src/fig9_latency_budget.py | E02 | TODO |
| NEW batch crossover | src/fig10_batch_crossover.py | E03 | TODO |
| NEW multi-CU scaling | src/fig11_cu_scaling.py | E04 | TODO |
| NEW d=5 vs PyMatching | src/fig12_d5_pymatching.py | E06 | TODO if Phase 4 runs |
