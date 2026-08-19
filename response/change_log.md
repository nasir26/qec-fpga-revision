# Change log

Every manuscript change, mapped to the reviewer point that motivated it. Checked at the end
against the reviewer checklist to prove no point was silently dropped.

| Date | Section / Table / Figure | Change | Reviewer point | Commit |
|---|---|---|---|---|
| 2026-08-19 | Bibliography, all 19 entries | Rebuilt `paper/bib/references.bib` from `main.tex`'s `\bibitem` list (the file previously held the Springer template's unrelated placeholder examples). Fixed ref [4] author list (Fowler, Mariantoni, Martinis, Cleland). Fixed `liyanage2023scalable`'s venue (QCE, not HPCA) and author list (dropped a non-existent 5th author). Flagged `ristE2024scalable` as unresolved/likely fabricated pending the author's real source, do not cite as-is. Renamed `battistel2023real`→`battistel2021leakage` (entry was accurate; the year in the old key and the in-text citation context were wrong) — the citing sentence at main.tex L92 still needs its own text fix in `paper/sections/` once written. | R3-4, general bib audit | 045bb54..HEAD |
| 2026-08-19 | Table 5 (LUT scalability) | Regenerated from `paper/tables/gen_table5.py` + `table5_scalability_data.yaml` with $m=n-k$ applied to every row. Steane: m corrected 3→6, with explicit $m_X{=}3\mid m_Z{=}3$ decomposition. BB[72,12,6]: m corrected 72→60. Surface code split into separate labelled rotated (m=8) / unrotated (m=16) rows instead of one ambiguous row. Qualitative "impractical past m≈16" conclusion unchanged. | R1-Maj-6 | HEAD |
