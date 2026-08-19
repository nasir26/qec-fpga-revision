#include <ap_int.h>

extern "C" {

void steane_decoder_kernel(
    const ap_uint<512>* syndromes,
    const ap_uint<8>* decoder_lut,
    ap_uint<512>* instructions,
    int num_chunks
) {
#pragma HLS INTERFACE m_axi port=syndromes offset=slave bundle=gmem0 depth=64
#pragma HLS INTERFACE m_axi port=decoder_lut offset=slave bundle=gmem1 depth=64
#pragma HLS INTERFACE m_axi port=instructions offset=slave bundle=gmem2 depth=64

#pragma HLS INTERFACE s_axilite port=syndromes bundle=control
#pragma HLS INTERFACE s_axilite port=decoder_lut bundle=control
#pragma HLS INTERFACE s_axilite port=instructions bundle=control
#pragma HLS INTERFACE s_axilite port=num_chunks bundle=control
#pragma HLS INTERFACE s_axilite port=return bundle=control

    ap_uint<8> local_lut[64];
#pragma HLS ARRAY_PARTITION variable=local_lut complete dim=1
    
    // Cache the LUT into local FPGA BRAM/Registers for O(1) random access
    load_lut_loop:
    for (int i = 0; i < 64; ++i) {
#pragma HLS PIPELINE II=1
        local_lut[i] = decoder_lut[i];
    }

    decode_loop:
    for (int i = 0; i < num_chunks; ++i) {
#pragma HLS PIPELINE II=1
        ap_uint<512> syn_chunk = syndromes[i];
        ap_uint<512> inst_chunk = 0;

        process_chunk:
        for (int j = 0; j < 64; ++j) {
#pragma HLS UNROLL
            ap_uint<8> syn_byte = syn_chunk(j * 8 + 7, j * 8);
            ap_uint<6> syndrome = syn_byte & 0x3F;
            ap_uint<8> inst_byte = local_lut[(int)syndrome];
            inst_chunk(j * 8 + 7, j * 8) = inst_byte;
        }

        instructions[i] = inst_chunk;
    }
}

}
