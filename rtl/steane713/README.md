# rtl/steane713

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

Two kernels live here, and they are architecturally different:

- `src/steane_qec_kernel.cpp`: **reconstructed**, not the original source (see the file's header
  comment and docs/BLOCKERS.md B-003). Monolithic AXI-Lite kernel with the LUT/MWPM/UF mode field
  main.tex Sections 6.3/9.1 describe, plus the m_axi output-buffer fix (matching
  `rtl/shor913/src/shor_qec_kernel.cpp`). Logic verified against a Python mirror
  (`models/mirrors/steane_mirror.py`, `models/tests/test_steane_mirror.py`, 63/63 self-test PASS).
  **HLS synthesis DONE (2026-08-19), `csynth` only, not yet placed and routed.**
  `cfg/run_hls_steane_qec_kernel.tcl` runs it; reports in
  `evidence/synthesis/steane_reconstructed_m_axi_hls_2026-08-19/`. Result: 2 BRAM18K, 0 DSP,
  1685 FF, 1832 LUT, 2.431 ns critical path, 71-cycle/236 ns latency, II=1. A stripped
  AXI-Lite-only variant (no m_axi port) was also synthesised for comparison
  (`evidence/synthesis/steane_reconstructed_axilite_only_hls_2026-08-19/`): 0 BRAM18K, 242 FF,
  699 LUT, 2.420 ns, 2-cycle/6.66 ns latency — quantifying what the output-buffer interface
  itself costs (ledger C-142-HLS). No `cfg/steane_link.cfg` exists yet for the `v++ -l` step;
  write one modelled on `rtl/shor913/cfg/shor_link.cfg` before attempting a real xclbin build.
- `src/steane_decoder_kernel.cpp`: present in the original archive. A different, batched,
  m_axi/HBM, LUT-only architecture (64 syndromes per 512-bit beat). Candidate basis for E03
  (batched throughput scan); unrelated to the single-shot three-mode kernel above. Not yet
  synthesised this pass.

Next steps: (1) write `cfg/steane_link.cfg`, (2) HLS C-simulation with a real testbench (not yet
written, only the Python mirror exists), (3) `v++ -c`/`v++ -l` for a real `.xo`/`.xclbin`.
