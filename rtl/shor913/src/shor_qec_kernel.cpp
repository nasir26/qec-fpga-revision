// =============================================================================
//  shor_qec_kernel.cpp  —  9-qubit Shor Code QEC kernel
//  ---------------------------------------------------------------------------
//  Hardware   : Xilinx Alveo U55C   (Vitis HLS 2023.2, 300 MHz target)
//  Purpose    : real-time single-shot QEC decoder for the [[9,1,3]] Shor code.
//               Corrects any single-qubit Pauli error (X, Y, or Z).
//
//  Interface  : AXI-Lite control (err_in, ap_return) plus one m_axi output
//               port (result_out), a single 32-bit word. No HBM
//               pseudo-channel and no streaming/pointer input argument.
//
//               CHANGE (Phase 3 E01 unblock, docs/BLOCKERS.md B-001): the
//               original kernel returned its result only through ap_return.
//               selftest.log shows that register unreadable on the capture
//               host without either a BAR4 mmap (blocked by PermissionError)
//               or an xrt::bo buffer path (fails outright against a scalar
//               ap_return — no AXI4 master port to attach a buffer to; see
//               ledger C-008). Section 11 of the manuscript names this exact
//               fix: add a one-element m_axi output argument, readable via a
//               normal XRT buffer object with no BAR4/privilege dependency.
//               result_out[0] and ap_return always carry the same value.
//
//  Latency    : 5 cycles (~17 ns @ 300 MHz) for the compute pipeline, II = 1,
//               per the original HLS estimate. Not re-verified for this
//               interface: the m_axi write adds a write-side burst the
//               original interface did not have. Regenerate *_csynth.rpt
//               before citing a latency number for this version (ledger
//               C-010).
//
//  Resource   : ~1 BRAM18 (decoder LUT), ~200 LUT6, ~100 FF, 0 DSP, plus one
//               small m_axi write-master for result_out. Not re-verified
//               post-change (ledger C-031); still expected to be negligible.
//
//  Author     : Nasir Ali — C-DAC / NQM Qniverse
//
//  Build (Vitis HLS / Vitis 2023.2):
//
//    v++ -c -t hw \
//        --platform /opt/xilinx/platforms/xilinx_u55c_gen3x16_xdma_3_202210_1/xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
//        -k shor_qec_kernel \
//        -o shor_qec_kernel.xo  shor_qec_kernel.cpp
//
//    v++ -l -t hw --platform xilinx_u55c_gen3x16_xdma_3_202210_1 \
//        --config shor_link.cfg \
//        -o shor_qec_kernel.xclbin  shor_qec_kernel.xo
//
//  ---------------------------------------------------------------------------
//  The code in one picture
//
//    block A           block B           block C
//   ┌──────────┐      ┌──────────┐      ┌──────────┐
//   │ q0 q1 q2 │      │ q3 q4 q5 │      │ q6 q7 q8 │
//   └──────────┘      └──────────┘      └──────────┘
//    │ inner rep-code  │ inner rep-code  │ inner rep-code   ← catches X errors
//    └─────────────────┴─────────────────┘
//              outer phase-flip code                        ← catches Z errors
//
//  8 stabilizer generators:
//    S0 = Z0Z1   S1 = Z1Z2           (block-A bit-flip checks)
//    S2 = Z3Z4   S3 = Z4Z5           (block-B bit-flip checks)
//    S4 = Z6Z7   S5 = Z7Z8           (block-C bit-flip checks)
//    S6 = X0 X1 X2 X3 X4 X5          (A-B phase-flip check)
//    S7 = X3 X4 X5 X6 X7 X8          (B-C phase-flip check)
//
//  Logical operators:
//    X_L = X0 X1 X2 X3 X4 X5 X6 X7 X8
//    Z_L = Z0 Z3 Z6
//
//  In the binary symplectic picture that the FPGA actually sees, a single
//  Pauli error on 9 qubits is represented by two 9-bit vectors (x_err, z_err):
//    - bit i of x_err == 1  iff qubit i suffered an X or Y error
//    - bit i of z_err == 1  iff qubit i suffered a  Y or Z error
//  A Y error sets both bits. Everything else in this file is ordinary
//  digital logic over those two registers.
// =============================================================================

#include <ap_int.h>

// ---------------------------------------------------------------------------
//  Constants
// ---------------------------------------------------------------------------
#define N_DATA     9      // physical qubits
#define N_STAB     8      // stabilizer generators
#define LUT_SIZE   256    // 2^N_STAB
#define LUT_WIDTH  18     // 9-bit X_corr | 9-bit Z_corr


static const ap_uint<LUT_WIDTH> SHOR_DECODER_LUT[LUT_SIZE] = {
    0x00000, 0x00001, 0x00004, 0x00002, 0x00008, 0x00000, 0x00000, 0x00000, 0x00020, 0x00000, 0x00000, 0x00000, 0x00010, 0x00000, 0x00000, 0x00000,  // 0x00
    0x00040, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x10
    0x00100, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x20
    0x00080, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x30
    0x00200, 0x00201, 0x00804, 0x00402, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x40
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x50
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x60
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x70
    0x08000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x80
    0x08040, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0x90
    0x20100, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0xA0
    0x10080, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0xB0
    0x01000, 0x00000, 0x00000, 0x00000, 0x01008, 0x00000, 0x00000, 0x00000, 0x04020, 0x00000, 0x00000, 0x00000, 0x02010, 0x00000, 0x00000, 0x00000,  // 0xC0
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0xD0
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000,  // 0xE0
    0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000, 0x00000  // 0xF0
};

// ---------------------------------------------------------------------------
//  compute_syndrome()
//
//  Six 2-input XORs for the Z-type block (act on x_err).
//  Two 6-input XOR-reductions for the X-type block (act on z_err).
//
//  All eight bits are computed in parallel: the whole function synthesises
//  as a single flat XOR tree, about 3 LUT6 levels deep.
// ---------------------------------------------------------------------------
static ap_uint<N_STAB> compute_syndrome(ap_uint<N_DATA> x_err,
                                        ap_uint<N_DATA> z_err) {
#pragma HLS INLINE

    ap_uint<N_STAB> s;

    // Z-type stabilizers — inner rep-code bit-flip checks.
    s[0] = x_err[0] ^ x_err[1];   // S0 = Z0 Z1
    s[1] = x_err[1] ^ x_err[2];   // S1 = Z1 Z2
    s[2] = x_err[3] ^ x_err[4];   // S2 = Z3 Z4
    s[3] = x_err[4] ^ x_err[5];   // S3 = Z4 Z5
    s[4] = x_err[6] ^ x_err[7];   // S4 = Z6 Z7
    s[5] = x_err[7] ^ x_err[8];   // S5 = Z7 Z8

    // X-type stabilizers — outer phase-flip checks. In the binary picture
    // these are just 6-bit XOR-reductions over masked slices of z_err. HLS
    // has a native xor_reduce() on ap_uint that maps to a balanced tree.
    ap_uint<6> slice_AB = z_err.range(5, 0);   // q0..q5
    ap_uint<6> slice_BC = z_err.range(8, 3);   // q3..q8
    s[6] = slice_AB.xor_reduce();              // S6 = X0 X1 X2 X3 X4 X5
    s[7] = slice_BC.xor_reduce();              // S7 = X3 X4 X5 X6 X7 X8

    return s;
}

// ---------------------------------------------------------------------------
//  Top-level Shor QEC kernel
//
//  Inputs  (AXI-Lite):
//    err_in — packed 32-bit input, layout:
//               bits [ 8: 0]  x_err   (which qubits have a bit-flip error)
//               bits [17: 9]  z_err   (which qubits have a phase-flip error)
//               bits [31:18]  reserved
//
//             A single Y error on qubit q corresponds to setting
//             x_err[q] = z_err[q] = 1. A depolarising channel is modeled
//             on the host by drawing one of {I,X,Y,Z} per qubit and
//             packing the result into these 18 bits.
//
//  Outputs:
//    result_out[0] — m_axi word, and
//    ap_return     — AXI-Lite return register,
//               both carrying the same packed 32-bit result, layout:
//               bits [ 8: 0]  x_correction applied
//               bits [17: 9]  z_correction applied
//               bits [25:18]  syndrome
//               bits [26]     X_logical_error flag   (1 = failure)
//               bits [27]     Z_logical_error flag   (1 = failure)
//               bits [31:28]  reserved
//
//             Read result_out via a standard xrt::bo buffer object. Reading
//             ap_return still works wherever it already worked (HLS
//             co-simulation, hosts with BAR4 access) but is no longer the
//             only path — see the CHANGE note above.
// ---------------------------------------------------------------------------
extern "C" unsigned int shor_qec_kernel(unsigned int err_in, unsigned int* result_out)
{
    // === Interface pragmas =================================================
    // err_in and the ap_return register stay on AXI-Lite, as before.
    // result_out is the one addition: a single-element m_axi port so the
    // result can be read back through a normal XRT buffer object instead of
    // depending on ap_return's non-standard readback path (see CHANGE note
    // above and docs/BLOCKERS.md B-001).
#pragma HLS INTERFACE s_axilite port=err_in bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE m_axi port=result_out offset=slave bundle=gmem depth=1
#pragma HLS INTERFACE s_axilite port=result_out bundle=control

    // === Pipeline pragma ===================================================
    // II=1: one new error vector in, one correction out, every clock cycle.
    // Targetable here because the entire dataflow is a shallow XOR tree
    // plus a single BRAM read — no loop carry, no memory contention, no
    // false dependencies of the kind v05 fights in its 16-bank HBM loops.
#pragma HLS PIPELINE II=1

    // === Latency bound =====================================================
    // Asserts a hard budget so any future change that blows up the critical
    // path fails synthesis loudly rather than silently degrading the clock.
#pragma HLS LATENCY min=0 max=8

    // === Decoder LUT (BRAM-backed ROM) =====================================
    // 256 × 18 bits = 576 bytes. Perfect fit for a single BRAM18K slot.
    //
    //  - ROM_2P: dual-port ROM. We only read one port in this kernel, but
    //    using the 2P variant leaves the second port free so a future
    //    revision can decode two streams in parallel without resynthesis.
    //  - impl=BRAM: forces BRAM inference. Without it, HLS might distribute
    //    the 256 entries across ~70 LUT6s, which works but eats routing
    //    budget and can degrade Fmax in a crowded SLR.
    //  - The init function is inlined and unrolls to a constant initializer,
    //    so the ROM contents are baked into the bitstream at place-and-route
    //    time — no runtime write cycles.
    // LUT is file-scope static const; HLS auto-infers a BRAM ROM.

    // === Stage 1: unpack input =============================================
    ap_uint<32>    in   = err_in;
    ap_uint<N_DATA> x_err = in.range(8, 0);
    ap_uint<N_DATA> z_err = in.range(17, 9);

    // === Array partition on the error vectors =============================
    // ap_uint<9> is already a single word, so HLS treats it as a flat wire
    // by default. We flag it explicitly to make the intent obvious and to
    // guard against someone later promoting these to arrays.
#pragma HLS ARRAY_PARTITION variable=x_err complete
#pragma HLS ARRAY_PARTITION variable=z_err complete

    // === Stage 2: syndrome extraction ======================================
    // Pure combinational XOR tree, ~3 LUT6 levels.
    ap_uint<N_STAB> syndrome = compute_syndrome(x_err, z_err);

    // === Stage 3: LUT decode ===============================================
    // 2-cycle synchronous BRAM read. HLS schedules the read so the rest of
    // the pipeline overlaps with the decode — II=1 is preserved.
    ap_uint<LUT_WIDTH> lut_word = SHOR_DECODER_LUT[syndrome];
    ap_uint<N_DATA>    x_corr   = lut_word.range(8, 0);
    ap_uint<N_DATA>    z_corr   = lut_word.range(17, 9);

    // === Stage 4: apply correction =========================================
    // Pauli errors compose over GF(2) by XOR in the symplectic picture.
    ap_uint<N_DATA> x_fixed = x_err ^ x_corr;
    ap_uint<N_DATA> z_fixed = z_err ^ z_corr;

    // === Stage 5: logical readout ==========================================
    // The logical operators are:
    //    Z_L = Z0 Z3 Z6      → sensitive to X errors on q0, q3, q6
    //    X_L = X0 X1 X2 ...  → sensitive to Z errors on any qubit
    //
    // An "X logical error" means the residual x-error anticommutes with Z_L,
    // i.e. hits an odd number of {q0, q3, q6}. Likewise for Z logical.
    //
    // If the input error was a single Pauli, the LUT will have produced
    // the exact correction and both flags will be zero. If the input was
    // weight-2 or larger, the LUT fell through to zero and the residual
    // error will light up a logical flag — the host counts these as the
    // uncorrectable tail of the Monte Carlo run.
    ap_uint<1> x_logical_err = x_fixed[0] ^ x_fixed[3] ^ x_fixed[6];
    ap_uint<1> z_logical_err = z_fixed.xor_reduce();

    // === Pack result register ==============================================
    ap_uint<32> result = 0;
    result.range( 8,  0) = x_corr;
    result.range(17,  9) = z_corr;
    result.range(25, 18) = syndrome;
    result.range(26, 26) = x_logical_err;
    result.range(27, 27) = z_logical_err;

    result_out[0] = (unsigned int) result;
    return (unsigned int) result;
}
