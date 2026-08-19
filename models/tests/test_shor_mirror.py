"""Self-test, cross-check, and exhaustive enumeration for the Shor mirror.

1. Reproduces the manuscript's claimed 27/27 self-test (main.tex L433-461)
   against this mirror -- a SOFTWARE-ONLY result, must not be logged in
   docs/CLAIMS_LEDGER.md as MEASURED-HW.
2. Cross-checks models/mirrors/shor_mirror.py (built by parsing the literal
   SHOR_DECODER_LUT out of the HLS kernel source) against the INDEPENDENT
   software decoder embedded in docs/legacy/implementation/shor_qec_host.py
   (built via that file's own _build_lut()/_sw_synd()/sw_decode()). These
   two were written independently (one derived from the .cpp source table,
   one reimplements it from scratch in the host driver) and agreeing
   exactly is real evidence for ledger row C-006 ("software mirror
   validated against the HLS golden-reference output"), which was
   previously UNSUPPORTED because no such comparison existed anywhere in
   either archive.
3. Exhaustive enumeration over all 4^9 = 262,144 (x_err, z_err) combinations
   (every qubit independently I/X/Y/Z), stratified by error weight. This is
   MORE complete than the brief's requested 3^9 = 19,683 patterns (whose
   exact enumeration convention -- which 3 of the 4 single-qubit Paulis --
   is not stated), so it supersedes rather than under-delivers on that ask.
   Still a SOFTWARE-ONLY characterisation, not a hardware comparison; E01's
   actual ask (hardware output vs software mirror, bit-for-bit) remains
   BLOCKED on B-001 until a real device run exists.
"""

import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "mirrors"))
from shor_mirror import shor_qec_kernel, N_DATA  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
HOST_DRIVER = REPO_ROOT / "docs" / "legacy" / "implementation" / "shor_qec_host.py"


def load_host_sw_decode():
    """Import sw_decode() directly out of the legacy host driver without
    running its module-level XRT probing code, by loading just the module
    (pyxrt import inside it is guarded/optional per that file's own design)."""
    spec = importlib.util.spec_from_file_location("shor_qec_host_legacy", HOST_DRIVER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod  # dataclasses' type introspection needs this registered
    spec.loader.exec_module(mod)
    return mod.sw_decode


def run_self_test():
    total = 0
    failed = 0
    for q in range(N_DATA):
        for kind in ("X", "Y", "Z"):
            x_err = (1 << q) if kind in ("X", "Y") else 0
            z_err = (1 << q) if kind in ("Y", "Z") else 0
            r = shor_qec_kernel(x_err, z_err)
            total += 1
            if r["x_logical_err"] != 0 or r["z_logical_err"] != 0:
                failed += 1
                print(f"FAIL {kind} q{q}: syndrome=0x{r['syndrome']:02X} "
                      f"x_corr={r['x_corr']:09b} z_corr={r['z_corr']:09b} "
                      f"Xlog={r['x_logical_err']} Zlog={r['z_logical_err']}")
    print(f"self-test: {total - failed}/{total} PASS "
          f"({'matches manuscript-claimed 27/27' if failed == 0 else 'MISMATCH'})")
    return failed == 0


def run_cross_check_against_host_driver():
    """Compare this mirror against the independently-written sw_decode() in
    the legacy host driver, over all 512*512 = 262,144 combinations."""
    sw_decode = load_host_sw_decode()
    mismatches = 0
    checked = 0
    for x_err in range(512):
        for z_err in range(512):
            checked += 1
            r = shor_qec_kernel(x_err, z_err)
            mirror_packed = (r["x_corr"] | (r["z_corr"] << 9) | (r["syndrome"] << 18)
                              | (r["x_logical_err"] << 26) | (r["z_logical_err"] << 27))
            host_packed = sw_decode(x_err, z_err)
            if mirror_packed != host_packed:
                mismatches += 1
                if mismatches <= 10:
                    print(f"CROSS-CHECK MISMATCH x_err={x_err:09b} z_err={z_err:09b}: "
                          f"mirror=0x{mirror_packed:08X} host_sw_decode=0x{host_packed:08X}")
    print(f"cross-check vs docs/legacy/implementation/shor_qec_host.py's independent "
          f"sw_decode(): {checked - mismatches}/{checked} identical "
          f"({'bit-exact, C-006 now has real evidence' if mismatches == 0 else 'MISMATCH -- see above'})")
    return mismatches == 0


def run_exhaustive_enumeration():
    """All 4^9 = 262,144 (x_err, z_err) combinations, stratified by weight
    (number of qubits touched by any X and/or Z error bit)."""
    by_weight_total = {}
    by_weight_pass = {}
    for x_err in range(512):
        for z_err in range(512):
            weight = bin(x_err | z_err).count("1")
            r = shor_qec_kernel(x_err, z_err)
            ok = (r["x_logical_err"] == 0 and r["z_logical_err"] == 0)
            by_weight_total[weight] = by_weight_total.get(weight, 0) + 1
            by_weight_pass[weight] = by_weight_pass.get(weight, 0) + (1 if ok else 0)

    print("exhaustive enumeration, all 4^9=262,144 (x_err,z_err) combinations, by weight:")
    for w in sorted(by_weight_total):
        total = by_weight_total[w]
        passed = by_weight_pass[w]
        print(f"  weight {w}: {passed}/{total} correctable ({100*passed/total:5.1f}%)")

    weight1_total = by_weight_total.get(1, 0)
    weight1_pass = by_weight_pass.get(1, 0)
    weight1_ok = (weight1_pass == weight1_total) and weight1_total == 9 * 3
    print(f"weight-1 (single-qubit Pauli): {weight1_pass}/{weight1_total} correctable, "
          f"expected 27/27 -> {'CONSISTENT with self-test' if weight1_ok else 'INCONSISTENT'}")
    return weight1_ok


if __name__ == "__main__":
    ok1 = run_self_test()
    ok2 = run_cross_check_against_host_driver()
    ok3 = run_exhaustive_enumeration()
    sys.exit(0 if (ok1 and ok2 and ok3) else 1)
