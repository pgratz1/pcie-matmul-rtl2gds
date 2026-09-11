# Phase 4 — Gate-level simulation report

**Owner:** validation-specialist
**Date:** 2026-09-11
**Netlist:** `results/sky130hd/pcie_matmul/base/6_final.v` (7.1 MB, 76,784 std
cells, 6,616 flops, N = 8)
**SDF:** `6_final.sdf` (30 MB, 112,854 `(CELL`, 191,054 `IOPATH`)
**Simulator:** Icarus Verilog 12.0 + cocotb 2.1.0

---

## Verdict (re-run, 2026-09-11 — supersedes the run-1 verdict below)

| Item | Result |
|---|---|
| Gate wording: "gate-level sim of at least the smoke test passes on `6_final.v` with SDF or unit delays" | **MET** — with **SDF**, and with far more than the smoke test |
| Is the netlist functionally the design? | **YES.** 4/4 smoke + **18/18 `test_matmul`** + 4 independent full 8×8 random matmuls vs the golden model, all on the netlist |
| **C row 6 — the BUG-007 regression** | **CORRECT.** Called out explicitly in §Re-run below |
| Recommendation | **Phase 4 gate item is met.** Sign-off may proceed |

> The verdict below is run 1's and is retained as the record of BUG-007.
> Run 1's artifacts are preserved as `base_prebug007_negctrl/`.

---

## Re-run against the fixed netlist (2026-09-11)

**Delays: SDF back-annotated** (not unit delays), same three-fix model approach
as run 1. The 21 new cell strength-variants required regenerating
`tb/gl/models_sdf` — `build_sdf_models.py` patched **124** strength-qualified
wrappers, up from 118. Compile 7.0 s → 308 MB `.vvp`.

### Annotation rate

| | run 1 | re-run |
|---|---|---|
| SDF `(CELL` entries | 112,854 | 116,058 |
| `IOPATH` entries | 191,054 | 198,657 |
| annotation failures | 6,616 | 6,680 |
| **annotated** | **94.1%** | **94.2%** (109,378 / 116,058) |

The 21 new variants did **not** change the failure mode. The failures are again
**exactly the flop count** — 6,680 `dfxtp` instances, 6,680 warnings — and again
the same cause: ORFS's flattened, escaped dotted instance names
(`\u_app_bar0.beat_cnt[0]$_SDFFE_PP0P_`), which Icarus's SDF parser splits on
the `.` instead of honouring the backslash escape. Combinational logic and the
clock tree are annotated; flop clock-to-Q is not. Tool limitation, not a netlist
property, and immaterial here because Icarus implements no timing checks at all
— timing sign-off is OpenSTA's and it is closed (0 setup / 0 hold, +0.05 ns).

### What was run

| Stimulus | Result | Sim wall |
|---|---|---|
| `test_smoke` (4) | **4/4 PASS** | |
| `probe_gl_row` — full random 8×8 matmul, A/B read back first, C vs golden | **PASS** | |
| `probe_gl_drain` — 3 more random 8×8 matmuls, C pre-loaded with a sentinel, per-row verdict | **PASS** — "all 3 trials matched golden exactly" | |
| `probe_gl_xprop` (3 X tests incl. internal census) | **3/3 PASS** | run total 4 m 36 s |
| `probe_gl_pe_x` — explicit-path PE scan | **PASS** | |
| **`test_matmul` — the entire module, 17 tests** | **17/17 PASS** | run total 4 m 40 s |

**Total: 22 distinct gate-level tests, all passing, ~10 min including two 92 s
SDF loads.**

The full `test_matmul` module matters because it contains
`test_matmul_c_addressing_and_persistence`, whose three complementary operand
patterns (row-varying, lane-varying, two-index) exist specifically to detect any
row permutation, lane permutation, transposition or drain-order reversal. It
passes on the netlist.

### C row 6 — the BUG-007 regression, explicitly

**Correct.** Four independent checks agree:

1. `probe_gl_drain` pre-loads every C word with a sentinel and runs three random
   operand pairs. Run 1 reported `trial N: C row 6 -> drain wrote ZEROS`. The
   re-run reports **"all 3 trials matched golden exactly"** — no row deviates.
2. `probe_gl_row`: a full random 8×8 matmul matches golden in all 64 elements
   (run 1: 8 of 64 differed, all in row 6, all DUT 0).
3. Explicit-path scan of the netlist's PE registers:
   `a_reg per row: [56, 56, 56, 56, 56, 56, 56, 56]` — **uniform**. Run 1's row 6
   had none. `acc_reg` is 256 per row, `v_reg` 7 per row, both uniform.
4. Static census of `6_final.v`: 56 `a_reg` nets in every one of the 8 rows.

### One anomaly checked rather than waved past

The same scan shows `b_reg per row: [64, 64, 64, 64, 64, 64, 64, 0]` — row 7 has
no `b_reg`. Given BUG-007 was exactly "a register missing from one row", this
was checked rather than assumed benign:

- It is **pre-existing, not new**: the preserved `base_prebug007_negctrl/`
  netlist has the identical `row7_b_reg=0`, and row 7 computed correctly there
  even while row 6 was broken.
- It is **expected by construction**: B flows north→south, so the south row's
  `b_out` has no consumer — one of the three `UNUSEDSIGNAL` suppressions already
  documented in `rtl/README.md`. Yosys forwards the value rather than registering
  it onward.
- It is **functionally disproven as a defect**: row 7 is correct in every random
  matmul and in the permutation-sensitive `c_addressing` patterns.

### X-propagation, corrected method

- **Zero X on every top-level output**, every cycle, for 200 cycles after reset,
  and again with `rst` held the REQ-109 minimum of 2 cycles.
- **Explicit-path PE scan reaching all 8 generate rows** (the method that
  replaces Phase 3's under-sampling walk): 1,088 PE nets across rows 0–7,
  signals `prod`, `v_in`, `v_out` — **zero X by signal, zero X by row**.
- Internal census: **256 of 51,138 nets X, static** — identical at reset+3 and
  reset+100. Same benign residue as run 1 (256 of 49,112): anonymous internal
  nets of the 64 Han-Carlson adder macros, masked by the accumulator's
  reset/enable mux, never reaching a flop or an output.

### One failure, triaged to my own harness

`probe_gl_pe_x` failed on its first run asserting `a_reg absent from the
netlist` — the BUG-007 signature. It was **my probe that was wrong**: at gate
level the PE registers survive only as flop *instance* names, which carry no
`.value`, so a net-only scan cannot see them while combinational `prod`/`v_in`/
`v_out` survive as readable nets. Fixed to scan both populations; it then
reported the uniform `a_reg` counts above. Recorded because a false BUG-007
signature is exactly the kind of thing that should not be quietly edited away.


The smoke test passes because it sets one non-zero operand (`A[0][0]=7`,
`B[0][0]=6`) and therefore *expects* zeros everywhere else — a permanently-zero
row 6 is invisible to it. Running more than the floor is what caught this.

---

## What was run

| # | Stimulus | Delays | Result | Wall time |
|---|---|---|---|---|
| 1 | `test_smoke` (4 tests, incl. a full matmul) | **SDF** | **4/4 PASS** | 1 m 43 s |
| 2 | `probe_gl_xprop` (3 X-propagation tests) | **SDF** | **3/3 PASS** | 3 m 37 s |
| 3 | `test_regs` (16 tests) + X-naming probe | **SDF** | **14/16** — 2 fail | 3 m 08 s |
| 4 | `test_regs` (15 tests) | none (zero delay) | **13/15** — same 2 fail | 47 s |
| 5 | `p_gl_ab_readback_then_matmul` | none | FAIL (by design — isolates the defect) | 13 s |
| 6 | `p_gl_drain_vs_compute`, 3 random operand pairs | none | FAIL (by design) | 24 s |
| 7 | `p_gl_identify_x` (40,848 cell instances scanned) | SDF | PASS | 9 m 36 s |

Compile: 5.8 s, producing a 262 MB `.vvp`. SDF annotation: **92 s**, once per
`vvp` invocation. Total GL work this phase: ~25 min.

**Skipped, deliberately:** the full `test_matmul` and `test_stress` modules.
`test_matmul_soft_reset_during_drain` alone costs ~2 min at RTL and GL is
~10–50× slower; with BUG-007 open, more failing runs would add cost and no
information. `test_stress` at 120 ops would be tens of minutes. Both should run
once BUG-007 is fixed.

---

## SDF: how it was made to work, and what it does not cover

**Icarus implements no timing checks.** Measured with a 20-line testcase before
touching the netlist:

```
warning: Timing checks are not supported and delayed signal "CLK_delayed"
         will not be driven.
```

This matters because the **default** sky130 `behavioral` cell models clock from
`D_delayed`/`CLK_delayed`, nets driven *only* as the delayed-signal outputs of
`$setuphold`. Under Icarus they stay undriven, so every flop output is X and
the whole netlist is dead. The `functional` models (`-DFUNCTIONAL`) wire D/CLK
straight through and work — but ship **no `specify` block**, so `$sdf_annotate`
has nothing to attach to and the run silently degrades to zero delay.

Neither stock flavour gives an annotated run. `tb/gl/build_sdf_models.py`
builds a third: the **functional** body plus a `specify` block containing only
the *module path* declarations from each cell's own `.specify.v`, timing checks
filtered out. 118 strength-qualified wrappers patched. Two further traps, both
silent:

- `iverilog -gspecify` is **required**; without it Icarus drops every specify
  block and prints `Omitting $sdf_annotate() since specify blocks are being
  omitted.` — no other symptom, and the run is un-annotated.
- The specify block must go in the **strength-qualified** module (`..._1`,
  `..._8`), because that is what the SDF's `(CELLTYPE ...)` names.

**Coverage achieved: 106,238 of 112,854 cells annotated (94.1%).** The
remaining **6,616 — exactly the flop count — fail**, all with
`SDF WARNING: Cannot find u_app_bar0 in scope gl_top.dut`. Cause: ORFS flattens
the hierarchy into escaped instance names containing dots
(`\u_app_bar0.beat_cnt[0]$_SDFFE_PP0P_`), and OpenSTA correctly escapes them in
the SDF (`(INSTANCE u_app_bar0\.beat_cnt\[0\]\$_SDFFE_PP0P_)`). **Icarus's SDF
parser does not honour the backslash escape on the divider character**, splits
on the `.`, and looks for a scope `u_app_bar0` that a flat netlist does not
have. So every flop's clock-to-Q `IOPATH` is un-annotated while the combinational
logic and the clock tree are annotated.

This is a **tool limitation, not a netlist problem**, and it does not weaken the
conclusions: Icarus cannot check setup or hold at all, so GL sim here is a
*functional* equivalence check. Timing sign-off is OpenSTA's, and it is done
(0 setup / 0 hold, WNS/TNS 0.00, worst slack +0.30 ns).

---

## X-propagation

RTL found zero X. Gate level, with real `sky130_fd_sc_hd__dfxtp_*` flops that
have **no reset pin** and start at X, is the unforgiving version:

- **Zero X on every top-level output, every cycle, for 200 cycles** after reset
  release, with no stimulus at all. `rx_tlp_ready`, `tx_tlp_valid/sop/eop`, all
  32 bits of `tx_tlp_data`, `irq`.
- **Zero X with `rst` held the REQ-109 minimum of 2 cycles**, not just a
  comfortable 5.
- **No flop output is X.** 40,848 cell instances scanned; the only X outputs
  are on 64 combinational Yosys `ALU_16_..._HAN_CARLSON` adder macros, one per PE.
- **Residual X is 256 nets out of 49,112, and static** — identical at reset+3
  and at reset+100. It does not spread. All 256 are *anonymous* synthesis nets
  (`_NNNNN_`); **not one RTL-named net is X**.

This is X-pessimism inside the mapped carry chains, masked by the accumulator's
reset/enable mux before it can reach a flop. It is a genuine RTL-vs-GL
difference — a direct RTL check of all 64 PEs (`prod`, `acc`, `a_reg`, `b_reg`,
`v_reg`) finds **zero** X, so it is introduced by mapping `a*b` into a
Han-Carlson structure. It is benign: a full matmul computes correctly through
those same adders for rows 0–5 and 7.

Note this also corrects a Phase 3 result: that scan reported "604 value-bearing
signals", which was too few for 64 PEs — it never descended into the generate
scopes. Re-run by explicit path, RTL is still clean, but the Phase 3 number was
an under-sample and should not be quoted as exhaustive.

---

## BUG-007 (summary; full entry in `docs/bugs.md`)

PE row 6 has **no `a_reg`** in the netlist — 0 nets, against 56 in every other
row — so it never receives an A operand, accumulates 0, and the drain writes
zeros. Triaged away from the harness step by step: operands read back correct
before START; a sentinel pre-loaded into C is *overwritten* by the drain, so the
drain fires and writes zero; identical with and without SDF; C reads a clean 0,
not X. **Present already in `1_2_yosys.v`, so it originates in synthesis, not
P&R.** Routed to circuit-designer.

---

## Harness

All new files are under `tb/gl/`, deliberately separate from `tb/`, and the RTL
suite is untouched (still 72/72). `rtl/` and `flow/` were not modified;
`results/` was not deleted.

| File | Purpose |
|---|---|
| `tb/gl/Makefile` | `make -C tb/gl test-gl [TEST=...] [SDF=]` |
| `tb/gl/gl_top.v` | wrapper with matmul_top's exact port list, so every existing cocotb test binds unchanged; `$sdf_annotate` selected at run time via `+sdf=` so one build serves both modes |
| `tb/gl/build_sdf_models.py` | generates `tb/gl/models_sdf/` from the read-only `flow/gl_models/` |
| `tb/gl/build_gl.sh` | standalone compile, outside cocotb |

The RTL suite runs against the netlist **unmodified** because `tb/` only ever
touches top-level ports — never internal hierarchy. That was worth the
discipline.
