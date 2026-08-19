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
comment in the file for the full rationale. **Not yet re-synthesised or re-simulated** with this
interface change — the original build's `*_csynth.rpt` doesn't exist in the archive either (ledger
C-010), so there is nothing to diff against yet. `cfg/shor_link.cfg` is unchanged and should still
work (no memory-bank connectivity was added; v++ will auto-assign `result_out`'s AXI master).

Next steps: (1) HLS C-simulation against the existing decode logic (unchanged from the original,
so should reproduce the same 27/27 self-test truth table), (2) synthesise and capture
`*_csynth.rpt` into `evidence/synthesis/` for the first time, (3) build the xclbin and attempt a
self-test against this host's live device (docs/BLOCKERS.md B-001) once authorised.
