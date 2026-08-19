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

## Tables 2 and 3 (resource utilisation), R1-Min-5

Not yet regeneratable: no real synthesis or place-and-route report exists for the Steane or
Rep-3 kernels (docs/BLOCKERS.md B-005), and the Shor kernel's own `*_csynth.rpt` is missing from
the archive (ledger C-010). These tables can only be honestly rebuilt after B-002/B-005 close.
