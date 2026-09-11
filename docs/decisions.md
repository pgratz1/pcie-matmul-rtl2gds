
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
