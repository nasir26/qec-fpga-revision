# QEC on the Alveo U55C — From 3-Bit Repetition to 9-Qubit Shor

**Audience:** you — an FPGA engineer who has already built a 30-qubit statevector simulator on the U55C (`fpga_kernel_v05.cpp`) and knows HLS pragmas, HBM interleaving, and AXI-Lite cold. You know *zero* quantum theory on purpose; this guide translates every QEC concept into the digital-logic equivalent before it asks you to write a line of code.

**Companion files in this package**

| file | purpose |
|---|---|
| `rep3_qec_kernel.cpp` | Step-1 warm-up: 3-bit classical repetition code on the U55C |
| `shor_qec_kernel.cpp` | Step-2 main deliverable: full 9-qubit Shor code |
| `shor_qec_host.py`    | PyXRT host, style-matched to `fpga_simulator_v05.py` |
| `shor_link.cfg`       | minimal v++ link config (AXI-Lite only, no HBM yet) |
| `build_shor.sh`       | drop-in `v++ -c` / `v++ -l` script |
| `lut_table.txt`       | the complete 256-entry decoder LUT, annotated |

---

## 0. The central insight — why a QEC kernel is *not* a quantum simulator

Your v05 kernel tracks `2^N` complex128 amplitudes and applies unitary gates. For QEC decoding **you do not need any of that**. After a stabilizer measurement, the quantum state has collapsed onto a definite syndrome eigenspace and the decoder lives in a purely classical world: binary error vectors and parity checks over GF(2). This is the **stabilizer / binary symplectic representation** and it is why QEC decoders map so beautifully to FPGA logic.

Concretely, for an `[[n,k,d]]` stabilizer code the decoder state is:

| quantum object | classical FPGA object |
|---|---|
| Pauli error `E = X^a Z^b` on `n` qubits | two `n`-bit vectors `x_err`, `z_err` |
| stabilizer generator (Pauli on `n` qubits) | two rows of a parity-check matrix `H_X`, `H_Z` over GF(2) |
| syndrome measurement of one stabilizer | one bit = XOR-reduction of masked error bits |
| full syndrome extraction | `s = H · e mod 2` — bit-matrix × bit-vector |
| decoder | function `s → correction` |
| correction | XOR of the correction vector into `(x_err, z_err)` |
| logical operator measurement | XOR-reduction of error bits masked by the logical Pauli support |

Everything on the right is a bitwise XOR, a popcount, or a BRAM lookup. None of it touches a `complex<double>`. This is why a QEC decoder fits in a few thousand LUTs on the U55C and runs at a few hundred MHz while your v05 simulator needs the full 16 HBM pseudo-channels and saturates at ~30 qubits.

**The mental model to hold onto:** the QEC kernel is a classical error-detection-and-correction circuit that happens to be describing a quantum code. Every XOR tree, every LUT, every popcount has an exact analogue in classical coding theory (Hamming codes, Reed–Muller, LDPC). The "quantum-ness" is entirely in how the parity-check matrix was derived — once you have `H`, the rest is digital logic.

---

## 1. Monolithic vs. three-kernel pipeline — pick an architecture first

You asked the right question before any code. Here is the trade-off for the U55C.

### Option A — three separate kernels, HBM ping-pong

```
┌─────────┐   HBM[14]   ┌──────────────┐   HBM[15]   ┌─────────┐
│ encoder │ ──errors──▶ │ syndrome     │ ──syndromes▶│ decoder │
│ kernel  │             │ extractor    │             │ kernel  │
└─────────┘             └──────────────┘             └─────────┘
                                                         │
                                                         ▼ HBM[13]
                                                     corrections
```

- **Pros:** each kernel independently pipelined; any stage can be swapped (e.g. drop in a BP decoder later without rebuilding the encoder); stages can overlap across shots → high *throughput* for Monte Carlo workloads.
- **Cons:** every hand-off is a round trip to HBM (~100 ns minimum), which **destroys latency**. For a 9-qubit Shor code the entire computation is ~40 bits of state; pushing it through HBM twice is like sending a postcard via freight container. You also burn 2–3 HBM pseudo-channels that your v05 simulator wants back.

### Option B — monolithic kernel

```
┌───────────────────────────────────────────────────┐
│   encode → inject → extract → LUT → correct → ✓  │
│   all inside one HLS function, all on BRAM/FF     │
└───────────────────────────────────────────────────┘
                           ▲
                       AXI-Lite
```

- **Pros:** end-to-end latency is *fundamentally* set by logic depth, not memory. At 300 MHz you can hit < 10 cycles = < 33 ns from error-in to correction-out. No HBM banks burned. Trivial to integrate as a co-processor alongside your v05 simulator (different compute unit, same xclbin).
- **Cons:** harder to swap the decoder out; the syndrome extractor is baked into the same SLR as the LUT.

### Recommendation

**Start monolithic.** For distance-3 codes the entire pipeline is combinational plus a single BRAM read — trying to amortize that over HBM is architectural malpractice. When you graduate to BB[72,12,6] with iterative BP decoding, the *decoder alone* will justify its own kernel (because a 30-iteration BP loop is its own pipelining problem), and at that point you split it off. Until then: one kernel, one AXI-Lite bundle, zero HBM banks.

This mirrors how you'd approach a classical Reed–Solomon decoder in FPGA: you don't put the syndrome computation on a separate die from the Berlekamp–Massey block; they share a clock domain and live together.

The rep-3 and Shor kernels in this package are both monolithic for exactly this reason.

---

## 2. Step 1 — the 3-bit repetition code warm-up

Before Shor, the classical 3-bit repetition code. It is the simplest code in the universe and maps 1-for-1 onto the Shor code's inner blocks, so everything you learn here transfers.

### 2.1 Encoding — `0 → 000`, `1 → 111`

Classically: write the bit three times. In the quantum repetition code: `|0⟩ → |000⟩`, `|1⟩ → |111⟩`, and crucially a superposition `α|0⟩+β|1⟩ → α|000⟩+β|111⟩` — **not** `(α|0⟩+β|1⟩)^⊗3`, because that is not the same state. This distinction is what quantum error correction buys: the logical information lives in a subspace that is *protected* from any single-qubit Pauli X (bit-flip) error.

On the FPGA, for *decoding* purposes, the encoding is irrelevant — we only care about the error vector. So our Step-1 kernel accepts a "clean" codeword `{0,0,0}` or `{1,1,1}` and an error mask that it XORs in. Exactly what you'd do for a classical repetition channel.

### 2.2 Error injection — XOR with a 3-bit mask

This *is* the model of a bit-flip error on the FPGA. A 3-bit register, XOR with a 3-bit mask. Done.

```cpp
ap_uint<3> received = codeword ^ error_mask;
```

Quantum-mechanically: applying an `X` gate to qubit `i` flips classical bit `i` in the stabilizer picture. The entire effect of a Pauli `X` error on a code that only protects against bit-flips is a single XOR. That is the whole payoff of the stabilizer formalism — *it lets you model Pauli errors as linear maps over GF(2)*.

### 2.3 Syndrome extraction — two parity checks

```
s0 = bit0 ⊕ bit1       ← "the Z₀Z₁ stabilizer"
s1 = bit1 ⊕ bit2       ← "the Z₁Z₂ stabilizer"
```

**Why these are called stabilizers.** A Pauli operator "stabilizes" a state if the state is a +1 eigenvector of it. `|000⟩` and `|111⟩` are both +1 eigenvectors of `Z₀Z₁` because `Z|0⟩=+|0⟩`, `Z|1⟩=-|1⟩`, and two sign flips cancel. Measuring `Z₀Z₁` therefore returns +1 on both codewords (syndrome bit = 0) and -1 on anything with exactly one bit flipped between positions 0 and 1 (syndrome bit = 1). In binary-vector language this measurement is literally `bit0 XOR bit1`.

**Parity-check matrix** `H` **over GF(2):**

```
        q0  q1  q2
  s0 [   1   1   0  ]
  s1 [   0   1   1  ]
```

Syndrome of an error vector `e`:  `s = H · e mod 2`. For a single-bit error on qubit `q`, `s` is the `q`-th column of `H`. For `[H]` as above:

| error | s0 s1 |
|---|---|
| none      | 0 0 |
| X on q0   | 1 0 |
| X on q1   | 1 1 |
| X on q2   | 0 1 |

Because the three non-zero columns of `H` are distinct, the syndrome uniquely identifies any single-bit error. **That is the definition of distance 3.** (Minimum distance `d` means the code can unambiguously correct up to `(d-1)/2 = 1` error; equivalently, any `d-1 = 2` columns of `H` are linearly independent.) The quantum code has the same structure; the only thing we gained by making it quantum is that superposition is preserved through the correction.

### 2.4 Lookup-table decoder — 4 entries, trivially a BRAM

```
syndrome  → correction (3 bits, one-hot)
  00      →  000   (no error)
  10      →  001   (flip q0)
  11      →  010   (flip q1)
  01      →  100   (flip q2)
```

This is already a BRAM. In HLS:

```cpp
static ap_uint<3> rep3_lut[4] = { 0b000, 0b001, 0b100, 0b010 };
#pragma HLS BIND_STORAGE variable=rep3_lut type=ROM_1P impl=LUTRAM
```

Four 3-bit entries is so small it will synthesize to a pair of LUT6 look-ups, not a BRAM — `LUTRAM` is the right hint here. For Shor's 256-entry LUT we will ask for BRAM instead. See Step 2 for the reasoning.

### 2.5 The kernel in 60 lines

See `rep3_qec_kernel.cpp`. Every line is commented; the whole pipeline has II=1 and latency 3 cycles.

---

## 3. Step 2 — the 9-qubit Shor code, in full

### 3.1 Why 9 qubits

The 3-qubit repetition code catches a bit-flip (X) but is blind to a phase-flip (Z). The 3-qubit **phase-flip** code catches Z but is blind to X. Shor's trick — the reason 1995 was a hinge year for quantum computing — was to **concatenate** them:

1. Protect against bit-flips with an inner 3-qubit repetition code: one qubit becomes three.
2. Protect the *resulting* logical qubit against phase-flips by repeating it three more times.

Three-of-three = nine. The structure is:

```
    block A       block B       block C
  ┌────────┐   ┌────────┐   ┌────────┐
  │ q0 q1 q2 │ │ q3 q4 q5 │ │ q6 q7 q8 │
  └────────┘   └────────┘   └────────┘
  \_________________ ________________/
                    ∨
       outer phase-flip code (blocks)
```

### 3.2 The 8 stabilizer generators

Six inner **Z-type** stabilizers (catch X errors inside each block):

```
  S0 = Z0 Z1        S1 = Z1 Z2        ← block A
  S2 = Z3 Z4        S3 = Z4 Z5        ← block B
  S4 = Z6 Z7        S5 = Z7 Z8        ← block C
```

Two outer **X-type** stabilizers (catch Z errors across blocks):

```
  S6 = X0 X1 X2 X3 X4 X5              ← blocks A and B
  S7 = X3 X4 X5 X6 X7 X8              ← blocks B and C
```

Eight stabilizers × 9 qubits − 1 logical qubit ⇒ `[[9,1,3]]`. Distance 3.

### 3.3 Why you can track X and Z errors separately

In the stabilizer formalism an arbitrary single-qubit Pauli error is one of `{I, X, Y, Z}`, and `Y = iXZ`. So the **most general** single-qubit Pauli error on `n` qubits is fully described by two `n`-bit vectors `(x_err, z_err)` — bit `i` of `x_err` says "was there a bit-flip on qubit `i`?", bit `i` of `z_err` says "was there a phase-flip on qubit `i`?". A `Y` error sets both.

**Z-type stabilizers anticommute with X (detect bit-flips)** but commute with Z. So `S0..S5` only see `x_err`. **X-type stabilizers anticommute with Z** but commute with X. So `S6, S7` only see `z_err`. The whole syndrome extraction decouples into two independent XOR trees over two independent 9-bit vectors. This is the single most important structural fact for an FPGA implementation.

In your v05 simulator, a `Y` gate would require a full complex-amplitude rotation on `2^N` numbers. In the Shor decoder, a `Y` error is just two bit-flips in two 9-bit registers.

### 3.4 The parity check matrices

Z-type block (acts on `x_err`):

```
            q0 q1 q2 q3 q4 q5 q6 q7 q8
  S0 (Z0Z1)  1  1  0  0  0  0  0  0  0
  S1 (Z1Z2)  0  1  1  0  0  0  0  0  0
  S2 (Z3Z4)  0  0  0  1  1  0  0  0  0
  S3 (Z4Z5)  0  0  0  0  1  1  0  0  0
  S4 (Z6Z7)  0  0  0  0  0  0  1  1  0
  S5 (Z7Z8)  0  0  0  0  0  0  0  1  1
```

X-type block (acts on `z_err`):

```
            q0 q1 q2 q3 q4 q5 q6 q7 q8
  S6         1  1  1  1  1  1  0  0  0
  S7         0  0  0  1  1  1  1  1  1
```

Syndromes: `s[5:0] = H_Z · x_err mod 2`, `s[7:6] = H_X · z_err mod 2`.

### 3.5 The complete single-Pauli syndrome table

| error | x_err | z_err | s7 s6 s5 s4 s3 s2 s1 s0 | hex |
|---|---|---|---|---|
| I (none)        | 000000000 | 000000000 | 00000000 | `0x00` |
| X on q0         | 000000001 | 000000000 | 00000001 | `0x01` |
| X on q1         | 000000010 | 000000000 | 00000011 | `0x03` |
| X on q2         | 000000100 | 000000000 | 00000010 | `0x02` |
| X on q3         | 000001000 | 000000000 | 00000100 | `0x04` |
| X on q4         | 000010000 | 000000000 | 00001100 | `0x0C` |
| X on q5         | 000100000 | 000000000 | 00001000 | `0x08` |
| X on q6         | 001000000 | 000000000 | 00010000 | `0x10` |
| X on q7         | 010000000 | 000000000 | 00110000 | `0x30` |
| X on q8         | 100000000 | 000000000 | 00100000 | `0x20` |
| **Z on q0 / q1 / q2**  (degenerate) | 000000000 | 0000000[abc] | 01000000 | `0x40` |
| **Z on q3 / q4 / q5**  (degenerate) | 000000000 | 000[abc]000  | 11000000 | `0xC0` |
| **Z on q6 / q7 / q8**  (degenerate) | 000000000 | [abc]000000  | 10000000 | `0x80` |
| Y on q0 (= X·Z) | 000000001 | 000000001 | 01000001 | `0x41` |
| Y on q1         | 000000010 | 000000010 | 01000011 | `0x43` |
| Y on q2         | 000000100 | 000000100 | 01000010 | `0x42` |
| Y on q3         | 000001000 | 000001000 | 11000100 | `0xC4` |
| Y on q4         | 000010000 | 000010000 | 11001100 | `0xCC` |
| Y on q5         | 000100000 | 000100000 | 11001000 | `0xC8` |
| Y on q6         | 001000000 | 001000000 | 10010000 | `0x90` |
| Y on q7         | 010000000 | 010000000 | 10110000 | `0xB0` |
| Y on q8         | 100000000 | 100000000 | 10100000 | `0xA0` |

**22 correctable syndromes. 234 unused patterns.**

**About degeneracy:** notice that a Z error on qubit 0, qubit 1, or qubit 2 all give the same syndrome `0x40`. The code physically cannot tell which one happened — and **it doesn't have to**. `Z0 · Z1 = S0` is a stabilizer, so `Z0|ψ⟩ = Z1 · S0 |ψ⟩ = Z1 |ψ⟩` on codewords. Correcting with `Z0` or `Z1` or `Z2` all produce the same physical state. The LUT therefore picks the lowest-index representative (q0 for block A, q3 for block B, q6 for block C) as a canonical choice. This is **code degeneracy** and it's one of the genuine advantages of quantum codes over classical ones: multiple errors that look identical are, operationally, the same error.

### 3.6 Why a 256-entry BRAM is the right primitive

The LUT is 8-bit addressed (256 entries), 18-bit wide (9 bits X-correction + 9 bits Z-correction). That is **576 bytes**. Why BRAM and not something else?

| option | fits? | good idea? |
|---|---|---|
| distributed LUTRAM (LUT6 SRLs) | yes, ~72 LUT6 | OK for rep-3, wasteful here |
| single 18K BRAM (RAM_2P) | yes, 1 block | **correct choice** |
| UltraRAM | overkill | 288 Kb per URAM block |
| DSP48-based ROM | no | DSPs are for multiply-add |
| pure combinational logic | could synthesize | routing nightmare; loses timing at 300 MHz |

A single 18Kb BRAM block on the U55C, configured as `RAM_2P` with 256×18, gives you **2-cycle synchronous read** at 300 MHz+ with near-zero routing cost. It also pipelines naturally: you can fire one lookup per clock indefinitely (II=1). The `BIND_STORAGE` pragma in the kernel forces HLS to infer a BRAM rather than dissolving the array into FFs.

For a surface code `d=5` (25 data qubits, 24 ancillas, ~24-bit syndrome) the LUT explodes to `2^24 = 16 M` entries and you **must** move to an iterative decoder like MWPM or BP — see §6.

### 3.7 HLS timing model

Target clock: 300 MHz (= your v05 kernel clock, so a co-unit in the same `.xclbin` shares the clock tree).

| stage | what happens | logic depth | cycles |
|---|---|---|---|
| `compute_syndrome` | 2 XOR trees: 6-input and 6-input | ~3 LUT6 levels | **1** (combinational, registered at loop boundary) |
| `decoder_lut[syndrome]` | synchronous BRAM read | fixed | **2** (BRAM RAM_2P latency) |
| `apply_correction` | 2 × 9-bit XOR | 1 LUT6 level | **1** |
| `logical_readout` | 2 XOR trees: 3-input and 9-input | ~3 LUT6 levels | **1** |

**End-to-end: 5 cycles ≈ 17 ns at 300 MHz.** Pipelined, you can ingest one `(x_err, z_err)` every clock and retire one 32-bit result every clock — 300 M corrections/sec per compute unit. A single U55C can comfortably host 20+ of these units before hitting resource limits.

Compare with your `cudaqx_qec_final.py` GPU path: ~2000 shots take a few hundred ms = ~10 k shots/s including host overhead. The FPGA path is four to five orders of magnitude faster per shot, **but only matters if the quantum hardware itself can feed syndromes that fast**. Superconducting qubits currently produce a syndrome every ~1 µs; the FPGA at ~17 ns is idling 98% of the time. That idle time is exactly the budget you need for a *real* decoder (BP with 50 iterations at ~50 ns/iter) on a QLDPC code.

---

## 4. HLS pragmas used in the kernels — cheat sheet

Every pragma in the two kernels is footnoted in place, but here is the big-picture rationale.

- **`#pragma HLS INTERFACE s_axilite`** on every scalar argument and on `return`: binds the control port and every argument register into one AXI-Lite slave. This is the only host↔kernel data path for this kernel — no m_axi/HBM, unlike v05. Same style as the `ctrl` bundle but simpler because there are no pointer arguments.

- **`#pragma HLS PIPELINE II=1`** on the top-level function body: tells HLS "I want a new input accepted every clock". Without it the whole thing degrades to a multi-cycle state machine. For this kernel the II=1 target is achievable because every stage is either a shallow XOR tree or a single BRAM read.

- **`#pragma HLS BIND_STORAGE variable=decoder_lut type=RAM_2P impl=BRAM`**: forces a dual-port BRAM for the decoder table. `RAM_2P` (rather than `RAM_1P`) gives you an idle second port that you'll use when you extend to two parallel decoders per unit.

- **`#pragma HLS ARRAY_PARTITION variable=x_err complete`** and same for `z_err`: tells HLS the 9-bit array is really 9 independent 1-bit wires, not a memory. Without this, HLS would try to infer a tiny BRAM for a 9-entry array and your XOR tree would become a state machine reading out one bit at a time.

- **`#pragma HLS INLINE`** on helper functions: merges them into the parent dataflow region so pipelining can see across function boundaries. Same reason you use it in v05's `apply_single_gate`.

- **`#pragma HLS LATENCY min=0 max=5`** on the top-level: tells the scheduler to try to hit ≤5 cycles end-to-end. If it misses, it complains at synthesis time instead of silently shipping a slow design.

Contrast with v05: your simulator uses `#pragma HLS DEPENDENCE` heavily because HBM bank pointers create *false* loop-carried dependencies that HLS can't prove away. Here there is no HBM and no loop carry, so no DEPENDENCE pragmas are needed. That alone is a reason this kernel will route cleanly.

---

## 5. Python host — matching `fpga_simulator_v05.py`

`shor_qec_host.py` uses the same PyXRT pattern your v05 host uses:

1. Look up the device, open the `.xclbin`, grab the UUID, create a kernel handle (`xrt.kernel(dev, uuid, "shor_qec_kernel")`).
2. Create a single `xrt.run()` per shot, pack the 32-bit input register with the error masks, `start()`, `wait()`, read the 32-bit output register.
3. For a Monte Carlo experiment, loop. There is no HBM buffer allocation at all — this is a pure AXI-Lite kernel, so the host code is about 30% of the size of your v05 driver.

It produces a `p_logical` vs `p_physical` curve over `{0.001, 0.005, 0.01, 0.05}` for 10 000 shots per point, plots it on a log-log axis, and overlays the `d=3` surface code curve from `cudaqx_qec_v6_threshold.png` if you pass the PNG path. The style matches your existing plotter down to the C-DAC NQM footer.

---

## 6. Generalization roadmap

### 6.1 Arbitrary stabilizer codes — store `H` in BRAM

For any `[[n,k,d]]` code, put `H_X` and `H_Z` in two BRAM arrays of shape `[n_stab][n]`, each row stored as an `n`-bit word. Syndrome extraction becomes:

```cpp
for (int r = 0; r < n_stab; ++r) {
#pragma HLS PIPELINE II=1
    ap_uint<n> masked_x = H_Z_rows[r] & x_err;   // row r of Z-type checks
    ap_uint<n> masked_z = H_X_rows[r] & z_err;   // row r of X-type checks
    syndrome[r] = xor_reduce(masked_x) ^ xor_reduce(masked_z);
}
```

`xor_reduce` is HLS-native (`.xor_reduce()` on `ap_uint`). This is exactly the pattern a classical LDPC syndrome extractor uses. At II=1 you get one syndrome bit per cycle; for `n_stab = 72` (BB[72,12,6]) that is 72 cycles = 240 ns. Still sub-microsecond.

### 6.2 Replacing the LUT with on-chip BP for QLDPC

For `d > 3` the LUT blows up and you need iterative decoding. Belief propagation on the Tanner graph is the standard answer. Rough budget on a U55C for BB[72,12,6]:

| resource | estimate | U55C budget | % |
|---|---|---|---|
| BRAM (messages, 72×72 × 64-bit fixed) | ~40 blocks | 2016 | 2% |
| DSP48 (log/exp table + multiply-add) | ~200 | 9024 | 2% |
| LUT6 (Tanner-graph permutation network) | ~120 k | 1 305 k | 9% |
| FF | ~180 k | 2 610 k | 7% |
| iterations per shot | 30 | — | — |
| latency per iteration (target) | 50 ns (15 cycles @ 300 MHz) | — | — |
| total decode latency | ~1.5 µs | — | — |

Your GPU pipeline (BB[72,12,6] at ~50 ms/shot in `qldpc_qec_pipeline.py`) is **~30 000× slower per shot** than this FPGA target. That is the real reason to move QEC to FPGA: GPU is fine for simulation-time threshold scans, but an actual quantum computer needs a decoder inside its real-time control loop, and "real-time" for superconducting qubits means sub-microsecond.

### 6.3 Integrating with your v05 statevector kernel via HBM ping-pong

Once the Shor (or BP) kernel works standalone, wire it into v05 as a second compute unit on the same xclbin:

```
  ┌──────────────────┐                      ┌─────────────────┐
  │ v05 simulator CU │                      │  QEC decoder CU │
  │                  │                      │                 │
  │ computes amps    │   HBM[14]:syndromes  │  reads syndromes│
  │ measures anc     │ ───────────────────▶ │  decodes        │
  │                  │                      │                 │
  │ applies corr.    │ ◀─────────────────── │  writes corr.   │
  │                  │   HBM[15]:corrections│                 │
  └──────────────────┘                      └─────────────────┘
        ▲                                          ▲
        │                                          │
   HBM[0..13]                                   AXI-Lite
   statevector                                  control
```

HBM[14] and HBM[15] become the ping-pong region. The simulator CU writes a 16-byte syndrome record every time a stabilizer round completes; the decoder CU polls for it (or is kicked by an AXI-Lite doorbell), runs, writes back a 16-byte correction, the simulator reads it back and XORs it into its error-tracking frame. The simulator never applies actual Pauli gates to the statevector for corrections — that's the Pauli-frame-tracking optimization, and it means each correction is a few register updates rather than 2^N amplitude rewrites.

### 6.4 GPU vs FPGA — when to use which

| property | GPU (cudaq-qec) | FPGA (this kernel) |
|---|---|---|
| latency per shot | ~0.1–10 ms | ~20 ns – 1 µs |
| throughput at batch size 10 000 | ~10–100 k shots/s | ~100 M shots/s per CU |
| decoder flexibility | any — BP, MWPM, NN, ML | whatever you synthesized |
| development loop | minutes (Python) | hours (HLS) to days (PnR) |
| right for | simulation, threshold scans, decoder research | real-time control loop, production QC |

Your `qldpc_qec_pipeline.py` and `cudaqx_qec_final.py` workflows remain the correct tools for *simulation*: they give you threshold curves with arbitrary decoder swaps in a few minutes. The FPGA kernel is the tool for *deployment*: once a decoder design is locked in, you freeze it into silicon because a real quantum computer can't wait 50 ms for a Python decoder to run between rounds.

---

## 7. Full pipeline diagram

```
                                AXI-Lite write
                                │
                                ▼
                        ┌───────────────┐
                        │ err_in[31:0]  │
                        │  [8:0]  x_err │
                        │  [17:9] z_err │
                        └───────┬───────┘
                                │
                                ▼
              ┌─────────────────────────────────┐
              │  compute_syndrome (1 cycle)     │
              │                                 │
              │   s[0] = x[0]⊕x[1]              │
              │   s[1] = x[1]⊕x[2]              │
              │   s[2] = x[3]⊕x[4]              │
              │   s[3] = x[4]⊕x[5]              │
              │   s[4] = x[6]⊕x[7]              │
              │   s[5] = x[7]⊕x[8]              │
              │   s[6] = x_reduce(z & 0x03F)    │
              │   s[7] = x_reduce(z & 0x1F8)    │
              └────────────────┬────────────────┘
                               │ syndrome[7:0]
                               ▼
                     ┌─────────────────┐
                     │  BRAM decoder   │   ◀── initialized at kernel reset
                     │  256 × 18 bit   │       with the 22 correctable entries
                     │  RAM_2P / BRAM  │
                     └────────┬────────┘
                              │ {z_corr[8:0], x_corr[8:0]}    (2-cycle read)
                              ▼
              ┌─────────────────────────────────┐
              │  apply_correction (1 cycle)     │
              │                                 │
              │   x_fix = x_err ^ x_corr        │
              │   z_fix = z_err ^ z_corr        │
              └────────────────┬────────────────┘
                               │
                               ▼
              ┌─────────────────────────────────┐
              │  logical_readout (1 cycle)      │
              │                                 │
              │   X_log_err = x_fix[0]^[3]^[6]  │  (Z_L = Z0 Z3 Z6)
              │   Z_log_err = xor_reduce(z_fix) │  (X_L = X0..X8)
              └────────────────┬────────────────┘
                               │
                               ▼
                   ┌───────────────────────┐
                   │      result[31:0]     │
                   │ [ 8: 0] x_corr        │
                   │ [17: 9] z_corr        │
                   │ [25:18] syndrome      │
                   │ [26]    X_log_err     │
                   │ [27]    Z_log_err     │
                   │ [31:28] reserved      │
                   └───────────────────────┘
                               │
                               ▼
                       AXI-Lite read
```

Total: **5 cycles end-to-end at 300 MHz ≈ 17 ns**. II=1.
