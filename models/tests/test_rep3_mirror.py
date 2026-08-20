"""Exhaustive test for models/mirrors/rep3_mirror.py. Only 8x8x2=128
combinations total, so this is a full enumeration, not a sample."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mirrors"))
from rep3_mirror import rep3_qec_kernel  # noqa: E402


def main():
    total = 0
    single_bit_flip_pass = 0
    single_bit_flip_total = 0
    for codeword_in in (0b000, 0b111):  # the two valid logical codewords
        logical_in = 0 if codeword_in == 0b000 else 1
        for error_mask in range(8):
            r = rep3_qec_kernel(codeword_in, error_mask, logical_in)
            total += 1
            weight = bin(error_mask).count("1")
            if weight <= 1:
                single_bit_flip_total += 1
                if r["recovery_success"]:
                    single_bit_flip_pass += 1
                else:
                    print(f"FAIL (weight<=1 should always recover) codeword={codeword_in:03b} "
                          f"error_mask={error_mask:03b}: {r}")

    print(f"single-bit-flip recovery (weight 0 or 1 error, both codewords): "
          f"{single_bit_flip_pass}/{single_bit_flip_total} "
          f"({'PASS, distance-3 guarantee holds' if single_bit_flip_pass == single_bit_flip_total else 'FAIL'})")
    print(f"total combinations checked: {total}")
    return single_bit_flip_pass == single_bit_flip_total


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
