// =============================================================================
//  rep3_qec_kernel.cpp  —  3-bit Repetition Code QEC (warm-up)
//  ---------------------------------------------------------------------------
//  Hardware   : Xilinx Alveo U55C   (Vitis HLS 2023.2, 300 MHz)
//  Purpose    : pedagogical warm-up before the full 9-qubit Shor kernel.
//               Classical 3-bit repetition code with XOR error injection,
//               2-bit syndrome, 4-entry LUT decoder, single-cycle correct.
//
//  Interface  : AXI-Lite only. No HBM. No gate buffer. Tiny.
//
//  Author     : Nasir Ali — C-DAC / NQM Qniverse
//
//  Build (matches v05 style):
//    v++ -c -t hw \
//        --platform .../xilinx_u55c_gen3x16_xdma_3_202210_1.xpfm \
//        -k rep3_qec_kernel \
//        -o rep3_qec_kernel.xo  rep3_qec_kernel.cpp
//
//    v++ -l -t hw --platform xilinx_u55c_gen3x16_xdma_3_202210_1 \
//        --config rep3_link.cfg \
//        -o rep3_qec_kernel.xclbin  rep3_qec_kernel.xo
//
//  ---------------------------------------------------------------------------
//  Pipeline (1 cycle, II=1, latency 3 cycles):
//
//      codeword_in ──┐
//                    ├── XOR ──▶ received ──┬── s0 = r[0]^r[1] ─┐
//      error_mask ───┘                      │                   ├── LUT ──▶
//                                           └── s1 = r[1]^r[2] ─┘         │
//                                                                         │
//                     corrected = received ^ correction  ◀─────────────────┘
//
//  The whole kernel is fully combinational: every stage registers at the
//  boundary of the PIPELINE region so HLS can achieve II=1.
// =============================================================================

#include <ap_int.h>

// ---------------------------------------------------------------------------
//  build_rep3_lut() — populates the 4-entry decoder LUT.
//
//  Address = 2-bit syndrome (s1, s0).  Data = 3-bit correction mask.
//
//    syndrome  s1 s0   meaning              correction (one-hot)
//       0x0     0  0   no error             0b000
//       0x1     0  1   q0 flipped           0b001  (s0 fires, s1 does not)
//       0x2     1  0   q2 flipped           0b100  (s1 fires, s0 does not)
//       0x3     1  1   q1 flipped           0b010  (both fire)
//
//  This is the *minimum-weight decoder* for distance-3 — it chooses the
//  single-qubit correction that matches the syndrome exactly. For d=3 this
//  is provably optimal for any single-bit error, which is the whole promise
//  of a distance-3 code.
// ---------------------------------------------------------------------------
static const ap_uint<3> REP3_DECODER_LUT[4] = {0b000, 0b001, 0b100, 0b010};

// ---------------------------------------------------------------------------
//  Top-level kernel
//
//  Inputs  (all AXI-Lite):
//    codeword_in  — 3 physical bits of the logical-bit encoding (0/1 each)
//    error_mask   — 3-bit XOR mask simulating the channel
//    logical_in   — the original 1-bit value that was encoded; used only for
//                   the verification bit in the result word
//
//  Output (AXI-Lite return):
//    result[31:0] packed as follows
//      [ 2: 0]  corrected codeword (should be 000 or 111)
//      [ 5: 3]  correction applied
//      [ 7: 6]  syndrome (s1, s0)
//      [ 8]     corrected_logical (majority vote of corrected bits)
//      [ 9]     error_detected   (syndrome != 0)
//      [10]     recovery_success (corrected_logical == logical_in)
//      [31:11]  reserved (0)
// ---------------------------------------------------------------------------
extern "C" unsigned int rep3_qec_kernel(
        unsigned int codeword_in,   // only low 3 bits used
        unsigned int error_mask,    // only low 3 bits used
        unsigned int logical_in)    // only low 1 bit used
{
    // === Interface pragmas =================================================
    // Every scalar sits on the single AXI-Lite slave; `return` is what XRT
    // uses as the control+status register (ap_done, ap_start, return value).
    // Same pattern your v05 kernel uses for control; we just have fewer ports.
#pragma HLS INTERFACE s_axilite port=codeword_in bundle=control
#pragma HLS INTERFACE s_axilite port=error_mask  bundle=control
#pragma HLS INTERFACE s_axilite port=logical_in  bundle=control
#pragma HLS INTERFACE s_axilite port=return      bundle=control

    // === Pipeline pragma ===================================================
    // II=1 means "accept a new (codeword, mask, logical) every clock". For
    // this kernel the critical path is 3 shallow XOR levels — HLS can always
    // hit II=1 at 300 MHz. Without this pragma HLS falls back to an FSM and
    // the whole thing takes ~8 cycles per invocation, wasting ~60% of the
    // throughput. Same reason v05 puts PIPELINE II=16 on its bank loops.
#pragma HLS PIPELINE II=1

    // === Decoder LUT (inferred as tiny LUTRAM ROM) =========================
    // Only 4 entries × 3 bits = 12 bits total. Asking HLS for BRAM here would
    // waste an 18Kb block; LUTRAM/ROM synthesis fits in a pair of LUT6s.
    // For the Shor kernel we *do* want BRAM (see that file) because 256×18
    // is worth its own block.
    // LUT is file-scope static const; HLS auto-infers LUTRAM ROM.

    // === Stage 1: error injection ==========================================
    // On an FPGA a bit-flip error is literally an XOR. Quantum-mechanically
    // an X error on qubit i flips the classical bit i in the code's binary
    // vector representation — this is why the stabilizer formalism reduces
    // Pauli-X noise to linear algebra over GF(2).
    ap_uint<3> cw  = codeword_in;
    ap_uint<3> em  = error_mask;
    ap_uint<3> rcv = cw ^ em;

    // === Stage 2: syndrome extraction ======================================
    // s0 measures the Z0 Z1 stabilizer (parity of q0 and q1).
    // s1 measures the Z1 Z2 stabilizer (parity of q1 and q2).
    // The parity-check matrix H over GF(2) is:
    //        q0 q1 q2
    //   s0 [  1  1  0 ]
    //   s1 [  0  1  1 ]
    // and the syndrome is s = H · rcv mod 2.
    ap_uint<1> s0 = rcv[0] ^ rcv[1];
    ap_uint<1> s1 = rcv[1] ^ rcv[2];
    ap_uint<2> syndrome = (s1, s0);   // HLS concat: {s1, s0}

    // === Stage 3: decoder lookup ===========================================
    // For d=3 the LUT is the optimal decoder: every single-bit error has a
    // unique syndrome, and the LUT maps each syndrome to the one-hot flip.
    // Degenerate errors (weight-2 and above) are *not* in the LUT — they
    // would wrap back into "no correction" and produce a logical error,
    // which is the defining limitation of a distance-3 code.
    ap_uint<3> correction = REP3_DECODER_LUT[syndrome];

    // === Stage 4: apply correction =========================================
    ap_uint<3> corrected = rcv ^ correction;

    // === Stage 5: logical readout (majority vote) ==========================
    // The corrected codeword is supposed to be 000 or 111. Majority vote
    // recovers the logical bit. Because we only promised to correct one
    // error, 2-bit errors will produce the wrong majority and be counted
    // as a logical failure by the host.
    ap_uint<1> corrected_logical =
        (corrected[0] + corrected[1] + corrected[2]) >= 2 ? 1 : 0;

    ap_uint<1> error_detected   = (syndrome != 0) ? 1 : 0;
    ap_uint<1> recovery_success = (corrected_logical == (logical_in & 1)) ? 1 : 0;

    // === Pack result register ==============================================
    ap_uint<32> result = 0;
    result.range( 2,  0) = corrected;
    result.range( 5,  3) = correction;
    result.range( 7,  6) = syndrome;
    result.range( 8,  8) = corrected_logical;
    result.range( 9,  9) = error_detected;
    result.range(10, 10) = recovery_success;

    return (unsigned int) result;
}
