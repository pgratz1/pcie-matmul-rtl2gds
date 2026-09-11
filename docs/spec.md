# PCIe-Attached Matrix Multiplier — Architecture and Micro-Architecture Specification

**Spec version: 1.1.3**
**Date: 2026-09-10**
**Owner: spec-writer**
**Status: Phase 1 deliverable. Binding on rtl-designer, test-writer, rtl-reviewer, circuit-designer.**

Companion documents:

- `docs/register-map.md` — BAR0 register map (same source of truth as this file; the
  two must never disagree).
- `docs/decisions.md` — dated decision log. DEC-001 … DEC-012 are binding inputs to
  and outputs of this spec.

Change log:

| Version | Date | Change | REQ IDs affected |
|---------|------|--------|------------------|
| 1.0.0 | 2026-09-10 | Initial issue. | all (REQ-001 … REQ-121) |
| 1.1.0 | 2026-09-10 | Amendment batch from Phase 2 (rtl-designer, test-writer) and the Phase 2b review. 11 items; no requirement was renumbered or repurposed. | **Reworded:** REQ-071, REQ-080, REQ-119, REQ-120. **Added:** REQ-122 … REQ-125. **Informative notes only, meaning unchanged:** REQ-012, REQ-021, REQ-041, REQ-077, REQ-101. |

| 1.1.1 | 2026-09-10 | Fixed an internal inconsistency in the definition of `t_start`, and the REQ-123 off-by-one it caused. §9.6 now names `t_beat`, `t_start` and `t_commit` separately and fixes `t_start = t_beat`. `D_WR` is deliberately excluded from every latency formula. No RTL change required. | **Corrected:** REQ-123 (`t_beat + 4*N + 2`, was `t_beat + D_WR + 4*N + 2`). **Clarified, meaning unchanged:** REQ-074, REQ-101, REQ-122. |

| 1.1.2 | 2026-09-10 | REQ-119's v1.1.0 repair was still unsatisfiable at `N`=16 and `N`=32 (one operand is 64 and 256 DW, over the 32-DW burst cap); burst count is now `ceil(ceil(N*N/4)/32)`. REQ-120 re-checked and confirmed correct for all legal `N`. Added REQ-126 for malformed-`Length` configuration requests. | **Corrected:** REQ-119. **Added:** REQ-126. **Re-confirmed, unchanged:** REQ-120. |

| 1.1.3 | 2026-09-10 | Overlap-class cleanup. Two older requirements had antecedents broad enough to literally forbid what a newer, more specific requirement demands, with the conflict resolved only by a precedence sentence. Both antecedents narrowed so the pairs are disjoint by construction. No behavior change. | **Antecedent narrowed:** REQ-042 (now disjoint from REQ-126), REQ-070 (now disjoint from REQ-124). |

### Overlap audit (v1.1.3)

Every requirement added or reworded in v1.1.0 – v1.1.2 was re-read against the
original 121 looking for one specific shape: **an older requirement whose antecedent
is broad enough to cover a case a newer requirement handles differently, where the
contradiction is settled only by a tie-breaker clause rather than by the two texts
being disjoint.** Two instances existed; both are fixed in v1.1.3.

| Newer req | Older req with an over-broad antecedent | Resolution |
|-----------|----------------------------------------|------------|
| REQ-126 (config `Length != 1` -> UR **and** `ERR_UNSUP_REQ` set) | REQ-042 (config to non-zero Device/Function -> UR and `ERR_UNSUP_REQ` **not** set) | REQ-042 antecedent gains "with `Length` == 1". |
| REQ-124 (`START`+`SOFT_RESET` while `BUSY` -> `ERR_START_BUSY` reads 0) | REQ-070 (`START` while `BUSY` -> `ERR_START_BUSY` **set**) | REQ-070 antecedent gains "with `CTRL.SOFT_RESET` written 0 in the same DWORD". |

Pairs checked and found already disjoint or already consistent, needing no change:
REQ-125 vs REQ-071 (REQ-071's `mem_c` clause was narrowed in v1.1.0, so the two are
already disjoint); REQ-123 vs REQ-074 and REQ-101 (reconciled in v1.1.1 by fixing
`t_start = t_beat` — all three now measure from the same cycle and agree in value);
REQ-122 (defines a constant, constrains no transaction, so it cannot overlap);
REQ-119 and REQ-120 (disjoint by direction — writes versus reads — and by region);
REQ-062 vs REQ-063 (disjoint by direction); REQ-044 vs REQ-038/REQ-039 (REQ-044
explicitly defers rather than restating); REQ-017 vs REQ-126 (a `Length`=0
configuration request falls under both, but they demand the *same* outcome — UR plus
`ERR_UNSUP_REQ` — so there is no contradiction to resolve).

One redundancy, deliberately left alone: REQ-081 (clearing deasserts `irq` within 2
cycles) is now a strict subset of the reworded REQ-080 (tracks within 2 cycles in both
directions). They agree, REQ-081 is simply the deassertion half stated separately, and
it has a passing test mapped to it. Narrowing or deleting it would churn
`tb/TESTPLAN.md` for no gain.

### What changed in v1.1.0, and what the test writer must re-check

**Meaning changed — re-check these four tests:**

| ID | Change |
|----|--------|
| REQ-071 | The `mem_c` clause is narrowed. `SOFT_RESET` no longer claims to leave `mem_c` "unchanged"; it claims only that it does not itself modify `mem_c`. The reachable guarantee moved to the new REQ-125. |
| REQ-080 | Was "`irq` is 1 **iff** `IRQ_STATUS != 0`", which contradicted REQ-012's *registered* output. Now "tracks within 2 clock cycles in both directions". REQ-012 is unchanged. |
| REQ-119 | Was arithmetically impossible (one 32-DW burst cannot span A at `0x1000` and B at `0x2000`, and A+B is 32 DW not 64). Now: one maximal burst per operand versus `2*ceil(N*N/4)` single-DW writes. |
| REQ-120 | Was arithmetically impossible (C is 64 DW at `N=8`, so one 32-DW burst covers half of it while the 64 single-DW reads covered all of it). Now: `ceil(N*N/32)` maximal bursts versus `N*N` single-DW reads, both covering all of C. |

**Added — four new tests needed:** REQ-122, REQ-123 (§9.6, the `D_WR` write-path
constant and the pin-observable form of the `4N+2` latency), REQ-124, REQ-125
(§10.3, `START`+`SOFT_RESET` together while busy, and `SOFT_RESET` mid-`DRAIN`).

**Unchanged in meaning, but read the new notes:** REQ-012 (kept as-is; REQ-080 moved
instead), REQ-021 (still a bound; §9.6 now closes the observability gap), REQ-041
(Message clause is unreachable with this host model — documented limitation, not a
coverage hole), REQ-077 (three of its four collisions are structurally unreachable),
REQ-101 (unchanged; REQ-123 is its boundary-observable restatement).

**Non-requirement corrections:** §12.5 `PRIME`/`FETCH` (operand read indices are
issued in `FETCH`, not `PRIME` — issuing in `PRIME` would double-count the `k=0`
product); §7.3 (`app_rdata_last` removed from the interface table); §4.3 (`IOWr`
treated as posted — recorded as a deliberate v1 simplification, DEC-013).

---

## 1. Scope and non-goals

### 1.1 What this design is

A single-clock, single-reset digital ASIC block, `matmul_top`, that:

1. Terminates a **PCIe Transaction Layer**: it parses inbound TLPs, implements a
   minimal Type 0 configuration space sufficient for a root complex to enumerate it
   and assign one 16 KiB memory BAR, and builds outbound Completion TLPs.
2. Exposes, through BAR0, a control/status register block and three operand
   storages (A, B, C).
3. Computes `C = A x B` for two `N x N` signed 8-bit integer matrices into 32-bit
   signed accumulators, using an `N x N` output-stationary systolic array.

Everything in `matmul_top` is synthesizable and goes through OpenROAD to GDS-II.

### 1.2 What is behavioral-model-only (never synthesized)

| Layer | Where it lives | Notes |
|-------|----------------|-------|
| PCIe Physical Layer (PHY), SerDes, PIPE | **Does not exist anywhere in this project.** | No open PDK ships a PCIe SerDes. See DEC-002. |
| Link training / LTSSM | Not modeled at all. | The link is assumed permanently up. |
| PCIe Data Link Layer (DLL) | `cocotbext-pcie`'s Python `Port`/`SimPort` classes, inside the testbench. | See §4.4 for exactly what it does and does not do. |
| Root complex, host bridge, host memory, enumeration software | `cocotbext.pcie.core.RootComplex`, inside the testbench. | |
| TLP encode/decode on the host side | `cocotbext.pcie.core.tlp.Tlp`, inside the testbench. | The testbench never hand-writes TLP encode/decode (`CLAUDE.md` rule). |
| The DWORD-stream shim between `Tlp` objects and the DUT pins | `tb/models/` (test-writer owns). | Specified in §5; buildable from this document alone. |

### 1.3 Explicit non-goals for v1

- **No PIPE interface.** Ruled out by DEC-002; `cocotbext-pcie` 0.2.16 contains no
  PIPE model at all.
- **No DLL in RTL.** No DLLP is generated or consumed by the DUT. No sequence
  numbers, no LCRC, no ACK/NAK, no replay buffer, no credit accounting. See §4.4.
- **No DMA / no requester role.** `matmul_top` is a pure *completer*. It never
  originates a Memory Read, Memory Write, or Message TLP. (DMA is a `CLAUDE.md`
  stretch goal gated on Phase 4.)
- **No MSI / MSI-X.** The configuration space contains **no capability list**
  (Capabilities Pointer = 0x00, Status[4] = 0). Interrupt delivery is a level
  output pin plus a status bit. See DEC-008 and §10.6.
- **No 64-bit addressing.** BAR0 is a 32-bit non-prefetchable memory BAR. 4 DW
  (64-bit address) requests are Unsupported Requests.
- **No I/O space, no Expansion ROM, no INTx.**
- **No completion splitting.** One Completion per Memory Read Request. See DEC-006.
- **No multiple outstanding requests inside the DUT.** Requests are serviced
  strictly in arrival order, one at a time. See DEC-007.
- **No BF16, no floating point.** INT8 x INT8 -> INT32 only.
- **No accumulate-into-C.** Every operation overwrites C completely.
- **No clock gating, no power management, no D-states beyond D0.**
- **No SRAM macros.** A, B and C storage are flip-flop register files. See DEC-010.
- **No CDC.** One clock, one reset, zero clock-domain crossings. See §13.

---

## 2. Fixed parameters for v1

| Parameter | v1 value | Kind | Legal range |
|-----------|----------|------|-------------|
| `N` (array/matrix dimension) | **8** | compile-time parameter of `matmul_top` | power of two, `2 <= N <= 32` |
| `DW` (operand width, bits) | **8** | compile-time parameter | `8` only in v1 |
| `ACCW` (accumulator width, bits) | **32** | compile-time parameter | `32` only in v1 |
| BAR0 aperture | 16384 B (16 KiB) | hard constant, not a parameter | fixed for all legal `N` |
| Target clock | **100 MHz** (10.000 ns period) | SDC constraint | see §13.2 for the sanctioned relaxation ladder |
| PDK / platform | `sky130hd` | ORFS | |
| Numeric format | signed two's complement | | |

`N = 8` for v1 is DEC-004. `N` remains a genuine compile-time parameter; nothing in
this specification is allowed to assume `N == 8`.

---

## 3. Top-level block diagram

Every box below is one SystemVerilog module. **These are the RTL module names.** One
module per file, file name = module name + `.sv`.

```
                         host (cocotbext-pcie RootComplex, Python)
                                        |
                     ==================================================
                       behavioral DLL + link   (cocotbext-pcie SimPort)
                       TLP <-> DWORD shim      (tb/models/, Python)
                     ==================================================
                                        |
  ------------------------------ chip boundary -------------------------------
   rx_tlp_data[31:0] rx_tlp_sop rx_tlp_eop rx_tlp_valid  ->  |          | -> rx_tlp_ready
   tx_tlp_data[31:0] tx_tlp_sop tx_tlp_eop tx_tlp_valid  <-  |          | <- tx_tlp_ready
                                                             |          | -> irq
  +--------------------------------------------------------------------------+
  | matmul_top                                                               |
  |                                                                          |
  |  +------------------------------------------+                            |
  |  | pcie_tl                                  |                            |
  |  |                                          |                            |
  |  |  +-----------+   +------------------+    |                            |
  |  |  | tlp_rx    |-->| pcie_cfg_space   |    |   cfg_bar0_base[31:14]     |
  |  |  |  header   |   |  Type 0 cfg regs |----|-- cfg_mem_space_en         |
  |  |  |  parse,   |   |  BAR0 decode,    |    |   cfg_completer_id[15:0]   |
  |  |  |  payload  |   |  bus/dev capture |    |                            |
  |  |  |  steering |   +------------------+    |                            |
  |  |  +-----+-----+            |              |                            |
  |  |        | app request      | cfg rsp      |                            |
  |  |        v                  v              |                            |
  |  |  +--------------------------------+      |                            |
  |  |  | tlp_tx                         |------|--> tx_tlp_* (completions)  |
  |  |  |  Cpl / CplD header build       |      |                            |
  |  |  +--------------------------------+      |                            |
  |  +--------------|---------------^-----------+                            |
  |                 | app_req       | app_rsp                                |
  |                 v               |                                        |
  |  +--------------------------------------------------+                    |
  |  | app_bar0   (BAR0 offset decode + burst sequencer) |                    |
  |  |                                                   |                    |
  |  |  +----------+  +--------+  +--------+  +--------+ |                    |
  |  |  | reg_file |  | mem_a  |  | mem_b  |  | mem_c  | |                    |
  |  |  | 0x0000.. |  | 0x1000 |  | 0x2000 |  | 0x3000 | |                    |
  |  |  +----+-----+  +---+----+  +---+----+  +---+----+ |                    |
  |  +-------|------------|-----------|-----------|------+                    |
  |          | ctrl/status|  a_rd     |  b_rd     | c_wr                      |
  |          v            v           v           ^                           |
  |  +------------------------------------------------------+                 |
  |  | matmul_engine                                        |                 |
  |  |   +------------+        +-------------------------+  |                 |
  |  |   | mm_ctrl    |------->| mm_array                |  |                 |
  |  |   |  FSM,      |        |   N x N instances of    |  |                 |
  |  |   |  operand   |        |   +---------+           |  |                 |
  |  |   |  addressing|        |   | mm_pe   |           |  |                 |
  |  |   |  drain seq |<-------|   +---------+           |  |                 |
  |  |   +------------+        +-------------------------+  |                 |
  |  +------------------------------------------------------+                 |
  |                                                          --> irq          |
  +--------------------------------------------------------------------------+
```

Module list, in hierarchy order:

| # | Module | Section | Instances |
|---|--------|---------|-----------|
| 1 | `matmul_top` | §6 | 1 (top) |
| 2 | `pcie_tl` | §7 | 1 |
| 3 | `tlp_rx` | §7.3 | 1 |
| 4 | `tlp_tx` | §7.4 | 1 |
| 5 | `pcie_cfg_space` | §8 | 1 |
| 6 | `app_bar0` | §9 | 1 |
| 7 | `reg_file` | §10 | 1 |
| 8 | `mem_a` | §11.1 | 1 |
| 9 | `mem_b` | §11.2 | 1 |
| 10 | `mem_c` | §11.3 | 1 |
| 11 | `matmul_engine` | §12.1 | 1 |
| 12 | `mm_pe` | §12.3 | `N*N` (64 for `N=8`) |
| 13 | `mm_array` | §12.4 | 1 |
| 14 | `mm_ctrl` | §12.5 | 1 |

(§12.2 states and justifies the dataflow choice that §12.3–§12.5 implement;
§12.6 states the accumulator width and overflow policy.)

Only `matmul_top`'s port list (§6.1) is binding on the test writer. The module names
above and the functional split between them are binding on the rtl-designer and the
rtl-reviewer. Internal signal names are advisory; internal *behaviour* and the
stated latencies are binding.

---

## 4. PCIe endpoint scope

### 4.1 Where the chip boundary is

`CLAUDE.md` originally placed the synthesizable boundary at PIPE. Phase 0 found that
`cocotbext-pcie` 0.2.16 has no PIPE model (DEC-002), so PIPE is out. This spec places
the boundary **one layer higher, at the TLP layer**: `matmul_top` ingests and emits
complete, DLL-stripped TLPs on a 32-bit synchronous valid/ready DWORD stream
(§5). This is DEC-003, Option B.

Consequence: the design still owns everything `CLAUDE.md`'s layering section assigns
to layer 3 and layer 4 — TLP header parse and build, Memory Read/Write to BAR0,
Completion generation, a minimal Type 0 configuration space sufficient for BAR
assignment, and the whole application layer. Only layers 1 and 2 are modeled.

### 4.2 TLP types the DUT accepts

| TLP | Fmt[2:0] | Type[4:0] | Direction | DUT behaviour |
|-----|----------|-----------|-----------|---------------|
| `MRd` (Memory Read, 3 DW) | `000` | `00000` | inbound | Serviced if it hits BAR0 and Memory Space Enable = 1; one `CplD` returned. Otherwise `Cpl` with UR. |
| `MWr` (Memory Write, 3 DW) | `010` | `00000` | inbound | Serviced if it hits BAR0 and Memory Space Enable = 1. Posted: no Completion. Otherwise discarded. |
| `CfgRd0` (Config Read Type 0) | `000` | `00100` | inbound | Serviced if Device Number = 0 and Function Number = 0; one `CplD` returned. Otherwise `Cpl` with UR. |
| `CfgWr0` (Config Write Type 0) | `010` | `00100` | inbound | Serviced if Device Number = 0 and Function Number = 0; one `Cpl` (no data) returned. Otherwise `Cpl` with UR. |
| `Cpl` (Completion, no data) | `000` | `01010` | **outbound only** | Generated by the DUT. |
| `CplD` (Completion with data) | `010` | `01010` | **outbound only** | Generated by the DUT. |

### 4.3 TLP types the DUT rejects

| TLP class | Examples | DUT behaviour |
|-----------|----------|---------------|
| Non-posted, unsupported | `MRd64` (Fmt `001`), `MRdLk`, `IORd`, `CfgRd1`/`CfgWr1` (Type `00101`), `FetchAdd`, `Swap`, `CAS` | Return `Cpl` with status **UR**; set `STATUS.ERR_UNSUP_REQ`. |
| Posted, unsupported | `MWr64` (Fmt `011`), `IOWr` (see note), any Message (`Msg`/`MsgD`) | Discard; set `STATUS.ERR_UNSUP_REQ`. No Completion (posted requests get none). |

> **Deliberate deviation — `IOWr` is treated as posted.** PCIe Base r6.0 §2.2.7 and
> Table 2-2 classify I/O Write as a **non-posted** request, so a fully compliant
> completer would answer an unsupported `IOWr` with a UR Completion rather than
> discarding it silently. This design discards it, i.e. it handles `IOWr` on the
> posted path. This is **accepted as a v1 simplification, not a defect.** Rationale:
> BAR0 is the only BAR and it is a memory BAR, the configuration space declares no
> I/O BARs at all (all of BAR1–BAR5 read 0 and `Command.IOSE` has no effect), so a
> conforming root complex will never route an I/O request to this device; the only
> source of one is a deliberately malformed test stimulus. Handling it on the posted
> path saves a decode case in `tlp_rx` and loses nothing a real host would notice.
> Recorded as DEC-013. If strict compliance is ever wanted, move `IOWr` to the
> non-posted row above and it acquires a UR Completion with no other change.
| Completions arriving inbound | `Cpl`, `CplD` | Discard silently. The DUT is never a requester, so a Completion arriving is a host-model error, not a DUT error. Do **not** set an error bit and do **not** return a Completion (PCIe Base r6.0 §2.3.2: a Completion never generates a Completion). |
| Any TLP with `TD` = 1 (TLP digest present) | | Treated as unsupported: same as the two rows above according to posted/non-posted. |
| Any TLP with `EP` = 1 (poisoned) | | Same as `TD` = 1. |

### 4.4 Data Link Layer: implemented vs. modeled

**Implemented in RTL: nothing.** The DUT has no DLL.

**Modeled behaviorally** by `cocotbext.pcie.core.port.Port` / `SimPort`, which sits
between the `RootComplex` and the DWORD-stream shim in the testbench:

| DLL feature | Modeled? | Detail |
|-------------|----------|--------|
| TLP sequence numbers | Yes | `Port.next_transmit_seq` / `next_recv_seq`, 12-bit, per PCIe Base r6.0 §3.5.2. |
| Ack DLLP | Yes | Generated on the ACK latency timer. `DllpType.ACK`. |
| Nak DLLP | Yes, generation only | `DllpType.NAK` is generated on out-of-sequence receipt. Replay is **not** implemented in the library (it raises). Since the shim is lossless, this path is never exercised. |
| Flow-control init (`InitFC1`/`InitFC2`, P/NP/CPL) | Yes | Credit values from `Device`'s default `fc_init` = P 64 hdr / 1024 data, NP 64/64, CPL 0/0 (0 = infinite). |
| `UpdateFC` DLLPs | Yes | Periodic and on credit release. |
| Credit gating of transmits | Yes | `Port.send()` blocks until credit is available. This is the source of `tx_tlp_ready` backpressure the DUT will see. |
| LCRC | **No** | Never computed or checked. TLPs are passed as Python objects across the link model. |
| ECRC / TLP digest | **No** | `TD` is always 0 on inbound TLPs. |
| Replay buffer / retry | **No** | The library raises on NAK replay. The link is lossless by construction. |
| DLLP CRC-16 | **No** | |
| Link training (LTSSM), `PM_Enter_L1`, etc. | **No** | The link is up from time zero. |

**Supported DLLPs, stated exactly as `CLAUDE.md` requires:** `Ack`, `Nak`,
`InitFC1-P/NP/Cpl`, `InitFC2-P/NP/Cpl`, `UpdateFC-P/NP/Cpl`, `Nop`. All of them exist
only in Python. **Zero DLLPs cross the chip boundary.** The DUT neither sees nor
produces one.

### 4.5 Testbench configuration the DUT depends on

These are requirements on the *testbench*, not on the DUT, but the DUT is only
correct in an environment that satisfies them. The test writer must configure the
`RootComplex` accordingly.

- `rc.max_payload_size = 0` (128 bytes) — bounds inbound `MWr` payload to 32 DW.
- `rc.max_read_request_size = 0` (128 bytes) — bounds inbound `MRd` length to 32 DW.
- Straddling / multiple TLPs per beat: impossible by construction on this stream.
- The shim must present exactly one TLP between `sop` and `eop` (§5).

---

## 5. The TLP DWORD stream (chip boundary)

This section is written so the test writer can build the shim without reading any RTL.

### 5.1 Signals

Two independent, identically-shaped streams. All signals are synchronous to `clk` and
reset by `rst`.

**Inbound (host -> device), prefix `rx_tlp_`:**

| Signal | Dir (w.r.t. `matmul_top`) | Width | Meaning |
|--------|---------------------------|-------|---------|
| `rx_tlp_data` | input | 32 | One TLP DWORD. Mapping in §5.3. |
| `rx_tlp_sop` | input | 1 | 1 on the beat carrying header DW0 of a TLP. |
| `rx_tlp_eop` | input | 1 | 1 on the beat carrying the final DWORD of a TLP. |
| `rx_tlp_valid` | input | 1 | Source asserts when `rx_tlp_data`/`sop`/`eop` are valid. |
| `rx_tlp_ready` | output | 1 | Sink (the DUT) asserts when it can accept a beat. |

**Outbound (device -> host), prefix `tx_tlp_`:**

| Signal | Dir | Width | Meaning |
|--------|-----|-------|---------|
| `tx_tlp_data` | output | 32 | One TLP DWORD. |
| `tx_tlp_sop` | output | 1 | 1 on header DW0. |
| `tx_tlp_eop` | output | 1 | 1 on the final DWORD. |
| `tx_tlp_valid` | output | 1 | |
| `tx_tlp_ready` | input | 1 | |

### 5.2 Handshake rules

A beat transfers on a rising edge of `clk` where `valid && ready` are both 1.

- **REQ-001** Once a source asserts `valid`, it shall hold `valid`, `data`, `sop` and
  `eop` stable until the beat transfers (no retraction).
- **REQ-002** A sink may assert or deassert `ready` on any cycle, including for an
  unbounded number of cycles, without loss of data.
- **REQ-003** `ready` shall not depend combinationally on `valid` in either direction
  (no combinational loop across the boundary). `valid` **may** depend
  combinationally on `ready`.
- **REQ-004** Exactly one TLP is delivered per `sop` … `eop` pair. A single-DWORD TLP
  is impossible (minimum TLP is 3 header DW), so `sop` and `eop` are never both 1 on
  the same beat.
- **REQ-005** Beats of one TLP may be separated by any number of idle cycles
  (`valid` = 0) and any number of stall cycles (`ready` = 0). TLPs are never
  interleaved on a stream.
- **REQ-006** While `rst` is asserted, `rx_tlp_ready`, `tx_tlp_valid`, `tx_tlp_sop`
  and `tx_tlp_eop` shall be 0. On the first cycle after `rst` deasserts,
  `rx_tlp_ready` may assert.
- **REQ-007** The DUT shall tolerate `tx_tlp_ready` held low for an unbounded number
  of cycles without losing or corrupting a completion, and without losing an
  in-progress inbound TLP.

### 5.3 DWORD byte mapping (this is the part that is easy to get wrong)

The stream carries the byte sequence produced by `cocotbext.pcie.core.tlp.Tlp.pack()`,
four bytes per beat, in order. The *byte-lane* mapping differs between header DWORDs
and payload DWORDs, exactly as it does on a real PCIe link:

- **Header DWORDs** (the first 3 DWORDs of every TLP this design uses) are carried in
  **PCIe wire order (big-endian)**. The 32-bit value on the bus equals the
  big-endian interpretation of `pack()[4k .. 4k+3]`. Equivalently, the bus value is
  numerically identical to the DWORD drawn in the PCIe Base Specification figures
  and in §7.2 of this document.

- **Payload DWORDs** (everything after the header) are carried in
  **host order (little-endian)**. `data[8*j+7 : 8*j]` is the byte whose address is
  `(DWORD-aligned address) + j`, for `j` in 0..3. Equivalently the bus value is the
  little-endian interpretation of `pack()[4k .. 4k+3]`.

  This is also the mapping used by the byte enables: First/Last DW BE bit `j`
  enables `data[8*j+7 : 8*j]`.

Reference shim conversion (Python, host -> DUT):

```
b   = tlp.pack()
hdr = tlp.get_header_size()          # 12 for every TLP in this design
dws = [int.from_bytes(b[i:i+4], 'big')    for i in range(0,   hdr,      4)] \
    + [int.from_bytes(b[i:i+4], 'little') for i in range(hdr, len(b),   4)]
```

and DUT -> host is the exact inverse followed by `Tlp.unpack()`.

- **REQ-008** The DUT shall interpret inbound header DWORDs with the big-endian
  mapping and inbound payload DWORDs with the little-endian mapping defined above.
- **REQ-009** The DUT shall emit outbound header and payload DWORDs using the same
  two mappings.

### 5.4 Attach point in `cocotbext-pcie`

DEC-003 Option B. The shim is a subclass of `cocotbext.pcie.core.device.Device`:

- Override `async def upstream_recv(self, tlp)` to serialize `tlp` onto `rx_tlp_*`
  per §5.3 instead of routing it to a Python `Function`.
- Run a cocotb task that deserializes `tx_tlp_*` into a `bytearray`, calls
  `Tlp.unpack()`, and `await self.upstream_send(tlp)`.
- `Device.__init__` already installs a `SimPort` with the DLL model; connect it to
  the `RootComplex` downstream port with `rc.make_port().connect(shim.upstream_port)`
  (or `rc.add_device(shim)`), so `rc.enumerate()` drives real Type 0 config TLPs
  into the DUT.
- Do **not** call `Device.append_function()` / `make_function()`. There must be no
  Python `Function`, because the DUT owns the configuration space.

Notes for the test writer, from reading the library:

- The `RootComplex` issues `CfgRd1`/`CfgWr1`; the downstream bridge converts them to
  `CfgRd0`/`CfgWr0` before they reach the `Device`. The DUT therefore only ever sees
  Type 0.
- `Tlp.get_lower_address()` in cocotbext-pcie 0.2.16 is **buggy** (it evaluates as
  `self.address & (0x7c + offset)` because of Python operator precedence) and is not
  used anywhere by the library itself. Do not use it as a reference. The correct
  value, and the one the DUT produces, is `(address + first_be_offset) & 0x7f`.
- `Region.read()` asserts `cpl.byte_count == requested_byte_length` for a single
  completion, and slices the returned data starting at `cpl.lower_address & 3`.
  §7.5 defines the DUT's field values to satisfy this.

---

## 6. Module: `matmul_top`

### 6.1 Ports (binding)

```
module matmul_top #(
    parameter int N    = 8,     // systolic array dimension; power of two, 2..32
    parameter int DW   = 8,     // operand width in bits; 8 in v1
    parameter int ACCW = 32     // accumulator width in bits; 32 in v1
) (
    // Clock and reset
    input  logic        clk,            // single clock, all logic
    input  logic        rst,            // active-high, SYNCHRONOUS

    // Inbound TLP stream (host -> device)
    input  logic [31:0] rx_tlp_data,
    input  logic        rx_tlp_sop,
    input  logic        rx_tlp_eop,
    input  logic        rx_tlp_valid,
    output logic        rx_tlp_ready,

    // Outbound TLP stream (device -> host)
    output logic [31:0] tx_tlp_data,
    output logic        tx_tlp_sop,
    output logic        tx_tlp_eop,
    output logic        tx_tlp_valid,
    input  logic        tx_tlp_ready,

    // Sideband
    output logic        irq             // level-sensitive, active high
);
```

- **REQ-010** `matmul_top` shall have exactly the ports listed above, with these
  names, directions and widths. No other top-level port shall exist.
- **REQ-011** `matmul_top` shall contain no logic other than instantiation and
  wiring of `pcie_tl`, `app_bar0` and `matmul_engine`.
- **REQ-012** `irq` shall be a registered output equal to `|IRQ_STATUS` (§10.5),
  i.e. 1 if and only if at least one bit is set in both `STATUS` and `IRQ_ENABLE`.

### 6.2 Latency contract

- `rx_tlp_*` to `app_bar0` request: see §7.3.
- Register write to observable effect: 1 cycle after the write DWORD is accepted by
  `app_bar0`.
- `START` to `DONE`: `4*N + 2` cycles (§12.5).

---

## 7. Module: `pcie_tl` (Transaction Layer)

### 7.1 Purpose and structure

`pcie_tl` owns everything between the TLP stream and the application. It contains
`tlp_rx`, `tlp_tx` and `pcie_cfg_space`.

**Serialization model (DEC-007):** `pcie_tl` services inbound TLPs strictly in
arrival order, one at a time. It holds `rx_tlp_ready` low while a request is being
serviced or while its Completion has not yet been fully transferred. At most one
Completion is in flight at any time. This makes an outbound arbiter unnecessary.

- **REQ-013** `pcie_tl` shall service inbound TLPs in strict arrival order.
- **REQ-014** `pcie_tl` shall have at most one Completion in flight at any time.
- **REQ-015** `pcie_tl` shall not deadlock when `tx_tlp_ready` is held low: it shall
  stall `rx_tlp_ready` and resume correctly when `tx_tlp_ready` asserts.

### 7.2 Header DWORD layouts

Bit positions are on the 32-bit stream word (§5.3, big-endian header mapping). These
layouts are the single authority; §9.4 and §10 refer back to them and add no
independent layout.

#### 7.2.1 DW0 — common to every TLP (PCIe Base r6.0 §2.2.1)

```
 bit  31 30 29 | 28 27 26 25 24 | 23 | 22 21 20 | 19 | 18 | 17 | 16 | 15 | 14 | 13 12 | 11 10 | 9 .......... 0
      +--------+----------------+----+----------+----+----+----+----+----+----+-------+-------+---------------+
      |  Fmt   |      Type      | T9 |    TC    | T8 |Atr2| LN | TH | TD | EP |Atr1:0 |  AT   |    Length     |
      +--------+----------------+----+----------+----+----+----+----+----+----+-------+-------+---------------+
```

| Field | Bits | DUT use |
|-------|------|---------|
| `Fmt` | 31:29 | Decoded. `000`=3DW no data, `010`=3DW with data, `001`/`011`= 4DW -> UR. |
| `Type` | 28:24 | Decoded. `00000`=Memory, `00100`=Config Type 0, `01010`=Completion. |
| `T9` | 23 | Tag bit 9 (10-bit tags). **Ignored on receive; always 0 on transmit.** |
| `TC` | 22:20 | Traffic Class. Copied verbatim into the Completion. |
| `T8` | 19 | Tag bit 8. **Ignored on receive; always 0 on transmit.** |
| `Attr[2]` | 18 | ID-Based Ordering. Copied verbatim into the Completion. |
| `LN` | 17 | Lightweight Notification. Ignored; 0 on transmit. |
| `TH` | 16 | TLP Processing Hints. Ignored; 0 on transmit. |
| `TD` | 15 | TLP Digest. If 1 -> treat as unsupported (§4.3). 0 on transmit. |
| `EP` | 14 | Poisoned. If 1 -> treat as unsupported (§4.3). 0 on transmit. |
| `Attr[1:0]` | 13:12 | Relaxed Ordering / No Snoop. Copied verbatim into the Completion. |
| `AT` | 11:10 | Address Type. Ignored; 0 on transmit. |
| `Length` | 9:0 | DWORD length. `0` encodes 1024 DW. §7.3 bounds it. |

#### 7.2.2 `MRd` / `MWr`, 3 DW (PCIe Base r6.0 §2.2.7)

```
 DW0 : as §7.2.1, Fmt=000 (MRd) or 010 (MWr), Type=00000

 DW1 : 31 ................. 16 | 15 ......... 8 | 7 6 5 4 | 3 2 1 0
       +-----------------------+----------------+---------+---------+
       |     Requester ID      |    Tag[7:0]    | Last BE | First BE|
       +-----------------------+----------------+---------+---------+

 DW2 : 31 ..................................... 2 | 1  0
       +-----------------------------------------+------+
       |             Address[31:2]               |  PH  |
       +-----------------------------------------+------+
```

`Requester ID[15:8]` = Bus, `[7:3]` = Device, `[2:0]` = Function.
`PH` is 0 whenever `TH` = 0; the DUT ignores it.

#### 7.2.3 `CfgRd0` / `CfgWr0` (PCIe Base r6.0 §2.2.7)

```
 DW0 : as §7.2.1, Fmt=000 (CfgRd0) or 010 (CfgWr0), Type=00100, Length=1
       (Length MUST be 1; any other value is malformed -- see REQ-126)

 DW1 : 31 ................. 16 | 15 ......... 8 | 7 6 5 4 | 3 2 1 0
       +-----------------------+----------------+---------+---------+
       |     Requester ID      |    Tag[7:0]    | Last BE | First BE|
       +-----------------------+----------------+---------+---------+
                                                    (=0)

 DW2 : 31 ................. 16 | 15 .... 12 | 11 ......... 2 | 1  0
       +-----------------------+------------+----------------+------+
       |     Completer ID      |  Reserved  | Cfg Addr[11:2] |  0 0 |
       +-----------------------+------------+----------------+------+
```

`Completer ID` is the *target* of the request: `[15:8]` Bus, `[7:3]` Device,
`[2:0]` Function. `Cfg Addr[11:2]` is the DWORD-aligned configuration-space offset
(PCIe Base r6.0 §7.2.2 splits this into Extended Register Number `[11:8]` and
Register Number `[7:2]`; the DUT treats it as one 10-bit DWORD index).

#### 7.2.4 `Cpl` / `CplD` (PCIe Base r6.0 §2.2.9) — outbound only

```
 DW0 : as §7.2.1, Fmt=000 (Cpl) or 010 (CplD), Type=01010

 DW1 : 31 ................. 16 | 15 14 13 | 12  | 11 ................. 0
       +-----------------------+----------+-----+-----------------------+
       |     Completer ID      |  Status  | BCM |      Byte Count       |
       +-----------------------+----------+-----+-----------------------+

 DW2 : 31 ................. 16 | 15 ......... 8 | 7  | 6 ........... 0
       +-----------------------+----------------+----+-----------------+
       |     Requester ID      |    Tag[7:0]    | R  |  Lower Address  |
       +-----------------------+----------------+----+-----------------+
```

`Status`: `000`=SC (Successful Completion), `001`=UR (Unsupported Request),
`010`=CRS, `100`=CA. The DUT emits only SC and UR. `BCM` is always 0. `R` is
reserved, always 0.

### 7.3 Submodule: `tlp_rx`

**Purpose.** Accept the inbound DWORD stream, capture and decode the 3 header DWORDs,
classify the TLP, and either (a) hand a decoded request to `pcie_cfg_space`
(config TLPs) or `app_bar0` (memory TLPs), or (b) reject it.

**Interface contract (advisory signal names, binding behaviour).**

Toward `app_bar0`:

| Signal | Dir | Width | Meaning |
|--------|-----|-------|---------|
| `app_req_valid` / `app_req_ready` | out / in | 1 | Handshake, one request. |
| `app_req_write` | out | 1 | 1 = write (from `MWr`), 0 = read (from `MRd`). |
| `app_req_addr` | out | 14 | BAR0 byte offset, bits [1:0] always 0. |
| `app_req_len` | out | 6 | DWORD count, 1..32. |
| `app_req_first_be` | out | 4 | First DW Byte Enables. |
| `app_req_last_be` | out | 4 | Last DW Byte Enables (0 when `len` == 1). |
| `app_wdata_valid`/`ready`/`data`/`last` | out/in/out/out | 1/1/32/1 | Write payload stream, `len` beats, little-endian mapping. |
| `app_rdata_valid`/`ready`/`data` | in/out/in | 1/1/32 | Read data stream, `len` beats. |

There is deliberately **no `app_rdata_last`**. `tlp_tx` already knows how many payload
DWORDs a Completion carries, because it builds the `Length` field itself from the
request; a last-beat marker on the read path would be redundant information that could
disagree with `Length`. (v1.0.0 listed `app_rdata_last`; it was removed in v1.1.0 after
Phase 2b found it driven and sunk but never consumed.)

Requirements:

- **REQ-016** `tlp_rx` shall extract `Fmt`, `Type`, `Length`, `TC`, `Attr`, `TD`,
  `EP`, `Requester ID`, `Tag[7:0]`, `First BE`, `Last BE` and `Address[31:2]` from
  inbound TLPs exactly as laid out in §7.2.
- **REQ-017** `tlp_rx` shall treat an inbound `Length` field value of 0 as 1024 DW
  (PCIe Base r6.0 §2.2.1) and, because 1024 > 32, shall reject the TLP as an
  unsupported request per §4.3.
- **REQ-018** `tlp_rx` shall reject as an unsupported request any `MRd` or `MWr`
  whose `Length` exceeds 32 DW.
- **REQ-019** `tlp_rx` shall consume and discard the entire payload of a rejected
  `MWr` (i.e. it shall stay framed and not misinterpret payload as a header).
- **REQ-020** `tlp_rx` shall re-synchronise on `rx_tlp_sop`: if `sop` arrives while
  the module believes it is mid-packet, the partially received TLP is abandoned and
  the new one is parsed from that beat.
- **REQ-021** `tlp_rx` shall present a decoded request no later than 1 clock cycle
  after the beat carrying header DW2 is accepted.
- **REQ-022** For an `MWr`, `tlp_rx` shall present the payload DWORDs to `app_bar0`
  in ascending address order, exactly `Length` of them.

**Latency.** Header DW0 accepted at cycle `t` and DW2 at cycle `t+2` (no stalls) ->
`app_req_valid` at cycle `t+3` at the latest. This is a bound, not an exact figure,
so the internal request latency is not by itself enough to make REQ-101's `4N+2`
observable from the chip pins. §9.6's `D_WR` constant closes that gap; see REQ-122
and REQ-123.

### 7.4 Submodule: `tlp_tx`

**Purpose.** Build and transmit `Cpl`/`CplD` TLPs.

- **REQ-023** `tlp_tx` shall emit each Completion as one contiguous framed packet:
  `sop` on header DW0, `eop` on the last DWORD, 3 header DWORDs followed by
  `Length` payload DWORDs.
- **REQ-024** `tlp_tx` shall set, in every Completion it emits: `T9`=0, `T8`=0,
  `LN`=0, `TH`=0, `TD`=0, `EP`=0, `AT`=00, `BCM`=0, and DW2 bit 7 = 0.
- **REQ-025** `tlp_tx` shall copy `TC` and `Attr[2:0]` from the request into the
  Completion (PCIe Base r6.0 §2.2.9).
- **REQ-026** `tlp_tx` shall copy `Requester ID` and `Tag[7:0]` from the request into
  the Completion.
- **REQ-027** `tlp_tx` shall set `Completer ID` to `cfg_completer_id` (§8.4).

### 7.5 Completion field values (normative)

Definitions used below, matching `cocotbext-pcie` bit-for-bit:

`first_be_offset(fbe)`:

| `fbe[3:0]` | offset |
|------------|--------|
| `xxx1` | 0 |
| `xx10` | 1 |
| `x100` | 2 |
| `1000` | 3 |
| `0000` | 3 |

`last_be_offset(lbe)` — where `lbe` is `Last BE` if `Length > 1`, else `First BE`:

| `lbe[3:0]` | offset |
|------------|--------|
| `0001` | 3 |
| `001x`, i.e. `lbe & 4'b1110 == 4'b0010` | 2 |
| `01xx`, i.e. `lbe & 4'b1100 == 4'b0100` | 1 |
| otherwise (including `0000`) | 0 |

`be_byte_count = Length*4 - first_be_offset - last_be_offset`.

| Completion for | Fmt/Type | Length | Byte Count | Lower Address | Status |
|----------------|----------|--------|------------|---------------|--------|
| `MRd` hit | `CplD` (`010`/`01010`) | request `Length` | `be_byte_count` | `(Address + first_be_offset) & 0x7F` | SC |
| `CfgRd0` accepted | `CplD` | 1 | 4 | 0 | SC |
| `CfgWr0` accepted | `Cpl` (`000`/`01010`) | 0 | 4 | 0 | SC |
| Any UR | `Cpl` | 0 | 4 | 0 | UR |

- **REQ-028** For a `CplD` responding to an `MRd`, `Length` shall equal the request's
  `Length`, and exactly that many payload DWORDs shall be transmitted.
- **REQ-029** For a `CplD` responding to an `MRd`, `Byte Count` shall equal
  `be_byte_count` computed from the request's `Length`, `First BE` and `Last BE`
  using the tables above.
- **REQ-030** For a `CplD` responding to an `MRd`, `Lower Address` shall equal
  `(request Address + first_be_offset) & 0x7F`.
- **REQ-031** The DUT shall return **exactly one** Completion per `MRd`. It shall
  never split a completion (DEC-006).
- **REQ-032** For a `CplD` responding to an `MRd`, the payload shall contain the
  full DWORDs read from BAR0 including bytes whose Byte Enable is 0.
- **REQ-033** A `CplD` responding to an accepted `CfgRd0` shall have `Length` = 1,
  `Byte Count` = 4, `Lower Address` = 0, and carry the full 32-bit content of the
  addressed configuration DWORD regardless of `First BE`.
- **REQ-034** A `Cpl` responding to an accepted `CfgWr0` shall have `Length` = 0,
  `Byte Count` = 4, `Lower Address` = 0, status SC.
- **REQ-035** A UR Completion shall have Fmt/Type = `Cpl`, `Length` = 0,
  `Byte Count` = 4, `Lower Address` = 0, status = `001` (UR).
- **REQ-036** The DUT shall never emit a Completion in response to a posted request
  (`MWr`, `MWr64`, `IOWr`, Message).
- **REQ-037** The DUT shall never emit a Completion in response to an inbound
  Completion.

### 7.6 Unsupported-request handling summary

- **REQ-038** An `MRd` (3 DW) that does not fall inside the BAR0 window, or that
  arrives while `Command.MSE` = 0, shall be answered with a UR Completion and shall
  set `STATUS.ERR_UNSUP_REQ`.
- **REQ-039** An `MWr` (3 DW) that does not fall inside the BAR0 window, or that
  arrives while `Command.MSE` = 0, shall be discarded and shall set
  `STATUS.ERR_UNSUP_REQ`. No Completion is emitted.
- **REQ-040** Any inbound TLP of a type listed in §4.3 as "non-posted, unsupported"
  shall be answered with a UR Completion and shall set `STATUS.ERR_UNSUP_REQ`.
- **REQ-041** Any inbound TLP of a type listed in §4.3 as "posted, unsupported" shall
  be discarded and shall set `STATUS.ERR_UNSUP_REQ`. No Completion is emitted.

> **Verification limitation on REQ-041's Message clause (v1.1.0, informative — does
> not change REQ-041).** `cocotbext-pcie` 0.2.16 cannot encode Message TLPs:
> `Tlp.pack_header()` raises `Exception("Unknown TLP type")` for every `MSG_*`
> fmt/type, so the shim physically cannot put a Message on `rx_tlp_*`. The Message
> clause of REQ-041 is therefore **unreachable by construction in this testbench**,
> not merely untested. It is covered indirectly: `MWr64` and `IOWr` exercise the same
> discard-and-flag path through `tlp_rx`, and they are the only posted-unsupported
> types a real host would ever send here. This is a documented environment limitation,
> **not a coverage hole**; the requirement stays in the spec because the RTL must
> still not mis-frame a Message if one ever arrives. Do not remove or weaken REQ-041
> to close a coverage report.
- **REQ-042** *(antecedent narrowed in v1.1.3 so it is disjoint from REQ-126 by
  construction.)* A `CfgRd0`/`CfgWr0` **with `Length` == 1** whose Device Number or
  Function Number is non-zero shall be answered with a UR Completion and shall
  **not** set `STATUS.ERR_UNSUP_REQ` (this happens on every bus scan and is not an
  error). A configuration request with `Length` != 1 is outside this requirement
  entirely and is governed by REQ-126, whatever its Device and Function Number.
- **REQ-043** An inbound `Cpl`/`CplD` shall be discarded with no error bit set and no
  Completion emitted.
- **REQ-044** An `MRd` or `MWr` that would cross the end of the BAR0 window
  (`offset + Length*4 > 16384`) shall be treated as not matching BAR0 (REQ-038 /
  REQ-039).
- **REQ-126** *(new in v1.1.2.)* A `CfgRd0` or `CfgWr0` whose `Length` field is not
  exactly 1 is malformed (§7.2.3; PCIe Base r6.0 §2.2.7 fixes Configuration Requests
  at one DWORD). The DUT shall:
  (a) answer it with a `Cpl` carrying UR status, formatted per REQ-035 — at
  `cfg_completer_id` = `0x0000` this is `DW0 = 0x0A000000`, `DW1 = 0x00002004`,
  `DW2` per §7.2.4, three beats total;
  (b) modify no configuration register;
  (c) for a `CfgWr0`, consume and discard all surplus payload DWORDs through
  `rx_tlp_eop`, so that framing is preserved and the next TLP is parsed correctly; and
  (d) set `STATUS.ERR_UNSUP_REQ`.
  This applies regardless of Device and Function number; the REQ-042 carve-out, which
  exists only because routine bus scans probe absent devices, does **not** extend to a
  malformed `Length`.

---

## 8. Module: `pcie_cfg_space`

### 8.1 Purpose

Implements the 256-byte Type 0 configuration space of Function 0, services
`CfgRd0`/`CfgWr0`, decodes BAR0 hits for `tlp_rx`, and captures the device's own
Bus/Device number.

### 8.2 Implemented configuration registers

Offsets are configuration-space byte offsets. All accesses are DWORD-based;
Byte Enables select which bytes a `CfgWr0` updates.

| Offset | 31:24 | 23:16 | 15:8 | 7:0 | Reset | Access |
|--------|-------|-------|------|-----|-------|--------|
| 0x00 | Device ID [15:8] | Device ID [7:0] | Vendor ID [15:8] | Vendor ID [7:0] | `0x8000_1234` | RO |
| 0x04 | Status [15:8] | Status [7:0] | Command [15:8] | Command [7:0] | `0x0000_0000` | Status RO, Command see §8.3 |
| 0x08 | Class Code [23:16] | Class Code [15:8] | Class Code [7:0] | Revision ID | `0x1200_0001` | RO |
| 0x0C | BIST | Header Type | Latency Timer | Cache Line Size | `0x0000_0000` | Cache Line Size RW, rest RO |
| 0x10 | BAR0 | | | | `0x0000_0000` | see §8.3 |
| 0x14 | BAR1 | | | | `0x0000_0000` | RO 0 |
| 0x18 | BAR2 | | | | `0x0000_0000` | RO 0 |
| 0x1C | BAR3 | | | | `0x0000_0000` | RO 0 |
| 0x20 | BAR4 | | | | `0x0000_0000` | RO 0 |
| 0x24 | BAR5 | | | | `0x0000_0000` | RO 0 |
| 0x28 | Cardbus CIS Pointer | | | | `0x0000_0000` | RO 0 |
| 0x2C | Subsystem ID [15:8] | Subsystem ID [7:0] | Subsys Vendor ID [15:8] | Subsys Vendor ID [7:0] | `0x0001_1234` | RO |
| 0x30 | Expansion ROM Base Address | | | | `0x0000_0000` | RO 0 |
| 0x34 | Reserved | Reserved | Reserved | Capabilities Pointer | `0x0000_0000` | RO 0 |
| 0x38 | Reserved | | | | `0x0000_0000` | RO 0 |
| 0x3C | Max Lat | Min Gnt | Interrupt Pin | Interrupt Line | `0x0000_0000` | Interrupt Line RW, rest RO |
| 0x40 – 0xFFF | | | | | `0x0000_0000` | RO 0 |

Field values chosen (DEC-011):

| Field | Value | Rationale |
|-------|-------|-----------|
| Vendor ID | `0x1234` | Non-allocated ID conventionally used by emulators; passes the RootComplex's "is this a device?" check (`{0, 0xFFFFFFFF, 0xFFFF0000, 0x0000FFFF}` are rejected). |
| Device ID | `0x8000` | Arbitrary. |
| Revision ID | `0x01` | |
| Class Code | `0x12_00_00` | Base class 0x12 "Processing Accelerators", subclass 0x00, prog-IF 0x00. |
| Header Type | `0x00` | Type 0, single function (bit 7 = 0). |
| Subsystem Vendor ID / Subsystem ID | `0x1234` / `0x0001` | |
| Capabilities Pointer | `0x00` | **No capability list.** Status[4] is therefore 0. Consequence: the host model never probes MSI or the PCI Express Capability. |
| Interrupt Pin | `0x00` | No INTx. |

### 8.3 Writable configuration fields

**Command register (offset 0x04, bits 15:0):**

| Bit | Name | Access | Reset | Effect |
|-----|------|--------|-------|--------|
| 0 | I/O Space Enable (IOSE) | RW | 0 | Stored, no effect (no I/O BARs). |
| 1 | Memory Space Enable (MSE) | RW | 0 | **Functional.** When 0, all `MRd`/`MWr` to BAR0 are Unsupported Requests. |
| 2 | Bus Master Enable (BME) | RW | 0 | Stored, no effect in v1 (the DUT is never a requester). |
| 15:3 | — | RO | 0 | Reads 0, writes ignored. |

**Status register (offset 0x04, bits 31:16):** RO, reads `0x0000` always. In
particular bit 4 (Capabilities List) is 0, consistent with Capabilities Pointer = 0.

**BAR0 (offset 0x10):**

| Bits | Name | Access | Reset |
|------|------|--------|-------|
| 31:14 | Base Address [31:14] | RW | 0 |
| 13:4 | — (encodes the 16 KiB size) | RO 0 | 0 |
| 3 | Prefetchable | RO 0 | 0 |
| 2:1 | Type (`00` = 32-bit) | RO 0 | 0 |
| 0 | Space Indicator (`0` = memory) | RO 0 | 0 |

Writing `0xFFFFFFFF` to BAR0 and reading it back therefore yields `0xFFFFC000`,
which the host decodes as a 16 KiB, 32-bit, non-prefetchable memory BAR.

**Cache Line Size (offset 0x0C bits 7:0):** RW, reset 0, no effect.
**Interrupt Line (offset 0x3C bits 7:0):** RW, reset 0, no effect.

Requirements:

- **REQ-045** `pcie_cfg_space` shall return the values in the table of §8.2 for
  `CfgRd0` to offsets 0x00 – 0x3C, and `0x00000000` for any configuration offset in
  0x40 – 0xFFF.
- **REQ-046** `CfgWr0` shall update only the fields marked RW in §8.3, and only those
  bytes whose `First BE` bit is 1.
- **REQ-047** `CfgWr0` to an RO field or to an unimplemented offset shall be accepted
  (SC Completion returned) and shall change no state.
- **REQ-048** After `0xFFFFFFFF` is written to BAR0, a read of BAR0 shall return
  `0xFFFFC000`.
- **REQ-049** BAR0 bits [13:0] shall read 0 under all circumstances.
- **REQ-050** `Command.MSE` shall gate BAR0 memory decoding: when 0, no `MRd`/`MWr`
  matches BAR0.
- **REQ-051** Configuration space shall be readable and writable regardless of the
  value of `Command.MSE`.

### 8.4 Bus/Device number capture and BAR0 decode

- **REQ-052** On every `CfgRd0` or `CfgWr0` accepted by the DUT (Device Number 0,
  Function Number 0), `pcie_cfg_space` shall capture the request's `Completer ID`
  into `cfg_completer_id`, which is used as the `Completer ID` of all subsequent
  Completions (PCIe Base r6.0 §2.2.9, §7.5.1.1). Reset value `0x0000`.
- **REQ-053** A memory request matches BAR0 if and only if
  `Command.MSE == 1` **and** `Address[31:14] == BAR0[31:14]`.
- **REQ-054** For a matching request the BAR0 byte offset presented to `app_bar0`
  shall be `Address[13:0]` with bits [1:0] forced to 0.

---

## 9. Module: `app_bar0`

### 9.1 Purpose

Decode the 14-bit BAR0 offset into one of four regions, sequence multi-DWORD bursts,
apply byte enables on writes, and return read data.

### 9.2 BAR0 address map

BAR0 aperture is 16384 bytes (16 KiB) for every legal `N`.

| BAR0 offset range | Region | Contents | Width of a host access |
|-------------------|--------|----------|------------------------|
| `0x0000` – `0x0FFF` | `reg_file` | Control/status registers, §10 | 32-bit DWORD |
| `0x1000` – `0x1FFF` | `mem_a` | Matrix A, `N*N` bytes at `0x1000 + (i*N + k)` | byte-addressable |
| `0x2000` – `0x2FFF` | `mem_b` | Matrix B, `N*N` bytes at `0x2000 + (k*N + j)` | byte-addressable |
| `0x3000` – `0x3FFF` | `mem_c` | Matrix C, `N*N` 32-bit words at `0x3000 + 4*(i*N + j)` | 32-bit word |

For `N = 8`: A occupies `0x1000`–`0x103F`, B occupies `0x2000`–`0x203F`,
C occupies `0x3000`–`0x30FF`.

- **REQ-055** Any BAR0 offset that is inside the 16 KiB aperture but is not an
  implemented register or storage location shall read as `0x00000000` and shall
  ignore writes. The Completion status is SC, not UR. ("Read-as-zero,
  write-ignored", RAZ/WI.)
- **REQ-056** `app_bar0` shall accept bursts of 1 to 32 DWORDs and shall service them
  as consecutive DWORD accesses at ascending addresses, at a rate of one DWORD per
  clock cycle when not stalled.
- **REQ-057** A burst that starts in one region and would run past that region's
  4 KiB boundary shall wrap **nowhere**: each DWORD is decoded independently from its
  own address, so DWORDs falling outside an implemented location follow REQ-055.

### 9.3 Byte-enable behaviour

Per PCIe Base r6.0 §2.2.5:

- **REQ-058** For a write burst of `L` DWORDs: `First BE` applies to DWORD 0,
  `Last BE` applies to DWORD `L-1`, and all intermediate DWORDs have all four bytes
  enabled. When `L == 1`, `Last BE` shall be ignored and `First BE` alone applies.
- **REQ-059** A byte whose Byte Enable is 0 shall not be modified by the write.
- **REQ-060** Byte Enable bit `j` corresponds to `data[8*j+7 : 8*j]` of the payload
  DWORD and to byte address `(DWORD address) + j`.
- **REQ-061** Reads shall ignore Byte Enables entirely and return the full 32-bit
  content of every addressed DWORD (the requester applies the enables).

### 9.4 Register-access encoding (must agree with §7.2)

A host DWORD write to BAR0 offset `X` arrives as an `MWr` with:
`DW0.Fmt=010, DW0.Type=00000, DW0.Length=1`; `DW1.First BE` = the enabled bytes,
`DW1.Last BE` = `0000`; `DW2.Address[31:2]` = `(BAR0[31:14] | X)[31:2]`.
The payload DWORD carries `data[8*j+7:8*j]` = the byte at `X + j` (§5.3 payload
mapping).

A host DWORD read of BAR0 offset `X` arrives as an `MRd` with the same DW1/DW2
layout and `DW0.Fmt=000, Length=1`, and is answered by a `CplD` with `Length=1`,
`Byte Count` and `Lower Address` per §7.5, and one payload DWORD in the payload
mapping.

No field layout is restated here; §7.2 is the only authority.

### 9.5 Access rules while the engine is busy

- **REQ-062** While `STATUS.BUSY == 1`, writes to `mem_a`, `mem_b` and `mem_c` shall
  be discarded and `STATUS.ERR_WRITE_BUSY` shall be set. Writes are posted, so no
  Completion is returned either way.
- **REQ-063** While `STATUS.BUSY == 1`, reads of `mem_a`, `mem_b` and `mem_c` shall
  complete normally with SC status. The data returned from `mem_c` is the current
  stored content, which may be partially updated; software must wait for
  `STATUS.DONE`.
- **REQ-064** Register reads and register writes (region `0x0000`–`0x0FFF`) are
  permitted at all times, including while `STATUS.BUSY == 1`.

### 9.6 Latency contract, and the `D_WR` write-path constant

- Read: `app_req_valid` accepted at cycle `t` -> first read DWORD available at cycle
  `t+2`, then one DWORD per cycle.
- Write: payload DWORD accepted by `app_bar0` at cycle `t` -> the new value is
  readable from cycle `t + D_WR` onward (`t_commit`), with `D_WR` as defined below.
  The write is *taken* at cycle `t`; it becomes *visible* at `t + D_WR`.

**Three cycles, named once, never conflated.** v1.1.0 used "accepted" and "updated"
loosely and ended up with two incompatible readings of `t_start`. The following three
names are now the only ones used anywhere in this specification:

| Name | Definition |
|------|------------|
| `t_beat` | The cycle on which the payload DWORD of a BAR0 write transfers on `rx_tlp_*`, i.e. `rx_tlp_valid` and `rx_tlp_ready` are both 1 for that beat. Externally observable. |
| `t_start` | **Identical to `t_beat`** for a write that carries `CTRL.START`. This is the cycle REQ-074 and REQ-101 measure `4*N + 2` from. "Accepted by `reg_file`" in REQ-074 means *this* cycle — the cycle the write is taken in, **not** the cycle its effect becomes readable. |
| `t_commit` | The cycle on which the addressed register or storage location holds the new value, i.e. the first cycle a read would return it. `t_commit = t_beat + D_WR`. |

**Definition — `D_WR` = `t_commit - t_beat`.** `D_WR` is a property of the
implementation's write path, not a free parameter of each access. Its measured value
in the v1 RTL is **1**.

`D_WR` describes when a write becomes *visible*. It is deliberately **not** a term in
any operation-latency formula: REQ-074, REQ-101 and REQ-123 all measure from `t_beat`,
so adding `D_WR` to them would double-count the write path. That double-count was the
v1.1.0 defect.

- **REQ-122** *(new in v1.1.0.)* `D_WR` shall be a single fixed constant of the
  implementation: identical for every BAR0 write regardless of target region
  (`reg_file`, `mem_a`, `mem_b`, `mem_c`), regardless of the DWORD's position within
  a burst, regardless of Byte Enables, and independent of `N`. Its value shall lie in
  the range 1 to 3 inclusive. It may be measured once at the chip boundary — write
  `SCRATCH`, then read it back on successive cycles — and reused for every other
  timing check.
- **REQ-123** *(new in v1.1.0; corrected in v1.1.1.)* Given a `CTRL` write whose
  payload DWORD has bit 0 (`START`) set and transfers on `rx_tlp_*` at cycle `t_beat`,
  and given that `STATUS.BUSY` was 0 at `t_beat`, `STATUS.DONE` shall be set at
  exactly cycle `t_beat + 4*N + 2`, provided neither `rx_tlp_*` nor `tx_tlp_*` stalls
  in that interval. This is the boundary-observable form of REQ-101: `t_start` is
  `t_beat`, so the two state the same thing and must agree. `PERF_CYCLES` (REQ-102)
  must independently read `4*N + 2`. At `N = 8`, `DONE` is set at `t_beat + 34`.

> **Why this was added, and why it was wrong in v1.1.0.** Phase 2b observed that §7.3
> states the internal request latency as an upper bound ("at the latest"), so
> REQ-101's exact `4N+2` could only be checked through `PERF_CYCLES`, never by
> watching the pins. v1.1.0 introduced `D_WR` to close that gap but wrote REQ-123 as
> `t_beat + D_WR + 4*N + 2`, which double-counted the write path: REQ-074 already
> measures `4N+2` from the cycle the write is *taken* (`t_beat`), not the cycle it
> becomes *visible* (`t_beat + D_WR`). The real defect was that §9.6 and REQ-074 could
> be read as placing `t_start` one cycle apart; the off-by-one was only its symptom.
> v1.1.1 names `t_beat`, `t_start` and `t_commit` separately above, fixes `t_start =
> t_beat`, and keeps `D_WR` out of every latency formula. `D_WR` survives only as the
> write-visibility invariant of REQ-122, which the RTL meets with `D_WR = 1`.
> **No RTL change is required:** the v1 RTL sets `DONE` at `t_beat + 4N + 2` = 34 at
> `N = 8`, which is what REQ-123 now demands.

---

## 10. Module: `reg_file`

The authoritative bit-level table is `docs/register-map.md`. This section defines
behaviour; the two files list the identical set of registers and the identical
reset values.

### 10.1 Register list

| BAR0 offset | Name | Access summary |
|-------------|------|----------------|
| `0x0000` | `ID` | RO |
| `0x0004` | `VERSION` | RO |
| `0x0008` | `CONFIG` | RO |
| `0x000C` | `CTRL` | WO, self-clearing |
| `0x0010` | `STATUS` | mixed RO / W1C |
| `0x0014` | `IRQ_ENABLE` | RW |
| `0x0018` | `IRQ_STATUS` | RO |
| `0x001C` | `PERF_CYCLES` | RO |
| `0x0020` | `SCRATCH` | RW |
| `0x0024` | `OP_COUNT` | RO |
| `0x0028` – `0x0FFF` | reserved | RAZ/WI |

### 10.2 Identification registers

- **REQ-065** `ID` (0x0000) shall read `0x4D415431` (ASCII "MAT1") at all times.
- **REQ-066** `VERSION` (0x0004) shall read `0x00010000`, encoding
  `[23:16]` major = 1, `[15:8]` minor = 0, `[7:0]` patch = 0, `[31:24]` = 0.
- **REQ-067** `CONFIG` (0x0008) shall read
  `{8'h00, ACCW[7:0], DW[7:0], N[7:0]}` — i.e. `[7:0]` = `N`, `[15:8]` = operand
  width in bits, `[23:16]` = accumulator width in bits, `[31:24]` = 0. For the v1
  build (`N=8, DW=8, ACCW=32`) this is `0x00200808`.

### 10.3 `CTRL` (0x000C) — write-only, self-clearing

| Bit | Name | Effect |
|-----|------|--------|
| 0 | `START` | Start one matrix multiply. |
| 1 | `SOFT_RESET` | Return the engine to IDLE and clear operational state. |
| 31:2 | — | Reserved, writes ignored. |

- **REQ-068** `CTRL` shall always read `0x00000000`.
- **REQ-069** Writing 1 to `CTRL.START` while `STATUS.BUSY == 0` shall start one
  matrix multiply: `STATUS.BUSY` becomes 1 on the next clock edge, `STATUS.DONE` is
  cleared, and all `mm_pe` accumulators are cleared to 0.
- **REQ-070** *(antecedent narrowed in v1.1.3 so it is disjoint from REQ-124 by
  construction.)* Writing 1 to `CTRL.START` **with `CTRL.SOFT_RESET` written 0 in the
  same DWORD** while `STATUS.BUSY == 1` shall have no effect on the running operation
  and shall set `STATUS.ERR_START_BUSY`. A write that sets both bits is outside this
  requirement entirely and is governed by REQ-124.
- **REQ-071** *(clause on `mem_c` narrowed in v1.1.0 — see REQ-125.)* Writing 1 to
  `CTRL.SOFT_RESET` shall, within 2 clock cycles: return `mm_ctrl` to IDLE, clear
  `STATUS.BUSY`, `STATUS.DONE` and all `STATUS` error bits, clear `PERF_CYCLES` to 0,
  and clear all `mm_pe` accumulators to 0. It shall leave `mem_a`, `mem_b`, `SCRATCH`,
  `IRQ_ENABLE`, `OP_COUNT` and the entire configuration space (including BAR0)
  unchanged. It shall not itself modify any word of `mem_c`; what `mem_c` contains
  afterwards is governed by REQ-125.
- **REQ-072** If `START` and `SOFT_RESET` are written 1 in the same DWORD write,
  `SOFT_RESET` takes precedence and no operation is started. See REQ-124 for the case
  where this happens while `STATUS.BUSY == 1`.
- **REQ-073** A `CTRL` write shall take effect only for bytes whose Byte Enable is 1;
  `CTRL.START` and `CTRL.SOFT_RESET` are in byte 0, so `First BE[0]` must be 1 for
  them to act.
- **REQ-124** *(new in v1.1.0.)* If `START` and `SOFT_RESET` are both written 1 in the
  same DWORD **while `STATUS.BUSY == 1`**, `SOFT_RESET` shall take effect in full per
  REQ-071, the `START` shall be ignored entirely, and `STATUS.ERR_START_BUSY` shall
  **not** be left set. (Whether the RTL suppresses the error at the source or sets it
  and has REQ-071's clear override it in the same cycle is not observable and is not
  constrained; the observable requirement is that `STATUS.ERR_START_BUSY` reads 0
  afterwards.)
- **REQ-125** *(new in v1.1.0.)* `CTRL.SOFT_RESET` asserted while `mm_ctrl` is in the
  `DRAIN` state shall abort the drain immediately. Words of `mem_c` already written by
  the drain retain their newly written values; words not yet reached retain whatever
  they held before the operation. `mem_c` is therefore left in a **defined but mixed**
  state: every word holds either its pre-operation value or its correct new value, and
  no word holds an otherwise-undefined value. Software must treat C as invalid after a
  mid-operation `SOFT_RESET` and must re-run the operation.

> **Why REQ-125 exists.** v1.0.0's REQ-071 said `SOFT_RESET` "leaves `mem_c`
> unchanged". That is unmappable to hardware if `SOFT_RESET` lands mid-`DRAIN`: the
> rows the drain has already committed are already written, and unwinding them would
> require shadow storage that this design deliberately does not have. REQ-071's
> `mem_c` clause has been narrowed to "`SOFT_RESET` does not itself modify `mem_c`",
> and REQ-125 now states the guarantee that is actually achievable and testable.

### 10.4 `STATUS` (0x0010)

| Bit | Name | Access | Set by | Cleared by |
|-----|------|--------|--------|------------|
| 0 | `BUSY` | RO | engine running | engine finishing, or `SOFT_RESET`, or `rst` |
| 1 | `DONE` | W1C | operation completing | writing 1, or `SOFT_RESET`, or `rst` |
| 2 | `ERR_START_BUSY` | W1C | `START` written while `BUSY` | writing 1, or `SOFT_RESET`, or `rst` |
| 3 | `ERR_WRITE_BUSY` | W1C | write to A/B/C while `BUSY` | writing 1, or `SOFT_RESET`, or `rst` |
| 4 | `ERR_UNSUP_REQ` | W1C | unsupported request (§7.6) | writing 1, or `SOFT_RESET`, or `rst` |
| 31:5 | — | RO 0 | | |

- **REQ-074** *(`t_start` pinned in v1.1.1; the requirement itself is unchanged.)* Let
  `t_start` be the cycle on which the `CTRL.START` write DWORD is **taken** by
  `reg_file` — which is `t_beat`, the cycle that write's payload DWORD transfers on
  `rx_tlp_*`, and **not** `t_commit = t_beat + D_WR`; see §9.6. Let
  `t_done = t_start + 4*N + 2` be the cycle on which `STATUS.DONE` is set.
  `STATUS.BUSY` shall read 1 on every cycle in the closed interval
  `[t_start + 1, t_done]` and 0 on every cycle outside it.
- **REQ-075** `STATUS.DONE` shall be set on the cycle the operation completes and
  shall remain set until written with 1, `SOFT_RESET`, or `rst`.
- **REQ-076** Each W1C bit shall be cleared when a `STATUS` write is performed with
  that bit position = 1 **and** the Byte Enable covering that bit = 1. Writing 0 to a
  W1C bit shall leave it unchanged.
- **REQ-077** If a W1C bit's set condition and a clearing write occur on the same
  clock edge, the **set** wins (the bit remains 1). This priority shall hold for all
  four W1C bits uniformly.

> **Reachability note (v1.1.0, informative — does not change REQ-077).** Of the four
> set-versus-clear collisions REQ-077 covers, only `DONE` is actually reachable in
> this design. `ERR_UNSUP_REQ` is set from `tlp_rx`'s header-parse state while a
> register write requires `tlp_rx` to be in its write-payload state, and the two
> states are mutually exclusive. `ERR_START_BUSY` and `ERR_WRITE_BUSY` each require a
> *different beat of the same burst* to be in flight simultaneously, which the
> one-DWORD-per-cycle sequencing of REQ-056 forbids. REQ-077 is still stated
> uniformly, because the priority must be designed in rather than depend on those
> arguments remaining true, and because they would stop being true if DEC-007's
> strict serialization were ever relaxed. Test-writer: do not treat the three
> unreachable collisions as a coverage hole.
- **REQ-078** `STATUS` bits 31:5 shall read 0 and ignore writes.

### 10.5 `IRQ_ENABLE` (0x0014) and `IRQ_STATUS` (0x0018)

`IRQ_ENABLE` bit positions mirror `STATUS` exactly.

| Bit | Name | Access | Reset |
|-----|------|--------|-------|
| 0 | — (there is no interrupt for `BUSY`) | RO 0 | 0 |
| 1 | `DONE_EN` | RW | 0 |
| 2 | `ERR_START_BUSY_EN` | RW | 0 |
| 3 | `ERR_WRITE_BUSY_EN` | RW | 0 |
| 4 | `ERR_UNSUP_REQ_EN` | RW | 0 |
| 31:5 | — | RO 0 | 0 |

- **REQ-079** `IRQ_STATUS` (0x0018) shall read `STATUS & IRQ_ENABLE`, evaluated
  bitwise, at all times. It is RO; writes are ignored.
- **REQ-080** *(reworded in v1.1.0 to remove a contradiction with REQ-012.)* `irq`
  (top-level output) shall track `IRQ_STATUS != 0` **within 2 clock cycles** in both
  directions: it shall assert within 2 cycles of `IRQ_STATUS` becoming non-zero and
  deassert within 2 cycles of `IRQ_STATUS` becoming zero. `irq` is a registered,
  level-sensitive, active-high output. There is no edge or pulse behaviour and no MSI
  (DEC-008).

> **Why this was reworded.** v1.0.0 had REQ-012 requiring a *registered* `irq` and
> REQ-080 requiring `irq` high *if and only if* `IRQ_STATUS != 0`. A registered output
> necessarily lags its input by at least one cycle, so the two could not both hold
> exactly; the rtl-designer and the rtl-reviewer reached that conclusion
> independently. REQ-012 (registered) is kept, because an unregistered `irq` would
> expose a combinational path from the register file straight to a chip output.
> REQ-080 now states a 2-cycle tracking window, consistent with REQ-081, which
> already allowed 2 cycles for deassertion. **REQ-012 is unchanged.**
- **REQ-081** Clearing the responsible `STATUS` bit (W1C) or clearing the
  corresponding `IRQ_ENABLE` bit shall deassert `irq` within 2 clock cycles, provided
  no other enabled status bit is set.

### 10.6 `PERF_CYCLES` (0x001C), `SCRATCH` (0x0020), `OP_COUNT` (0x0024)

- **REQ-082** `PERF_CYCLES` shall report the number of clock cycles taken by the most
  recently completed operation, measured from the cycle after `START` is accepted to
  the cycle on which `DONE` is set, inclusive. Reset value 0. RO.
- **REQ-083** `SCRATCH` shall be a 32-bit RW register with no side effects and reset
  value `0x00000000`. It supports byte-granular writes.
- **REQ-084** `OP_COUNT` shall be a 32-bit RO counter of completed operations since
  `rst`, incrementing by 1 each time `DONE` is set, wrapping modulo 2^32. It is
  **not** cleared by `SOFT_RESET`. Reset value 0.

---

## 11. Modules `mem_a`, `mem_b`, `mem_c`

All three are **flip-flop register files**, not SRAM macros (DEC-010). No OpenRAM or
`fakeram` macro is instantiated anywhere in this design.

Sizing for general `N` (`N = 8` in parentheses):

| Storage | Elements | Element width | Total bits | (`N=8`) |
|---------|----------|---------------|------------|---------|
| `mem_a` | `N*N` | 8 | `8*N*N` bits | 512 bits (64 B) |
| `mem_b` | `N*N` | 8 | `8*N*N` bits | 512 bits (64 B) |
| `mem_c` | `N*N` | 32 | `32*N*N` bits | 2048 bits (256 B) |

### 11.1 `mem_a`

Holds A in row-major order: BAR0 byte `0x1000 + (i*N + k)` is `A[i][k]`, a signed
8-bit value.

Ports:

- Host side: byte-enabled DWORD write, DWORD read (4 consecutive bytes).
- Engine side: `N` simultaneous byte reads per cycle — read port `i` returns
  `A[i][ka_i]` for an independently supplied index `ka_i`.

- **REQ-085** `mem_a` shall present, on engine read port `i`, the byte `A[i][ka_i]`
  combinationally selected by `ka_i` and registered such that the value is available
  1 clock cycle after `ka_i` is applied.
- **REQ-086** Host byte `0x1000 + m` for `m >= N*N` shall be RAZ/WI.

### 11.2 `mem_b`

Holds B in row-major order: BAR0 byte `0x2000 + (k*N + j)` is `B[k][j]`, signed
8-bit.

- **REQ-087** `mem_b` shall present, on engine read port `j`, the byte `B[kb_j][j]`
  for an independently supplied index `kb_j`, available 1 clock cycle after `kb_j` is
  applied.
- **REQ-088** Host byte `0x2000 + m` for `m >= N*N` shall be RAZ/WI.

### 11.3 `mem_c`

Holds C: BAR0 word at `0x3000 + 4*(i*N + j)` is `C[i][j]`, a signed 32-bit value.

- **REQ-089** `mem_c` shall accept, during the drain phase, `N` 32-bit words per
  clock cycle (one complete row of C), written to indices `(i*N + j)` for
  `j = 0..N-1` with a single supplied `i`.
- **REQ-090** `mem_c` shall return, on a host read of `0x3000 + 4*m` for `m < N*N`,
  the stored 32-bit value.
- **REQ-091** Host DWORD `0x3000 + 4*m` for `m >= N*N` shall be RAZ/WI.
- **REQ-092** `rst` shall clear all of `mem_c` to 0 (see §13.4). Neither `CTRL.START`
  nor `CTRL.SOFT_RESET` shall clear `mem_c`; its contents change only through a host
  write or through the drain phase of an operation.

---

## 12. Matmul engine micro-architecture

### 12.1 Module `matmul_engine`

Container for `mm_ctrl` and `mm_array`. Presents to `app_bar0`/`reg_file`: `start`,
`soft_reset`, `busy`, `done_pulse`, `cycle_count`; to `mem_a`/`mem_b`: read indices;
to `mem_c`: the drain write bus.

### 12.2 Dataflow choice: output-stationary

**Chosen: output-stationary.** Justification, in two sentences: each PE owns the
accumulator for exactly one element of C, so during the entire compute phase the only
signals crossing the array are 8-bit operands and a 1-bit valid, and the wide 32-bit
paths are confined inside a PE and to a drain shift chain that is idle while
computing. Weight-stationary pays for its advantage — weight reuse across many
activation rows — only when one operand is reused across several problems, which
never happens here because every `START` computes exactly one `N x N` by `N x N`
product from freshly loaded operands.

Recorded as DEC-005.

### 12.3 Module `mm_pe` (processing element)

One instance per `(i, j)`, `0 <= i, j < N`.

```
                 b_in[7:0]  (from north)
                     |
                     v
            +-------------------+
 a_in[7:0]->|  a_reg  b_reg     |-> a_out[7:0]  (to east)
 v_in ----->|  v_reg            |-> v_out       (to east)
            |                   |
            |  acc[31:0]        |-> b_out[7:0]  (to south)
            +-------------------+
                     |
              acc_out[31:0] (to south, drain chain)
```

Per-cycle behaviour when the array is enabled:

| Register | Width | Next value |
|----------|-------|-----------|
| `a_reg` | 8 | `a_in` |
| `b_reg` | 8 | `b_in` |
| `v_reg` | 1 | `v_in` |
| `acc` | 32 | compute phase: `v_in ? acc + signed(a_in)*signed(b_in) : acc`; drain phase: `acc_in_from_north`; on `start`: `0` |

Outputs: `a_out = a_reg`, `b_out = b_reg`, `v_out = v_reg`, `acc_out = acc`.

- **REQ-093** `mm_pe` shall compute `acc <= acc + $signed(a_in) * $signed(b_in)` on
  every clock edge for which `v_in == 1` and the array is in the compute phase.
- **REQ-094** `mm_pe` shall register and forward `a_in`, `b_in` and `v_in` with
  exactly **one** clock cycle of latency each.
- **REQ-095** `mm_pe` accumulators shall be cleared to 0 when a `START` is accepted
  and when `SOFT_RESET` or `rst` is applied.

**Pipeline depth of a PE: 1 stage.** The 8x8 signed multiply and the 32-bit add are
combinational within one cycle, registered into `acc`. This is fixed, because the
cycle-count formula (§12.5) is a testable requirement; if 100 MHz cannot be met, the
sanctioned fix is to lower the clock (§13.2), not to add a pipeline stage.

### 12.4 Module `mm_array`

An `N x N` mesh of `mm_pe`. `a`/`v` flow west -> east, `b` flows north -> south,
`acc` flows north -> south during drain only.

Feed schedule. Let `t = 0` be the first cycle of the compute phase.

- West edge of row `i` at cycle `t`: `a_in = A[i][t-i]`, `v_in = (0 <= t-i < N)`.
  When `v_in` is 0, `a_in` shall be driven to `8'h00`.
- North edge of column `j` at cycle `t`: `b_in = B[t-j][j]`. When `(t-j)` is out of
  `[0, N-1]`, `b_in` shall be driven to `8'h00`.

With this skew, PE `(i,j)` sees operand index `k = t - i - j` on both its inputs
simultaneously, and its `v_in` (which travelled `j` hops east from row `i`'s edge)
is exactly `0 <= t-i-j < N`. A single valid bit propagating east is therefore
sufficient; no separate valid is needed on the `b` path.

- **REQ-096** The compute phase shall last exactly `3*N - 2` cycles
  (`t = 0 .. 3N-3`). The last accumulation, at PE `(N-1, N-1)` with `k = N-1`,
  occurs on `t = 3N-3`.
- **REQ-097** After the compute phase, `acc(i,j)` shall equal
  `sum over k=0..N-1 of A[i][k] * B[k][j]`, computed in exact two's-complement
  arithmetic on `ACCW` bits.
- **REQ-098** During the drain phase, on drain cycle `m` (`m = 0 .. N-1`), the
  bottom-row output bus shall carry `acc(N-1-m, j)` on lane `j`, and `mm_ctrl` shall
  write it to `mem_c` index `(N-1-m)*N + j`.
- **REQ-099** The drain phase shall last exactly `N` cycles.
- **REQ-100** No accumulation shall occur during the drain phase.

### 12.5 Module `mm_ctrl` — sequencing and cycle count

State machine:

| State | Entered when | Duration | Action |
|-------|--------------|----------|--------|
| `IDLE` | reset, `SOFT_RESET`, or after `DONE` | — | `busy = 0`. Waits for `start`. |
| `PRIME` | `start` accepted | 1 cycle | Clear all accumulators (`clr_acc` asserted in this state and only in this state). **No `mem_a`/`mem_b` read index is issued in `PRIME`.** |
| `FETCH` | after `PRIME` | 1 cycle | Issue the `k = 0` `mem_a`/`mem_b` read indices, and absorb the 1-cycle read latency, so that the first operands arrive at the array edge on the first cycle of `COMPUTE`. |
| `COMPUTE` | after `FETCH` | `3N-2` cycles | Feed schedule of §12.4. |
| `TURN` | after `COMPUTE` | 1 cycle | Switch the array from accumulate to shift. |
| `DRAIN` | after `TURN` | `N` cycles | Shift accumulators south, write `mem_c` rows. |
| `FINISH` | after `DRAIN` | 1 cycle | Set `DONE`, clear `BUSY`, latch `PERF_CYCLES`, increment `OP_COUNT`. |

Cycle count for one `N x N` multiply:

```
  T_mm(N) = 1 (PRIME) + 1 (FETCH) + (3N - 2) (COMPUTE) + 1 (TURN) + N (DRAIN) + 1 (FINISH)
          = 4N + 2 cycles
```

**Why the read indices are issued in `FETCH` and not in `PRIME`** (spec v1.1.0
correction): `clr_acc` is asserted only during `PRIME`. If `PRIME` issued the `k = 0`
indices, the `k = 0` operands would reach the array edge during `FETCH`, be
accumulated at the end of `FETCH`, and then be presented and accumulated *again* at
`COMPUTE` `t = 0` — double-counting the `k = 0` product in every element of C.
Issuing in `FETCH` leaves `PRIME` as a pure accumulator-clear cycle, keeps
`T_mm = 4N + 2` unchanged, and yields the exact C required by REQ-097 and REQ-105.

For `N = 8`: **`T_mm = 34` cycles**. For `N = 16`: 66 cycles.

- **REQ-101** `STATUS.DONE` shall be set exactly `4*N + 2` clock cycles after the
  clock edge on which `CTRL.START` is accepted.
- **REQ-102** `PERF_CYCLES` shall read `4*N + 2` after any completed operation.
- **REQ-103** `mm_ctrl` shall assert `busy` for the whole interval from the cycle
  after `START` is accepted through the cycle on which `DONE` is set.
- **REQ-104** A `START` accepted while in any state other than `IDLE` shall be
  ignored (REQ-070).

### 12.6 Accumulator width and overflow policy

- Operands are signed 8-bit: range `[-128, +127]`.
- A single product has range `[-16256, +16384]`, i.e. fits in 16 bits signed
  (`-128 * -128 = +16384`).
- The sum of `N` such products has magnitude at most `N * 16384`.
- With `ACCW = 32`, the accumulator range is `[-2^31, 2^31 - 1]`. Overflow requires
  `N * 16384 >= 2^31`, i.e. `N >= 131072`, which is far outside the legal range of
  `N` (`2 <= N <= 32`).

**Policy: exact two's-complement arithmetic, no saturation, no overflow detection,
no overflow status bit.** Overflow is provably unreachable for every legal
parameterisation, so adding saturation logic would add area and an untestable branch.

- **REQ-105** `C[i][j]` shall equal the exact integer
  `sum over k of A[i][k] * B[k][j]` for all legal inputs, with no saturation and no
  truncation.
- **REQ-106** No overflow, saturation or clamping status bit shall exist.

---

## 13. Clocking, reset and timing

### 13.1 Clock domains

- **One clock, `clk`.** `pcie_tl`, `app_bar0`, `reg_file`, `mem_a`, `mem_b`,
  `mem_c`, `matmul_engine` and every `mm_pe` are in it.
- **Zero clock-domain crossings.** There is no PIPE clock, no `user_clk`, no
  reference clock. The TLP stream at the chip boundary is synchronous to `clk`, and
  the testbench drives it from the same cocotb `Clock`.
- **REQ-107** `matmul_top` shall contain exactly one clock input and no internally
  generated or gated clock.

### 13.2 Target frequency

- **Target: 100 MHz (10.000 ns period), sky130hd, typical corner.**
- Expected critical path: `mm_pe`'s 8x8 signed multiplier feeding the 32-bit
  accumulate adder.
- **Sanctioned relaxation ladder** if the circuit designer cannot close 100 MHz:
  100 MHz -> 75 MHz -> 50 MHz. Each step must be recorded in `docs/decisions.md`
  and the final number written back into this section by spec-writer. **Changing the
  PE pipeline depth is not a sanctioned fix**, because it would invalidate REQ-101
  and REQ-102.

### 13.3 Reset

- **REQ-108** `rst` shall be active-high and **synchronous** to `clk`. Every flip-flop
  in the design shall be reset by it.
- **REQ-109** `rst` shall be held for at least 2 `clk` cycles for the reset state to
  be guaranteed.
- **REQ-110** No `initial` block, no `#` delay and no `$display` shall appear in
  `rtl/`. Reset values come from the synchronous reset only.

### 13.4 State of every register after reset

| Register / storage | Reset value |
|--------------------|-------------|
| `rx_tlp_ready` | 0 |
| `tx_tlp_valid`, `tx_tlp_sop`, `tx_tlp_eop` | 0 |
| `tx_tlp_data` | `0x00000000` |
| `irq` | 0 |
| `tlp_rx` framing state | idle / awaiting `sop` |
| `tlp_tx` framing state | idle |
| cfg Command | `0x0000` (MSE = 0, so BAR0 does not decode) |
| cfg BAR0 | `0x00000000` |
| cfg Cache Line Size | `0x00` |
| cfg Interrupt Line | `0x00` |
| `cfg_completer_id` | `0x0000` |
| all other cfg fields | fixed RO values of §8.2 |
| `ID`, `VERSION`, `CONFIG` | fixed RO values of §10.2 |
| `CTRL` | reads 0 (no state) |
| `STATUS` | `0x00000000` (BUSY=0, DONE=0, all errors 0) |
| `IRQ_ENABLE` | `0x00000000` |
| `IRQ_STATUS` | `0x00000000` |
| `PERF_CYCLES` | `0x00000000` |
| `SCRATCH` | `0x00000000` |
| `OP_COUNT` | `0x00000000` |
| `mem_a` all bytes | `0x00` |
| `mem_b` all bytes | `0x00` |
| `mem_c` all words | `0x00000000` |
| every `mm_pe.acc` | `0x00000000` |
| every `mm_pe.a_reg`, `b_reg` | `0x00` |
| every `mm_pe.v_reg` | 0 |
| `mm_ctrl` state | `IDLE` |

- **REQ-111** After `rst` deasserts, every register shall hold the value in the table
  above.
- **REQ-112** After `rst`, a `CfgRd0` of configuration offset 0x00 shall return
  `0x80001234`, allowing the host to enumerate the device without any prior
  configuration.

---

## 14. Parameters

| Name | Kind | v1 value | Legal range | Notes |
|------|------|----------|-------------|-------|
| `N` | compile-time | 8 | power of two, 2..32 | Power of two is required because the BAR0 offset -> `(i, j)` decode uses bit slicing (`j = offset[log2(N)-1:0]`). |
| `DW` | compile-time | 8 | 8 only | The `mm_pe` multiplier and `mem_a`/`mem_b` widths follow it, but only 8 is verified in v1. |
| `ACCW` | compile-time | 32 | 32 only | §12.6 proves non-overflow at 32 for all legal `N`. |
| BAR0 aperture | constant | 16384 B | fixed | Independent of `N` up to `N = 32` (A: 1024 B, B: 1024 B, C: 4096 B all fit in their 4 KiB windows). |

- **REQ-113** `matmul_top` shall elaborate correctly for any legal `N` in
  `{2, 4, 8, 16, 32}` without source edits.
- **REQ-114** `CONFIG[7:0]` shall report the elaborated `N`, so a test can discover
  the array size at run time.
- **REQ-115** The BAR0 aperture shall be 16384 bytes for every legal `N`, and the
  BAR0 sizing readback shall be `0xFFFFC000` for every legal `N`.

### What would have to change to move to `N = 16`

1. Nothing in RTL — set `N = 16` at elaboration.
2. `flow/config.mk`: `CORE_AREA` / `DIE_AREA` roughly 4x the `N = 8` footprint
   (256 PEs instead of 64), and `mem_c` grows from 2048 to 8192 flip-flops.
3. `flow/constraint.sdc`: unchanged; the critical path through `mm_pe` is
   independent of `N`.
4. Test expectations parameterised on `N` already: `T_mm = 4N+2 = 66`,
   A/B occupy 256 bytes each, C occupies 1024 bytes.
5. Simulation time grows roughly with `N^2` under Icarus; the full regression should
   be re-timed before committing to it.

---

## 15. End-to-end operating sequence (normative)

1. Host resets the device (`rst` for >= 2 cycles).
2. Host enumerates: `CfgRd0` of offset 0x00 returns `0x80001234`; header type,
   class code, subsystem IDs read; BAR0 sized by writing `0xFFFFFFFF` and reading
   back `0xFFFFC000`; BAR0 assigned by writing the base address; Capabilities
   Pointer reads 0 so no capability walk occurs; extended-capability probe of offset
   0x100 reads 0 and terminates.
3. Host writes `Command` with MSE = 1 (and typically BME = 1, which the DUT stores
   but does not use).
4. Host writes `N*N` bytes of A into `BAR0 + 0x1000` and `N*N` bytes of B into
   `BAR0 + 0x2000`, in any order, any granularity, any number of `MWr` TLPs of up to
   32 DW each.
5. Host optionally writes `IRQ_ENABLE.DONE_EN = 1`.
6. Host writes `CTRL = 0x00000001` (`START`).
7. Device asserts `STATUS.BUSY`, runs for `4N+2` cycles, writes `mem_c`, sets
   `STATUS.DONE`, clears `STATUS.BUSY`, latches `PERF_CYCLES`, increments
   `OP_COUNT`, and asserts `irq` if `DONE_EN` is set.
8. Host polls `STATUS` (or waits on `irq`), then reads `N*N` 32-bit words from
   `BAR0 + 0x3000`.
9. Host writes `STATUS = 0x00000002` to clear `DONE` and deassert `irq`.
10. Repeat from step 4.

- **REQ-116** The sequence above shall complete successfully with no Unsupported
  Request and no error bit set.
- **REQ-117** Two consecutive operations without an intervening `rst` or
  `SOFT_RESET` shall each produce correct results; the second `START` shall clear
  the accumulators so that no residue of the first operation appears in C.
- **REQ-118** An operation started while `mem_a`/`mem_b` contain all zeros shall
  produce an all-zero C and shall set `DONE` normally.
- **REQ-119** *(reworded in v1.1.0, corrected again in v1.1.2 — see the note below.)*
  Let `DW_op = ceil(N*N/4)` be the DWORD size of one operand matrix. Loading A and B
  with the **minimum number of maximal bursts**, i.e. `ceil(DW_op/32)` `MWr` TLPs of
  up to 32 DWORDs each at `BAR0 + 0x1000` and the same again at `BAR0 + 0x2000`,
  shall leave `mem_a` and `mem_b` holding exactly the same bytes as loading the same
  data with `2*DW_op` single-DW `MWr` TLPs, and the operation run afterwards shall
  produce identical C. At `N = 8`: `DW_op = 16`, so one 16-DW burst per operand versus
  32 single-DW writes. At `N = 16`: `DW_op = 64`, so **two** 32-DW bursts per operand
  versus 128 single-DW writes. At `N = 32`: `DW_op = 256`, so eight 32-DW bursts per
  operand.
- **REQ-120** *(reworded in v1.1.0; re-confirmed correct in v1.1.2.)* Reading the
  whole of C with the **minimum number of maximal bursts**, i.e. `ceil(N*N/32)` `MRd`
  TLPs of up to 32 DWORDs each, shall return byte-for-byte the same data as reading it
  with `N*N` single-DW `MRd` TLPs. At `N = 8` that is two 32-DW reads versus 64
  single-DW reads, both covering all 256 bytes of C.

> **Why REQ-119 needed a second repair (v1.1.2).** The v1.1.0 wording said "one
> maximal burst per operand" of `ceil(N*N/4)` DWORDs. That is fine up to `N = 8`
> (16 DW) but exceeds the 32-DW burst cap of REQ-018 and REQ-056 at `N = 16` (64 DW)
> and `N = 32` (256 DW), so the requirement was still unsatisfiable for two of the five
> legal values of `N` — the same defect class as v1.0.0, merely moved. The burst count
> is now `ceil(DW_op/32)`, which is correct for every legal `N`.
>
> **REQ-120 was re-checked under the same lens and is correct as written.** C is
> `N*N` DWORDs, so `ceil(N*N/32)` bursts of at most 32 DW each covers it with no burst
> exceeding the cap, for every legal `N`: 1 burst at `N`=2 and 4, 2 at `N`=8, 8 at
> `N`=16, 32 at `N`=32. At `N = 32` the C region is exactly 4096 bytes, so the last
> burst ends exactly on the region boundary and none overruns it (REQ-044).

> **Why these two were wrong in v1.0.0.** REQ-119 asked for "a single 32-DW `MWr`
> burst" covering both A and B. At `N = 8`, A is 16 DW at `0x1000` and B is 16 DW at
> `0x2000`; they sit in different 4 KiB regions of the BAR0 map (§9.2) and REQ-057
> forbids a burst wrapping between regions, so no single burst can reach both. The
> "64 single-DW" figure was also wrong: A and B together are 32 DW, not 64. REQ-120
> asked for "a single 32-DW `MRd`" of C, but C at `N = 8` is 64 DW, so one maximal
> burst reaches only half of it, while the 64 single-DW reads it was compared
> against covered all of it — the two sides did not cover the same bytes. REQ-056
> caps any burst at 32 DW, so a full C read needs two bursts. Both are now stated in
> terms of `N` so they stay true for every legal `N`.
- **REQ-121** The device shall be re-enumerable after `rst` without power cycling:
  BAR0 returns to `0x00000000` and `Command.MSE` returns to 0.

---

## 16. Numbered requirements table

Every functional behaviour in this specification carries exactly one `REQ-nnn`. IDs
are unique and contiguous from REQ-001 to REQ-121.

| ID | Section | Requirement (one line, testable) |
|----|---------|----------------------------------|
| REQ-001 | 5.2 | Once `valid` asserts, `valid`/`data`/`sop`/`eop` hold stable until the beat transfers. |
| REQ-002 | 5.2 | A sink may hold `ready` low for an unbounded number of cycles with no data loss. |
| REQ-003 | 5.2 | `ready` has no combinational dependence on `valid`; `valid` may depend on `ready`. |
| REQ-004 | 5.2 | Exactly one TLP per `sop`…`eop`; `sop` and `eop` never coincide on one beat. |
| REQ-005 | 5.2 | Idle and stall cycles may occur anywhere within a TLP; TLPs are never interleaved. |
| REQ-006 | 5.2 | During `rst`, `rx_tlp_ready`, `tx_tlp_valid`, `tx_tlp_sop`, `tx_tlp_eop` are 0. |
| REQ-007 | 5.2 | The DUT tolerates `tx_tlp_ready` low indefinitely without losing a completion or an inbound TLP. |
| REQ-008 | 5.3 | Inbound header DWORDs are decoded big-endian; inbound payload DWORDs little-endian. |
| REQ-009 | 5.3 | Outbound header DWORDs are encoded big-endian; outbound payload DWORDs little-endian. |
| REQ-010 | 6.1 | `matmul_top` has exactly the specified port list; no other top-level port exists. |
| REQ-011 | 6.1 | `matmul_top` contains only instantiation and wiring of `pcie_tl`, `app_bar0`, `matmul_engine`. |
| REQ-012 | 6.1 | `irq` is a registered output equal to the OR of all bits of `IRQ_STATUS`. |
| REQ-013 | 7.1 | Inbound TLPs are serviced in strict arrival order. |
| REQ-014 | 7.1 | At most one Completion is in flight at any time. |
| REQ-015 | 7.1 | No deadlock when `tx_tlp_ready` is held low; `rx_tlp_ready` stalls and service resumes. |
| REQ-016 | 7.3 | All listed header fields are extracted exactly as laid out in §7.2. |
| REQ-017 | 7.3 | `Length` = 0 means 1024 DW and is therefore rejected as unsupported. |
| REQ-018 | 7.3 | `MRd`/`MWr` with `Length` > 32 DW is rejected as unsupported. |
| REQ-019 | 7.3 | The full payload of a rejected `MWr` is consumed and discarded without loss of framing. |
| REQ-020 | 7.3 | `rx_tlp_sop` mid-packet abandons the partial TLP and restarts parsing at that beat. |
| REQ-021 | 7.3 | A decoded request appears at most 1 cycle after header DW2 is accepted. |
| REQ-022 | 7.3 | `MWr` payload DWORDs are presented to `app_bar0` in ascending address order, exactly `Length` of them. |
| REQ-023 | 7.4 | Each Completion is one contiguous framed packet: `sop` on DW0, `eop` on the last DWORD. |
| REQ-024 | 7.4 | Every emitted Completion has T9=T8=LN=TH=TD=EP=0, AT=00, BCM=0, DW2[7]=0. |
| REQ-025 | 7.4 | `TC` and `Attr[2:0]` are copied from the request into the Completion. |
| REQ-026 | 7.4 | `Requester ID` and `Tag[7:0]` are copied from the request into the Completion. |
| REQ-027 | 7.4 | `Completer ID` in every Completion equals the captured `cfg_completer_id`. |
| REQ-028 | 7.5 | A `CplD` for an `MRd` has `Length` = the request's `Length` and that many payload DWORDs. |
| REQ-029 | 7.5 | `Byte Count` = `Length*4 - first_be_offset - last_be_offset` per the §7.5 tables. |
| REQ-030 | 7.5 | `Lower Address` = `(request Address + first_be_offset) & 0x7F`. |
| REQ-031 | 7.5 | Exactly one Completion is returned per `MRd`; completions are never split. |
| REQ-032 | 7.5 | Completion payload contains full DWORDs including bytes whose BE is 0. |
| REQ-033 | 7.5 | `CfgRd0` Completion: `Length`=1, `Byte Count`=4, `Lower Address`=0, full DWORD returned regardless of BE. |
| REQ-034 | 7.5 | `CfgWr0` Completion: `Cpl` with `Length`=0, `Byte Count`=4, `Lower Address`=0, status SC. |
| REQ-035 | 7.5 | UR Completion: `Cpl`, `Length`=0, `Byte Count`=4, `Lower Address`=0, status UR. |
| REQ-036 | 7.5 | No Completion is ever emitted for a posted request. |
| REQ-037 | 7.5 | No Completion is ever emitted in response to an inbound Completion. |
| REQ-038 | 7.6 | `MRd` missing BAR0 or with MSE=0 -> UR Completion and `STATUS.ERR_UNSUP_REQ` set. |
| REQ-039 | 7.6 | `MWr` missing BAR0 or with MSE=0 -> discarded, `STATUS.ERR_UNSUP_REQ` set, no Completion. |
| REQ-040 | 7.6 | Unsupported non-posted TLP -> UR Completion and `STATUS.ERR_UNSUP_REQ` set. |
| REQ-041 | 7.6 | Unsupported posted TLP -> discarded, `STATUS.ERR_UNSUP_REQ` set, no Completion. |
| REQ-042 | 7.6 | `CfgRd0`/`CfgWr0` **with `Length` == 1** and non-zero Device or Function number -> UR, and no error bit set. **Antecedent narrowed in v1.1.3.** |
| REQ-043 | 7.6 | Inbound `Cpl`/`CplD` discarded silently; no error bit, no Completion. |
| REQ-044 | 7.6 | A memory request running past the end of the 16 KiB BAR0 window is treated as a BAR0 miss. |
| REQ-045 | 8.3 | `CfgRd0` returns the §8.2 values for 0x00–0x3C and `0x00000000` for 0x40–0xFFF. |
| REQ-046 | 8.3 | `CfgWr0` updates only RW fields and only byte-enabled bytes. |
| REQ-047 | 8.3 | `CfgWr0` to an RO or unimplemented offset returns SC and changes no state. |
| REQ-048 | 8.3 | After writing `0xFFFFFFFF` to BAR0, reading BAR0 returns `0xFFFFC000`. |
| REQ-049 | 8.3 | BAR0 bits [13:0] always read 0. |
| REQ-050 | 8.3 | `Command.MSE` = 0 disables all BAR0 memory decoding. |
| REQ-051 | 8.3 | Configuration space is accessible regardless of `Command.MSE`. |
| REQ-052 | 8.4 | Every accepted Type 0 config request captures its `Completer ID` into `cfg_completer_id`. |
| REQ-053 | 8.4 | BAR0 match requires `MSE`=1 and `Address[31:14] == BAR0[31:14]`. |
| REQ-054 | 8.4 | The BAR0 offset presented to `app_bar0` is `Address[13:0]` with bits [1:0] forced to 0. |
| REQ-055 | 9.2 | Unimplemented BAR0 offsets are RAZ/WI and complete with SC, not UR. |
| REQ-056 | 9.2 | Bursts of 1–32 DWORDs are serviced as consecutive ascending DWORD accesses, 1 DWORD/cycle. |
| REQ-057 | 9.2 | Each DWORD of a burst is decoded independently from its own address. |
| REQ-058 | 9.3 | `First BE` -> DWORD 0, `Last BE` -> DWORD L-1, middle DWORDs fully enabled; `Last BE` ignored when L=1. |
| REQ-059 | 9.3 | A byte with BE = 0 is not modified by a write. |
| REQ-060 | 9.3 | BE bit `j` corresponds to payload `data[8j+7:8j]` and byte address `DWORD addr + j`. |
| REQ-061 | 9.3 | Reads ignore Byte Enables and return the full 32-bit content. |
| REQ-062 | 9.5 | Writes to A/B/C while `BUSY` are discarded and set `STATUS.ERR_WRITE_BUSY`. |
| REQ-063 | 9.5 | Reads of A/B/C while `BUSY` complete with SC status. |
| REQ-064 | 9.5 | Register reads and writes are permitted at all times, including while `BUSY`. |
| REQ-065 | 10.2 | `ID` reads `0x4D415431` at all times. |
| REQ-066 | 10.2 | `VERSION` reads `0x00010000`. |
| REQ-067 | 10.2 | `CONFIG` reads `{8'h00, ACCW, DW, N}`; `0x00200808` for the v1 build. |
| REQ-068 | 10.3 | `CTRL` always reads `0x00000000`. |
| REQ-069 | 10.3 | `CTRL.START` while not `BUSY` starts one multiply, sets `BUSY`, clears `DONE`, clears accumulators. |
| REQ-070 | 10.3 | `CTRL.START` **with `SOFT_RESET` = 0** while `BUSY` is ignored and sets `STATUS.ERR_START_BUSY`. **Antecedent narrowed in v1.1.3.** |
| REQ-071 | 10.3 | `CTRL.SOFT_RESET` returns the engine to IDLE and clears BUSY/DONE/errors/PERF_CYCLES/accumulators within 2 cycles, leaving A, B, SCRATCH, IRQ_ENABLE, OP_COUNT and config space unchanged, and not itself modifying `mem_c` (see REQ-125). **Reworded in v1.1.0.** |
| REQ-072 | 10.3 | `SOFT_RESET` takes precedence over `START` when both are written in one DWORD. |
| REQ-073 | 10.3 | `CTRL` bits act only when their byte's Byte Enable is 1. |
| REQ-074 | 10.4 | `STATUS.BUSY` reads 1 exactly over `[t_start+1, t_done]` and 0 elsewhere. |
| REQ-075 | 10.4 | `STATUS.DONE` is set on completion and persists until W1C, `SOFT_RESET` or `rst`. |
| REQ-076 | 10.4 | A W1C bit clears only when written with 1 and its Byte Enable is 1; writing 0 leaves it unchanged. |
| REQ-077 | 10.4 | On a simultaneous set and W1C clear of the same status bit, the set wins, uniformly for all four W1C bits. (Only the `DONE` collision is reachable — see the §10.4 note.) |
| REQ-078 | 10.4 | `STATUS[31:5]` reads 0 and ignores writes. |
| REQ-079 | 10.5 | `IRQ_STATUS` reads `STATUS & IRQ_ENABLE` and ignores writes. |
| REQ-080 | 10.5 | `irq` tracks `IRQ_STATUS != 0` within 2 cycles in both directions; registered, level-sensitive, active high; no MSI. **Reworded in v1.1.0.** |
| REQ-081 | 10.5 | Clearing the responsible `STATUS` or `IRQ_ENABLE` bit deasserts `irq` within 2 cycles. |
| REQ-082 | 10.6 | `PERF_CYCLES` reports the cycle count of the most recently completed operation. |
| REQ-083 | 10.6 | `SCRATCH` is a byte-writable 32-bit RW register with no side effects, reset `0x00000000`. |
| REQ-084 | 10.6 | `OP_COUNT` increments on every `DONE`, wraps modulo 2^32, is not cleared by `SOFT_RESET`. |
| REQ-085 | 11.1 | `mem_a` engine read port `i` returns `A[i][ka_i]` 1 cycle after `ka_i` is applied. |
| REQ-086 | 11.1 | `mem_a` host bytes at offsets >= `N*N` are RAZ/WI. |
| REQ-087 | 11.2 | `mem_b` engine read port `j` returns `B[kb_j][j]` 1 cycle after `kb_j` is applied. |
| REQ-088 | 11.2 | `mem_b` host bytes at offsets >= `N*N` are RAZ/WI. |
| REQ-089 | 11.3 | `mem_c` accepts `N` 32-bit words (one C row) per cycle during drain. |
| REQ-090 | 11.3 | A host read of `0x3000 + 4*m`, `m < N*N`, returns the stored `C` word. |
| REQ-091 | 11.3 | `mem_c` host DWORDs at indices >= `N*N` are RAZ/WI. |
| REQ-092 | 11.3 | `mem_c` is cleared by `rst` only; neither `START` nor `SOFT_RESET` clears it. |
| REQ-093 | 12.3 | `mm_pe` computes `acc <= acc + signed(a_in)*signed(b_in)` whenever `v_in`=1 in the compute phase. |
| REQ-094 | 12.3 | `mm_pe` forwards `a_in`, `b_in`, `v_in` with exactly 1 cycle of latency each. |
| REQ-095 | 12.3 | `mm_pe` accumulators clear to 0 on `START`, `SOFT_RESET` and `rst`. |
| REQ-096 | 12.4 | The compute phase lasts exactly `3N-2` cycles. |
| REQ-097 | 12.4 | After compute, `acc(i,j)` equals the exact dot product of A row `i` and B column `j`. |
| REQ-098 | 12.4 | On drain cycle `m`, lane `j` carries `acc(N-1-m, j)` and is written to `mem_c[(N-1-m)*N + j]`. |
| REQ-099 | 12.4 | The drain phase lasts exactly `N` cycles. |
| REQ-100 | 12.4 | No accumulation occurs during the drain phase. |
| REQ-101 | 12.5 | `STATUS.DONE` is set exactly `4*N + 2` cycles after `CTRL.START` is accepted. |
| REQ-102 | 12.5 | `PERF_CYCLES` reads `4*N + 2` after any completed operation. |
| REQ-103 | 12.5 | `busy` is asserted from the cycle after `START` through the cycle `DONE` is set. |
| REQ-104 | 12.5 | A `START` accepted outside `IDLE` is ignored. |
| REQ-105 | 12.6 | `C[i][j]` is the exact integer dot product; no saturation, no truncation. |
| REQ-106 | 12.6 | No overflow/saturation status bit exists anywhere in the design. |
| REQ-107 | 13.1 | `matmul_top` has exactly one clock input and no generated or gated clock. |
| REQ-108 | 13.3 | `rst` is active-high and synchronous; every flip-flop is reset by it. |
| REQ-109 | 13.3 | `rst` held >= 2 cycles guarantees the reset state. |
| REQ-110 | 13.3 | No `initial`, no `#` delay and no `$display` appears in `rtl/`. |
| REQ-111 | 13.4 | After `rst` deasserts, every register holds the value in the §13.4 table. |
| REQ-112 | 13.4 | After `rst`, `CfgRd0` of offset 0x00 returns `0x80001234`. |
| REQ-113 | 14 | `matmul_top` elaborates for any `N` in {2,4,8,16,32} without source edits. |
| REQ-114 | 14 | `CONFIG[7:0]` reports the elaborated `N`. |
| REQ-115 | 14 | BAR0 aperture is 16384 B and sizes back as `0xFFFFC000` for every legal `N`. |
| REQ-116 | 15 | The full operating sequence of §15 completes with no UR and no error bit set. |
| REQ-117 | 15 | Two consecutive operations without reset each produce correct results; no accumulator residue. |
| REQ-118 | 15 | An operation on all-zero A and B produces all-zero C and sets `DONE` normally. |
| REQ-119 | 15 | A and B loaded as `ceil(ceil(N*N/4)/32)` maximal bursts per operand give the same bytes and the same C as `2*ceil(N*N/4)` single-DW writes. **Reworded in v1.1.0, corrected again in v1.1.2 (the v1.1.0 form was still impossible at `N`=16 and 32).** |
| REQ-120 | 15 | All of C read as `ceil(N*N/32)` maximal bursts (2 x 32 DW at `N=8`) returns the same bytes as `N*N` single-DW reads. **Reworded in v1.1.0; re-confirmed correct for all legal `N` in v1.1.2.** |
| REQ-121 | 15 | After `rst` the device is re-enumerable: BAR0 = `0x00000000`, `Command.MSE` = 0. |
| REQ-122 | 9.6 | `D_WR` is one fixed constant in 1..3 for every BAR0 write, independent of region, burst position, Byte Enables and `N`. **New in v1.1.0.** |
| REQ-123 | 9.6 | With no stalls, `STATUS.DONE` is set at exactly `t_beat + 4*N + 2` (34 at `N=8`), where `t_beat` is the cycle the `CTRL.START` payload DWORD transfers on `rx_tlp_*`. **New in v1.1.0; off-by-one corrected in v1.1.1.** |
| REQ-124 | 10.3 | `START` + `SOFT_RESET` in one DWORD while `BUSY`: `SOFT_RESET` takes full effect, `START` is ignored, `STATUS.ERR_START_BUSY` reads 0 afterwards. **New in v1.1.0.** |
| REQ-125 | 10.3 | `SOFT_RESET` during `DRAIN` aborts the drain; every `mem_c` word then holds either its pre-operation value or its correct new value, never an undefined one. **New in v1.1.0.** |
| REQ-126 | 7.6 | `CfgRd0`/`CfgWr0` with `Length != 1` -> UR Completion, no config register modified, surplus payload drained to `eop`, `STATUS.ERR_UNSUP_REQ` set. **New in v1.1.2.** |

**Total: 126 requirements, REQ-001 … REQ-126, unique and contiguous.**

REQ-001 … REQ-121 keep the identical IDs they had in v1.0.0; none has ever been
renumbered or repurposed. REQ-122 … REQ-125 were added in v1.1.0; REQ-126 in v1.1.2.
The existing IDs whose *wording* changed are REQ-071, REQ-080, REQ-119 and REQ-120
(REQ-119 twice: v1.1.0 and again in v1.1.2), plus REQ-123's value correction in
v1.1.1 — `tb/TESTPLAN.md` should be re-checked for those five only.
