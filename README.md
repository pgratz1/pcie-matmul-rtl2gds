# PCIe-Attached Matrix Multiplier — RTL to GDS-II

A PCIe endpoint with an 8×8 INT8 systolic matrix multiplier, taken from an empty
repository to a signed-off GDS-II on the SkyWater 130 nm open PDK — designed,
verified and physically implemented by a team of six AI subagents under an
orchestrator, with full session logs.

## Result

| | |
|---|---|
| Platform | sky130hd (OpenROAD-flow-scripts) |
| Array | 8 × 8 systolic, output-stationary, INT8 × INT8 → INT32 |
| **Clock** | **100 MHz, closed with no relaxation** (core fmax 125.69 MHz) |
| Die area | 1,525,570 µm² (1235 × 1235 µm) |
| Cells / flops | 55,457 / 6,680 |
| Utilization | 40.38% |
| Power | 78.0 mW |
| Setup / hold violations | **0 / 0** (WNS/TNS 0.00) |
| DRC / antenna violations | **0 / 0** |
| Operation latency | 34 cycles (`4N+2`), 340 ns |

**Verification:** 72/72 RTL tests at N = 2, 4, 8, 16 across two seeds · 72/72
post-synthesis replay · 22 gate-level tests with SDF back-annotation · 127/127
requirements mapped to tests · 7 bugs found, 7 closed.

## What this is

The design is a real one — a TLP-level PCIe endpoint (config space, BAR0 decode,
Memory Read/Write, Completions) driving a parameterized systolic array, all
synthesizable SystemVerilog. But the more interesting artifact is **how it was
built**: six specialist agents with separate responsibilities and enforced
phase gates, each handing work to the next through files on disk rather than
shared context.

- **spec-writer** owns `docs/spec.md` and the register map — 127 numbered requirements
- **rtl-designer** owns `rtl/` — 14 modules, synthesizable SystemVerilog
- **test-writer** owns `tb/` — writes tests *from the spec, never from the RTL*
- **rtl-reviewer** is read-only — reviews RTL against the spec between phases
- **validation-specialist** runs the suite, debugs to root cause, owns the bug ledger
- **circuit-designer** owns `flow/` — ORFS configuration through to GDS-II

The orchestrator wrote none of it. It delegated, enforced the gates in
[`CLAUDE.md`](CLAUDE.md), and independently re-verified every claim.

## The bug that nearly shipped

Gate-level simulation found the **synthesized** design computed matrix row 6 as
always zero — and at N=16 and N=32 it lost two and four operand ports. The RTL
was correct; a Yosys `peepopt` peephole mis-compiled legal code.

It survived every automated check in the flow: lint was clean, `yosys check`
reported "0 problems", and all 72 RTL tests passed. The Phase 4 gate as written
requires only that "the smoke test" pass on the netlist — and **the smoke test
passed on the broken chip**, because it sets only `A[0][0]`/`B[0][0]` and is
structurally incapable of detecting a whole-row fault.

It was caught only because the gate-level run went beyond the gate's stated floor
to a full matrix multiply against a golden model. See
[`docs/bugs.md`](docs/bugs.md) and
[`docs/session-logs/`](docs/session-logs/).

## Layout

```
docs/spec.md              Architecture + micro-architecture spec (v1.1.4, 127 REQs)
docs/register-map.md      BAR0 register map
docs/decisions.md         Dated decision log (DEC-001 … DEC-018)
docs/bugs.md              Bug ledger (BUG-001 … BUG-007, all closed)
docs/phase-reports/       One report per phase, plus the sign-off summary
docs/session-logs/        Full agent transcripts — 3,042 turns
rtl/                      14 synthesizable SystemVerilog modules
tb/                       cocotb testbench, TLP shim, golden model
tb/gl/                    Gate-level sim harness + post-synthesis replay
flow/                     ORFS config, SDC, gate-level cell models
```

Start with [`docs/phase-reports/summary.md`](docs/phase-reports/summary.md).

## Reproducing

Requires [OpenROAD-flow-scripts](https://github.com/The-OpenROAD-Project/OpenROAD-flow-scripts),
Icarus Verilog, Verilator (lint only), and Python with `cocotb` + `cocotbext-pcie`.

```bash
python3 -m venv .venv && .venv/bin/pip install cocotb cocotbext-pcie

make -C tb lint                 # Verilator --lint-only -Wall
make -C tb test                 # full cocotb suite (N=8)
make -C tb test N=16            # genuine per-N rebuild
tb/gl/postsyn_replay.sh 8       # post-synthesis replay, ~90 s, no PDK needed

cd flow && make                 # full ORFS flow to GDS-II, ~1 h 49 min
```

Flow outputs (`results/`, `reports/`, `logs/`) are gitignored — the GDS alone is
75 MB. They regenerate from `flow/config.mk`; see [`flow/README.md`](flow/README.md).

## A note on the process

The single highest-value tool in the project was built *in response* to a bug:
`tb/gl/postsyn_replay.sh` replays the full test suite against a synthesized
netlist in ~90 seconds with no PDK, versus 1 h 49 min for a full physical flow.
It would have caught the row-6 defect immediately. It is now a mandatory
pre-flight gate, and it proved itself on first use.

Three confident structural claims were refuted by measurement during the project,
including one from the orchestrator. The session logs keep all of them.

---

Built with [Claude Code](https://claude.com/claude-code).
