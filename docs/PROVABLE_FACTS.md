# What the artifact provably does

One page, based only on files physically present in the two submitted archives plus what this
working host can independently confirm. Derived from `CLAIMS_LEDGER.md` (86 rows). No number
below is estimated or reconstructed; each has a citable file.

## What is actually demonstrated

1. **A Shor [[9,1,3]] AXI-Lite HLS kernel was synthesised and linked into a working xclbin.**
   `shor_qec_kernel.xo`, `shor_qec_kernel.xclbin`, `build.log`, and `xcd.log` all exist and are
   mutually consistent. The xclbin's own metadata (`shor_qec_kernel.xclbin.info`) shows the
   300 MHz kernel clock domain achieved its requested frequency. This is real synthesis and
   place-and-route evidence, for one kernel.
2. **A bit-exact software mirror of the Shor decoder exists and passes all 27 single-qubit Pauli
   tests.** `selftest.log` shows 27/27 PASS with correct syndromes and corrections. This is a
   genuine, verifiable correctness result for the *software* model of the decoder logic.
3. **The xclbin was loaded onto real hardware, but its output register was never successfully
   read.** `selftest.log` documents two independent hardware read-back attempts failing (an XRT
   buffer path with a range error, and a BAR4 mmap blocked by a permission error on all four
   device BDFs), followed by an automatic fallback to the software mirror for every reported
   result. No bit ever crossed from the FPGA fabric back to the host in the evidence provided.
4. **A single-threaded Python software decoder runs at ≈192,000 corrections/s.** Measured
   directly (`selftest.log`, 52 ms / 10,000 shots). This is a real number; it is a weak baseline
   (single core, single shot per call, interpreted language), not a hardware result.
5. **A batched, HBM-backed Steane LUT kernel and an OpenCL C++ host to drive it both exist as
   source code** (`steane_decoder_kernel.cpp`, `host_decoder.cpp`), architecturally unrelated to
   the AXI-Lite monolithic three-mode kernel the manuscript describes, and with no build artifact
   (no `.xo`/`.xclbin`) proving it was ever compiled.

## What is asserted in the manuscript but has no artifact in the archive

- Steane and Rep-3 kernel synthesis, resource utilisation, and post-route reports (Tables 2, 3):
  no build of either kernel exists anywhere in either archive.
- The Steane self-test (21/21 × 3 modes): no log, no kernel with three modes, at all.
- Any hardware wall-clock latency measurement, for any kernel (the 17-20 ns figures are HLS
  pipeline-depth arithmetic, and even the underlying HLS synthesis report is missing).
- Any Monte Carlo run at 200,000 shots/point, at $10^5$ shots/point, over the claimed 9-point
  error-rate grid, or under the IID-depolarising noise model. The only Monte Carlo run in the
  archive is 10,000 shots/point, 4 grid points, single-Pauli model only.
- The 20-compute-unit / $6\times10^9$-corrections/s figure: no multi-CU build, config, or resource
  study of any kind.
- Any statistical test supporting "LUT, MWPM, and UF curves are statistically identical."

## What this working host adds to the picture (new since the archives were captured)

A live, XRT-visible Alveo U55C is present on this machine, the current user already has the
`render`-group permission the original capture log recommends, and a matching Vitis 2023.2 +
platform install is present locally. This does not mean hardware verification is done — the
delivered xclbin's platform/shell and XRT version differ slightly from this host's, and the
underlying return-register problem is architectural, not permissions-only — but it means the
E01/E02 hardware campaign is far more tractable here than the original blockers assumed, pending
the author's authorisation to use this device. See `docs/BLOCKERS.md` B-001/B-002 for detail.

## Bottom line

The archive proves that one of three claimed kernels was built, and that its software mirror is
internally correct. It does not prove that any kernel was ever exercised on hardware, that the
other two kernels were ever synthesised, or that any of the manuscript's timing, throughput, or
Monte Carlo numbers came from a run that is traceable in what was submitted.
