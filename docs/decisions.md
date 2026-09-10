
## 2026-09-10 — DEC-001: Simulator flips to Icarus Verilog 12.0
**Context:** Phase 0 environment check. cocotb 2.1.0 hard-errors on Verilator below
5.036 (`cocotb_tools/makefiles/simulators/Makefile.verilator:29`, `VLT_MIN := 5.036`).
This machine has Verilator 5.032 and `apt-cache policy verilator` offers no newer
candidate. Python 3.14 is the only interpreter, which forces cocotb 2.1.0 (the only
release with a cp314 wheel), so downgrading cocotb to dodge the floor is not available.
**Decision:** Icarus Verilog 12.0 is the cocotb simulator. Verilator remains the lint
tool (`--lint-only -Wall`) — the version floor applies only to cocotb's VPI build, not
to linting. Icarus was already required for Phase 4 gate-level sim because Verilator
has no SDF support.
**Alternatives not taken:** build Verilator 5.038 from source (deferred; revisit only if
Icarus is too slow on the chosen array size). Decided by: orchestrator, on
validation-specialist evidence.
**Consequence:** simulation is slower than Verilator would have been. This is an input
to the N=8 vs N=16 array-size decision in Phase 1.

## 2026-09-10 — DEC-002: PIPE boundary ruled out; endpoint is TLP-level
**Context:** `CLAUDE.md` set the synthesizable boundary at PIPE, and separately required
that the endpoint boundary be one `cocotbext-pcie` can attach to. Phase 0 found these
two requirements are in direct conflict: `cocotbext-pcie` 0.2.16 contains no PIPE
interface whatsoever (`grep -ri pipe` over the package returns nothing). Its RTL-facing
devices are `xilinx.us.UltraScalePlusPcieDevice` (AXI-Stream CQ/CC/RQ/RC), `intel.ptile`
and `intel.s10`; `core.RootComplex` and `core.MemoryEndpoint` are pure-Python models
with no RTL ports.
**Decision:** the "attachable by cocotbext-pcie" requirement wins, so the TLP-level
endpoint fallback already sanctioned in the "PCIe scope" section of `CLAUDE.md` is
**mandatory for v1, not optional**. The DLL is modeled behaviorally.
**Open — decided in Phase 1 by spec-writer:** the exact TLP-level boundary. See DEC-003.
Decided by: orchestrator, on validation-specialist evidence.
