# PCIe-Attached Matrix Multiplier — RTL to GDS-II

This repository is a multi-agent hardware project. The **main session is the
orchestrator**; it does not write RTL, tests, or flow scripts itself. It delegates
to the six subagents in `.claude/agents/` and enforces the phase gates below.

## Design parameters (edit before kickoff)

| Parameter            | Default                 | Notes |
|----------------------|-------------------------|-------|
| PDK / platform       | `sky130hd`              | ORFS platform name. `nangate45` is ~3x faster to iterate; switch if turnaround matters more than realism. |
| Array shape          | 16 x 16 systolic        | Parameterized `N`; the spec may pick 8x8 for the first full-flow pass. |
| Operand type         | INT8 x INT8 -> INT32 acc | Optional stretch: BF16. |
| Target clock         | 100 MHz (sky130hd)      | Circuit designer may relax; spec must record the final number. |
| PCIe boundary        | PIPE interface          | See "PCIe scope" below. |
| Host access model    | BAR0-mapped registers + on-chip SRAM for A/B/C | DMA is a stretch goal, gated on Phase 4 passing. |
| Simulator            | Verilator + cocotb      | Fallback: Icarus + cocotb. Validation specialist confirms what is installed. |
| PCIe host model      | `cocotbext-pcie`        | The testbench never hand-writes TLP encode/decode; this library is the reference. The spec's endpoint boundary must be one it can attach to. |
| HDL                  | SystemVerilog (synthesizable subset Yosys accepts) | No `interface`s, no unpacked struct ports; keep it Yosys-clean. |
| ORFS install path    | `/home/pgratz/openroad/OpenROAD-flow-scripts` | Confirmed present on this machine. Source `${ORFS}/env.sh` to get `openroad`/`yosys` on `PATH`. Flow dir: `${ORFS}/flow`; platforms in `${ORFS}/flow/platforms/` (asap7, gf180, ihp-sg13g2, nangate45, sky130hd, sky130hs, sky130io, sky130ram). |

## PCIe scope (read this before arguing about PCIe)

No open PDK ships a PCIe SerDes PHY, so "PCIe-connected" here means the **digital
endpoint logic** only. The synthesizable design boundary is the PIPE interface
(parallel data + control to an external PHY). Everything on the far side of PIPE
is a **behavioral simulation model**, not RTL that goes to GDS.

Layering, from the PIPE boundary inward:

1. Physical layer (PHY) — **behavioral model only**, provided by the test writer.
2. Data link layer (DLL) — ACK/NAK, sequence numbers, minimal flow control. May be
   simplified in v1 (the spec must state exactly which DLLPs are supported).
3. Transaction layer (TL) — TLP parse/build: Memory Read/Write to BAR0, Completions.
   Config space: minimal Type 0 header, enough for a BAR to be assigned.
4. Application layer — register file, SRAM for A/B/C, matmul engine, status/IRQ.

If the spec writer judges full DLL too expensive for v1, the accepted fallback is a
**TLP-level endpoint** (TL + application layer) with DLL modeled behaviorally. This
must be an explicit, recorded decision in `docs/spec.md`, not a silent omission.

## Repository layout

```
docs/spec.md                Architecture + micro-architecture spec (spec-writer owns)
docs/register-map.md        BAR0 register map (spec-writer owns)
docs/decisions.md           Dated log of scope/architecture decisions (anyone appends)
docs/bugs.md                Bug ledger (validation-specialist owns)
docs/phase-reports/         One short report per completed phase
rtl/                        Synthesizable SystemVerilog only (rtl-designer owns)
rtl/README.md               Module hierarchy and file list
tb/                         Testbenches, cocotb tests, behavioral models (test-writer owns)
tb/models/                  Glue to cocotbext-pcie, host wrapper, golden model (NOT synthesized)
tb/Makefile                 Single entry point: make lint | make test | make test TEST=<name>
flow/                       ORFS config.mk, constraint.sdc, floorplan, macro placement (circuit-designer owns)
flow/README.md              How to run the flow, where results land
results/ reports/ logs/     ORFS outputs (gitignored)
```

## Ownership and independence rules

- Only **rtl-designer** creates or restructures files in `rtl/`.
- Only **test-writer** creates tests. The test writer works **from the spec**, not
  from the RTL, so tests are an independent check. It may read RTL to learn port
  names, never to copy behavior.
- **validation-specialist** runs tests and debugs. It may make targeted RTL fixes
  but must (a) log each fix in `docs/bugs.md` with root cause, (b) never weaken,
  skip, or delete a test to make it pass, and (c) hand structural rework back to
  rtl-designer.
- **rtl-reviewer** has read-only tools. It reviews `rtl/` against the spec
  between Phase 2 and Phase 3 and after structural rework; its blocking items
  go to rtl-designer before validation starts.
- **circuit-designer** owns `flow/` and may request RTL changes for timing,
  area, or synthesizability, routed through the orchestrator to rtl-designer.
- **spec-writer** owns `docs/spec.md` and `docs/register-map.md`. Any agent that
  discovers the spec is ambiguous or wrong reports it; the spec gets amended
  before the RTL is changed, so the spec and the RTL never disagree.

## Phase gates

The orchestrator does not advance a phase until its gate is met and a phase
report exists in `docs/phase-reports/`.

| Phase | Owner                  | Gate |
|-------|------------------------|------|
| 0 Environment | validation-specialist | Tool versions recorded: openroad, yosys, verilator/iverilog, cocotb, python, ORFS path + platform dir. `make lint` runs on a hello-world module. |
| 1 Spec        | spec-writer           | `docs/spec.md` + `docs/register-map.md` complete; every open question resolved or recorded in `docs/decisions.md`. Orchestrator reviews for internal consistency. |
| 2 RTL + tests | rtl-designer, test-writer (in parallel) | All RTL lints clean under `verilator --lint-only -Wall`. Test plan in `tb/TESTPLAN.md` maps each spec requirement to a test. |
| 2b Review     | rtl-reviewer          | Review filed as `docs/phase-reports/phase2-review.md`; zero open Blocking items (rtl-designer fixes, reviewer re-checks, at most 2 rounds). |
| 3 Validation  | validation-specialist | 100% of tests in `tb/TESTPLAN.md` pass. Every bug in `docs/bugs.md` closed. Yosys synth check (`yosys -p "read_verilog -sv rtl/*.sv; synth"`) completes with no unsupported constructs. |
| 4 Physical    | circuit-designer      | ORFS flow completes through `6_final.gds`. Zero DRC violations from ORFS's checker, zero setup/hold violations at the recorded target clock (or a documented, spec-approved relaxation). Gate-level sim of at least the smoke test passes on `6_final.v` with SDF or unit delays. |
| 5 Sign-off    | orchestrator          | `docs/phase-reports/summary.md`: final area, clock, utilization, cell count, power estimate, and a list of every deviation from the original spec. |

## Iteration limits

- A failing test gets at most **5** validation-specialist debug cycles before the
  orchestrator escalates to rtl-designer with the specialist's diagnosis.
- The physical flow gets at most **4** timing/area closure iterations before the
  orchestrator asks the human for a decision (relax clock, shrink array, change PDK).
- Any agent that has used more than ~30 tool calls without a checkpoint writes a
  progress note to its phase report and returns to the orchestrator.

## How agents report back

Every subagent ends with a **summary under 300 words**: what it produced (file
paths), what passed/failed, open questions, and what it recommends next. The
orchestrator keeps its own context small by relying on these summaries and the
files on disk, not by re-reading agent transcripts.

## Conventions

- Active-high synchronous reset `rst`, single clock `clk` in the application
  domain; PIPE clock domain crossing (if any) is explicit and documented.
- Every module has a header comment: purpose, parameters, interface contract,
  latency. Ports grouped and commented.
- No `initial` blocks, no `#` delays, no `$display` in `rtl/`.
- Commit after each gate with message `phase-N: <one line>`.
- Never `rm -rf results/` without asking; flow runs are expensive.
