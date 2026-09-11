
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

## 2026-09-10 — DEC-003: TLP boundary is a raw-TLP DWORD stream (Option B), not Xilinx CQ/CC
**Context:** DEC-002 fixed the boundary at TLP level and left the exact form to Phase 1.
Two candidates were weighed.
*Option A* — attach `cocotbext.pcie.xilinx.us.UltraScalePlusPcieDevice` directly, so the
DUT's PCIe port becomes Xilinx AXI-Stream CQ/CC and the DUT parses Xilinx *descriptors*.
*Option B* — define our own raw-TLP boundary: a 32-bit synchronous valid/ready DWORD
stream carrying complete, DLL-stripped TLPs, with a thin testbench shim moving bytes
between `cocotbext-pcie`'s `Tlp` objects and that stream.
**Decision: Option B.** The DUT's PCIe ports are `rx_tlp_data[31:0]/sop/eop/valid/ready`
and `tx_tlp_data[31:0]/sop/eop/valid/ready`, fully specified in `docs/spec.md` §5.
**Reasoning:**
1. `CLAUDE.md`'s layering section explicitly assigns to the *design* both "TLP
   parse/build: Memory Read/Write to BAR0, Completions" and "Config space: minimal
   Type 0 header, enough for a BAR to be assigned". Option A moves all of that into a
   vendor-shaped Python model and leaves the DUT decoding a descriptor format that has
   nothing to do with PCIe. Option B keeps the layer-3 work in RTL, which is the point
   of the project.
2. Option A's "lower risk" is partly illusory. `UltraScalePlusPcieDevice` takes ~200
   keyword arguments and requires exact Xilinx signal naming; the 128-bit CQ descriptor
   and the width-dependent `tuser` sideband (`first_be`/`last_be`/`byte_en`/`sop`/
   `discontinue`/parity) are specified in Xilinx PG213, which is not on this machine and
   is not the PCIe Base Spec. That is *more* obscure bit-layout risk to get wrong, not
   less, and it is unverifiable against the reference documents we actually have.
3. Option B's shim is small and fully specifiable from the spec alone: subclass
   `cocotbext.pcie.core.device.Device`, override `upstream_recv()` to serialize
   `tlp.pack()` onto the stream, and run a task that deserializes the TX stream,
   calls `Tlp.unpack()` and `await self.upstream_send(tlp)`. The library still performs
   100% of TLP encode/decode, so `CLAUDE.md`'s "the testbench never hand-writes TLP
   encode/decode" rule is honoured — the shim only moves already-encoded DWORDs.
4. Icarus is the simulator (DEC-001). A 32-bit valid/ready stream is far cheaper to
   simulate than a 256-bit AXI-Stream with `tkeep`/`tuser`.
5. Verified by reading the library: `Device.__init__` installs a `SimPort` that
   implements the behavioral DLL, and the RootComplex's downstream bridge converts
   `CfgRd1`/`CfgWr1` to `CfgRd0`/`CfgWr0` before they reach the `Device`. So
   `rc.enumerate()` drives genuine Type 0 config TLPs into the DUT with no extra work.
**DLL scope, stated exactly:** zero DLL features in RTL. Zero DLLPs cross the chip
boundary. The behavioral DLL (`cocotbext.pcie.core.port.SimPort`) models: TLP sequence
numbers, `Ack`, `Nak` (generation only), `InitFC1`/`InitFC2`/`UpdateFC` for P/NP/CPL,
`Nop`, and credit gating of transmits. It does **not** model LCRC, ECRC, replay-on-NAK,
DLLP CRC-16, or link training.
**Consequence:** test-writer must build `tb/models/tlp_stream_shim.py` from
`docs/spec.md` §5 alone. Decided by: spec-writer.

## 2026-09-10 — DEC-004: v1 array size is N = 8, not 16
**Context:** `CLAUDE.md` defaults to 16x16 and permits 8x8 for the first full-flow pass.
**Decision:** `N = 8` for v1. `N` stays a genuine compile-time parameter with legal
range {2, 4, 8, 16, 32}; no RTL may assume `N == 8`.
**Reasoning:** (a) DEC-001 forces Icarus, roughly an order of magnitude slower than
Verilator, and simulation cost grows as `N^2` in PE count; (b) 256 PEs in sky130hd is
roughly 4x the area of 64 PEs, pushing the estimated core from ~0.35 mm^2 to ~1.4 mm^2
and ORFS runtime up with it; (c) the spec-writer brief prefers a smaller design that
closes the full flow over a larger one that does not. `docs/spec.md` §14 lists exactly
what changes to move to `N = 16` (nothing in RTL; die area and test expectations only).
Decided by: spec-writer.

## 2026-09-10 — DEC-005: Output-stationary dataflow
**Context:** weight-stationary vs output-stationary, one had to be chosen.
**Decision:** output-stationary. Each PE owns the accumulator for exactly one element
of C; A and a 1-bit valid flow west-to-east, B flows north-to-south, and the 32-bit
accumulators are drained through a south-flowing shift chain after the compute phase.
**Reasoning:** during compute, the only signals crossing the array are 8-bit operands
plus one valid bit, so no wide partial-sum bus exists; the 32-bit drain chain is idle
while computing. Weight-stationary's advantage is weight reuse across many activation
rows, which never occurs here because every `START` computes exactly one NxN by NxN
product from freshly loaded operands, and it would additionally require a separate
weight-load phase. Decided by: spec-writer.

## 2026-09-10 — DEC-006: One Completion per Memory Read Request; no completion splitting
**Context:** a compliant completer must split completions at Max Payload Size and must
not cross a Read Completion Boundary (PCIe Base r6.0 §2.3.1.1). Implementing that is
real RTL for no functional benefit in this project.
**Decision:** the DUT returns exactly one Completion per `MRd`, carrying the full
requested Length (1..32 DW), and rejects any `MRd`/`MWr` longer than 32 DW as an
Unsupported Request. The RCB rule is knowingly not enforced.
**Justification that this is safe with our host model:** verified by reading
`cocotbext-pcie` 0.2.16. `RootComplex.perform_nonposted_operation` reassembles
completions purely by byte count and performs no RCB check;
`region.TlpRegion.read()` asserts only `cpl.byte_count == requested_byte_length` and
slices from `cpl.lower_address & 3`. `region.py` splits host requests at
`128 << max_read_request_size` and `128 << max_payload_size`.
**Testbench obligation:** the test writer must set `rc.max_payload_size = 0` and
`rc.max_read_request_size = 0` (both 128 bytes = 32 DW). This is recorded in
`docs/spec.md` §4.5. Decided by: spec-writer.

## 2026-09-10 — DEC-007: Strictly serialized request servicing
**Context:** a general endpoint pipelines inbound requests and arbitrates outbound
completions against each other.
**Decision:** `pcie_tl` services inbound TLPs in strict arrival order, one at a time,
and holds at most one Completion in flight. It deasserts `rx_tlp_ready` while busy.
**Reasoning:** removes the outbound arbiter, the tag/ordering tracker and a whole class
of ordering bugs, at the cost of throughput that this design does not need. PCIe places
no upper bound on completer latency, so a slow completer is legal. The Python host model
buffers inbound TLPs in an unbounded queue, so stalling `rx_tlp_ready` indefinitely
cannot deadlock the testbench. Decided by: spec-writer.

## 2026-09-10 — DEC-008: Interrupt model is a status bit plus a level `irq` pin; no MSI
**Context:** the spec-writer brief required a choice between MSI and a status bit only.
**Decision:** `STATUS.DONE` / error bits, a maskable `IRQ_ENABLE`, a read-only
`IRQ_STATUS = STATUS & IRQ_ENABLE`, and a level-sensitive top-level output `irq` equal
to `|IRQ_STATUS`. **No MSI, no MSI-X, no INTx.** The configuration space contains **no
capability list at all** (Capabilities Pointer = 0x00, Status[4] = 0).
**Reasoning:** MSI would require (a) an MSI capability structure in config space,
(b) the DUT becoming a *requester* that originates Memory Write TLPs on the TX stream,
and (c) arbitration between those writes and Completions — which directly contradicts
DEC-007 and roughly doubles the transaction-layer RTL. Omitting the capability list also
shortens host enumeration: `PciDevice.walk_capabilities()` terminates immediately and
`is_pcie()` returns False, so the host skips MPS/extended-tag/CRS configuration entirely.
**Consequence:** software polls `STATUS` or watches the `irq` pin. MSI is a v2 item.
Decided by: spec-writer.

## 2026-09-10 — DEC-009: Target clock 100 MHz; PE pipeline depth fixed at one stage
**Context:** `CLAUDE.md` defaults to 100 MHz on sky130hd and lets the circuit designer
relax it, provided the spec records the final number.
**Decision:** the spec targets **100 MHz (10.000 ns)**. The `mm_pe` MAC is a single
pipeline stage: a combinational 8x8 signed multiply feeding a 32-bit accumulate adder,
registered into `acc`.
**Sanctioned relaxation ladder if 100 MHz will not close:** 100 -> 75 -> 50 MHz, each
step recorded here and written back into `docs/spec.md` §13.2 by spec-writer.
**Explicitly not sanctioned:** adding a pipeline stage inside `mm_pe`. That would change
the operation latency from `4N+2` cycles and invalidate REQ-101 and REQ-102, which the
test writer is building tests against. Clock relaxation costs nothing in verification;
pipeline changes cost a spec amendment and a test re-check. Decided by: spec-writer.

## 2026-09-10 — DEC-010: A/B/C storage is flip-flop register files, not SRAM macros
**Context:** the Phase 0 report flagged that sky130hd's SRAM story is the separate
`sky130ram` platform with four fixed OpenRAM macros, and that if none fit the fallback
is flop arrays.
**Decision:** A, B and C are implemented as flip-flop register files inside
`mem_a`, `mem_b`, `mem_c`. **No SRAM macro is instantiated anywhere in this design**,
and the platform stays `sky130hd` (no switch to `sky130ram` or `nangate45`/`fakeram`).
**Reasoning:** at `N = 8` the totals are tiny — A and B are 64 bytes each (512 flops)
and C is 256 bytes (2048 flops), about 3.1 kbit in all. More importantly, the systolic
feed schedule needs `N` *independent* byte reads per cycle from A and `N` from B, and
`N` 32-bit word writes per cycle into C; no single- or dual-port SRAM macro provides
that, so a banked flop array is the natural structure rather than a compromise. Keeping
macros out of the flow also removes macro placement, PDN-over-macro and LVS complications
from Phase 4, which materially improves the odds of reaching `6_final.gds`.
**Consequence:** at `N = 16` the flop count roughly quadruples (C alone becomes 8192
flops); if `N = 16` is ever taken, revisit this decision. Decided by: spec-writer.

## 2026-09-10 — DEC-011: Identification constants
**Context:** the device needs a Vendor/Device ID that the host model will accept.
**Decision:** Vendor ID `0x1234`, Device ID `0x8000`, Revision ID `0x01`, Class Code
`0x120000` (base class 0x12 "Processing Accelerators"), Subsystem Vendor ID `0x1234`,
Subsystem ID `0x0001`. BAR0 `ID` register reads `0x4D415431` (ASCII "MAT1").
**Reasoning:** `0x1234` is not a PCI-SIG-allocated vendor ID and is conventionally used
by emulated devices, so it cannot be confused with real hardware. The combined DWORD at
config offset 0x00 is `0x80001234`, which is not in the set
`{0, 0xFFFFFFFF, 0xFFFF0000, 0x0000FFFF}` that `cocotbext-pcie`'s `PciBus.scan()`
rejects, so enumeration finds the device. Decided by: spec-writer.

## 2026-09-10 — DEC-012: C lives in a separate `mem_c`, not in the accumulators
**Context:** an alternative micro-architecture makes the PE accumulators themselves
host-readable, saving the `mem_c` flops and the entire drain phase.
**Decision:** keep a separate `mem_c` and a drain phase.
**Reasoning:** it decouples the host read path from the array (a 64:1 32-bit read mux
reaching into every PE would put a long combinational path across the whole array,
directly against the 100 MHz target), it lets a test pre-write C and confirm the engine
overwrote it, and it keeps `mm_array` a pure compute block with one narrow output bus.
The cost is 2048 flops at `N = 8`, roughly 0.04 mm^2, which is affordable.
Decided by: spec-writer.

## 2026-09-10 — DEC-013: `IOWr` is handled on the posted path (deliberate deviation)
**Context:** Phase 2b noticed that `docs/spec.md` §4.3 classifies I/O Write as posted.
PCIe Base r6.0 §2.2.7 / Table 2-2 classifies it as **non-posted**, so a compliant
completer answers an unsupported `IOWr` with a UR Completion instead of discarding it.
The RTL follows the spec, so spec and RTL agree; the question is which of them to change.
**Decision:** keep the simplification and record it. `IOWr` stays on the posted path:
discarded, `STATUS.ERR_UNSUP_REQ` set, no Completion.
**Reasoning:** BAR0 is the only BAR and it is a memory BAR; BAR1–BAR5 all read 0 and
`Command.IOSE` has no effect, so the configuration space declares no I/O resources at
all. A conforming root complex will therefore never route an I/O request here — the only
possible source is deliberately malformed test stimulus. Handling `IOWr` on the posted
path removes a decode case from `tlp_rx` and loses nothing a real host could observe.
**Cost of reversing:** move `IOWr` from the posted row to the non-posted row of §4.3;
it then acquires a UR Completion via the existing REQ-040 path, with no other change.
Decided by: spec-writer, on rtl-reviewer's observation.

## 2026-09-10 — Spec amendment batch, v1.0.0 -> v1.1.0
Eleven items raised by rtl-designer, test-writer and the Phase 2b review, all
non-blocking. Full detail is in the `docs/spec.md` change log; summarised here so the
decision history is in one place.
**Spec was wrong, RTL was right (3):** `mm_ctrl` issues the `k=0` operand read indices
in `FETCH`, not `PRIME` — issuing in `PRIME` would double-count the `k=0` product
because `clr_acc` is asserted only in `PRIME`; REQ-119 and REQ-120 were arithmetically
impossible as written and are now stated in terms of `N`.
**Mutually unsatisfiable or underdetermined (4):** REQ-012 (registered `irq`) versus
REQ-080 (`irq` exactly equal to `|IRQ_STATUS`) could not both hold — REQ-080 now allows
2 cycles, REQ-012 is untouched, because an unregistered `irq` would be a combinational
path to a chip output; new REQ-124 covers `START`+`SOFT_RESET` written together while
busy; new REQ-125 replaces REQ-071's unmappable "leaves `mem_c` unchanged" with the
guarantee that actually holds mid-drain; new REQ-122/REQ-123 introduce the `D_WR`
write-path constant so REQ-101's exact `4N+2` becomes observable at the chip pins.
**Record-keeping (4):** `app_rdata_last` removed from §7.3 (dead signal, removed from
RTL in the same round); `IOWr` recorded as DEC-013 above; REQ-077's three structurally
unreachable collisions documented so they are not mistaken for a coverage hole; REQ-041's
Message clause documented as unreachable with `cocotbext-pcie` (its `Tlp.pack_header()`
raises for every `MSG_*` type), covered indirectly by `MWr64`/`IOWr`.
**Numbering:** no existing REQ ID was renumbered or repurposed. REQ-001 … REQ-121 keep
their v1.0.0 identities. Added REQ-122 … REQ-125. Reworded REQ-071, REQ-080, REQ-119,
REQ-120 — those four route to test-writer for a re-check. Decided by: spec-writer.

## 2026-09-10 — Spec correction, v1.1.0 -> v1.1.1: one definition of `t_start`
**Context:** rtl-designer measured `D_WR = 1` and `DONE` at `t_beat + 4N + 2` (34 at
`N=8`), while v1.1.0's new REQ-123 demanded `t_beat + D_WR + 4N + 2` (35). It reported
rather than patching, which was correct.
**Root cause (not the off-by-one):** v1.1.0 used "accepted" and "updated" loosely, so
REQ-074 placed `t_start` at the cycle the `CTRL` write is *taken* while §9.6 placed it
at the cycle the write becomes *visible*. Those are one cycle apart, and REQ-123 then
added `D_WR` on top of a `4N+2` that already started at `t_beat` — double-counting the
write path.
**Decision:** option (b). REQ-123 reads `t_beat + 4*N + 2`. §9.6 now names `t_beat`,
`t_start` and `t_commit` as three distinct terms, fixes `t_start = t_beat`, and states
explicitly that `D_WR` is **not** a term in any latency formula — it survives only as
the write-*visibility* invariant of REQ-122. Option (a) (`+ D_WR + 4N + 1`) was
rejected: keeping `D_WR` in the formula is exactly what invited the double-count, and
the `+1` correction would have looked arbitrary rather than derived.
**No RTL change required**; the v1 RTL already satisfies the corrected REQ-123.
Decided by: spec-writer, on rtl-designer's measurement.

## 2026-09-10 — Spec correction, v1.1.1 -> v1.1.2
**1. REQ-119 repaired a second time.** The v1.1.0 fix ("one maximal burst per operand",
`ceil(N*N/4)` DW) was correct only up to `N = 8`. At `N = 16` an operand is 64 DW and at
`N = 32` it is 256 DW, both over the 32-DW burst cap of REQ-018/REQ-056, so the
requirement stayed unsatisfiable for two of the five legal `N` — the original defect
class, relocated rather than removed. Burst count is now `ceil(ceil(N*N/4)/32)`.
**Lesson recorded:** any requirement that names a burst size must be written as a
function of `N` and checked against the 32-DW cap at `N = 32`, not just at the v1 value.
REQ-120 was re-checked under the same lens and is correct unmodified (`ceil(N*N/32)`
bursts; at `N = 32` the last burst ends exactly on the 4096-byte C region boundary).
**2. REQ-126 added** for a behavior rtl-designer introduced in response to Phase 2b
"Should fix" item 3: `CfgRd0`/`CfgWr0` with `Length != 1` is malformed (PCIe Base r6.0
§2.2.7 fixes Configuration Requests at one DWORD) and is answered with UR, with surplus
payload drained to `eop`. The RTL had the behavior but no requirement, so no test
covered it. Clause (d) — that `STATUS.ERR_UNSUP_REQ` is set — is the one part **not** in
the verified-behavior report; it is specified that way for consistency with §4.3's
treatment of other malformed TLPs, and rtl-designer should confirm or flag it.
Decided by: spec-writer, on test-writer's findings.

## 2026-09-10 — Spec correction, v1.1.2 -> v1.1.3: overlap-class cleanup
**Context:** round-2 review found REQ-042's antecedent ("`CfgRd0`/`CfgWr0` with non-zero
Device or Function Number") still literally covering a malformed-`Length` request and
forbidding `ERR_UNSUP_REQ`, while the newer REQ-126 requires it. Behaviour was never in
doubt — the RTL follows REQ-126 and the reviewer verified it — but the contradiction was
settled only by REQ-126's precedence sentence.
**Decision:** resolve overlaps by making antecedents **disjoint by construction**, never
by a precedence clause. A reader who lands on the older requirement must not be misled,
and precedence clauses only work if you happen to read both requirements.
**Two instances fixed:** REQ-042 gains "with `Length` == 1" (disjoint from REQ-126);
REQ-070 gains "with `CTRL.SOFT_RESET` written 0 in the same DWORD" (disjoint from
REQ-124). REQ-070 was found by the audit, not by review. No behavior change; both
narrowed antecedents still cover the cases the existing passing tests exercise.
**Audit recorded in `docs/spec.md`** under "Overlap audit (v1.1.3)", listing the pairs
checked and found already disjoint, so the next amendment does not repeat the work.
**Lesson:** this is the second overlap-class defect found in review rather than by test.
When adding a requirement that carves an exception out of an existing one, amend the
existing one's antecedent in the same edit. Decided by: spec-writer, on rtl-reviewer's
round-2 finding.

## 2026-09-10 — Spec correction, v1.1.3 -> v1.1.4: BUG-004, over-length memory requests
**Context:** Phase 3 found zero RTL defects but reported BUG-004 — nothing specified the
outcome for an in-aperture memory request with decoded length > 32 DW, including the
`Length` = 0 / 1024-DW encoding. The RTL returns UR (`tlp_rx.sv:200`), which is correct
but was unrequired and therefore untested.
**Refinement of the diagnosis:** REQ-017 and REQ-018 *did* already mandate rejecting
such a request, and REQ-019 already mandated the payload drain. The real gap was the
**dangling consequence chain**: REQ-018 said "reject as an unsupported request", but the
requirements that define what rejection looks like — REQ-040 and REQ-041 — key off the
TLP *type* tables in §4.3, and an over-length `MRd` is a *supported* type. So nothing
said UR, nothing said `ERR_UNSUP_REQ`, nothing said the write payload must be drained
without desynchronizing the parser.
**Decision:** added REQ-127 stating the observable outcome, explicitly independent of
address and of `Command.MSE`, and explicitly decoding `Length` = 0 as 1024 DW rather
than zero. Narrowed REQ-044's antecedent to `1 <= L <= 32` so the two are disjoint by
construction — this was the third instance of the overlap defect class (after
REQ-042/126 and REQ-070/124), so §7.6 now records the disjointness argument against
REQ-044, REQ-056, REQ-017/018 and REQ-038/039 inline.
**Lesson:** a requirement that says "shall reject" is incomplete unless some other
requirement defines the observable form of rejection *for that antecedent*. Deferring to
a table that is keyed on a different attribute (type, not length) does not compose.
Decided by: spec-writer, on validation-specialist's BUG-004.

## 2026-09-10 — Open questions for the human (spec-writer, Phase 1)
None of these block Phase 2. They are recorded so they are not silently omitted.

**OQ-001 — Does 100 MHz actually close in sky130hd?** The estimated critical path is an
8x8 signed multiply plus a 32-bit accumulate adder in one 10 ns cycle. This is an
estimate, not a measurement; the first synthesis run in Phase 4 settles it. If it does
not close, DEC-009's ladder applies and no spec amendment beyond the clock number is
needed.

**OQ-002 — Estimated area is unvalidated.** Rough estimate for `N = 8` in sky130hd:
~6.6 k flops plus 64 multiply-accumulate datapaths, about 0.35 mm^2 of cells, so roughly
a 800 x 800 um die at ~55% utilization. If the real number is far off, the human may
prefer `nangate45` (3x faster iteration, and its `fakeram` generator is available)
over `sky130hd`. The spec is platform-neutral; only `flow/config.mk` would change.

**OQ-003 — Should DMA (`CLAUDE.md`'s stretch goal) reuse this TX stream?** The
`tx_tlp_*` stream as specified can carry a Memory Write just as easily as a Completion,
so DMA is a natural extension. But it breaks DEC-007 (it needs an outbound arbiter) and
would want MSI (DEC-008). Recommendation: do not attempt it in v1; if it is taken up
after Phase 4, DEC-007 and DEC-008 must both be reopened.

**OQ-004 — Gate-level simulation needs sky130 cell models that are not on this
machine** (Phase 0 report §6, carried-forward item 3). Not a spec issue, but it gates
the Phase 4 exit criterion, so someone has to fetch them before Phase 4.

---

## 2026-09-11 — Phase 4 physical design (circuit-designer)

**DEC-014 — Keep A/B/C as flip-flops; no memory macro, no shrink of `N`.**
The Phase 4 brief requires a decision, before place-and-route, on whether the
Yosys-inferred flop register files are affordable on this platform. Measured at
`N = 8` on sky130hd from `reports/sky130hd/pcie_matmul/base/synth_stat.txt`:

| Metric | Value |
|--------|-------|
| Mapped standard cells | 53,880 |
| `sky130_fd_sc_hd__dfxtp_1` (all storage, incl. A/B/C/PE accumulators) | 6,616 |
| Cell area | 518,645 um^2 |
| of which sequential | 132,447 um^2 (25.5%) |

This is affordable: it is the same order as ORFS's own sky130hd `aes` and `jpeg`
designs, which route on this platform. Sequential logic is only a quarter of the
area, so a memory macro would recover at most ~25% of the die while (a) breaking
DEC-010, (b) breaking the `D_WR = 1` write latency of REQ-122, which no
single-cycle-write SRAM in `platforms/sky130ram` supports for the byte-enabled
`N`-port read pattern `mem_a`/`mem_b` need, and (c) invalidating 72 passing
Phase 3 tests. Options (a) shrink `N` and (c) ask for a narrower array are
therefore both rejected as unnecessary, and option (b) a platform macro is
rejected as incompatible with the validated interface contract.
**Consequence:** the binding difficulty in Phase 4 is routing congestion, not
area. `flow/config.mk` sets `CORE_UTILIZATION = 35` (not the platform default
implied ~50-60%) for that reason, matching what ORFS uses for its own
congestion-limited sky130hd design, `aes`.

This resolves the area half of **OQ-002**: the real cell area is 0.52 mm^2,
about 1.5x the 0.35 mm^2 estimate, and at 35% utilization the core is ~1.22 mm
on a side. That is large but not unworkable, so `sky130hd` is retained and the
`nangate45` fallback in OQ-002 is **not** invoked.

**DEC-015 — I/O timing budget at the TLP boundary: 40% of the clock period.**
The spec fixes no external timing budget for the `rx_tlp_*` / `tx_tlp_*` / `irq`
boundary, so one had to be assumed. `flow/constraint.sdc` sets
`set_input_delay` and `set_output_delay` to `0.40 * clk_period` = 4.000 ns,
per the circuit-designer brief's default. This is deliberately pessimistic
relative to the 20% that every ORFS sky130hd example design uses, and it leaves
6.0 ns for the pin-to-flop TLP classifier (`tlp_rx.sv:200-222`, the Phase 2b
reviewer's predicted path #5). If a boundary path turns out to be the binding
constraint, relaxing this number to the ORFS-conventional 20% is the first
move, and it will be recorded here with the before/after slack.

**OQ-004 is now actionable, not just open.** Confirmed by direct search: no
sky130 PDK, no `sky130_fd_sc_hd.v`, no `volare` and no `magic` exist anywhere on
this machine, and ORFS's `platforms/sky130hd/` ships only the three Yosys
*mapping* files (`cells_adders_hd.v`, `cells_clkgate_hd.v`,
`cells_latch_hd.v`), which are not simulation models. Network access to GitHub
is available and `github.com/google/skywater-pdk-libs-sky130_fd_sc_hd` (branch
`main`) carries per-cell `.v` with `specify` blocks, which is what Icarus needs
for SDF back-annotation. `flow/make_gl_models.sh` fetches exactly the cells the
final netlist instantiates. The Phase 4 gate-level simulation is therefore
unblocked, but it depends on network access at that moment.

**DEC-016 — 100 MHz closed; the DEC-009 relaxation ladder is NOT invoked.**
Measured post-route on sky130hd at `N = 8`, typical corner, 10.000 ns:
setup violation count **0**, hold violation count **0**, WNS/TNS **0.00/0.00**,
worst setup slack **+0.30 ns**, worst hold slack **+0.42 ns**. Reg-to-reg
`period_min` is 8.20 ns (fmax 121.98 MHz), so the PE MAC — the path §13.2
predicted would be critical — finishes with **+1.80 ns** of slack and is not the
binding constraint. **OQ-001 is closed: yes, 100 MHz closes.** No clock number
changes anywhere; spec §13.2 stands as written. Zero of the four permitted
closure iterations were used.

For the record, the number that *would* have moved first if it had not closed:
the binding path is `rst` (input pin) -> 3 levels of logic -> `tx_tlp_data[20]`
(output pin), of which only 1.69 ns is silicon and 8.00 ns is the DEC-015 I/O
budget. Relaxing DEC-015 from 40% to the ORFS-conventional 20% would take that
path from +0.30 ns to roughly +4.30 ns and leave the design PE-limited at
~122 MHz. It was not needed, so it was not done.

**DEC-017 — One residual antenna violation accepted for v1.**
`check_antennas` on `6_final.odb` reports one violating net, `net2802` into
`u_app_bar0.u_mem_b.e_rdata[58]/D`: met5 side-area ratio 16988.95 against a
10781.00 limit. ORFS's diode-repair loop hit its iteration cap and oscillated
8 -> 1 -> 2 -> 1 without clearing it, after inserting 242 diodes.
Before: 8 antenna violations. After: 1.
Neither ORFS DRC checker counts it — the detailed router reports 0 and the
sky130hd KLayout sign-off deck reports 0, and neither deck contains antenna
rules — so the Phase 4 gate's "zero DRC violations" criterion is met as written.
Accepted rather than fixed because the only remedy is raising
`MAX_REPAIR_ANTENNAS_ITER_DRT` and re-routing, which costs ~97 minutes for one
net out of 76,784 instances. Recorded here so it is not rediscovered as a
surprise: a real tapeout would have to clear it.

**DEC-018 — Re-ran the full flow on the BUG-007-fixed RTL; no config change, no
clock relaxation, DEC-017 closed.** Run 1's GDS was clean but built from a
netlist in which a Yosys `peepopt` mis-transformation deleted PE row 6's A
operand. `rtl/mem_a.sv`/`mem_b.sv` now use an explicit N-way mux over
constant-base slices. Measured effect at `N = 8` on sky130hd:

| Metric | Run 1 (defective) | Run 2 (fixed) |
|---|---|---|
| ABC-mapped cells | 53,880 | 55,457 (+2.9%) |
| Flip-flops | 6,616 | 6,680 |
| Die area | 1,478,510 um^2 | 1,525,570 um^2 (+3.2%) |
| Final utilization | 40.46% | 40.38% |
| Worst setup slack | +0.30 ns | **+0.05 ns** |
| Reg-to-reg fmax | 121.98 MHz | **125.69 MHz** |
| Worst hold slack | +0.42 ns | +0.43 ns |
| Router / KLayout DRC | 0 / 0 | 0 / 0 |
| Antenna violations | 1 | **0** |
| Power | 77.8 mW | 78.0 mW |

**100 MHz still closes; the DEC-009 ladder is still not invoked** and spec §13.2
is unchanged. `CORE_UTILIZATION` stays at 35 and the floorplan is unchanged:
ORFS sizes the die from cell area, so the +3.2% cells produced a +3.2% die and
held utilization flat, which is the correct behaviour and needed no
intervention. Zero of the four permitted closure iterations used.

**DEC-017 is closed, not merely accepted.** The single residual met5 antenna
violation from run 1 did not recur; run 2's diode-repair loop converged
53 -> 5 -> **0** with 149 diodes. Before: 1. After: 0.

The binding path is unchanged in kind: `rst` (input pin) -> ~1.7 ns of logic ->
`tx_tlp_data[8]` (output pin). 8.00 of the 10.00 ns is the DEC-015 40% I/O
budget. That assumption, not the design, is what sets the +0.05 ns margin;
relaxing it to the ORFS-conventional 20% would restore ~4.3 ns. **It was not
relaxed**, because the design closes without it. Recorded as the first lever for
any future respin.

The new `mem_a`/`mem_b` operand mux was checked explicitly against STA rather
than assumed benign, per the coordinator's instruction: worst path into it is
**+2.586 ns** (`mem_a.e_rdata[51]`) / **+2.658 ns** (`mem_b.e_rdata[33]`). Not a
critical path. The replacement structure is *faster* than the `$shiftx` it
replaced.

**Process change adopted: `tb/gl/postsyn_replay.sh` is now a mandatory
pre-flight before any full P&R run on changed RTL.** It ran 72/72 in 86 seconds
on the fixed RTL before run 2 started. BUG-007 cost a full 110-minute flow plus
a gate-level debug; this check would have caught it in under two minutes.
