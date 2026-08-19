// =============================================================================
//  steane_qec_kernel.cpp  —  7-qubit Steane [[7,1,3]] CSS QEC kernel
//  ---------------------------------------------------------------------------
//  STATUS: RECONSTRUCTED, NOT THE ORIGINAL SOURCE.
//
//  This file does not exist in either submitted archive (docs/BLOCKERS.md
//  B-003, claims ledger C-061). The only Steane kernel present there,
//  rtl/steane713/src/steane_decoder_kernel.cpp, is a different, batched,
//  m_axi/HBM, LUT-only architecture and has no mode field, no MWPM, and no
//  UF logic. This file is a from-scratch implementation of the monolithic,
//  AXI-Lite, three-mode kernel that docs/legacy/manuscript/main.tex Sections
//  6.3 and 9.1 (L285-308, L498-509) and Algorithm 3 describe, following that
//  description as closely as the text specifies it. It has not been
//  synthesised, simulated, or run on hardware. Every number attached to it
//  belongs in the claims ledger as UNSUPPORTED until E01 exercises it.
//
//  Hardware   : Xilinx Alveo U55C   (Vitis HLS 2023.2, 300 MHz target)
//  Interface  : AXI-Lite only, matching main.tex L233 ("a single AXI-Lite
//               slave port as their only external interface").
//
//  Design source: main.tex L168-192 (code description), L285-308
//  (Algorithm 3), L498-509 (why all three modes agree for weight-1 errors).
//
//  H (CSS parity-check matrix, [7,4,3] Hamming code), main.tex L172:
//    H = [ 1 0 1 0 1 0 1 ]
//        [ 0 1 1 0 0 1 1 ]
//        [ 0 0 0 1 1 1 1 ]
//  Column q of H equals (q+1) in binary for q = 0..6 (main.tex L179: "a
//  single-qubit error on qubit q produces syndrome s = q+1").
// =============================================================================

#include <ap_int.h>

#define N_DATA   7   // physical qubits
#define N_STAB   3   // stabilizer generators per CSS half (X-type or Z-type)
#define N_PAIRS  21  // C(7,2), used by the MWPM weight-2 fallback

// H-matrix columns, indexed by qubit: H_COL[q] = q + 1 (Hamming property).
static const ap_uint<N_STAB> H_COL[N_DATA] = {1, 2, 3, 4, 5, 6, 7};

// Mode 0 LUT: syndrome s (1..7) -> one-hot correction on the matching qubit.
// s = 0 (no error) -> no correction.
static const ap_uint<N_DATA> STEANE_LUT[8] = {
    0b0000000,  // s=0: no error
    0b0000001,  // s=1: qubit 0
    0b0000010,  // s=2: qubit 1
    0b0000100,  // s=3: qubit 2
    0b0001000,  // s=4: qubit 3
    0b0010000,  // s=5: qubit 4
    0b0100000,  // s=6: qubit 5
    0b1000000,  // s=7: qubit 6
};

// All 21 (i,j) pairs, i<j, for the MWPM weight->=2 fallback (main.tex L306).
static const ap_uint<3> PAIR_I[N_PAIRS] = {0,0,0,0,0,0,1,1,1,1,1,2,2,2,2,3,3,3,4,4,5};
static const ap_uint<3> PAIR_J[N_PAIRS] = {1,2,3,4,5,6,2,3,4,5,6,3,4,5,6,4,5,6,5,6,6};

// ---------------------------------------------------------------------------
//  syndrome(): s = H . err  (mod 2), same H for X-type and Z-type (CSS).
// ---------------------------------------------------------------------------
static ap_uint<N_STAB> syndrome(ap_uint<N_DATA> err) {
#pragma HLS INLINE
    ap_uint<N_STAB> s = 0;
    for (int r = 0; r < N_STAB; r++) {
#pragma HLS UNROLL
        ap_uint<N_DATA> row_mask = 0;
        for (int q = 0; q < N_DATA; q++) {
#pragma HLS UNROLL
            row_mask[q] = H_COL[q][r];
        }
        s[r] = (err & row_mask).xor_reduce();
    }
    return s;
}

// ---------------------------------------------------------------------------
//  lut_decode(): Mode 0, main.tex L181, Algorithm 3 line "STEANE_LUT[s_z]".
// ---------------------------------------------------------------------------
static ap_uint<N_DATA> lut_decode(ap_uint<N_STAB> s) {
#pragma HLS INLINE
    return STEANE_LUT[s];
}

// ---------------------------------------------------------------------------
//  mwpm_decode(): Mode 1, main.tex L182, L306. Priority encoder over the 7
//  single-qubit candidates (weight-1, always matches for a correctable
//  error); falls through to the 21-pair enumeration for weight->=2 inputs.
//  This is a small-code specialised decision circuit exploiting the Hamming
//  bijection (main.tex L500-509), not a general MWPM graph solver.
// ---------------------------------------------------------------------------
static ap_uint<N_DATA> mwpm_decode(ap_uint<N_STAB> s) {
#pragma HLS INLINE
    ap_uint<N_DATA> corr = 0;
    bool matched = false;

    for (int q = 0; q < N_DATA; q++) {
#pragma HLS UNROLL
        if (!matched && H_COL[q] == s) {
            corr = ap_uint<N_DATA>(1) << q;
            matched = true;
        }
    }

    if (!matched) {
        for (int p = 0; p < N_PAIRS; p++) {
#pragma HLS UNROLL
            ap_uint<N_STAB> pair_synd = H_COL[PAIR_I[p]] ^ H_COL[PAIR_J[p]];
            if (!matched && pair_synd == s) {
                corr = (ap_uint<N_DATA>(1) << PAIR_I[p]) | (ap_uint<N_DATA>(1) << PAIR_J[p]);
                matched = true;
            }
        }
    }
    return corr;
}

// ---------------------------------------------------------------------------
//  uf_decode(): Mode 2, main.tex L183, L308.
//
//  main.tex L183 literally reads "qubit q counts how many of its adjacent
//  check nodes are active; if the count is odd, qubit q is included." Taken
//  literally over the WHOLE syndrome (popcount(H_COL[q] & s) odd), that rule
//  does NOT decode single-qubit errors correctly on this graph: for e.g.
//  s = H_COL[0] = 0b001, four of the seven qubits have odd-parity overlap
//  with s, not just qubit 0 (verified by models/tests/test_steane_mirror.py
//  during reconstruction, which is exactly what caught this).
//
//  main.tex L308 gives the resolution: "[UF] collapses to the same
//  XOR-reduce for one growth round on a distance-3 code with the Hamming
//  structure" -- i.e. after growing the seed cluster by one round on this
//  graph (each check has degree 4, each qubit degree <=3), the surviving
//  boundary qubit is exactly the one whose full column matches the
//  currently active check set. That is column-vs-syndrome equality, the
//  same primitive the MWPM weight-1 path uses. This function implements
//  that collapsed form, not the naive per-syndrome-bit parity count.
//  Weight->=2 syndromes matching no column are outside one growth round's
//  reach and correctly return no correction (main.tex L506: the code is at
//  its distance boundary there regardless of decoder choice).
// ---------------------------------------------------------------------------
static ap_uint<N_DATA> uf_decode(ap_uint<N_STAB> s) {
#pragma HLS INLINE
    ap_uint<N_DATA> corr = 0;
    for (int q = 0; q < N_DATA; q++) {
#pragma HLS UNROLL
        if (H_COL[q] == s) {
            corr[q] = 1;
        }
    }
    return corr;
}

// ---------------------------------------------------------------------------
//  Top-level Steane QEC kernel
//
//  Inputs (AXI-Lite):
//    err_in — packed 32-bit input, main.tex L292 layout:
//               bits [ 6: 0]  x_err
//               bits [13: 7]  z_err
//               bits [15:14]  mode  (0=LUT, 1=MWPM, 2=UF; 3 reserved)
//
//  Outputs:
//    result_out[0] (m_axi) and ap_return (AXI-Lite), same layout, following
//    the same output-buffer convention as the revised shor_qec_kernel (see
//    rtl/shor913/src/shor_qec_kernel.cpp and docs/BLOCKERS.md B-001):
//               bits [ 6: 0]  x_correction applied
//               bits [13: 7]  z_correction applied
//               bits [16:14]  s_z (X-type syndrome)
//               bits [19:17]  s_x (Z-type syndrome)
//               bits [20]     X_logical_error flag (odd overlap with {q0,q1,q2})
//               bits [21]     Z_logical_error flag (odd overlap with {q0,q1,q2})
//               bits [23:22]  mode (echoed back)
// ---------------------------------------------------------------------------
extern "C" unsigned int steane_qec_kernel(unsigned int err_in, unsigned int* result_out)
{
#pragma HLS INTERFACE s_axilite port=err_in bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control
#pragma HLS INTERFACE m_axi port=result_out offset=slave bundle=gmem depth=1
#pragma HLS INTERFACE s_axilite port=result_out bundle=control
#pragma HLS PIPELINE II=1

    ap_uint<32> in = err_in;
    ap_uint<N_DATA> x_err = in.range(6, 0);
    ap_uint<N_DATA> z_err = in.range(13, 7);
    ap_uint<2>      mode  = in.range(15, 14);

#pragma HLS ARRAY_PARTITION variable=x_err complete
#pragma HLS ARRAY_PARTITION variable=z_err complete

    // Same H for both halves (CSS property, main.tex L293).
    ap_uint<N_STAB> s_z = syndrome(x_err);   // X-type errors -> X correction
    ap_uint<N_STAB> s_x = syndrome(z_err);   // Z-type errors -> Z correction

    ap_uint<N_DATA> x_corr, z_corr;
    if (mode == 1) {
        x_corr = mwpm_decode(s_z);
        z_corr = mwpm_decode(s_x);
    } else if (mode == 2) {
        x_corr = uf_decode(s_z);
        z_corr = uf_decode(s_x);
    } else {
        x_corr = lut_decode(s_z);
        z_corr = lut_decode(s_x);
    }

    ap_uint<N_DATA> x_fixed = x_err ^ x_corr;
    ap_uint<N_DATA> z_fixed = z_err ^ z_corr;

    // X_L = X0 X1 X2, Z_L = Z0 Z1 Z2 (main.tex L186, the weight-3 logicals,
    // not the weight-4 stabilizer-equivalent operators).
    ap_uint<1> x_logical_err = (x_fixed & ap_uint<N_DATA>(0b0000111)).xor_reduce();
    ap_uint<1> z_logical_err = (z_fixed & ap_uint<N_DATA>(0b0000111)).xor_reduce();

    ap_uint<32> result = 0;
    result.range(6, 0)   = x_corr;
    result.range(13, 7)  = z_corr;
    result.range(16, 14) = s_z;
    result.range(19, 17) = s_x;
    result.range(20, 20) = x_logical_err;
    result.range(21, 21) = z_logical_err;
    result.range(23, 22) = mode;

    result_out[0] = (unsigned int) result;
    return (unsigned int) result;
}
