# E05b: Rep-3 circuit-level, multi-round (Stim + PyMatching)

**Status: RUN, 2026-08-20.** Not `experiments/E05_repeated_rounds_meas_error` (the real
hardware multi-round experiment E05 asks for — a Pauli-frame-update kernel driven by a live or
Stim-synthetic syndrome stream at 1 MHz, per the brief's Phase 3 E05 description). This is
software-only, using Stim's circuit generator and sampler plus PyMatching's MWPM decoder — a
different, general-purpose decoder from this project's own `rep3_qec_kernel.cpp` LUT.

## Why this is worth having anyway

Every other logical-error-rate number in this campaign so far
(`experiments/E07b_montecarlo_software_mirror/`) uses a **phenomenological** noise model: inject
a Pauli error directly on the data qubits, decode once, done. Real quantum hardware doesn't work
that way — syndrome extraction is itself a noisy circuit, ancilla measurement can be wrong, and a
real QEC protocol runs many rounds in a row, with each round's decode depending on the
accumulated space-time history. R1-Maj-5 and R1-Maj-1 both ask for exactly this regime, and
nothing in either archive or this campaign's other experiments touches it. This does, for one
code.

## What was run

`run_circuit_level.py`: Stim's built-in `repetition_code:memory` circuit generator, distance 3,
rounds $\in\{1,3,10,50\}$, per-gate depolarising + measurement-flip + reset-flip probability
$p\in\{0.001,0.003,0.01,0.03,0.05,0.08,0.10\}$ (all set to the same $p$ for simplicity — a
uniform circuit-level noise model, not IBM-calibration-derived). $10^6$ shots per (rounds, $p$)
point, decoded with PyMatching's exact MWPM against the real detector error model Stim derives
from the circuit. 28 points, full grid, ~4 minutes wall time.

## Findings

- Logical error rate grows both with $p$ and with round count, as expected for a real repeated
  QEC protocol accumulating measurement error: at $p=0.01$, $p_L$ goes from $3.1\times10^{-3}$
  (1 round) to $2.2\times10^{-2}$ (10 rounds) to $9.95\times10^{-2}$ (50 rounds) — a roughly
  linear-in-rounds growth in this regime, consistent with independent per-round failure
  probability rather than the code "learning" or degrading super-linearly.
- At high $p$ and high round count the curve saturates near $p_L\approx0.5$ (50 rounds, $p\ge0.05$),
  the expected signature of the decoder doing no better than a coin flip once the code is
  thoroughly overwhelmed.
- This uses **PyMatching's MWPM**, not this project's own LUT decoder, so it validates the code's
  behaviour under circuit-level, multi-round noise in the abstract, not this specific kernel's
  correctness. Building an equivalent multi-round circuit with this project's own decoder swapped
  in (matching the "Pauli-frame update kernel" E05 describes) is separate, larger engineering work
  not attempted here.

## Scope limitation, stated plainly

**Rep-3 only.** Shor [[9,1,3]] and Steane [[7,1,3]] have no off-the-shelf Stim circuit generator;
building one requires specifying an actual qubit layout, two-qubit gate schedule, and stabilizer
measurement circuit for each code from scratch. That is real, separate work for a future pass,
not attempted in this session.

## Claims this experiment resolves

New ground, not a fix to an existing ledger row: see `docs/CLAIMS_LEDGER.md` C-148. Directly
usable as one panel of a "circuit-level noise" figure in the manuscript rewrite (R1-Maj-5), and
as partial (Rep-3-only), software-only evidence toward the repeated-rounds claim structure R1-Maj-1
asks for — real hardware, multi-round, and Shor/Steane circuit-level all remain open.
