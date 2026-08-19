# evidence/synthesis

Append-only. Real tool output only, never hand-edited or reconstructed.

## 2026-08-19: first real HLS synthesis runs of this campaign

Tool: Vitis HLS 2023.2, part `xcu55c-fsvh2892-2L-e`, target clock 3.33 ns (300 MHz), on this
working host (`xbutil examine` confirms a live Alveo U55C present; these HLS runs themselves do
not touch the device, only the tool's static timing/resource estimator).

- `shor_original_hls_2026-08-19/` — the **unmodified** `docs/legacy/implementation/shor_qec_kernel.cpp`,
  resynthesised as-is. This is the report that never existed anywhere in either submitted archive
  (ledger C-010). Result: critical path 2.318 ns and resources (1 BRAM18K, 0 DSP, 190 FF, 228 LUT)
  match the manuscript's Table 2 row for Shor **exactly**. Latency is reported as **1 cycle**
  (3.33 ns), not the manuscript's claimed 5 cycles (17 ns) — same kernel, same tool, same part,
  same clock target. See ledger C-010/C-012/C-017/C-031.
- `shor_m_axi_fix_hls_2026-08-19/` — `rtl/shor913/src/shor_qec_kernel.cpp`, i.e. the original
  kernel plus the one-element `m_axi` output-buffer argument that unblocks B-001. Result:
  3 BRAM18K, 0 DSP, 1209 FF, 1137 LUT, 70-cycle latency (233 ns), II=1, 2.431 ns critical path.
- `steane_reconstructed_m_axi_hls_2026-08-19/` — `rtl/steane713/src/steane_qec_kernel.cpp`, the
  from-scratch reconstruction (B-003) with the same output-buffer convention. Result: 2 BRAM18K,
  0 DSP, 1685 FF, 1832 LUT, 71-cycle latency (236 ns), II=1, 2.431 ns critical path.
- `steane_reconstructed_axilite_only_hls_2026-08-19/` — the same reconstructed Steane kernel with
  the `m_axi` port stripped back out (`steane_axilite_only_variant_source.cpp`, kept alongside the
  report for reproducibility), to isolate the interface's own cost. Result: 0 BRAM18K, 0 DSP,
  242 FF, 699 LUT, 2-cycle latency (6.66 ns), II=1, 2.420 ns critical path.

**The headline finding from this batch:** comparing the m_axi and AXI-Lite-only variants of the
same logic in both kernels isolates what the BAR4-workaround interface actually costs. For Shor:
+2 BRAM18K, +1019 FF, +909 LUT, latency 1 → 70 cycles. For Steane: +2 BRAM18K, +1443 FF,
+1133 LUT, latency 2 → 71 cycles. The fix the manuscript's own Section 11 recommends for the
BAR4 permission problem is not free — it costs roughly 35-70x pipeline depth. This is real,
reproducible HLS-ESTIMATE data (not post-route, not hardware-measured) directly supporting the
"the decoder is free, the interface is not" framing pivot in `docs/DECISIONS.md` ADR-001. See
ledger row C-142-HLS.

**What this batch does NOT show:** post-route utilisation or timing (Vivado implementation has
not been run for any of these variants), and no hardware measurement of any kind. The read-side
cost of the m_axi port (what a host actually experiences when reading `result_out` back) has not
been measured either — this data is write-side pipeline depth from the HLS estimator only.

Regenerate the two committed-source variants with:
```
vitis_hls -f rtl/shor913/cfg/run_hls.tcl
vitis_hls -f rtl/steane713/cfg/run_hls_steane_qec_kernel.tcl
```
Both verified reproducible (rerun during this same session, same Fmax/latency/resources both
times). The `shor_original_hls_2026-08-19/` and `steane_reconstructed_axilite_only_hls_2026-08-19/`
variants are one-off comparisons (unmodified legacy source, and a temporarily stripped-down copy
respectively) and do not have a committed `.tcl`/source pair yet; the AXI-Lite-only Steane source
used is archived alongside its report as `steane_axilite_only_variant_source.cpp` for reference.
