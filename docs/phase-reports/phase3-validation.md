# Phase 3 — Validation report

**Owner:** validation-specialist
**Date:** 2026-09-10
**Design under test:** `rtl/` against `docs/spec.md` v1.1.3 and
`docs/register-map.md` v1.1.3
**Simulator:** Icarus Verilog 12.0 + cocotb 2.1.0 (DEC-001);
Verilator 5.032 as linter only
**Yosys:** 0.68+ (git a5af9d690, OpenROAD fork), via
`/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys`
(not on the default `PATH` — see `phase0-env.md`)

---

## 1. Gate status, item by item

| # | Gate criterion (CLAUDE.md) | Status |
|---|---|---|
| 1 | 100% of the tests in `tb/TESTPLAN.md` pass | **MET at `N` = 4 and `N` = 8 only. NOT MET at `N` = 2 (69/71) or `N` = 16 (70/71).** `N` = 32 not completed — see §7. All 3 distinct failures are test bugs, all routed — see §4 |
| 2 | Every bug in `docs/bugs.md` closed | **NOT MET** — 6 bugs opened, **0 are RTL defects**, 6 routed out of validation (5 to test-writer, 1 to spec-writer) |
| 3 | `yosys -p "read_verilog -sv rtl/*.sv; synth"` completes with no unsupported constructs | **MET** |

**Headline: no RTL defect was found.** Every failure and every gap found in
this phase lives in the testbench or in the specification. That is a genuinely
good result for `rtl/`, and it is also why items 1 and 2 are held open: the
*evidence* behind the previously-reported "71/71 green" was not what it
appeared to be (BUG-001).

---

## 2. Exact commands run

Baseline reproduction:
```
make -C tb test SEED=1 N=8                       # 71/71 PASS, 15.6 s wall
```

Gate item 3, in the exact form the gate specifies (glob order, **not**
`filelist.f` order, and no `hierarchy -top`):
```
/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys \
    -p "read_verilog -sv rtl/*.sv; synth"
```
→ **exit 0**, `Found and reported 0 problems.`, 24.6 s, 1.33 GB peak.
Warnings: 17 × `ABC: Warning: The network is combinational`, which is ABC
noise, not a design issue. Ten `No latch inferred for signal ...` notices,
which are Yosys *confirming* that ten combinational `always` blocks are
latch-free — the desired outcome, not a warning.

**Finding: glob order works.** `rtl/*.sv` sorts to
`app_bar0, matmul_engine, matmul_top, mem_a, mem_b, mem_c, mm_array, mm_ctrl,
mm_pe, pcie_cfg_space, pcie_tl, reg_file, tlp_rx, tlp_tx` — i.e. parents are
read before children, the reverse of `filelist.f`. Yosys resolves the
hierarchy after reading all files, so ordering is immaterial here, and the
auto-selected top is `matmul_top`. Nothing in `rtl/` depends on compile order
(no package, no `include`, no cross-file `localparam`). Negative result
recorded as requested.

Suite sweep — **with `make -C tb clean` before every run**, which is load-bearing
(BUG-001):
```
for n in 2 4 8 16 32; do for s in 1 7 424242 20260910; do
    make -C tb clean && make -C tb test N=$n SEED=$s
done; done
```

Adversarial probes (validation-specialist's own, kept **out of `tb/`** so the
test-writer's independence is preserved — sources under
`$SCRATCH/probes/`, run with `SIM_BUILD` pointed away from `tb/sim_build`):
```
PYTHONPATH=$SCRATCH/probes:tb/tests:tb make -C tb test \
    TEST=__probe__ N=<n> COCOTB_TEST_MODULES=<module> SIM_BUILD=$SCRATCH/build_n<n>
```

Soak:
```
STRESS_OPS=1500 SEED=31337   make -C tb test TEST=test_stress N=8   # PASS
STRESS_OPS=1500 SEED=8675309 make -C tb test TEST=test_stress N=8   # PASS
```
(12.5× the default `STRESS_OPS=120`, against `golden.DeviceModel`.)

---

## 3. Suite results across seeds and `N`

Seeds 1, 7, 424242, 20260910. `N` = 2, 4, 8, 16, 32.

| `N` | SEED 1 | SEED 7 | SEED 424242 | SEED 20260910 | wall / run (uncontended) |
|---|---|---|---|---|---|
| 2  | 69/71 | 69/71 | 69/71 | 69/71 | ~6–8 s |
| 4  | 71/71 | 71/71 | 71/71 | 71/71 | ~8–10 s |
| 8  | 71/71 | 71/71 | 71/71 | 71/71 | ~19–21 s |
| 16 | 70/71 | 70/71 | 70/71 | 70/71 | ~20 min |
| 32 | 14/71 then aborted | — | — | — | **> 80 min for 15 tests** |

Two further confirmation runs at seeds **555** and **987654321**, `N` = 8,
clean build, dedicated `SIM_BUILD`: **71/71 both**.

Every failure is **deterministic and identical across all four seeds** — none
is a randomization artifact, and every one is a test bug, not an RTL bug:

| `N` | failing test | bug |
|---|---|---|
| 2 | `test_tlp_back_to_back_tlps_no_idle_cycles` | BUG-002 |
| 2 | `test_matmul_write_abc_while_busy` | BUG-003 |
| 16 | `test_matmul_c_addressing_and_persistence` | BUG-005 |

Runtime scales far worse than linearly: the engine is `O(N^2)` PEs each
evaluated per cycle by a single-threaded event simulator, and the drain bus is
`N*32` bits wide. `N` = 8 → 20 s, `N` = 16 → 20 min (60×), `N` = 32 →
extrapolates to many hours.

**A note on how the `N` = 16 SEED 1 number was obtained.** My first `N` = 16
run was killed by my own over-broad `pkill` while it was on test 70/71. Its log
shows three failures; two of them
(`test_matmul_soft_reset_during_drain`, `test_stress_random_sequence`) are
`cocotb.regression.SimFailure: ... the simulation ended prematurely`, i.e.
artifacts of my kill, not results. Only
`test_matmul_c_addressing_and_persistence` was a real assertion failure. The
three seeds re-run cleanly afterwards (7, 424242, 20260910) each report exactly
70/71 with exactly that one test failing, which confirms the reading. Recording
this so nobody later mistakes that log for evidence of an RTL problem.

---

## 4. Bugs found

Full entries with evidence in `docs/bugs.md`.

| ID | One line | Owner | Status |
|---|---|---|---|
| BUG-001 | `make test N=<n>` does not rebuild `sim.vvp`; the `N` override was silently ignored for every run | test-writer | `ROUTED-test` |
| BUG-002 | `test_tlp_back_to_back_tlps_no_idle_cycles` hard-codes 16 DWORDs into `mem_c`, which holds only `N*N` = 4 words at `N` = 2 (REQ-091) | test-writer | `ROUTED-test` |
| BUG-003 | `test_matmul_write_abc_while_busy` assumes the operation is still `BUSY` when the 4th TLP arrives; false at `N` = 2 where `4N+2` = 10 cycles < the TLP stream | test-writer | `ROUTED-test` |
| BUG-004 | No requirement covers a memory request with `Length` > 32 or `Length` field = 0 inside the BAR0 window; REQ-044 / REQ-056 / §4.5 do not compose | spec-writer | `ROUTED-spec` |
| BUG-005 | `test_matmul_c_addressing_and_persistence` builds `A[i][j] = i*N + j - 100`, which leaves INT8 range at `N` >= 16 (max 155 at `N` = 16, 923 at `N` = 32); the golden model rejects the stimulus before the DUT sees it | test-writer | `ROUTED-test` |
| BUG-006 | `Host.OP_TIMEOUT_NS` is a fixed 20 us covering a whole multi-completion region read; at `N` = 16 under heavy backpressure a full-C readback cannot finish inside it. Latent flake at `N` = 32 | test-writer | `ROUTED-test` |

**Zero RTL changes were made in Phase 3.** `rtl/` is byte-identical to what
rtl-reviewer signed off in `phase2-review-round2.md`.

BUG-005 is the direct consequence of BUG-001: it is a deterministic,
seed-independent failure that has been sitting in the suite since the test was
written, and it was invisible only because `make test N=16` never actually
built an `N` = 16 design.

BUG-001 is the important one. It means the "71/71 at `N` = 2, 8, 32" claim that
came into this phase was produced by re-running the `N` = 8 binary three times.
Lint and `elab-sweep` *do* re-invoke their tools per `N`, so those claims stand;
the *simulation* claims at `N` != 8 did not.

---

## 5. What I probed that found nothing

Negative results, on record as evidence the gate was actually tested. All of
the following were written from `docs/spec.md` and run at `N` = 2, 4, 8 and 16;
**all passed at every `N`**, i.e. they found no defect. (The single probe
non-pass, `p_heavy_random_backpressure` at `N` = 16, was bisected to the
harness's fixed timeout and is BUG-006, not a DUT defect — see below.)

### Reset (task b, "reset behavior")
- **`p_reset_mid_operation_and_drain`** — asserts `rst` at **every single cycle
  offset 1 … 4N+3** after `CTRL.START`, i.e. mid-PRIME, mid-FETCH, mid-COMPUTE,
  mid-TURN, mid-DRAIN (including between the two/eight row-drain writes) and
  mid-FINISH. After each one it checks the §13.4 table on the DUT rather than on
  the tests' expectations: `STATUS` = 0, `OP_COUNT` = 0, `PERF_CYCLES` = 0,
  all of `mem_c` = 0 (REQ-092), all of `mem_a` = 0, cfg `Command` = 0,
  cfg `BAR0` = 0, cfg 0x00 = `0x80001234` (REQ-112). Then re-arms the device and
  runs a clean operation to prove recovery. 35 reset points at `N` = 8, 67 at
  `N` = 16. **No violation found.**
- **`p_reset_mid_inbound_tlp`** — `rst` asserted after 2 beats of a 4-beat
  `MWr`, with no `eop` ever delivered. Device recovers; the abandoned TLP does
  not resume or corrupt the next one.
- **`p_reset_mid_completion_burst`** — `rst` asserted 1, 2, 3, 4, 5, 6, 8 and 12
  cycles into a multi-DWORD `CplD`. `tx_tlp_valid` goes low and **stays** low
  for 20 cycles (checked every cycle), i.e. `tlp_tx`'s framing state really
  does reset to idle rather than resuming a half-sent completion.
- Throughout, REQ-006 is checked on **every cycle `rst` is high**:
  `rx_tlp_ready`, `tx_tlp_valid`, `tx_tlp_sop`, `tx_tlp_eop` and `irq` all 0.

### Backpressure (task b, "backpressure")
- **`p_tx_stall_mid_completion_burst`** — `tx_tlp_ready` forced low for 150
  cycles **after 0, 1, 2, 3, 4 and 5 beats** of a 32-DWORD `CplD` have already
  transferred, i.e. deasserted *mid-Completion*, in the header and in the
  payload. Full payload and `Length` compared byte-for-byte on release.
  **No corruption, no loss.**
- **`p_tx_stall_across_start`** — `tx_tlp_ready` held low across an entire
  operation plus 200 cycles. `PERF_CYCLES` still reads exactly `4N+2`
  (REQ-102), so outbound backpressure does not leak into the engine's timing,
  and `C` is correct.
- **`p_heavy_random_backpressure`** — 90% per-cycle idle probability on `rx` and
  90% per-cycle stall on `tx`, simultaneously, through load/START/DONE/readback.
  (The suite's own worst case is 50%/50% in `test_tlp_idle_and_stall_cycles`
  and 15%/15% in `test_stress`.) Passes at `N` = 2, 4, 8. At `N` = 16 it hit a
  `Timeout`, which I bisected rather than assumed: 50%/50% passes, 75%/75%
  passes, and 90%/90% passes with the *identical* stimulus when the C readback
  is chunked so no single `cocotbext-axi` region read has to complete inside
  `OP_TIMEOUT_NS`. The DUT delivers every byte correctly in all four; the
  budget is the harness's (BUG-006).
- REQ-003 checked structurally as well: `rx_tlp_ready` is
  `!rst && (state ∈ {S_H0,S_H1,S_H2,S_CFGW,S_DRAIN}) || (S_WDATA && app_wdata_ready)`
  (`rtl/tlp_rx.sv:161`). `rx_tlp_valid` appears nowhere in it, and neither does
  `tx_tlp_ready` — so there is no combinational valid→ready loop and no
  cross-stream combinational path either.

### Malformed and adversarial TLPs (task b)
- **`p_truncated_then_fresh_sop`** — packets cut off after 1, 2 and 3 beats with
  no `eop`, immediately followed by a complete `MWr`. The complete one lands.
- **`p_sop_mid_packet`** — `sop` re-asserted 1, 2 and 3 beats into a packet.
  The DUT restarts header capture (`restart` term at `tlp_rx.sv:167`) and the
  re-sent packet is executed correctly.
- **`p_td_ep_set`** — `TD` = 1 and `EP` = 1 on both a non-posted `MRd`
  (→ UR Completion + `ERR_UNSUP_REQ`, REQ-040) and a posted `MWr`
  (→ discarded, no Completion, + `ERR_UNSUP_REQ`, REQ-041), 4 cases total.
  Verified the `MWr` really was discarded by reading `SCRATCH` back.
- **`p_back_to_back_no_gap_framing`** — 8 `MWr` TLPs as one contiguous beat
  stream with `rx_gap_prob` forced to 0, so `sop` is on the cycle immediately
  after the previous `eop`, repeatedly.
- **`p_zero_length_write`** — `Length` = 1 with First BE = `0000`, the PCIe
  zero-length write. Modifies nothing and correctly does **not** raise
  `ERR_UNSUP_REQ` (it is a legal BAR0 write).
- 4 DW formats (`MRd64` Fmt `001`, `MWr64` Fmt `011`) are already covered by
  `test_tlp` per TESTPLAN; not duplicated here.

### Boundary arithmetic (task b)
- **`p_burst_crossing_region_boundary`** — an 8-DWORD `MWr` starting at
  BAR0+`0x0FF0`, straddling the reg→`mem_a` boundary. Confirms REQ-057's
  "each DWORD decodes from its own address, nothing wraps": the first 4 DWORDs
  are swallowed (RAZ/WI reg space) and the last 4 land at `mem_a[0..15]`, and
  nothing is aliased back into the register region.
- **`p_last_dword_of_each_region`** — the very last implemented DWORD of
  `mem_a`, `mem_b` and `mem_c` is written and read back; then the **first**
  DWORD past each region is written with `0xFFFFFFFF` and confirmed to read 0
  (RAZ/WI, REQ-055/REQ-091) *and* to have left the last implemented DWORD
  untouched — the classic off-by-one that a range compare gets wrong.
- **`p_crossing_end_of_bar0`** — `MRd` at `0x3FF0` Length 8 (ends at `0x4010`,
  past 16384) → UR + `ERR_UNSUP_REQ` per REQ-044; and the exactly-fits case,
  `0x3FF0` Length 4 (ends at exactly 16384) → SC. Both correct; the `>` in
  REQ-044 is implemented as `>`, not `>=`.
- **`p_zero_byte_enables`** — BE = `0000` writes to `reg_file` and to `mem_a`
  modify nothing (REQ-059); an `MRd` with First BE = `0000` still completes SC
  (REQ-061, reads ignore BE).
- **`p_length_over_32_and_zero`** — this one found the **spec gap** in BUG-004.
  The DUT's behaviour (UR, framing preserved) is self-consistent and safe; it
  is simply not specified.

### X-propagation (task b)
- **`p_no_x_on_outputs_after_reset`** — clock + 5 cycles of `rst` and **no
  stimulus whatsoever** (exactly what a Phase 4 gate-level smoke test looks
  like), then every top-level output — `rx_tlp_ready`, `tx_tlp_valid`,
  `tx_tlp_sop`, `tx_tlp_eop`, all 32 bits of `tx_tlp_data`, `irq` — is checked
  for X/Z on **every one of 200 cycles**. **Zero X.**
- **`p_no_x_in_internal_state_after_reset`** — recursive walk of the whole
  instance hierarchy 3 cycles after `rst` deasserts; **604 value-bearing
  signals visited at `N` = 8, zero X/Z**. This is REQ-108 ("every flip-flop
  shall be reset by `rst`") holding in practice, and it is the single best
  predictor available that Phase 4's gate-level simulation will not drown in X.

### Soak
- `test_stress` at `STRESS_OPS=1500` (12.5× default) against
  `golden.DeviceModel`, at two fresh seeds. Both pass. No slow-accumulating
  divergence in `STATUS`, `IRQ_STATUS`, `OP_COUNT`, `PERF_CYCLES`, A, B or C.

---

## 6. Things deliberately **not** done

- **No test was skipped, deleted, loosened, or had its iteration count reduced.**
  `tb/` is untouched — `git status` shows no modification under `tb/`.
- **No RTL was changed.** `git status` at the end of this phase shows only
  `docs/bugs.md` (mine), `docs/phase-reports/phase3-validation.md` (mine) and a
  regenerated `tb/results.xml`. Nothing under `rtl/` and no test source is
  modified. Both `N = 2` failures were root-caused to test bugs
  with waveform evidence before any RTL was considered, so the "targeted RTL
  fix" path in CLAUDE.md was never entered.
- **No side taken on BUG-004.** The spec gap is described with the RTL's actual
  behaviour and a recommendation; the decision is spec-writer's.
- My probe modules live in the scratchpad, not in `tb/`, so the test-writer's
  independence from the RTL is preserved. They are debug instruments, not
  deliverables, and are **not** a substitute for the test-writer adding proper
  coverage for the gaps they exposed.

---

## 7. Long-`N` runtime note

`N` = 16 runs the full 71-test suite in ~20 minutes uncontended (vs ~20 s at
`N` = 8) — a 60× step for a 2× array dimension. Four seeds were run to
completion.

**`N` = 32 was not completed and I am recording that as a measured result, not
an omission.** One seed ran for **80+ minutes** and reached test **15 of 71**
(`test_regs.test_reg_start_and_soft_reset_while_busy`). The process was at
99.9% CPU throughout, so it was grinding, not deadlocked: 1024 `mm_pe`
instances plus a 32768-bit `mem_c` evaluated by a single-threaded event
simulator. The first 14 tests (all of `test_smoke` and most of `test_regs`)
**passed**. Extrapolating, a full `N` = 32 suite is on the order of 6–8 hours
per seed under Icarus.

What *is* established at `N` = 32 without a full suite run:
`verilator --lint-only -Wall` clean, `iverilog` elaboration clean
(`make elab-sweep`), Yosys `synth` clean, and the first 14 tests pass.

**Recommendation.** Do not make a full `N` = 32 simulation a gate. If `N` = 32
sign-off is wanted, it needs Verilator as the *simulator*, which is blocked by
DEC-001 (cocotb 2.1.0 hard-errors on Verilator < 5.036; this machine has
5.032). Upgrading Verilator to >= 5.036 is the single highest-leverage change
available to this project's turnaround time, and it would also make `N` = 16
regressions cheap. That is an orchestrator/human decision, not mine.

---

## 8. Recommended order of operations out of this phase

1. **test-writer** fixes BUG-001 first. Until `make test N=<n>` rebuilds,
   no `N`-sweep result from anyone can be trusted.
2. **test-writer** fixes BUG-002, BUG-003, BUG-005 (all scaling bugs of the
   same family: a constant tuned for `N` = 8), and BUG-006.
3. **spec-writer** rules on BUG-004. No RTL change is expected either way.
4. I re-run the sweep at `N` = 2, 4, 8, 16 and close the gate.

> **Footnote, because it is the best possible evidence for BUG-001.** While
> writing this report I ran my own final confirmation pass with
> `make -C tb test N=8` in `tb/sim_build` immediately after an `N` = 16 run had
> populated that directory. It would have silently simulated the `N` = 16
> binary and reported 71/71 under the label "N=8". I caught it only because I
> had just written BUG-001 up. The re-run with a clean, dedicated `SIM_BUILD`
> is the one reported above.
5. Phase 4 proceeds in parallel with 1–3; none of these six bugs touches
   `rtl/`, so nothing blocks the circuit-designer.

