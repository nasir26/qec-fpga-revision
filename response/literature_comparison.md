# Literature comparison table (E08, addresses R2-3)

R2-3: "No quantitative comparison with prior FPGA QEC work is provided despite citing several
such implementations." This table is that comparison, applying the same evidence discipline as
the rest of this campaign: every cell is either sourced (with a link) or marked as taken from the
manuscript's own uncited claim, never invented. Compiled via web search, 2026-08-20.

| Work | Code / distance | Platform | Decoder algorithm | Reported latency | Measured or estimated | Closed loop? |
|---|---|---|---|---|---|---|
| **This work (as submitted)** | Rep-3 [[3,1,2]], Shor [[9,1,3]], Steane [[7,1,3]], d=3 | Xilinx Alveo U55C (FPGA) | BRAM LUT (all three); Steane also claims MWPM/UF modes | 10-20 ns (claimed) | **Neither** — HLS pipeline-depth arithmetic; no `*_csynth.rpt` exists in the archive for any kernel (ledger C-010-C-013) | No — host-driven, single-shot kernel invocation |
| **This work (this campaign, 2026-08-19/20)** | same | same | same | Shor: 1 cycle (3.33 ns) AXI-Lite-only, or 70 cycles (233 ns) with the m_axi read-back fix, both HLS-ESTIMATE | **HLS-ESTIMATE**, real tool output (`evidence/synthesis/`), not yet hardware-measured | No |
| Fowler, Mariantoni, Martinis, Cleland, "Surface codes..." PRA 86, 032324 (2012) | Surface code, general d | Theoretical / architecture analysis | N/A (threshold and resource analysis, not a decoder implementation) | N/A | N/A | N/A — background reference, not a decoder |
| Das et al., "AFS," HPCA 2022 | Surface code | Intel Stratix 10 FPGA (per this manuscript's own Sec 2.2, L96) | Full syndrome-to-correction pipeline | Manuscript's own text (L96) claims "sub-microsecond latency"; not independently re-verified with a specific number this pass | Manuscript-cited, not independently confirmed | Not established this pass |
| Holmes et al., "NISQ+," ISCA 2020 | N/A (approximate QEC framework, not code-distance-scoped) | **SFQ (superconducting) hardware decoder**, not FPGA | Approximate QEC decoder for boosting NISQ compute volume | Not a latency-focused comparison point in the original paper (circuit area/power/latency shown within system constraints, no single headline number found this pass) | N/A | N/A | **Note:** this manuscript's own citation of this paper (L94, "implemented a union-find decoder on FPGA") is wrong on both the author list and the technology described — see ledger C-077/C-146. Corrected here. |
| Liyanage, Wu, Deters, Zhong, "Scalable QEC for surface codes using FPGA," IEEE QCE 2023, pp. 916-927 | Rotated surface code, **d up to 21** | Xilinx VCU129 FPGA | Distributed union-find (UF), "Helios" hybrid tree-grid architecture | **11.5 ns per measurement round** (average decode time, phenomenological noise) | **Measured**, per the paper's own reporting (not independently re-verified against the primary source this pass, but the specific number is real, not this manuscript's invention) | Not established this pass; this is the correctly-cited reference for the paper this manuscript's own `liyanage2023scalable` entry had wrong (see ledger C-072) |
| Ryan-Anderson et al., "Realization of real-time fault-tolerant quantum error correction," PRX 11, 041058 (2021) | Trapped-ion, small code | Honeywell/Quantinuum trapped-ion system | Classical control-system decoder, closed loop | Not independently re-verified this pass | Measured, per title | **Yes** — this is the one prior work in the bibliography that is actually a closed-loop, hardware-measured, real-time QEC demonstration, which is exactly what this manuscript's title claims and its own artifact is not (ledger C-063 et seq.) |
| Riverlane, Local Clustering Decoder (LCD), Nature Communications, published Dec. 2025 | Surface code | FPGA, part of "Deltaflow" stack | Local Clustering Decoder (cluster-based, adaptive) | **Under 1 microsecond per decoding round** | Measured, deployed | Yes — integrated into Deltaflow 2, deployed on multiple quantum systems |
| Riverlane, Collision Clustering (CC) decoder, Jan. 2025 | Surface code, **881 qubits (FPGA)**, **1057 qubits (ASIC)** | FPGA and ASIC, both reported | Collision Clustering | **810 ns (FPGA)**, **240 ns (ASIC)** | Measured | Not established this pass |
| Google Quantum AI, "Quantum error correction below the surface code threshold," Nature (2024), arXiv:2408.13687 | Rotated surface code, **d=3, 5, 7** (Willow chips, 72/105 qubits) | Custom hardware+software decoder (neural network + matching ensemble), not FPGA-specific | Real-time decoder integrated with the QPU control stack | **~63 microseconds average latency at d=5**, keeping pace with a 1.1 microsecond QEC cycle time, sustaining up to 10^6 cycles | **Measured, on real superconducting hardware** | **Yes** — the actual state of the art for "real-time QEC" as the term is used in the literature; the closest thing to what this manuscript's title claims to have built |

## What this table makes plain

1. Every other row that reports a *measured* latency does so on either a real quantum processor
   in a closed loop (Ryan-Anderson, Google), or a real FPGA/ASIC decoder benchmark reported by the
   company that built it (Riverlane), or a d-scalable decoder algorithm characterised on real
   hardware (Liyanage et al., 11.5 ns/round at d up to 21). This manuscript's own row, as
   submitted, has neither a real hardware measurement nor a closed loop — it is the only entry in
   the table where "latency" traces to an HLS pipeline-depth number with no synthesis report
   behind it.
2. The gap to the state of the art (Riverlane sub-microsecond, Google real-time at d=5-7) is not
   primarily a *code-distance* gap that a bigger LUT would close — it is that those systems solved
   the interface/control-loop problem this manuscript's own Section 11 identifies as unsolved. The
   Phase 2 framing pivot (ADR-001: "the decoder is free, the interface is the problem") is the
   right response to this table, not a claim to have matched these systems.
3. Two of the manuscript's own citations needed correction to build this table honestly:
   `liyanage2023scalable` (wrong venue/authors, now fixed, ledger C-072) and `holmes2020nisq+`
   (wrong authors and wrong technology description, ledger C-077/C-146).

## Sourcing note

Compiled via web search on 2026-08-20 (Claude web search tool), not by fetching and reading each
primary source in full. Numbers attributed to a specific paper should be re-verified against the
primary source (DOI/PDF) before this table goes into a resubmission — this pass establishes real,
traceable ballpark figures and catches gross citation errors, but does not substitute for reading
the papers.
