# Phase 4 — Gate-level simulation report

**Owner:** validation-specialist
**Date:** 2026-09-11
**Netlist:** `results/sky130hd/pcie_matmul/base/6_final.v` (7.1 MB, 76,784 std
cells, 6,616 flops, N = 8)
**SDF:** `6_final.sdf` (30 MB, 112,854 `(CELL`, 191,054 `IOPATH`)
**Simulator:** Icarus Verilog 12.0 + cocotb 2.1.0

---

## Verdict

| Item | Result |
|---|---|
| Gate wording: "gate-level sim of at least the smoke test passes on `6_final.v` with SDF or unit delays" | **Literally MET** — `test_smoke` 4/4 with SDF back-annotation |
| Is the netlist functionally the design? | **NO — BUG-007.** PE row 6 computes zero. Deterministic, reproduced on 3 operand pairs, with and without SDF |
| Recommendation | **Do not sign off Phase 4.** The gate's floor passes on a netlist that returns the wrong answer for 1/8 of every matrix |

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
