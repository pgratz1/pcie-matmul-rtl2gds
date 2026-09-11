# Kickoff prompt (paste into Claude Code from the repo root)

Read `CLAUDE.md` in full before doing anything else. You are the orchestrator
for a multi-agent hardware project: a PCIe-attached matrix multiplier taken
from specification to a signed-off GDS-II using the OpenROAD flow installed on
this machine. Six subagents are defined in `.claude/agents/`: spec-writer,
rtl-designer, rtl-reviewer, test-writer, validation-specialist, and
circuit-designer. You
delegate all substantive work to them and enforce the phase gates in
`CLAUDE.md`. You do not write RTL, tests, or flow scripts yourself.

Design parameters are in the table at the top of `CLAUDE.md`. Current values:
sky130hd, 16x16 systolic INT8 with INT32 accumulate, 100 MHz target, PIPE
boundary, BAR0-mapped SRAM host model, Verilator + cocotb. The spec writer may
propose N=8 for v1 if that improves the odds of closing the full flow; accept
that if the reasoning is sound and make sure the design stays parameterized.

Execute the phases in order:

Phase 0. Delegate to validation-specialist: environment check, including
`cocotbext-pcie`, which the testbench depends on. If a required tool is
missing, stop and show me the install commands; do not install anything
without my confirmation.

Phase 1. Delegate to spec-writer. When it returns, read `docs/spec.md` and
`docs/register-map.md` yourself and check for internal consistency: every
module in the block diagram has a section, every register in the map appears
in the spec, every functional behavior has a `REQ-nnn`, TLP header layouts
match each other between the TL section and the register-access section.
Send it back with a specific list if anything fails. Then summarize the key
decisions to me in under 200 words and pause for my approval before Phase 2.

Phase 2. Launch rtl-designer and test-writer **in parallel**, both from the
approved spec. Each must not touch the other's directory. When both return,
confirm the lint gate and the test-plan gate from `CLAUDE.md`.

Phase 2b. Delegate to rtl-reviewer. Save its returned review verbatim as
`docs/phase-reports/phase2-review.md`. Send every Blocking item to
rtl-designer in one batch, then re-run rtl-reviewer. Two rounds maximum; if
Blocking items remain after that, stop and show me the review. Forward the
"Should fix" list to circuit-designer's brief in Phase 4 and the "Coverage
gaps" list to spec-writer (missing REQs) or rtl-designer (missing code) as
appropriate before Phase 3.

Phase 3. Delegate to validation-specialist. Follow the escalation rules: when
it returns with a structural bug, send the diagnosis to rtl-designer, then
re-run validation. When it returns with a spec ambiguity, send it to
spec-writer first, then to test-writer if `REQ` IDs changed, then re-run
validation. Continue until the Phase 3 gate is met. If the same bug survives
five cycles, stop and show me the ledger entry.

Phase 4. Delegate to circuit-designer. Route any RTL-change request it makes
through rtl-designer, then back through validation-specialist (full suite)
before the flow re-runs. After the GDS exists, delegate the gate-level sim to
validation-specialist. If closure needs a clock relaxation or array shrink
beyond what the spec allows, stop and ask me.

Phase 5. Write `docs/phase-reports/summary.md` yourself from the phase
reports: final numbers, deviations from the original spec, total agent
invocations per phase, and what you would change about the process.

Working rules for you as orchestrator:
- Commit at every gate with message `phase-N: <one line>`.
- Keep your own context small: read agents' summaries and the files they
  name; do not re-read whole transcripts or large logs unless a gate check
  requires it.
- Before each delegation, give the subagent a precise brief: which phase,
  which files to read, what it must return, and any escalation you are
  routing to it. Include the relevant `BUG-nnn` or critical-path text
  verbatim so the agent does not need to hunt for it.
- Pause and ask me only at the points named above (missing tools, Phase 1
  approval, five-cycle bugs, closure decisions). Otherwise keep going.

Begin with Phase 0.
