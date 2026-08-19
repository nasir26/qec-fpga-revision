import math
import os
import random
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd
from qiskit_aer.noise import (
    NoiseModel,
    ReadoutError,
    depolarizing_error,
    pauli_error,
    thermal_relaxation_error,
)


def _pick_column(columns: Iterable[str], candidates: Iterable[str]) -> Optional[str]:
    col_lookup = {c.strip().lower(): c for c in columns}
    for candidate in candidates:
        hit = col_lookup.get(candidate.strip().lower())
        if hit is not None:
            return hit
    return None


def _to_float(value: object, default: float = 0.0) -> float:
    if value is None:
        return default
    text = str(value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _parse_neighbor_error_map(field_value: object) -> Dict[int, float]:
    text = str(field_value).strip()
    if text == "" or text.lower() in {"nan", "none"}:
        return {}

    out: Dict[int, float] = {}
    for entry in text.split(";"):
        pair = entry.strip()
        if not pair or ":" not in pair:
            continue
        qubit_text, error_text = pair.split(":", 1)
        try:
            out[int(qubit_text.strip())] = float(error_text.strip())
        except ValueError:
            continue
    return out


def _resolve_selection_seed(selection_seed: Optional[int]) -> Optional[int]:
    if selection_seed is not None:
        return selection_seed

    env_seed = os.getenv("QEC_SEED", "").strip()
    if not env_seed:
        return None

    try:
        return int(env_seed)
    except ValueError:
        return None


def load_ibm_calibration_csv(csv_path: str) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip() for c in df.columns]

    q_col = _pick_column(df.columns, ["Qubit"])
    if q_col is None:
        raise ValueError("CSV does not include a Qubit column")
    df[q_col] = pd.to_numeric(df[q_col], errors="coerce").astype("Int64")
    df = df.dropna(subset=[q_col]).copy()
    df[q_col] = df[q_col].astype(int)

    op_col = _pick_column(df.columns, ["Operational"])
    if op_col is not None:
        op = df[op_col].astype(str).str.strip().str.lower()
        df = df[(op == "yes") | (op == "true") | (op == "1")].copy()

    return df.sort_values(q_col).reset_index(drop=True)


def choose_operational_qubits(
    df: pd.DataFrame,
    required_qubits: int,
    qubit_indices: Optional[List[int]] = None,
    selection_seed: Optional[int] = None,
) -> List[int]:
    q_col = _pick_column(df.columns, ["Qubit"])
    available = set(df[q_col].tolist())

    if qubit_indices is not None:
        if len(set(qubit_indices)) != len(qubit_indices):
            raise ValueError("Explicit qubit list contains duplicates; each hardware qubit must be unique")
        missing = [q for q in qubit_indices if q not in available]
        if missing:
            raise ValueError(f"Requested qubits are missing or non-operational: {missing}")
        if len(qubit_indices) < required_qubits:
            raise ValueError(
                f"Need {required_qubits} qubits, but only {len(qubit_indices)} were provided"
            )
        return qubit_indices[:required_qubits]

    # Always look for blocks of 13 to ensure independent scripts (7 vs 13 qubits) 
    # align on the same physical data qubits, so LUT and Simulator match perfectly.
    search_len = max(required_qubits, 13)

    sorted_available = sorted(list(available))
    valid_sequences = []
    
    for i in range(len(sorted_available) - search_len + 1):
        seq = sorted_available[i:i + search_len]
        if seq[-1] - seq[0] == search_len - 1:
            valid_sequences.append(seq)
            
    if not valid_sequences:
        raise ValueError(
            f"No consecutive sequence of {search_len} operational qubits found in the CSV."
        )

    # Select from top-quality sequences. If a seed is available, pick stochastically
    # among top candidates to emulate natural run-to-run drift while keeping scripts aligned.
    x_error_col = _pick_column(
        df.columns,
        ["Pauli-X error", "RX error", "ID error", "Single-qubit error"],
    )
    readout_p01_col = _pick_column(df.columns, ["Prob meas0 prep1", "prob_meas0_prep1"])
    readout_p10_col = _pick_column(df.columns, ["Prob meas1 prep0", "prob_meas1_prep0"])
    readout_total_col = _pick_column(
        df.columns,
        ["Readout assignment error", "readout assignment error"],
    )

    row_by_qubit: Dict[int, pd.Series] = {}
    for _, row in df.iterrows():
        row_by_qubit[int(row[q_col])] = row

    def sequence_score(sequence: List[int]) -> Tuple[float, int]:
        total_score = 0.0
        for hw_qubit in sequence:
            row = row_by_qubit[hw_qubit]
            x_err = _to_float(row.get(x_error_col), 1e-4) if x_error_col is not None else 1e-4

            if readout_total_col is not None:
                readout_err = _to_float(row.get(readout_total_col), 0.0)
            else:
                p01 = _to_float(row.get(readout_p01_col), 0.0)
                p10 = _to_float(row.get(readout_p10_col), 0.0)
                readout_err = p01 + p10

            total_score += x_err + 0.5 * readout_err

        # Tie-break with first index for deterministic ordering.
        return (total_score / float(len(sequence)), sequence[0])

    ranked_sequences = sorted(valid_sequences, key=sequence_score)
    resolved_seed = _resolve_selection_seed(selection_seed)
    if resolved_seed is None:
        selected = ranked_sequences[0]
    else:
        top_k = min(5, len(ranked_sequences))
        candidates = ranked_sequences[:top_k]
        scores = [sequence_score(seq)[0] for seq in candidates]
        weights = [1.0 / max(score, 1e-12) for score in scores]
        rnd = random.Random(resolved_seed + required_qubits * 1009 + search_len * 131)
        selected = rnd.choices(candidates, weights=weights, k=1)[0]

    return selected[:required_qubits]


def build_noise_model_from_ibm_csv(
    csv_path: str,
    num_qubits: int = 13, 
    noise_scale: float = 1.0,
    qubit_indices: Optional[List[int]] = None,
    dynamic_safe: bool = True,
    selection_seed: Optional[int] = None,
) -> Tuple[NoiseModel, List[int]]:
    df = load_ibm_calibration_csv(csv_path)
    selected_hw_qubits = choose_operational_qubits(
        df,
        num_qubits,
        qubit_indices,
        selection_seed=selection_seed,
    )

    q_col = _pick_column(df.columns, ["Qubit"])
    t1_col = _pick_column(df.columns, ["T1 (us)", "T1"])
    t2_col = _pick_column(df.columns, ["T2 (us)", "T2"])
    readout_p01_col = _pick_column(df.columns, ["Prob meas0 prep1", "prob_meas0_prep1"])
    readout_p10_col = _pick_column(df.columns, ["Prob meas1 prep0", "prob_meas1_prep0"])
    readout_total_col = _pick_column(
        df.columns,
        ["Readout assignment error", "readout assignment error"],
    )
    sq_gate_len_col = _pick_column(
        df.columns,
        ["Single-qubit gate length (ns)", "single-qubit gate length (ns)"],
    )
    x_error_col = _pick_column(
        df.columns,
        ["Pauli-X error", "RX error", "ID error", "Single-qubit error"],
    )
    cz_error_col = _pick_column(df.columns, ["CZ error", "CX error"])
    tq_gate_len_col = _pick_column(df.columns, ["Gate length (ns)", "CX gate length (ns)", "CZ gate length (ns)"])

    noise_model = NoiseModel()
    hw_to_local = {hw: local for local, hw in enumerate(selected_hw_qubits)}

    for local_qubit, hw_qubit in enumerate(selected_hw_qubits):
        row = df[df[q_col] == hw_qubit].iloc[0]

        t1_ns = max(_to_float(row.get(t1_col), 100.0) * 1000.0, 1.0)
        t2_ns = max(_to_float(row.get(t2_col), 100.0) * 1000.0, 1.0)
        t2_ns = min(t2_ns, 2.0 * t1_ns)

        gate_ns = max(_to_float(row.get(sq_gate_len_col), 32.0), 1.0)
        single_error = min(max(_to_float(row.get(x_error_col), 1e-4) * noise_scale, 0.0), 1.0)

        if dynamic_safe:
            cycle_ns = gate_ns * 8.0 + 2200.0
            p_relax = 1.0 - math.exp(-cycle_ns / t1_ns)
            p_dephase = 1.0 - math.exp(-cycle_ns / t2_ns)

            p_x = noise_scale * (single_error + 0.50 * p_relax)
            p_z = noise_scale * (0.50 * p_dephase + 0.10 * single_error)
            p_y = noise_scale * (0.25 * (p_relax + p_dephase))

            p_x = min(max(p_x, 0.0), 0.30)
            p_y = min(max(p_y, 0.0), 0.30)
            p_z = min(max(p_z, 0.0), 0.30)
            total = p_x + p_y + p_z
            if total > 0.90:
                scale = 0.90 / total
                p_x *= scale
                p_y *= scale
                p_z *= scale
                total = p_x + p_y + p_z
            p_i = 1.0 - total

            pauli = pauli_error([
                ("X", p_x),
                ("Y", p_y),
                ("Z", p_z),
                ("I", p_i),
            ])
            # Keep readout error exclusively in ReadoutError (below) to avoid double-counting
            # measurement noise in syndrome extraction.
            for gate in ["id", "x", "sx", "h", "y", "z", "reset"]:
                noise_model.add_quantum_error(pauli, gate, [local_qubit])
        else:
            thermal_id = thermal_relaxation_error(t1_ns, t2_ns, 0.0)
            thermal_x = thermal_relaxation_error(t1_ns, t2_ns, gate_ns)
            thermal_sx = thermal_relaxation_error(t1_ns, t2_ns, gate_ns)
            dep1 = depolarizing_error(single_error, 1)

            noise_model.add_quantum_error(dep1.compose(thermal_x), "x", [local_qubit])
            noise_model.add_quantum_error(dep1.compose(thermal_sx), "sx", [local_qubit])
            noise_model.add_quantum_error(dep1.compose(thermal_x), "h", [local_qubit])
            noise_model.add_quantum_error(dep1.compose(thermal_x), "y", [local_qubit])
            noise_model.add_quantum_error(thermal_id, "z", [local_qubit])
            noise_model.add_quantum_error(thermal_id, "id", [local_qubit])

        # ALWAYS APPLY READOUT ERROR
        p01 = min(max(_to_float(row.get(readout_p01_col), 0.0) * noise_scale, 0.0), 0.5)
        p10 = min(max(_to_float(row.get(readout_p10_col), 0.0) * noise_scale, 0.0), 0.5)
        if p01 == 0.0 and p10 == 0.0 and readout_total_col is not None:
            half = (_to_float(row.get(readout_total_col), 0.0) / 2.0) * noise_scale
            p01 = half
            p10 = half

        p01 = min(max(p01 * noise_scale, 0.0), 0.5)
        p10 = min(max(p10 * noise_scale, 0.0), 0.5)
        readout = ReadoutError([[1.0 - p10, p10], [p01, 1.0 - p01]])
        noise_model.add_readout_error(readout, [local_qubit])

    added_pair_error = False
    if cz_error_col is not None:
        for hw_q0 in selected_hw_qubits:
            row0 = df[df[q_col] == hw_q0].iloc[0]
            pair_errors = _parse_neighbor_error_map(row0.get(cz_error_col))
            pair_lens = _parse_neighbor_error_map(row0.get(tq_gate_len_col)) if tq_gate_len_col else {}
            
            for hw_q1, err in pair_errors.items():
                if hw_q1 not in hw_to_local:
                    continue
                q0 = hw_to_local[hw_q0]
                q1 = hw_to_local[hw_q1]
                if q0 >= q1:
                    continue
                
                row1 = df[df[q_col] == hw_q1].iloc[0]
                
                # High-fidelity Superconducting Qubit model: Thermal relaxation applied to both targets during the gate
                t1_0_ns = max(_to_float(row0.get(t1_col), 100.0) * 1000.0, 1.0)
                t2_0_ns = min(max(_to_float(row0.get(t2_col), 100.0) * 1000.0, 1.0), 2.0 * t1_0_ns)
                t1_1_ns = max(_to_float(row1.get(t1_col), 100.0) * 1000.0, 1.0)
                t2_1_ns = min(max(_to_float(row1.get(t2_col), 100.0) * 1000.0, 1.0), 2.0 * t1_1_ns)
                
                gate_time_ns = pair_lens.get(hw_q1, 300.0)
                
                # Approximate thermal decay over the 2Q gate instead of blowing up Kraus operator limits
                p_relax_0 = 1.0 - math.exp(-gate_time_ns / t1_0_ns)
                p_dephase_0 = 1.0 - math.exp(-gate_time_ns / t2_0_ns)
                p_relax_1 = 1.0 - math.exp(-gate_time_ns / t1_1_ns)
                p_dephase_1 = 1.0 - math.exp(-gate_time_ns / t2_1_ns)
                
                # Combine base calibration error with thermal decay approximation into a pure depolarizing
                # to prevent segfaults in AerSimulator C++ execution from generating 256-kraus tensors.
                combined_err = err + (p_relax_0 + p_dephase_0 + p_relax_1 + p_dephase_1) * 0.25
                p2 = min(max(combined_err * noise_scale, 0.0), 1.0)
                
                noise_model.add_quantum_error(depolarizing_error(p2, 2), "cx", [q0, q1])
                noise_model.add_quantum_error(depolarizing_error(p2, 2), "cx", [q1, q0])
                added_pair_error = True

    if not added_pair_error:
        fallback_pair_error = 0.01 * noise_scale
        fallback_pair_error = min(max(fallback_pair_error, 0.0), 1.0)
        noise_model.add_all_qubit_quantum_error(
            depolarizing_error(fallback_pair_error, 2),
            ["cx"],
        )

    return noise_model, selected_hw_qubits


def build_pauli_error_priors_from_ibm_csv(
    csv_path: str,
    num_data_qubits: int = 7,
    noise_scale: float = 1.0,
    qubit_indices: Optional[List[int]] = None,
    selection_seed: Optional[int] = None,
) -> Tuple[List[Dict[str, float]], List[int]]:
    df = load_ibm_calibration_csv(csv_path)
    selected_hw_qubits = choose_operational_qubits(
        df,
        num_data_qubits,
        qubit_indices,
        selection_seed=selection_seed,
    )

    q_col = _pick_column(df.columns, ["Qubit"])
    t1_col = _pick_column(df.columns, ["T1 (us)", "T1"])
    t2_col = _pick_column(df.columns, ["T2 (us)", "T2"])
    sq_gate_len_col = _pick_column(
        df.columns,
        ["Single-qubit gate length (ns)", "single-qubit gate length (ns)"],
    )
    readout_len_col = _pick_column(df.columns, ["Readout length (ns)"])
    x_error_col = _pick_column(
        df.columns,
        ["Pauli-X error", "RX error", "ID error", "Single-qubit error"],
    )

    priors: List[Dict[str, float]] = []
    for hw_qubit in selected_hw_qubits:
        row = df[df[q_col] == hw_qubit].iloc[0]

        t1_ns = max(_to_float(row.get(t1_col), 100.0) * 1000.0, 1.0)
        t2_ns = max(_to_float(row.get(t2_col), 100.0) * 1000.0, 1.0)
        gate_ns = max(_to_float(row.get(sq_gate_len_col), 32.0), 1.0)
        readout_ns = max(_to_float(row.get(readout_len_col), 2200.0), 1.0)

        cycle_ns = readout_ns + 8.0 * gate_ns
        p_relax = 1.0 - math.exp(-cycle_ns / t1_ns)
        p_dephase = 1.0 - math.exp(-cycle_ns / t2_ns)
        p_x_base = _to_float(row.get(x_error_col), 1e-4)

        p_x = noise_scale * (p_x_base + 0.50 * p_relax)
        p_z = noise_scale * (0.50 * p_dephase + 0.10 * p_x_base)
        p_y = noise_scale * (0.25 * (p_relax + p_dephase))

        p_x = min(max(p_x, 0.0), 0.35)
        p_y = min(max(p_y, 0.0), 0.35)
        p_z = min(max(p_z, 0.0), 0.35)

        total_err = p_x + p_y + p_z
        if total_err > 0.90:
            scale = 0.90 / total_err
            p_x *= scale
            p_y *= scale
            p_z *= scale
            total_err = p_x + p_y + p_z

        p_i = 1.0 - total_err
        priors.append({"I": p_i, "X": p_x, "Y": p_y, "Z": p_z})

    return priors, selected_hw_qubits