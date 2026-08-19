import argparse
import os
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister, transpile
from qiskit_aer import AerSimulator

from noise import build_noise_model_from_ibm_csv, build_pauli_error_priors_from_ibm_csv


STEANE_H = [
    [1, 1, 1, 0, 1, 0, 0],
    [1, 1, 0, 1, 0, 1, 0],
    [1, 0, 1, 1, 0, 0, 1],
]


@dataclass
class DecoderInstruction:
    op: str
    qubit: int
    probability: float


def steane_column_syndromes() -> Dict[int, str]:
    return {
        q: "".join(str(STEANE_H[row][q]) for row in range(3))
        for q in range(7)
    }


def steane_z_stabilizer_supports() -> List[List[int]]:
    supports = []
    for row in range(3):
        supports.append([q for q in range(7) if STEANE_H[row][q] == 1])
    return supports


def syndrome_to_int(syndrome_bits: str) -> int:
    value = 0
    for i, bit in enumerate(syndrome_bits):
        value |= (int(bit) << i)
    return value


def int_to_syndrome(value: int, width: int = 6) -> str:
    return "".join("1" if (value >> i) & 1 else "0" for i in range(width))


def candidate_error_syndrome(op: str, qubit: int, columns: Dict[int, str]) -> str:
    zero = "000"
    col = columns[qubit]
    if op == "I":
        return zero + zero
    if op == "X":
        return col + zero
    if op == "Z":
        return zero + col
    if op == "Y":
        return col + col
    raise ValueError(f"Unsupported Pauli op: {op}")


def build_optimal_decoder_lut(priors: List[Dict[str, float]]) -> Dict[str, DecoderInstruction]:
    columns = steane_column_syndromes()
    lut: Dict[str, DecoderInstruction] = {}

    candidates: List[Tuple[str, int, str, float]] = []
    p_identity = 1.0
    for q in range(7):
        p_identity *= max(priors[q].get("I", 1.0), 1e-12)
    candidates.append(("I", -1, "000000", p_identity))

    for qubit in range(7):
        for op in ("X", "Y", "Z"):
            syn = candidate_error_syndrome(op, qubit, columns)
            prob = max(priors[qubit].get(op, 0.0), 0.0)
            candidates.append((op, qubit, syn, prob))

    for syndrome_int in range(64):
        syndrome = int_to_syndrome(syndrome_int)
        best = DecoderInstruction("I", -1, 0.0)
        for op, qubit, syn, prob in candidates:
            if syn == syndrome and prob > best.probability:
                best = DecoderInstruction(op, qubit, prob)
        lut[syndrome] = best

    return lut


def prepare_logical_zero_steane(circuit: QuantumCircuit, data: QuantumRegister) -> None:
    # Build |0_L> as a superposition over the row-space of the Steane H matrix.
    # Qubits 4,5,6 store the three generator coefficients in |+>.
    for q in [4, 5, 6]:
        circuit.h(data[q])

    # Compute linear combinations onto qubits 0..3.
    cnot_pairs = [
        (4, 0), (5, 0), (6, 0),
        (4, 1), (5, 1),
        (4, 2), (6, 2),
        (5, 3), (6, 3),
    ]
    for control, target in cnot_pairs:
        circuit.cx(data[control], data[target])


def add_random_errors_from_priors(
    circuit: QuantumCircuit,
    data: QuantumRegister,
    priors: List[Dict[str, float]],
) -> None:
    for qubit_idx, prior in enumerate(priors):
        ops = ["I", "X", "Y", "Z"]
        probs = [prior.get(op, 0.0) for op in ops]
        chosen_op = random.choices(ops, weights=probs, k=1)[0]
        if chosen_op == "X":
            circuit.x(data[qubit_idx])
        elif chosen_op == "Y":
            circuit.y(data[qubit_idx])
        elif chosen_op == "Z":
            circuit.z(data[qubit_idx])
        # I does nothing


def add_syndrome_extraction(circuit: QuantumCircuit, data: QuantumRegister, ancilla: QuantumRegister, syn: ClassicalRegister) -> None:
    supports = steane_z_stabilizer_supports()

    # Z stabilizers detect X/Y components.
    for i, support in enumerate(supports):
        for dq in support:
            circuit.cx(data[dq], ancilla[i])

    # X stabilizers detect Z/Y components (basis-rotated measurement).
    for dq in range(7):
        circuit.h(data[dq])
    for i, support in enumerate(supports):
        anc_idx = 3 + i
        for dq in support:
            circuit.cx(data[dq], ancilla[anc_idx])
    for dq in range(7):
        circuit.h(data[dq])

    for i in range(6):
        circuit.measure(ancilla[i], syn[i])


def add_fpga_conditional_correction(
    circuit: QuantumCircuit,
    data: QuantumRegister,
    syn: ClassicalRegister,
    decoder_lut: Dict[str, DecoderInstruction],
) -> None:
    for syndrome in sorted(decoder_lut.keys(), key=syndrome_to_int):
        instruction = decoder_lut[syndrome]
        if instruction.op == "I" or instruction.qubit < 0:
            continue
        syn_val = syndrome_to_int(syndrome)
        with circuit.if_test((syn, syn_val)):
            if instruction.op == "X":
                circuit.x(data[instruction.qubit])
            elif instruction.op == "Y":
                circuit.y(data[instruction.qubit])
            elif instruction.op == "Z":
                circuit.z(data[instruction.qubit])


def build_steane_fpga_circuit(apply_correction: bool, decoder_lut: Dict[str, DecoderInstruction], priors: List[Dict[str, float]] = None) -> QuantumCircuit:
    data = QuantumRegister(7, "data")
    anc = QuantumRegister(6, "anc")
    syn = ClassicalRegister(6, "syn")
    post = ClassicalRegister(6, "post")
    out = ClassicalRegister(7, "out")
    circuit = QuantumCircuit(data, anc, syn, post, out)

    prepare_logical_zero_steane(circuit, data)

    if priors:
        add_random_errors_from_priors(circuit, data, priors)

    add_syndrome_extraction(circuit, data, anc, syn)

    if apply_correction:
        add_fpga_conditional_correction(circuit, data, syn, decoder_lut)

    for i in range(6):
        circuit.reset(anc[i])

    # Second syndrome round quantifies residual error after the FPGA action.
    add_syndrome_extraction(circuit, data, anc, post)

    for i in range(7):
        circuit.measure(data[i], out[i])

    return circuit


def parse_count_key(count_key: str) -> Tuple[str, str, str]:
    parts = count_key.split()
    if len(parts) == 1:
        key = parts[0]
        if len(key) != 19:
            raise ValueError(f"Unexpected count key format: {count_key}")
        out_msb = key[:7]
        post_msb = key[7:13]
        syn_msb = key[13:]
    else:
        if len(parts) != 3:
            raise ValueError(f"Unexpected count key format: {count_key}")
        out_msb, post_msb, syn_msb = parts
        if len(out_msb) != 7 or len(post_msb) != 6 or len(syn_msb) != 6:
            raise ValueError(f"Unexpected count key format: {count_key}")

    out_qorder = out_msb[::-1]
    post_qorder = post_msb[::-1]
    syn_qorder = syn_msb[::-1]
    return out_qorder, syn_qorder, post_qorder


def export_syndromes_from_memory(memory: List[str], output_path: str) -> int:
    syndromes: List[int] = []
    for key in memory:
        _, syn_bits, _ = parse_count_key(key)
        syndromes.append(syndrome_to_int(syn_bits))

    out_dir = os.path.dirname(os.path.abspath(output_path))
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(output_path, "w", encoding="ascii") as stream:
        for syndrome in syndromes:
            stream.write(f"{syndrome}\n")

    return len(syndromes)


def steane_logical_zero_codewords() -> set:
    codewords = set()
    for a in [0, 1]:
        for b in [0, 1]:
            for c in [0, 1]:
                bits = [
                    a ^ b ^ c,
                    a ^ b,
                    a ^ c,
                    b ^ c,
                    a,
                    b,
                    c,
                ]
                codewords.add("".join(str(x) for x in bits))
    return codewords


def summarize_results(
    counts: Dict[str, int],
    decoder_lut: Dict[str, DecoderInstruction],
) -> Tuple[float, float, Dict[str, int], Dict[str, int], List[Tuple[str, int, DecoderInstruction]]]:
    codewords = steane_logical_zero_codewords()
    total = sum(counts.values())

    codeword_hits = 0
    syndrome_hist: Dict[str, int] = {}
    post_syndrome_hist: Dict[str, int] = {}
    post_zero_hits = 0

    for key, c in counts.items():
        out_bits, syn_bits, post_bits = parse_count_key(key)
        if out_bits in codewords:
            codeword_hits += c
        if post_bits == "000000":
            post_zero_hits += c
        syndrome_hist[syn_bits] = syndrome_hist.get(syn_bits, 0) + c
        post_syndrome_hist[post_bits] = post_syndrome_hist.get(post_bits, 0) + c

    codeword_rate = (codeword_hits / total) if total else 0.0
    post_zero_rate = (post_zero_hits / total) if total else 0.0
    top_syndromes = sorted(syndrome_hist.items(), key=lambda item: item[1], reverse=True)[:8]
    top_with_actions: List[Tuple[str, int, DecoderInstruction]] = []
    for syn, c in top_syndromes:
        top_with_actions.append((syn, c, decoder_lut[syn]))

    return codeword_rate, post_zero_rate, syndrome_hist, post_syndrome_hist, top_with_actions


def resolve_runtime_seed(seed: Optional[int]) -> int:
    if seed is not None:
        return int(seed)

    env_seed = os.getenv("QEC_SEED", "").strip()
    if env_seed:
        try:
            return int(env_seed)
        except ValueError:
            pass

    return random.SystemRandom().randrange(1, 2**31 - 1)


def render_circuit_mpl(circuit: QuantumCircuit, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        figure = circuit.draw(output="mpl")
    except Exception as exc:
        raise RuntimeError(
            "Failed to draw circuit with output='mpl'. Ensure matplotlib is installed in the active environment."
        ) from exc

    figure.savefig(str(output_path), dpi=180, bbox_inches="tight")
    try:
        import matplotlib.pyplot as plt

        plt.close(figure)
    except Exception:
        pass

    return output_path


def print_circuit_terminal(label: str, circuit: QuantumCircuit, fold: int = 120) -> None:
    print(f"\n=== {label} ===")
    print(circuit.draw(output="text", fold=fold, idle_wires=False))


def run_pipeline(
    csv_path: str,
    shots: int,
    noise_scale: float,
    seed: Optional[int],
    qubit_indices: List[int],
    export_syndromes_path: str,
    export_only: bool,
    manual_error_injection: bool,
    show_circuit_terminal: str,
    show_transpiled_terminal: bool,
    show_circuit_mpl: str,
    circuit_mpl_dir: str,
) -> None:
    active_seed = resolve_runtime_seed(seed)
    random.seed(active_seed)

    noise_model, selected_hw = build_noise_model_from_ibm_csv(
        csv_path=csv_path,
        num_qubits=13,
        noise_scale=noise_scale,
        qubit_indices=qubit_indices if qubit_indices else None,
        selection_seed=active_seed,
    )

    data_hw = selected_hw[:7]
    priors, _ = build_pauli_error_priors_from_ibm_csv(
        csv_path=csv_path,
        num_data_qubits=7,
        noise_scale=noise_scale,
        qubit_indices=data_hw,
        selection_seed=active_seed,
    )
    decoder_lut = build_optimal_decoder_lut(priors)

    if manual_error_injection:
        simulator = AerSimulator()  # no backend noise model, pure manual faults
    else:
        simulator = AerSimulator(noise_model=noise_model)

    priors_for_injection = priors if manual_error_injection else None

    no_corr = build_steane_fpga_circuit(
        apply_correction=False,
        decoder_lut=decoder_lut,
        priors=priors_for_injection,
    )
    no_corr_t = transpile(no_corr, simulator, optimization_level=0)

    if show_circuit_terminal in {"no_corr", "both"}:
        print_circuit_terminal("Steane circuit (no correction, pre-transpile)", no_corr)
        if show_transpiled_terminal:
            print_circuit_terminal("Steane circuit (no correction, transpiled)", no_corr_t)

    mpl_dir = Path(circuit_mpl_dir)
    if show_circuit_mpl in {"no_corr", "both"}:
        saved_path = render_circuit_mpl(no_corr, mpl_dir / "steane_qec_circuit_no_correction_mpl.png")
        print(f"Saved circuit image (mpl): {saved_path}")

    capture_memory = bool(export_syndromes_path)
    if export_only and not capture_memory:
        raise ValueError("--export-only requires --export-syndromes to be set")

    no_corr_result = simulator.run(
        no_corr_t,
        shots=shots,
        seed_simulator=active_seed,
        memory=capture_memory,
    ).result()

    if capture_memory:
        no_corr_memory = no_corr_result.get_memory(no_corr_t)
        exported = export_syndromes_from_memory(no_corr_memory, export_syndromes_path)
        print(f"Exported {exported} Steane syndromes to: {export_syndromes_path}")
        print("")

    if export_only:
        if show_circuit_terminal in {"with_corr", "both"}:
            print("Skipped with-correction terminal circuit in export-only mode.")
        if show_circuit_mpl in {"with_corr", "both"}:
            print("Skipped with-correction mpl circuit in export-only mode.")
        print("Export-only mode enabled: skipped CPU-side comparison metrics.")
        print(f"Calibration CSV: {csv_path}")
        print(f"Selected hardware qubits ({len(selected_hw)} total): {selected_hw}")
        print(f"Data qubits used for code block: {data_hw}")
        print(f"Shots: {shots}")
        print(f"Noise scale: {noise_scale}")
        print(f"Seed: {active_seed}")
        return

    with_corr = build_steane_fpga_circuit(
        apply_correction=True,
        decoder_lut=decoder_lut,
        priors=priors_for_injection,
    )
    with_corr_t = transpile(with_corr, simulator, optimization_level=0)

    if show_circuit_terminal in {"with_corr", "both"}:
        print_circuit_terminal("Steane circuit (with correction, pre-transpile)", with_corr)
        if show_transpiled_terminal:
            print_circuit_terminal("Steane circuit (with correction, transpiled)", with_corr_t)

    if show_circuit_mpl in {"with_corr", "both"}:
        saved_path = render_circuit_mpl(with_corr, mpl_dir / "steane_qec_circuit_with_correction_mpl.png")
        print(f"Saved circuit image (mpl): {saved_path}")

    with_corr_result = simulator.run(with_corr_t, shots=shots, seed_simulator=active_seed).result()

    no_corr_counts = no_corr_result.get_counts(no_corr_t)
    with_corr_counts = with_corr_result.get_counts(with_corr_t)

    no_corr_rate, no_corr_post_zero, _, no_corr_post_hist, _ = summarize_results(no_corr_counts, decoder_lut)
    with_corr_rate, with_corr_post_zero, syndrome_hist, with_corr_post_hist, top_actions = summarize_results(with_corr_counts, decoder_lut)

    print("=== Steane [[7,1,3]] QEC with FPGA-style Optimal Decoder ===")
    print(f"Calibration CSV: {csv_path}")
    print(f"Selected hardware qubits ({len(selected_hw)} total): {selected_hw}")
    print(f"Data qubits used for code block: {data_hw}")
    print(f"Shots: {shots}")
    print(f"Noise scale: {noise_scale}")
    print(f"Seed: {active_seed}")
    print(f"Manual prior-error injection: {'enabled' if manual_error_injection else 'disabled (noise model only)'}")
    print("")

    print("--- FPGA decoder priors per data qubit ---")
    for q, p in enumerate(priors):
        print(
            f"q{q} (hw {data_hw[q]}): "
            f"P(I)={p['I']:.6f}, P(X)={p['X']:.6f}, P(Y)={p['Y']:.6f}, P(Z)={p['Z']:.6f}"
        )
    print("")

    print("--- Top measured syndromes and FPGA action ---")
    for syndrome, count, action in top_actions:
        if action.op == "I":
            text = "No correction"
        else:
            text = f"Apply {action.op} on data qubit {action.qubit}"
        print(f"syndrome={syndrome} count={count:5d} -> {text}")
    print(f"Total unique syndromes observed: {len(syndrome_hist)}")
    print("")

    print("--- Final result metrics ---")
    print("Logical code-space population (from data measurement):")
    print(f"Without FPGA correction: {no_corr_rate * 100:.2f}%")
    print(f"With FPGA correction:    {with_corr_rate * 100:.2f}%")
    print(f"Absolute improvement:    {(with_corr_rate - no_corr_rate) * 100:.2f}%")
    print("")
    print("Residual error metric :")
    print(f"Without FPGA correction: {no_corr_post_zero * 100:.2f}%")
    print(f"With FPGA correction:    {with_corr_post_zero * 100:.2f}%")
    print(f"Absolute improvement:    {(with_corr_post_zero - no_corr_post_zero) * 100:.2f}%")
    print("")
    print("Top post-correction syndromes (without correction run):")
    for syn, c in sorted(no_corr_post_hist.items(), key=lambda item: item[1], reverse=True)[:5]:
        print(f"post_syndrome={syn} count={c:5d}")
    print("Top post-correction syndromes (with correction run):")
    for syn, c in sorted(with_corr_post_hist.items(), key=lambda item: item[1], reverse=True)[:5]:
        print(f"post_syndrome={syn} count={c:5d}")

    # Invoke hardware host decoder to fetch the processing latency
    print("\nExecuting Hardware FPGA Kernel for Latency Metric...")
    import subprocess
    import re
    host_bin = "./build/hw/host_decoder"
    xclbin = "./build/hw/steane_decoder_kernel.hw.xclbin"
    syn_path = export_syndromes_path if export_syndromes_path else "data/syndromes.txt"
    lut_path = "data/decoder_lut.hex"
    
    if os.path.exists(host_bin) and os.path.exists(xclbin):
        try:
            # We must use the XRT environment if not already loaded, but normally it's set by setup.sh
            # Assume it's available or run it through bash source
            cmd = f"source /opt/xilinx/xrt/setup.sh && {host_bin} {xclbin} {syn_path} {lut_path}"
            res = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
            if res.returncode == 0:
                match_avg = re.search(r"Time per syndrome decoded:\s+([\d\.]+)\s+ns", res.stdout)
                match_tot = re.search(r"Total FPGA Kernel Execution Time:\s+([\d\.]+)\s+ns", res.stdout)
                
                if match_tot:
                    print(f"Total FPGA Kernel Execution Time (All Shots): {match_tot.group(1)} ns")
                if match_avg:
                    print(f"FPGA Kernel Latency (Per Shot):               {match_avg.group(1)} ns")
                    
                if not match_avg and not match_tot:
                    print("FPGA Kernel Latency: Not found in profiling output.")
            else:
                print("FPGA Kernel Latency: execution failed.")
        except Exception as e:
            print(f"FPGA Kernel Latency check failed: {e}")
    else:
        print("Hardware binaries not found. Skipping latency metric.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Steane 7-qubit QEC + IBM CSV noise + FPGA-style optimal decoder"
    )
    parser.add_argument(
        "--csv",
        type=str,
        required=True,
        help="Path to IBM calibration CSV",
    )
    parser.add_argument("--shots", type=int, default=2048, help="Number of simulation shots")
    parser.add_argument(
        "--noise-scale",
        type=float,
        default=1.0,
        help="Global multiplier for all noise probabilities",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional seed for simulator and qubit/noise selection (default: auto from QEC_SEED or random)",
    )
    parser.add_argument(
        "--qubits",
        type=int,
        nargs="*",
        default=[],
        help="Optional explicit list of 13 hardware qubits to map into the simulation",
    )
    parser.add_argument(
        "--export-syndromes",
        type=str,
        default="",
        help="Optional output path for decoder-input syndromes (one value 0..63 per shot)",
    )
    parser.add_argument(
        "--export-only",
        action="store_true",
        help="Only export Steane syndromes and skip CPU-side comparison metrics",
    )
    parser.add_argument(
        "--manual-error-injection",
        action="store_true",
        help="Enable legacy prior-based error gate insertion in addition to Aer noise model",
    )
    parser.add_argument(
        "--show-circuit-terminal",
        type=str,
        choices=["none", "no_corr", "with_corr", "both"],
        default="none",
        help="Print Steane circuit diagram(s) in terminal using circuit.draw(output='text')",
    )
    parser.add_argument(
        "--show-transpiled-terminal",
        action="store_true",
        help="Also print transpiled terminal diagram(s)",
    )
    parser.add_argument(
        "--show-circuit-mpl",
        type=str,
        choices=["none", "no_corr", "with_corr", "both"],
        default="none",
        help="Render and save Steane circuit image(s) using circuit.draw(output='mpl')",
    )
    parser.add_argument(
        "--circuit-mpl-dir",
        type=str,
        default="data",
        help="Output directory for mpl-rendered circuit image files",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_pipeline(
        csv_path=args.csv,
        shots=args.shots,
        noise_scale=args.noise_scale,
        seed=args.seed,
        qubit_indices=args.qubits,
        export_syndromes_path=args.export_syndromes,
        export_only=args.export_only,
        manual_error_injection=args.manual_error_injection,
        show_circuit_terminal=args.show_circuit_terminal,
        show_transpiled_terminal=args.show_transpiled_terminal,
        show_circuit_mpl=args.show_circuit_mpl,
        circuit_mpl_dir=args.circuit_mpl_dir,
    )
