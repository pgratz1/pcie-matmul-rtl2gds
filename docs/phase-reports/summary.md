# Phase 5 — Sign-off summary

**Project:** PCIe-attached matrix multiplier, RTL to GDS-II
**Date:** 2026-09-11
**Author:** orchestrator
**Status:** all phase gates met; GDS-II signed off

---

## 1. Final numbers

| Metric | Value |
|--------|-------|
| Platform | sky130hd (ORFS, OpenROAD 26Q3-1985-gc3e680b01b) |
| Array | 8 x 8 systolic, output-stationary, INT8 x INT8 -> INT32 |
| **Target clock** | **100 MHz (10.000 ns)** — met, no relaxation used |
| Core fmax (reg-to-reg) | **125.69 MHz** (period_min 7.96 ns) |
| I/O-path fmax | 100.52 MHz (9.95 ns), against a self-imposed 40% I/O budget |
| Setup / hold violations | **0 / 0** (WNS 0.00, TNS 0.00, worst setup +0.05 ns, worst hold +0.43 ns) |
| **Die area** | **1,525,570 um^2** (1235.14 x 1235.14 um, measured from the GDS bbox) |
| **Utilization** | **40.38%** (`CORE_UTILIZATION` = 35; ORFS auto-sized the die) |
| **Cell count** | **55,457** ABC-mapped standard cells |
| Flip-flops | 6,680 (`sky130_fd_sc_hd__dfxtp_1`) |
| **Power estimate** | **78.0 mW** (56.0 mW internal, 22.0 mW switching, 0.257 uW leakage) |
| DRC | **0** router, **0** KLayout sign-off deck |
| Antenna | **0** net violations, **0** pin violations (53 -> 5 -> 0, 149 diodes) |
| Operation latency | 34 cycles at N=8 (`4N+2`), 340 ns at 100 MHz |

**Verification at sign-off:** 72/72 RTL tests at N = 2, 4, 8, 16 across two seeds;
72/72 post-synthesis replay at all four N; 22 gate-level tests with SDF
back-annotation (94.2% of cells annotated), including the full `test_matmul`
module and four independent random 8x8 matmuls against the golden model.
127/127 requirements mapped, 126 verified by test and REQ-077 by code review.
7 bugs found, 7 closed.

---

## 2. Every deviation from the original specification

The parameters table in `CLAUDE.md` at kickoff is the baseline. Nine deviations,
each recorded as a dated decision.

| # | Baseline | Delivered | Why | Ref |
|---|----------|-----------|-----|-----|
| 1 | Simulator: **Verilator** + cocotb | **Icarus Verilog 12.0** + cocotb | cocotb 2.1.0 hard-errors below Verilator 5.036; this machine has 5.032 and apt offers no newer. Python 3.14 is the only interpreter, and 2.1.0 is the only release with a cp314 wheel, so downgrading cocotb was not available either. Verilator remains the linter. | DEC-001 |
| 2 | Boundary: **PIPE interface** | **Raw-TLP 32-bit DWORD stream** | `cocotbext-pcie` 0.2.16 contains no PIPE interface at all. `CLAUDE.md` required both "boundary is PIPE" and "a boundary cocotbext-pcie can attach to"; these proved mutually exclusive and the second won, making the sanctioned TLP-level fallback mandatory. | DEC-002 |
| 3 | — | **Option B over Xilinx CQ/CC** | The Xilinx descriptor format lives in PG213, absent from this machine, so attaching the vendor model would have added *unverifiable* bit-layout risk. Option B also keeps TLP parse/build and the Type 0 config space in the design, as `CLAUDE.md`'s layering assigns. | DEC-003 |
| 4 | Array: **16 x 16** | **8 x 8**, genuinely parameterized over {2,4,8,16,32} | Icarus is roughly an order of magnitude slower than Verilator would have been; N=16 costs ~48 min per suite run. Explicitly sanctioned at kickoff. | DEC-004 |
| 5 | Data link layer in RTL | **Behavioral DLL only; zero DLLPs at the pin boundary** | Follows from deviation 2. | DEC-002 |
| 6 | — | **No MSI; status bit + level `irq` pin** | No capability list at all in v1. | DEC-008 |
| 7 | On-chip **SRAM** for A/B/C | **Flip-flop register files** | Avoids `sky130ram` macro integration entirely; at N=8 the cost is ~6.7k flops, which the area budget absorbed at 40% utilization. | DEC-010 |
| 8 | — | **`IOWr` treated as posted** | PCIe Base makes `IOWr` non-posted. Deliberate v1 simplification, recorded rather than silently deviated. | DEC-013 |
| 9 | **DMA** (stretch goal) | **Not implemented** | Gated on Phase 4 passing; adopting it would reopen DEC-007 and DEC-008. | OQ-003 |

The specification itself went from **v1.0.0 (121 requirements) to v1.1.4 (127)**
across five amendment rounds. No requirement was ever renumbered or repurposed,
so the test-to-requirement mapping stayed stable throughout.

---

## 3. Agent invocations per phase

Counted from the orchestrator's own dispatch log. "Invocation" = one launch or
one resume with a new brief.

| Phase | Invocations | Breakdown |
|-------|-------------|-----------|
| 0 Environment | 2 | validation-specialist x2 |
| 1 Spec | 1 | spec-writer x1 |
| 2 RTL + tests | 2 | rtl-designer x1, test-writer x1 (parallel) |
| 2b Review | 12 | rtl-reviewer x2, spec-writer x4, rtl-designer x3, test-writer x3 |
| 3 Validation | 6 | validation-specialist x2, test-writer x3, spec-writer x1 |
| 4 Physical | 6 | circuit-designer x2, validation-specialist x3, rtl-designer x1 |
| 5 Sign-off | 0 | orchestrator |
| **Total** | **29** | spec-writer 6, test-writer 6, validation-specialist 6, rtl-designer 5, rtl-reviewer 2, circuit-designer 2 |

Phase 2b dominates the count. That is not waste: it is where the parallel-authored
spec, RTL and tests were reconciled, and it caught three arithmetically impossible
requirements and two requirement-overlap defects before any of them reached validation.

**Iteration limits:** the 5-cycle debug limit was never reached (worst case: 1 cycle).
The 4-iteration physical closure limit was never reached — **0 of 4 used on both
P&R runs**; 100 MHz closed first try each time.

---

## 4. What actually caught the defects

Worth recording, because it is the argument for the process.

| Defect | Found by | Would the "obvious" check have caught it? |
|--------|----------|-------------------------------------------|
| **BUG-007** — synthesized design computed C row 6 as always zero; at N=16 and N=32 it lost 2 and 4 operand ports respectively | Gate-level simulation running a **full matmul**, beyond the gate's stated floor | **No.** Lint clean, `yosys check` reported "0 problems", and all 72 RTL tests passed. The smoke test — the gate's literal requirement — passed on the broken netlist, because it sets only `A[0][0]`/`B[0][0]`. |
| **BUG-001** — `make test N=<n>` never rebuilt the simulation binary | Validation specialist re-running the N-sweep with a forced rebuild | **No.** Every prior "passes at N=4/N=16" result was the N=8 binary re-run, including results the orchestrator had reported as verified. |
| REQ-119, REQ-120 arithmetically impossible | Test author working from the spec, unable to write the test | **No.** Both read as plausible prose. |
| PRIME-vs-FETCH double-accumulate | RTL author refusing to implement §12.5 literally, then the reviewer confirming independently | **No.** The spec was wrong; following it would have produced silently wrong results. |
| REQ-042/126 and REQ-070/124 overlaps | Code review, then a requested sweep for the same defect *class* | Partially — the first was found by review; the second only by deliberately hunting the pattern. |

Three of these were invisible to every automated check in the flow.

---

## 5. What I would change about the process

**1. Add a post-synthesis replay gate between Phase 3 and Phase 4.** This is the
single highest-value change. `tb/gl/postsyn_replay.sh` — built by the validation
specialist in response to BUG-007 — replays the full 72-test suite against a Yosys
netlist using `simcells.v`, with **no PDK and ~90 seconds** of runtime versus 1 h 49 min
for a full ORFS run. It would have caught BUG-007 immediately instead of after a
complete physical flow plus gate-level bring-up. It proved itself on first use: the
circuit designer ran it as a pre-flight before the second flow. `CLAUDE.md`'s Phase 3
gate should require it, not just `yosys synth` completing — "synthesis completes with
no unsupported constructs" is a much weaker claim than it sounds, since `check`
reported 0 problems on a design that computed one-eighth of every matrix wrong.

**2. Phase gates should name the *strength* of a test, not just its existence.**
The Phase 4 gate said "gate-level sim of at least the smoke test passes." Taken
literally, that would have signed off a broken chip. The smoke test is the weakest
test in the suite and structurally incapable of detecting a whole-row fault. Gates
should say what a test must *distinguish*, not merely that it passes.

**3. Make "check the pattern, not the instance" a standing rule.** Twice, asking
"does this defect class appear anywhere else?" found more than the original report:
the REQ-070/124 overlap (after REQ-042/126), and the N=16/N=32 exposure of BUG-007
(the report was only about row 6 at N=8). The second one mattered — fixing only the
reported symptom would have shipped the same latent bug at every other array size.

**4. Require measurement before speculative fixes.** Three confident structural
claims were refuted by measurement: the reviewer's `WIDTHCONCAT` call (the warning
does fire, but only at N=32), its cell-delta hypothesis (`mem_c` synthesizes
identically under all three reset forms), and my own root-cause guess for BUG-007
(`mm_ctrl`'s wrap test — actually a Yosys `peepopt` bug in `mem_a`). Each cost
minutes to check and would have cost a change to working code otherwise.

**5. Keep agents blind to each other's work — it paid for itself.** The RTL and test
authors worked in parallel from the spec alone. That independence is what surfaced
six spec under-determinations in Phase 2, and why the tests were a genuine check
rather than a restatement of the implementation. Both agents independently diagnosed
the REQ-123 off-by-one from different evidence.

**6. Upgrade Verilator if this project continues.** DEC-001 forced Icarus, which
costs ~48 min per N=16 suite run and makes N=32 (~6-8 h) effectively untestable.
Building Verilator 5.038 from source is the highest-leverage remaining change to
verification throughput. Not done here: a from-source toolchain change mid-project
carried more risk than it was worth once the flow was closing.

**7. One process failure to own.** The orchestrator reported N-sweep results as
verified when they were an artifact of BUG-001, and separately cited distinct binary
hashes as proof of per-N rebuilds — unsound, since `iverilog` output is not
byte-reproducible. Both were caught downstream (the second by the test author
volunteering that its own headline evidence was weak). The lesson is that
*verifying a claim* and *verifying the evidence for a claim* are different acts,
and the orchestrator should do the second on anything it repeats upward.

---

## 6. Artifacts

| Item | Path |
|------|------|
| GDS-II | `results/sky130hd/pcie_matmul/base/6_final.gds` (75 MB) |
| Gate netlist + SDF | `results/sky130hd/pcie_matmul/base/6_final.{v,sdf,spef}` |
| BUG-007 negative control | `results/sky130hd/pcie_matmul/base_prebug007_negctrl/` |
| Specification | `docs/spec.md` v1.1.4, `docs/register-map.md` v1.1.4 |
| Decision log | `docs/decisions.md` (DEC-001 … DEC-018, OQ-001 … OQ-004) |
| Bug ledger | `docs/bugs.md` (BUG-001 … BUG-007, all CLOSED) |
| Test plan | `tb/TESTPLAN.md` (127/127 mapped) |
| Phase reports | `docs/phase-reports/` (7 reports) |
| Flow config | `flow/config.mk`, `flow/constraint.sdc`, `flow/README.md` |
| Post-synthesis replay | `tb/gl/postsyn_replay.sh` |
