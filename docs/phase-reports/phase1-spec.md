# Phase 1 — Specification: gate report

**Date:** 2026-09-10
**Owner:** spec-writer
**Reviewed by:** orchestrator
**Gate:** MET (pending human approval to enter Phase 2)

## Deliverables

| File | Version | Size |
|------|---------|------|
| `docs/spec.md` | v1.0.0 | 1444 lines, 16 sections |
| `docs/register-map.md` | v1.0.0 | 243 lines, 10 registers |
| `docs/decisions.md` | — | DEC-001 … DEC-012, OQ-001 … OQ-004 |

## Orchestrator consistency review

Every check named in the Phase 1 gate was run against the returned files.

| Check | Method | Result |
|-------|--------|--------|
| Every module in the block diagram has a spec section | §3 module table (14 modules) cross-referenced against the section headings extracted from `docs/spec.md` | **PASS** — 14/14 resolve to a real section |
| Every register in the map appears in the spec, and the reverse | 10 offset/name rows extracted from `docs/register-map.md`, matched against §10.1 | **PASS** — 1:1, no register in only one file |
| Every functional behavior carries a `REQ-nnn` | Regex extraction and set comparison | **PASS** — REQ-001…REQ-121, 121 unique, contiguous, no gaps; all 121 appear both inline and in the §16 table; no duplicate table rows |
| TLP header layouts agree between the TL section and the register-access section | §7.2 vs §9.4 | **PASS** — §9.4 restates no layout and defers to §7.2 as sole authority, so the two cannot diverge by construction |
| Field layouts correct against PCIe Base r6.0 | Spot-checked DW0 (Fmt/Type/Length), MRd/MWr DW1–DW2, CfgRd0/CfgWr0 DW2, Cpl/CplD DW1–DW2 | **PASS** |
| Arithmetic claims | `T_mm = 1+1+(3N-2)+1+N+1 = 4N+2` → 34 at N=8, 66 at N=16; overflow bound `2^31 / 16384 = 131072` | **PASS** |
| Encoding constants | `VERSION = 0x00010000` vs its stated field split; `CONFIG = 0x00200808` vs `{8'h00, ACCW, DW, N}` at N=8,DW=8,ACCW=32 | **PASS** |

## Library assumptions verified against the installed package

The spec depends on specific `cocotbext-pcie` 0.2.16 APIs. These were executed, not assumed:

- `Tlp.pack()`, `Tlp.unpack()`, `Tlp.get_header_size()` all exist; `get_header_size()` returns **12**, exactly as §5.3 states.
- `RootComplex.max_payload_size` / `.max_read_request_size` exist as properties **with setters** (`core/rc.py:140-152`); defaults are `_max_payload_size = 0`, `_max_read_request_size = 2`. The §4.5 instruction to set both to 0 is therefore valid and non-trivial.
- `Device` is subclassable with `upstream_recv` / `upstream_send` — the hooks DEC-003's shim relies on.
- **Note for test-writer:** `RootComplex()` calls `cocotb.start_soon()` in its constructor, so it **must be constructed inside a running test**, not at module import. Constructing it at import raises `RuntimeError: No test is currently running`.

## Key decisions

DEC-003 raw-TLP DWORD stream (Option B) · DEC-004 N=8, parameterized · DEC-005 output-stationary · DEC-006 one Completion per MRd · DEC-007 strict serialization · DEC-008 status bit + level `irq`, no MSI · DEC-009 100 MHz, 1-stage PE MAC · DEC-010 flip-flop register files, no SRAM macros · DEC-011 ID constants · DEC-012 separate `mem_c` with drain phase.

## Open questions carried forward (none blocking)

- **OQ-001** Does 100 MHz close on sky130hd? Resolved in Phase 4. Sanctioned relaxation ladder 100 → 75 → 50 MHz.
- **OQ-002** Area estimate unvalidated; `nangate45` remains the fallback platform.
- **OQ-003** DMA remains a stretch goal; adopting it would reopen DEC-007 and DEC-008.
- **OQ-004** sky130 standard-cell Verilog models are absent on disk; needed for the Phase 4 gate-level sim.

## Recommendation

Proceed to Phase 2. Launch `rtl-designer` and `test-writer` in parallel from this spec. Test-writer must set `rc.max_payload_size = 0` and `rc.max_read_request_size = 0` (§4.5) and must construct `RootComplex` inside the test body.
