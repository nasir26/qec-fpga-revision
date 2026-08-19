# rtl/rep3

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

`src/rep3_qec_kernel.cpp` is the unmodified original kernel (no m_axi output-buffer fix applied
yet, unlike Shor/Steane — this kernel's own BAR4 readback status hasn't been separately tested).

**HLS synthesis DONE (2026-08-19), `csynth` only.** `cfg/run_hls.tcl` runs it; report in
`evidence/synthesis/rep3_original_hls_2026-08-19/`. Result: 0 BRAM18K, 0 DSP, 198 FF, 367 LUT,
2.053 ns critical path, **0-cycle latency** (fully combinational, II=1). This contradicts the
manuscript's Table 2 row (≈40 FF, ≈60 LUT6, <1.0 ns) by a wide margin — FF and LUT are roughly
5-6x higher and the critical path is more than double the claimed figure. See ledger C-019/C-030.

Next steps: same as Shor/Steane — add the m_axi output-buffer fix if this kernel is going to be
tested on hardware, write a C-simulation testbench, then `v++ -c`/`v++ -l`.
