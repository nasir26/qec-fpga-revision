# paper/tables

Generated `.tex` tables only. Never hand-edit a `.tex` file here; edit the generating script or
its data file and regenerate.

## Table 5 (LUT scalability), R1-Maj-6

- `table5_scalability_data.yaml` — source data: (n, k) per code, architecture (combined vs.
  CSS-split), decoder type. This is architectural/definitional data, not an experimental
  measurement, so it lives here rather than under `experiments/*/processed/`.
- `gen_table5.py` — computes `m = n - k` (and the `m_X | m_Z` CSS decomposition for Steane),
  LUT entry counts, and a capacity-only BRAM18K estimate. Run: `python3 gen_table5.py > table5_lut_scaling.tex`.
- `table5_lut_scaling.tex` — generated output, committed so the manuscript build doesn't require
  re-running Python.

Fixes applied relative to the original submission (docs/CLAIMS_LEDGER.md section E):
Steane's syndrome width corrected from the printed m=3 (one CSS half) to the full m=6, with the
m_X=3/m_Z=3 decomposition now explicit; BB[72,12,6] corrected from m=72 (=n) to m=n-k=60; the two
surface-code rows split into explicitly labelled rotated (m=8) and unrotated (m=16) variants
instead of one ambiguous row. The qualitative conclusion (LUT decoding stops being viable past
m≈16) is unchanged by any of these fixes — only the specific cell values were wrong.

The Shor row's BRAM18K estimate (1 block) computed here independently matches Table 2's original
claim of 1 BRAM18K for the Shor kernel, which is a small but real cross-check that the underlying
LUT-size arithmetic is sound.

## Table 2 (post-synthesis resource utilisation), R1-Min-5

**Regenerated, 2026-08-19,** from real `evidence/synthesis/*/*.rpt` data (`vitis_hls
csynth_design`, not estimated or hand-written):
- `table2_resources_data.yaml` — transcribed from five real HLS runs (Rep-3 original; Shor
  original and with the m_axi fix; reconstructed Steane with and without the m_axi fix).
- `gen_table2.py` — emits the table, including an honest total row (AXI-Lite-only configuration
  only, matching what the manuscript claims all three kernels use) and utilisation percentages
  computed against the real U55C device totals.
- `table2_resources.tex` — generated output.

This table now shows the m_axi fix's cost directly (Shor and Steane each roughly 5-8x their
AXI-Lite-only FF/LUT count once the output-buffer argument is added), which is the same finding
as ledger C-142-HLS, just presented as a table instead of prose. The AXI-Lite-only total across
all three kernels is 1 BRAM18K, 630 FF, 1294 LUT — 0.025%/0.024%/0.099% of the device respectively.
Still smaller than 0.1% of the fabric either way, so the manuscript's qualitative "negligible"
conclusion survives; the specific "<0.02%" figure does not (0.099% LUT utilisation is roughly 5x
that).

**Not yet regeneratable:** post-route (Table 3) numbers — Vivado implementation has not been run
for any kernel yet (docs/BLOCKERS.md B-002/B-005).
