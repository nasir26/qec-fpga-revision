# rtl/shor913

Kernel source in `src/`, link and connectivity configuration in `cfg/`.

## Record the exact build invocation here
```
v++ -c -t hw --platform <xpfm> -k <kernel> -o <kernel>.xo src/<kernel>.cpp
v++ -l -t hw --platform <xpfm> --config cfg/<kernel>_link.cfg -o <kernel>.xclbin <kernel>.xo
```

## Reports to copy into evidence/synthesis/ after every build
- `*_csynth.rpt` (HLS estimate)
- Vivado utilization report (post-route actual)
- Vivado timing summary (achieved slack, achieved clock)
- `*.link_summary`, `*.compile_summary`

## Status

`src/shor_qec_kernel.cpp` is the original kernel with one change: a one-element `m_axi`
output-buffer argument (`result_out`) added alongside the existing `ap_return` register, per the
manuscript's own Section 11 recommendation and to unblock docs/BLOCKERS.md B-001 (the BAR4
`PermissionError` / zero-length-buffer failure in `evidence/runs/selftest.log`). See the header
comment in the file for the full rationale.

**HLS synthesis DONE (2026-08-19), `csynth` only, not yet placed and routed.**
`cfg/run_hls.tcl` runs it; reports are in `evidence/synthesis/shor_m_axi_fix_hls_2026-08-19/`.
Result: 3 BRAM18K, 0 DSP, 1209 FF, 1137 LUT, 2.431 ns critical path, 70-cycle/233 ns latency,
II=1. For comparison, `evidence/synthesis/shor_original_hls_2026-08-19/` reproduces the
*unmodified* original kernel and matches the manuscript's resource/timing claims exactly
(1 BRAM18K, 190 FF, 228 LUT, 2.318 ns) but gives 1-cycle latency, not the claimed 5 — see ledger
C-010. `cfg/shor_link.cfg` is unchanged and should still work for the `v++ -l` step (no
memory-bank connectivity was added; `v++` will auto-assign `result_out`'s AXI master).

Next steps: (1) HLS C-simulation against a testbench (not yet written) to confirm functional
correctness pre-synthesis, not just that it compiles, (2) `v++ -c`/`v++ -l` to produce a real
`.xo`/`.xclbin`, (3) attempt a self-test against this host's live device (docs/BLOCKERS.md B-001).
