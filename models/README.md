# Models

- `mirrors/` bit-exact software twins of each hardware decoder. Their only job is to be compared
  against hardware output, never to stand in for it.
- `reference/` Stim circuit definitions, PyMatching baselines, an independent union-find reference.
- `tests/` pytest suite: mirror versus hardware (requires card), mirror versus PyMatching
  (no card), exhaustive enumeration at d=3, and property tests over random Pauli frames.

The correctness argument changes with distance. At d=3 it is exhaustive enumeration over all
3^n single-block error patterns. At d=5 it is agreement with PyMatching under an identical
circuit-level noise model, with confidence intervals.
