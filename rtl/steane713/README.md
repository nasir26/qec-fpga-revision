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
  (`models/mirrors/steane_mirror.py`, `models/tests/test_steane_mirror.py`, 63/63 self-test PASS)
  but **not yet synthesised, simulated in HLS, or run on hardware**. No `cfg/steane_link.cfg`
  exists yet either; write one modelled on `rtl/shor913/cfg/shor_link.cfg` before the first build.
- `src/steane_decoder_kernel.cpp`: present in the original archive. A different, batched,
  m_axi/HBM, LUT-only architecture (64 syndromes per 512-bit beat). Candidate basis for E03
  (batched throughput scan); unrelated to the single-shot three-mode kernel above.

Next steps: (1) write `cfg/steane_link.cfg`, (2) run Vitis HLS C-simulation against
`models/mirrors/steane_mirror.py` before synthesis, (3) synthesise and copy the resulting
`*_csynth.rpt` into `evidence/synthesis/` — no Steane build of any kind exists there yet
(docs/BLOCKERS.md B-005).
