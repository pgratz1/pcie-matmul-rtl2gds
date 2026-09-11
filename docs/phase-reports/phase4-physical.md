# Phase 4 — Physical design (RTL to GDS-II)

Owner: circuit-designer. Platform **sky130hd**, design `matmul_top`, `N = 8`,
target **100 MHz / 10.000 ns** (spec v1.1.4 §13.2, DEC-009).

> **Run 2 (2026-09-11, post-BUG-007).** Run 1 completed clean but was built from
> a netlist containing BUG-007 — a Yosys `peepopt` mis-transformation in `mem_a`
> that deleted PE row 6's A operand. Run 1's layout is **preserved** as the
> BUG-007 negative control (see §10); nothing was deleted. This report describes
> **run 2**, on the fixed RTL, and calls out every delta.
>
> **Still 0 of 4 closure iterations used.** No config change was needed and none
> was made.

## 0. Headline

**The target clock closed again on the fixed RTL, first try. No relaxation; the
DEC-009 ladder is still not invoked.** Zero setup, zero hold, zero router DRC,
zero KLayout DRC, and — an improvement over run 1 — **zero antenna violations**.

| Gate criterion (CLAUDE.md Phase 4) | Result |
|---|---|
| Flow completes through `6_final.gds` | **MET** — 75 MB GDS, single top cell `matmul_top`, 1235.14 x 1235.14 um |
| Zero DRC violations from ORFS's checker | **MET** — router `5_route_drc.rpt` empty; KLayout `6_drc_count.rpt` = 0 |
| Zero setup/hold violations at the recorded target clock | **MET** — `setup_violation_count 0`, `hold_violation_count 0` at 10.000 ns |
| Gate-level sim of the smoke test on `6_final.v` | **Handed off.** De-risked: §7. |

## 0b. Run 2 vs run 1 — every number that moved

| Metric | Run 1 (BUG-007 netlist) | Run 2 (fixed) | Delta |
|---|---|---|---|
| Yosys generic cells (coordinator's figure) | 70,148 | 75,665 | +7.9% |
| **ABC-mapped cells** | 53,880 | **55,457** | **+2.9%** |
| Flip-flops | 6,616 | **6,680** | +64 |
| Synth cell area (um^2) | 518,645 | **535,061** | +3.2% |
| Placed std-cell instances | 76,784 | **78,892** | +2.7% |
| Total placed instances | 221,018 | **227,573** | +3.0% |
| Die area (um^2) | 1,478,510 | **1,525,570** | +3.2% |
| Die side (um) | 1215.94 | **1235.14** | +1.6% |
| Final utilization | 40.46% | **40.38%** | flat |
| Worst setup slack (ns) | +0.30 | **+0.05** | -0.25 |
| Reg-to-reg `period_min` (ns) | 8.20 (121.98 MHz) | **7.96 (125.69 MHz)** | **faster** |
| Worst hold slack (ns) | +0.42 | **+0.43** | flat |
| Antenna violations | 1 | **0** | **fixed** |
| Total power (mW) | 77.8 | **78.0** | +0.3% |
| Flow runtime | 6,526 s | 6,573 s | +0.7% |

The +2.9% mapped-cell growth is smaller than the +7.9% the coordinator measured
on generic `synth -flatten` cells, because ABC re-maps the explicit N-way mux
more efficiently than the generic-cell count suggests: `mux4_2` actually fell
240 -> 144 and `mux2i_1` 2,299 -> 2,082, while total logic still rose.

**Note the direction of the two timing numbers.** The *core* got faster
(reg-to-reg fmax 121.98 -> 125.69 MHz): the explicit mux is a better structure
than the `$shiftx` it replaced. Worst slack nevertheless fell to +0.05 ns
because the binding path is not core logic at all — see §6.

## 1. Deliverables

| File | What it is |
|------|-----------|
| `flow/config.mk` | ORFS design config. `DESIGN_NAME = matmul_top`, `DESIGN_NICKNAME = pcie_matmul`. |
| `flow/constraint.sdc` | One `create_clock` at 10.000 ns + virtual I/O clock; I/O delays at 40% of period; **no timing exceptions at all**. |
| `flow/README.md` | Run commands, results locations, runtimes, GL-sim model caveat. |
| `flow/make_gl_models.sh` | Fetches the sky130 cell simulation models the GL sim needs (they are not on this machine). |
| `flow/gl_models/` | The fetched models: 70 base cells, 119 strength variants, 8 UDP primitives. |

Two notes on the config:

* **The top module is `matmul_top`, not `pcie_matmul_top`.** The Phase 4 brief's
  boilerplate named the latter; `rtl/matmul_top.sv` and the entire testbench use
  the former, so the RTL wins.
* **`VERILOG_FILES` is generated from `rtl/filelist.f`** at make time
  (`$(shell cat ...)`), not copied. The flow and the simulation therefore cannot
  drift apart in file set or compile order.

`SYNTH_PARAMETERS = N=8 DW=8 ACCW=32` sets the array size at elaboration
(REQ-113); `IDXW` is left derived, as `rtl/README.md` requires. **No `rtl/` file
was modified, and no RTL change is being requested.**

## 2. Two configuration errors, found and fixed before the real run

Neither is a closure iteration; both were mechanics bugs in what I wrote,
caught by reading the failing stage's log.

1. **`SWAP_ARITH_OPERATORS = 1` without `OPENROAD_HIERARCHICAL = 1`.**
   `synth_odb.tcl` rejects the combination by name. All three sky130hd reference
   designs set both. Fixed by setting both.
2. **`make -j16` breaks the ORFS dependency graph.** It fails with
   `No rule to make target '.../2_1_floorplan.sdc', needed by '.../2_floorplan.sdc'`.
   `2_1_floorplan.sdc` is a *side product* of the rule whose declared target is
   `2_1_floorplan.odb` (`flow/Makefile` lines 450, 452, 468), so it exists only
   after that rule has run; serial make orders it correctly, `-j` does not.
   **The flow must be run without `-j`.** OpenROAD multi-threads internally.

## 3. Synthesis, and the DEC-014 sizing decision

From `reports/sky130hd/pcie_matmul/base/synth_stat.txt`:

| Metric | Value |
|--------|-------|
| Mapped standard cells | 53,880 |
| Flip-flops (`sky130_fd_sc_hd__dfxtp_1`) | 6,616 |
| Cell area | 518,645 um^2 (25.5% sequential) |
| Adders | 64 x `ALU_16` + 64 x `ALU_32` Han-Carlson, one pair per PE |
| Latches in the mapped netlist | **zero** |

The "Latch inferred" warnings in `1_2_yosys.log` all name
`share/yosys/choices/han-carlson.v:18` — loop variables inside **Yosys's own**
adder-choice file, not in `rtl/`. The mapped cell list contains no `dlxtp` or
`dlatch` of any kind, which confirms it.

**DEC-014** (in `docs/decisions.md`): keep A/B/C as flip-flops, do not shrink
`N`, do not substitute a platform memory macro. Sequential logic is only a
quarter of the area, so a macro would recover little, and every candidate breaks
the `D_WR = 1` write latency of REQ-122 that 72 Phase 3 tests depend on. This
also resolves the area half of **OQ-002** (0.52 mm^2 of cells vs the 0.35 mm^2
estimate), so the `nangate45` fallback was **not** invoked.
**DEC-015** records the 40%-of-period I/O budget assumption.

## 4. Final results (run 2)

### Timing — at 10.000 ns, typical corner

| Metric | Value |
|--------|-------|
| Setup violation count | **0** |
| Setup WNS / TNS | **0.00 / 0.00 ns** |
| Worst setup slack | **+0.05 ns** |
| Hold violation count | **0** |
| Hold TNS | **0.00 ns** |
| Worst hold slack | **+0.43 ns** |
| `core_clock` min period (reg-to-reg) | 7.96 ns -> **fmax 125.69 MHz** |
| `vclk_core_clock` min period (I/O) | 9.95 ns -> fmax 100.52 MHz |
| Post-CTS clock skew | 0.14 ns |
| max slew / max cap / max fanout violations | 9 / 2 / 0 |

### Area, count, power

| Metric | Value |
|--------|-------|
| Die area | **1,525,570 um^2** (1235.14 x 1235.14 um, measured from the GDS bbox) |
| Core area | 1,512,830 um^2 |
| Standard-cell instances | **78,892** |
| Total placed instances | 227,573 (incl. fill, tap, 149 antenna diodes) |
| Flip-flops | 6,680 |
| Placed instance area | 610,911 um^2 |
| Final utilization | **40.38%** |
| **Total power** | **78.0 mW** — clock 53.4%, sequential 34.2%, combinational 12.4% |
| Flow errors / warnings | 0 / 2 (benign) |

### DRC and antenna

| Check | Result |
|-------|--------|
| Detailed router (`5_route_drc.rpt`) | **0** — file is empty |
| KLayout sign-off deck (`6_drc_count.rpt`) | **0** |
| Antenna (`check_antennas` on `6_final.odb`) | **0 net / 0 pin** |

Detailed routing converged: 51,049 after the 0th optimization iteration, then
33,255 -> 31,224 -> 6,720 -> 1,942 -> 820 -> 380 -> 228 -> 157 -> ... -> **0**,
and re-converged to 0 after each diode-insertion pass. Antenna repair went
**53 -> 5 -> 0** with 149 diodes; run 1's single residual met5 violation
(DEC-017) did not recur, so **DEC-017 is moot** and is marked closed.

## 5. Config changes made this run

**None.** This is a deliberate answer to the coordinator's question, not an
omission:

* `CORE_UTILIZATION` stays at **35**. ORFS sizes the die *from* the cell area at
  that utilization, so a +3.2% cell area automatically produced a +3.2% die and
  held final utilization essentially constant (40.46% -> 40.38%). Raising or
  lowering the number would have changed the one variable that was already
  correct. Routing converged to zero DRC at this density in both runs.
* The floorplan is unchanged — still auto-generated, aspect ratio 1, 2 um
  margin, no macros, no macro placement file.
* `flow/constraint.sdc` is unchanged. In particular the DEC-015 40% I/O budget
  was **not** relaxed, even though it is what consumes the remaining margin;
  see §6.

## 5. The one open item: a residual antenna violation

`check_antennas` on the final database reports **one** violating net:

```
Net: net2802
  Pin: u_app_bar0.u_mem_b.e_rdata[58]$_SDFF_PP0_/D  (sky130_fd_sc_hd__dfxtp_1)
    Layer: met5
      Partial area ratio: 16988.95   Required: 10781.00 (Side area) (VIOLATED)
```

One long met5 segment on the `mem_b` engine-read-data path. ORFS's diode-repair
loop ran to its `MAX_REPAIR_ANTENNAS_ITER_DRT` cap and oscillated 8 -> 1 -> 2 ->
1 without clearing this one; it inserted 242 diodes in the process.

This is **not** counted by either DRC checker — neither the detailed router nor
the sky130hd KLayout deck has antenna rules — so the Phase 4 gate's "zero DRC
violations" criterion is met as written. I am flagging it anyway rather than
letting it pass silently, because a real tapeout would have to clear it.
Cheapest fix is to raise `MAX_REPAIR_ANTENNAS_ITER_DRT` in `flow/config.mk`;
the cost is a full re-route, ~97 minutes. It needs no RTL change. Recommendation:
**accept for v1**, since it is one net out of 76,784 instances and the gate does
not require it.

## 6. The critical path, and the operand mux the coordinator flagged

### Is the new `mem_a`/`mem_b` N-way mux a critical path? Checked explicitly — no.

The coordinator asked for this to be measured rather than assumed. Targeted STA
on the final database, querying every path that *ends* at the operand-mux output
registers:

| Endpoint | Worst slack |
|---|---|
| `u_app_bar0.u_mem_a.e_rdata[51]` | **+2.586 ns** |
| `u_app_bar0.u_mem_a.e_rdata[55]` | +2.788 ns |
| `u_app_bar0.u_mem_b.e_rdata[33]` | **+2.658 ns** |

The mux has ~2.6 ns of margin. It is not a risk, and the structural change made
the core *faster* overall (reg-to-reg fmax 121.98 -> 125.69 MHz).

The mux path does now appear at the top of the reg-to-reg list, but as the
**launch** point, not as the mux itself: the worst reg-to-reg path is
`u_app_bar0.u_mem_a.e_rdata[39]` -> `u_engine.u_array.g_row[4].g_col[0].u_pe.acc_reg[27]`,
slack **+2.04 ns** — that is the registered operand feeding the PE MAC. It
displaced run 1's worst reg-to-reg path (PE `a_reg` -> `acc_reg`, +1.80 ns) and
is *less* critical than what it displaced.

### The actual critical path — unchanged in kind from run 1

```
Startpoint: rst             (input port, clocked by vclk_core_clock)
Endpoint:   tx_tlp_data[8]  (output port, clocked by vclk_core_clock)
Path Group: vclk_core_clock                    slack +0.05 ns (MET)
```

Run 1's was the same path to `tx_tlp_data[20]` at +0.30 ns. It is a pure
input-to-output path: roughly 1.7 ns of silicon, with **8.00 ns of the 10.00 ns
budget consumed by my own `set_input_delay` + `set_output_delay` at 40% of the
period (DEC-015)** — double the 20% every ORFS sky130hd example design uses.

**This is why worst slack fell from +0.30 to +0.05 ns even though the core got
faster.** The margin on this path is set by an assumption I made, not by the
design. At the conventional 20% it would have roughly +4.3 ns. I did **not**
relax it, because it closes as-is and relaxing a constraint to buy margin you
do not need is how a budget assumption quietly becomes a lie. It is recorded
here so that whoever owns the next respin knows exactly which number to move
first, and that moving it is free.

### The five Phase 2b predictions, re-checked against run 2

| # | Predicted path | Verdict in run 2 |
|---|---|---|
| 1 | `mm_pe` multiply -> add -> `acc_reg` | Still the dominant reg-to-reg *family*, now reached via the registered operand, +2.04 ns. Comfortable, still not critical. |
| 2 | `mem_c` 64:1 read mux | Still refuted. `mem_c` appears only as a capture endpoint (`mem[300]`, +1.00 ns). |
| 3 | `d_wr_en` / `clr_acc` fanout | Still refuted: `max fanout violation count 0`. |
| 4, 5 | `tlp_rx` classifier / `reg_file` decode off `rx_tlp_data` | Still refuted as the worst path. `rx_tlp_valid` -> `mem_c.mem[300]` is the worst *constrained-to-flop* input path at +1.00 ns. |

The observation from run 1 stands: **there is a purely combinational path from
the `rst` input pin to the `tx_tlp_data` output pins.** Not a violation of
anything the spec states (§13.4 fixes the reset *value*; only `irq` is specified
as a registered output, REQ-012), and not a timing problem. Recorded so nobody
assumes the TLP outputs are flop-bounded. **No RTL change requested.**

## 7. Gate-level simulation handoff — risk closed

The Phase 0 carried-forward risk (OQ-004) was real and is now resolved.

**There are no sky130 standard-cell Verilog simulation models on this machine.**
`platforms/sky130hd/` ships only `cells_adders_hd.v`, `cells_clkgate_hd.v` and
`cells_latch_hd.v`, which are Yosys *mapping* files, not models. No sky130 PDK
is installed; `volare` and `magic` are both absent.

`flow/make_gl_models.sh` fetches them from
`github.com/google/skywater-pdk-libs-sky130_fd_sc_hd` (branch `main`). Three
non-obvious things it has to get right, all of which cost me a debug cycle:

* The upstream cell files `include their siblings by **repo-relative** path
  (`../../models/udp_dff_p/...`), so the upstream directory layout must be
  mirrored, not flattened.
* Icarus resolves `` `include `` relative to the **cwd**, not to the including
  file, so every `cells/*/` and `models/*/` directory needs its own `-I`.
* The netlist instantiates **strength-qualified** cells (`..__fa_1`), which are
  separate upstream files (`cells/fa/sky130_fd_sc_hd__fa_1.v`); fetching only
  the base `..__fa` leaves every instance unresolved.

**Verified working**: `6_final.v` plus the fetched models **compiles cleanly
under Icarus 12.0** (exit 0, 117 MB `.vvp`, root module `matmul_top` elaborated).

| Artefact for the validation specialist | Path |
|---|---|
| Final netlist | `results/sky130hd/pcie_matmul/base/6_final.v` (129 modules, hierarchy preserved) |
| **SDF** | `results/sky130hd/pcie_matmul/base/6_final.sdf` (30 MB, `DESIGN "matmul_top"`, `TIMESCALE 1ns`, typ corner) |
| Parasitics | `results/sky130hd/pcie_matmul/base/6_final.spef` |
| Cell models | `flow/gl_models/sky130_fd_sc_hd.v` (+ `cells/`, `models/`) |

ORFS does **not** write SDF in any stage; I generated `6_final.sdf` separately
with OpenROAD `write_sdf -divider /` from `6_final.odb` + `6_final.spef`.
Compile recipe is printed by `make_gl_models.sh` and repeated in
`flow/README.md`. For SDF back-annotation, drop `-DFUNCTIONAL` (the `specify`
blocks are in the non-functional variant) and use `$sdf_annotate`.

## 8. Runtimes on this machine (24C/32T, serial make)

| Stage | Run 2 |
|-------|-------|
| `1_2_yosys` synthesis | 101 s |
| `2_*` floorplan + tapcell + PDN | 11 s |
| `3_*` place | 147 s |
| `4_1_cts` | 38 s |
| `5_1_grt` global route | 343 s |
| `5_2_route` detailed route + antenna repair | **5,872 s (98 min)** |
| `6_*` fill, merge, report | 58 s |
| **Total flow** | **6,573 s (1 h 50 min)** |
| KLayout sign-off DRC (`make drc`) | ~9 min |
| `tb/gl/postsyn_replay.sh 8` (pre-flight) | **86 s** |

Peak memory 8.3 GB, in detailed routing.

**The post-synthesis replay was used this time and is worth keeping.** Before
committing to the 110-minute flow I ran `tb/gl/postsyn_replay.sh 8` on the fixed
RTL: **TESTS=72 PASS=72 FAIL=0 in 86 seconds.** That is the check that would have
caught BUG-007 before run 1 rather than after it, at ~1/75th of the cost of a
P&R run. It is now a standing pre-flight gate for this flow: **do not start a
full flow on changed RTL without it.**

## 9. Deviations from the spec's numbers

| Spec number | Delivered | Deviation |
|---|---|---|
| 100 MHz / 10.000 ns (§13.2) | 100 MHz, WNS 0.00, worst slack +0.05 ns | **none** |
| `N = 8`, `DW = 8`, `ACCW = 32` (§14) | as specified | **none** |
| Clock ladder 100 -> 75 -> 50 MHz (DEC-009) | not invoked | **none** |
| `sky130hd` (CLAUDE.md) | as specified; `nangate45` fallback not invoked | **none** |
| Single clock, sync reset, zero CDC (§13.1) | confirmed by STA: one `create_clock`, no exceptions needed | **none** |
| OQ-002 area estimate ~0.35 mm^2 cells, ~800x800 um die at ~55% util | 0.54 mm^2 cells, 1235x1235 um die at 40% util | **die is ~2.4x the estimated area.** Driven by the deliberately low `CORE_UTILIZATION = 35` chosen for routability (DEC-014), not by the RTL being larger than expected. |

Nothing in `rtl/`, `docs/spec.md` or `docs/register-map.md` needs to change as a
result of Phase 4.

## 10. Run 1 preserved as the BUG-007 negative control

Run 1's complete output — the layout built from the defective netlist — was
**moved, not deleted**, and is intact:

| Run 1 artefact | Preserved at |
|---|---|
| Results (incl. `6_final.gds`, `6_final.v`, `6_final.sdf`) | `results/sky130hd/pcie_matmul/base_prebug007_negctrl/` |
| Reports (incl. `synth_stat.txt`, `6_finish.rpt`, `6_drc.lyrdb`) | `reports/sky130hd/pcie_matmul/base_prebug007_negctrl/` |
| Logs | `logs/sky130hd/pcie_matmul/base_prebug007_negctrl/` |
| ORFS objects | `objects/sky130hd/pcie_matmul/base_prebug007_negctrl/` |

Nothing was removed. The rename was needed so run 2 could write to `base/` and
keep the output paths byte-identical to what `tb/gl/` already expects. If the
negative control should live somewhere else, or be discarded, that is the
coordinator's call — I have not touched it beyond the rename.
