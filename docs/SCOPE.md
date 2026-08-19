# Scope: what the artifact demonstrates versus what the manuscript claimed

**Status: finalised end of Phase 1**, from the verdict column of `CLAIMS_LEDGER.md` (86 rows,
2026-08-19). This file is the skeleton of `response/response_to_reviewers.md`.

| The manuscript claimed | The archive demonstrates |
|---|---|
| Real-time QEC for superconducting processors | A host-driven syndrome decoder kernel, with no closed loop, no feedback path, and no repeated rounds |
| 17 to 20 ns end-to-end decode latency for Shor and Steane | An HLS-estimated pipeline depth of 5 cycles for Shor, unverifiable because no `*_csynth.rpt` is in the archive. The Steane number has **no build of any kind** behind it |
| Post-synthesis (Table 2) and post-route (Table 3) resource use for all three kernels | Only the Shor kernel has any synthesis evidence in the archive (and even that is incomplete). Steane and Rep-3 were never taken through `v++` as far as `build.log`/`xcd.log` show; Table 3 in particular reports post-*route* numbers for a kernel with no traceable Vivado run at all |
| 27/27 and 21/21 hardware self-tests | A 27/27 self-test executed by the host software mirror, with the log stating the xclbin was not exercised. No Steane self-test log |
| 3e8 corrections/s per CU, 6e9 aggregate | An arithmetic product of clock and II, plus a resource-based extrapolation to 20 CUs that was never built |
| 200,000 shots per point (10^5 in the abstract, 200,000 in Section 9.6) | 10,000 shots per point, 4 of the claimed 9 grid points, `single_pauli` model only, in the only log present. No `IID-depolarising` run of any kind exists in the archive |
| Three runtime-selectable Steane decoder modes | No such kernel source in the archive; the Steane kernel present is a batched HBM LUT decoder with no mode field |
| Monolithic, AXI-Lite only, no HBM | The Steane kernel uses three m_axi gmem bundles; the C++ host uses OpenCL buffers |
| Scalable MWPM and union-find support | Small-code decision circuits specialised to the Hamming syndrome structure |
| Table 5 syndrome widths (Steane m=3, BB[72,12,6] m=72) | $m=n-k$ gives Steane m=6, BB[72,12,6] m=60. Printed values are $n$ or a half-syndrome, not $n-k$ |
| Bibliography: 19 clean references | At least 3 confirmed defects on inspection plus external verification: ref [4] author list garbled, `battistel2023real` miscited in text (entry itself is accurate), `liyanage2023scalable`/`ristE2024scalable` share a fabricated-looking duplicate title with wrong venue/authors on at least one |

## What this paper should claim instead

1. An open, reproducible HLS reference design for distance-3 stabilizer decoders on a commodity
   accelerator card, with synthesis and post-route data separated and correctly labelled.
2. A **measured** decomposition of the host-to-FPGA latency budget, showing that the decoder is
   effectively free (tens of nanoseconds, under 0.02% of fabric) and the interface is not
   (microseconds, dominated by host dispatch).
3. The **measured batching threshold**: the batch size at which amortised per-syndrome cost falls
   below the syndrome round time, and the loop-latency price paid for it.
4. A corrected scalability analysis with m = n - k applied consistently, showing precisely where
   LUT decoding stops being viable and what replaces it.

## What this paper explicitly does not claim

- Real-time closed-loop operation with a quantum processor.
- General MWPM or union-find graph decoding.
- Behaviour under leakage, correlated noise, or hardware syndrome traces.
- Anything about distance 5 or above beyond a resource projection, unless Phase 4 is executed.
