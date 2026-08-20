"""Bit-exact Python mirror of rtl/rep3/src/rep3_qec_kernel.cpp."""

from __future__ import annotations

REP3_DECODER_LUT = [0b000, 0b001, 0b100, 0b010]


def majority(bits3: int) -> int:
    return 1 if bin(bits3).count("1") >= 2 else 0


def rep3_qec_kernel(codeword_in: int, error_mask: int, logical_in: int) -> dict:
    assert 0 <= codeword_in < 8 and 0 <= error_mask < 8 and logical_in in (0, 1)

    rcv = codeword_in ^ error_mask
    s0 = (rcv & 1) ^ ((rcv >> 1) & 1)
    s1 = ((rcv >> 1) & 1) ^ ((rcv >> 2) & 1)
    syndrome = (s1 << 1) | s0

    correction = REP3_DECODER_LUT[syndrome]
    corrected = rcv ^ correction
    corrected_logical = majority(corrected)

    return {
        "corrected": corrected,
        "correction": correction,
        "syndrome": syndrome,
        "corrected_logical": corrected_logical,
        "error_detected": 1 if syndrome != 0 else 0,
        "recovery_success": 1 if corrected_logical == logical_in else 0,
    }
