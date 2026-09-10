# PCIe matmul multi-agent skeleton

1. Copy this directory's contents into your project repo root (or `git init` here).
2. Edit the parameters table at the top of `CLAUDE.md` if the defaults aren't right.
3. `pip install cocotb cocotbext-pcie` (the test writer relies on cocotbext-pcie for
   the PCIe root-complex/TLP model; Phase 0 checks for it).
4. Optionally set `model:` in each `.claude/agents/*.md` (e.g. `opus` for spec-writer,
   rtl-designer, circuit-designer; `sonnet` for test-writer, validation-specialist,
   rtl-reviewer).
5. `claude` from the repo root, then paste the body of `KICKOFF-PROMPT.md`.
6. Run `/agents` inside Claude Code to confirm all six subagents loaded.
