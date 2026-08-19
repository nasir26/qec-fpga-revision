"""Bit-exact Python mirror of rtl/shor913/src/shor_qec_kernel.cpp's decode logic.

The 256-entry SHOR_DECODER_LUT below is transcribed directly from the HLS
kernel source (docs/legacy/implementation/shor_qec_kernel.cpp lines 74-91 /
rtl/shor913/src/shor_qec_kernel.cpp), which is the closest thing to a
golden reference this archive has -- it is the literal C++ array HLS
synthesises into the decoder ROM. Do not hand-edit this table; regenerate
it with extract_lut_from_cpp() if the kernel source changes.
"""

from __future__ import annotations

import re
from pathlib import Path

N_DATA = 9
N_STAB = 8

_KERNEL_CPP = Path(__file__).resolve().parents[2] / "rtl" / "shor913" / "src" / "shor_qec_kernel.cpp"


def extract_lut_from_cpp(path: Path = _KERNEL_CPP) -> list[int]:
    """Parse the SHOR_DECODER_LUT initializer directly out of the .cpp source,
    so this mirror can never silently drift from the file HLS actually
    synthesises. Returns a 256-entry list of 18-bit packed (z_corr<<9|x_corr)
    words."""
    text = path.read_text()
    m = re.search(r"SHOR_DECODER_LUT\[LUT_SIZE\]\s*=\s*\{(.*?)\};", text, re.S)
    if not m:
        raise ValueError(f"could not find SHOR_DECODER_LUT initializer in {path}")
    body = m.group(1)
    body = re.sub(r"//.*", "", body)  # strip the "// 0x00" row-address comments
    tokens = re.findall(r"0x[0-9A-Fa-f]+", body)
    values = [int(t, 16) for t in tokens]
    if len(values) != 256:
        raise ValueError(f"expected 256 LUT entries, parsed {len(values)} from {path}")
    return values


SHOR_DECODER_LUT = extract_lut_from_cpp()


def compute_syndrome(x_err: int, z_err: int) -> int:
    s = 0
    s |= ((x_err >> 0) ^ (x_err >> 1)) & 1
    s |= (((x_err >> 1) ^ (x_err >> 2)) & 1) << 1
    s |= (((x_err >> 3) ^ (x_err >> 4)) & 1) << 2
    s |= (((x_err >> 4) ^ (x_err >> 5)) & 1) << 3
    s |= (((x_err >> 6) ^ (x_err >> 7)) & 1) << 4
    s |= (((x_err >> 7) ^ (x_err >> 8)) & 1) << 5
    slice_ab = z_err & 0x3F           # q0..q5
    slice_bc = (z_err >> 3) & 0x3F    # q3..q8
    s |= (bin(slice_ab).count("1") & 1) << 6
    s |= (bin(slice_bc).count("1") & 1) << 7
    return s


def shor_qec_kernel(x_err: int, z_err: int) -> dict:
    assert 0 <= x_err < (1 << N_DATA)
    assert 0 <= z_err < (1 << N_DATA)

    syndrome = compute_syndrome(x_err, z_err)
    lut_word = SHOR_DECODER_LUT[syndrome]
    x_corr = lut_word & 0x1FF
    z_corr = (lut_word >> 9) & 0x1FF

    x_fixed = x_err ^ x_corr
    z_fixed = z_err ^ z_corr

    x_logical_err = (x_fixed & 1) ^ ((x_fixed >> 3) & 1) ^ ((x_fixed >> 6) & 1)
    z_logical_err = bin(z_fixed).count("1") & 1

    return {
        "syndrome": syndrome,
        "x_corr": x_corr,
        "z_corr": z_corr,
        "x_logical_err": x_logical_err,
        "z_logical_err": z_logical_err,
    }
