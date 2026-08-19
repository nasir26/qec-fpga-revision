"""Bit-exact Python mirror of rtl/steane713/src/steane_qec_kernel.cpp.

This mirrors the RECONSTRUCTED kernel (see that file's header comment and
docs/BLOCKERS.md B-003): the original steane_qec_kernel.cpp was not present
in either submitted archive. Every function here must track the C++ file
line for line; if you change one, change the other and rerun
models/tests/test_steane_mirror.py.
"""

from dataclasses import dataclass

N_DATA = 7
N_STAB = 3

H_COL = [1, 2, 3, 4, 5, 6, 7]  # H_COL[q] = q + 1

STEANE_LUT = [0b0000000, 0b0000001, 0b0000010, 0b0000100,
              0b0001000, 0b0010000, 0b0100000, 0b1000000]

PAIRS = [(i, j) for i in range(N_DATA) for j in range(i + 1, N_DATA)]
assert len(PAIRS) == 21


def syndrome(err: int) -> int:
    s = 0
    for r in range(N_STAB):
        row_mask = 0
        for q in range(N_DATA):
            if (H_COL[q] >> r) & 1:
                row_mask |= (1 << q)
        bit = bin(err & row_mask).count("1") & 1
        s |= (bit << r)
    return s


def lut_decode(s: int) -> int:
    return STEANE_LUT[s]


def mwpm_decode(s: int) -> int:
    for q in range(N_DATA):
        if H_COL[q] == s:
            return 1 << q
    for (i, j) in PAIRS:
        if (H_COL[i] ^ H_COL[j]) == s:
            return (1 << i) | (1 << j)
    return 0


def uf_decode(s: int) -> int:
    # One growth round of peeling: for this code, that algebraically
    # collapses to the same column-vs-syndrome equality as the MWPM
    # weight-1 path (main.tex L308: "collapses to the same XOR-reduce
    # for one growth round"). See steane_qec_kernel.cpp uf_decode()
    # for the full derivation note; this is not the naive "parity of
    # all active adjacent checks" reading of L183, which does not
    # decode single-qubit errors correctly on this graph (verified by
    # test_steane_mirror.py catching exactly that bug during
    # reconstruction).
    corr = 0
    for q in range(N_DATA):
        if H_COL[q] == s:
            corr |= (1 << q)
    return corr


DECODERS = {0: lut_decode, 1: mwpm_decode, 2: uf_decode}
MODE_NAMES = {0: "LUT", 1: "MWPM", 2: "UF"}


@dataclass
class SteaneResult:
    x_corr: int
    z_corr: int
    s_z: int
    s_x: int
    x_logical_err: int
    z_logical_err: int
    mode: int


def steane_qec_kernel(x_err: int, z_err: int, mode: int) -> SteaneResult:
    assert 0 <= x_err < (1 << N_DATA)
    assert 0 <= z_err < (1 << N_DATA)
    assert mode in (0, 1, 2)

    s_z = syndrome(x_err)
    s_x = syndrome(z_err)

    decode = DECODERS[mode]
    x_corr = decode(s_z)
    z_corr = decode(s_x)

    x_fixed = x_err ^ x_corr
    z_fixed = z_err ^ z_corr

    x_logical_err = bin(x_fixed & 0b0000111).count("1") & 1
    z_logical_err = bin(z_fixed & 0b0000111).count("1") & 1

    return SteaneResult(x_corr, z_corr, s_z, s_x, x_logical_err, z_logical_err, mode)
