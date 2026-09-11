# rtl-reviewer — Phase 2b (review)

_Two read-only review rounds; zero Blocking both times._

_Rendered 2026-09-11 from the raw session transcript. Tool output is truncated at 2,500 characters per call; credentials are redacted._

---


## 1. Prompt / Result

You are executing **Phase 2b (RTL review)** of the PCIe-attached matrix multiplier project. Working directory: /home/pgratz/pcie-matmul

You are **read-only**. Do not modify any file. Your review is filed by the orchestrator as `docs/phase-reports/phase2-review.md` and its Blocking items go to rtl-designer before validation starts.

## Read first
- `docs/spec.md` v1.0.0 (121 requirements, REQ-001…REQ-121) and `docs/register-map.md` v1.0.0 — the contract.
- `docs/decisions.md` — DEC-001…DEC-012 are settled; do not reopen them.
- `rtl/*.sv` (14 modules), `rtl/filelist.f`, `rtl/README.md`.
- `CLAUDE.md` conventions.
- Your own brief: `.claude/agents/rtl-reviewer.md`.

## State of play — already verified by the orchestrator, don't spend calls re-checking
- `verilator --lint-only -Wall -Wno-DECLFILENAME --top-module matmul_top $(cat rtl/filelist.f)` → exit 0, zero warnings. I ran this myself.
- Yosys `synth` completes: 68,970 cells, 6,607 flops at N=8.
- The independent 65-test cocotb suite passes 65/65 on Icarus.
- Exactly one lint suppression exists: `rtl/mem_c.sv:87-89`, `WIDTHCONCAT`, scoped to two lines with a matching `lint_on`. **Judge whether it is legitimate** — that is in scope — but you need not hunt for others; I grepped and there are none.
- No `initial`, no `#` delays, no `$display` in `rtl/` — I grepped.

**A passing test suite is not proof of correctness.** Tests were written from the spec by an independent agent, but they observe the boundary only. Your job is the things simulation cannot see: latch inference, CDC, reset coverage, unreachable/dead logic, structural fragility, and places where RTL and spec diverge in ways the current tests happen not to exercise.

## Priority items — the RTL author self-reported these interpretations. Check each against the spec and say whether the RTL is right, wrong, or spec-ambiguous.
1. **§12.5 `PRIME` vs `FETCH` operand issue.** Spec says `PRIME` should "issue the first `mem_a`/`mem_b` read indices." The author says doing so makes operand pair k=0 arrive at the array edge a cycle early and be **accumulated twice**, so he issues in `FETCH` instead. Verify the double-accumulate claim and whether `4N+2` and the C result still hold.
2. **§12.5 `FINISH` timing.** Author registers `DONE`/`BUSY`/`PERF_CYCLES`/`OP_COUNT` on the edge *entering* `FINISH`, so `DONE` reads 1 *during* cycle `t+4N+2` and `BUSY` spans `[t+1, t_done]`. Check against REQ-101, REQ-074, REQ-103.
3. **REQ-012 vs REQ-080.** REQ-012 wants a *registered* output equal to `|IRQ_STATUS`; REQ-080 wants `irq` to be 1 *iff* `IRQ_STATUS != 0`. The author says these cannot both hold exactly and used one cycle of lag, citing REQ-081 as sanctioning up to 2. Confirm or refute.
4. **REQ-070 + REQ-072.** Spec is silent on `START` and `SOFT_RESET` written together while `BUSY`. Author chose: SOFT_RESET wins entirely, START ignored, no `ERR_START_BUSY`. Is that consistent with the rest of the spec?
5. **REQ-020 mid-packet `sop`.** Author added an internal `app_req_abort` to stop a stranded `app_bar0` write burst from deadlocking. Check it cannot itself corrupt state or drop a legitimate burst.
6. **`app_rdata_last`** (§7.3 table) has no consumer; `tlp_tx` counts payload beats from the Length field instead. The signal is kept on the interface and sunk in `matmul_top`. Is that dead logic, or a spec signal that should be driving something?

## Also specifically check
- **REQ-077 (W1C set-vs-clear on the same clock edge).** The test writer reports this is **not observable from the chip boundary** — both outcomes are individually legal externally, so no test can distinguish them. Read the priority expression in `reg_file.sv` directly and state what the RTL actually does and whether it matches the spec's intent. This is exactly the kind of thing only a code reviewer can settle.
- **Reset coverage** against §13.4, which states the required post-reset value of every register. Yosys optimized 14 flops' resets away; the author claims every flop is reset in source. Verify that claim — an un-reset flop that Yosys happens to tie off is still a spec violation and a gate-level-sim hazard in Phase 4.
- **Latch inference** and incompletely-specified `case`. Note: Icarus 12 rejects `unique case`, so the author removed all `unique` qualifiers and relies on `default`. Confirm every `case` is genuinely fully specified.
- **CDC.** The design is nominally single-clock (`clk`, sync active-high `rst`). Confirm there is genuinely no second domain and no asynchronous path, per §13.1.
- **Parameterization (DEC-004 / REQ-113).** `N` must be a real parameter over {2,4,8,16,32} with nothing hardcoded to 8. The lint passes at all five values; check for hidden width assumptions that lint would not catch (e.g. a 3-bit index that breaks at N=32, or a `$clog2` off-by-one at N=2).
- The `mem_c.sv` WIDTHCONCAT suppression — legitimate or masking a real width bug?

## Output format — return the review itself, in full, as your final message
The orchestrator saves your returned text **verbatim** as `docs/phase-reports/phase2-review.md`, so return the complete review, not a description of it. Structure it as:

- **Blocking** — must be fixed before validation. Each item: file:line, what is wrong, which REQ or spec section it violates, and the concrete failure it causes.
- **Should fix** — real issues that do not block Phase 3. These get forwarded into the circuit designer's Phase 4 brief, so flag anything with timing, area, or synthesis impact.
- **Coverage gaps** — behavior in the spec with no corresponding RTL (goes to rtl-designer), or RTL behavior with no REQ covering it (goes to spec-writer). Label which.
- **Verified clean** — what you checked and found genuinely correct. Be specific; this is the evidence the gate was really met.

Cite `file:line` for every finding. If you find nothing blocking, say so plainly — do not manufacture findings to seem thorough. Equally, do not soften a real problem because the tests pass.


## 2. Agent

I'll start by reading the governing documents.


## 3. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/spec.md"
}
```


## 4. Prompt / Result

<details><summary>output</summary>

```
1	# PCIe-Attached Matrix Multiplier — Architecture and Micro-Architecture Specification
2	
3	**Spec version: 1.0.0**
4	**Date: 2026-09-10**
5	**Owner: spec-writer**
6	**Status: Phase 1 deliverable. Binding on rtl-designer, test-writer, rtl-reviewer, circuit-designer.**
7	
8	Companion documents:
9	
10	- `docs/register-map.md` — BAR0 register map (same source of truth as this file; the
11	  two must never disagree).
12	- `docs/decisions.md` — dated decision log. DEC-001 … DEC-012 are binding inputs to
13	  and outputs of this spec.
14	
15	Change log:
16	
17	| Version | Date | Change | REQ IDs affected |
18	|---------|------|--------|------------------|
19	| 1.0.0 | 2026-09-10 | Initial issue. | all (REQ-001 … REQ-121) |
20	
21	---
22	
23	## 1. Scope and non-goals
24	
25	### 1.1 What this design is
26	
27	A single-clock, single-reset digital ASIC block, `matmul_top`, that:
28	
29	1. Terminates a **PCIe Transaction Layer**: it parses inbound TLPs, implements a
30	   minimal Type 0 configuration space sufficient for a root complex to enumerate it
31	   and assign one 16 KiB memory BAR, and builds outbound Completion TLPs.
32	2. Exposes, through BAR0, a control/status register block and three operand
33	   storages (A, B, C).
34	3. Computes `C = A x B` for two `N x N` signed 8-bit integer matrices into 32-bit
35	   signed accumulators, using an `N x N` output-stationary systolic array.
36	
37	Everything in `matmul_top` is synthesizable and goes through OpenROAD to GDS-II.
38	
39	### 1.2 What is behavioral-model-only (never synthesized)
40	
41	| Layer | Where it lives | Notes |
42	|-------|----------------|-------|
43	| PCIe Physical Layer (PHY), SerDes, PIPE | **Does not exist anywhere in this project.** | No open PDK ships a PCIe SerDes. See DEC-002. |
44	| Link training / LTSSM | Not modeled at all. | The link is assumed permanently up. |
45	| PCIe Data Link Layer (DLL) | `cocotbext-pcie`'s Python `Port`/`SimPort` classes, inside the testbench. | See §4.4 for exactly what it does and does not do. |
46	| Root complex, host bridge, host memory, enumeration software | `cocotbext.pcie.core.RootComplex`, inside the testbench. | |
47	| TLP encode/decode on the host side | `cocotbext.pcie.core.tlp.Tlp`, inside the testbench. | The testbench never hand-writes TLP encode/decode (`CLAUDE.md` rule). |
48	| The DWORD-stream shim between `Tlp` objects and the DUT pins | `tb/models/` (test-writer owns). | Specified in §5; buildable from this document alone. |
49	
50	### 1.3

… [truncated, 43,855 more chars]
```

</details>


## 5. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/register-map.md"
}
```


## 6. Prompt / Result

<details><summary>output</summary>

```
1	# BAR0 Register Map — PCIe-Attached Matrix Multiplier
2	
3	**Version: 1.0.0 — matches `docs/spec.md` v1.0.0**
4	**Date: 2026-09-10**
5	**Owner: spec-writer**
6	
7	This file and `docs/spec.md` are two views of one source of truth. Every register
8	listed here appears in `docs/spec.md` §10; every register in `docs/spec.md` §10
9	appears here. If they ever disagree, that is a bug — report it to spec-writer, do not
10	guess.
11	
12	Conventions used below:
13	
14	| Access | Meaning |
15	|--------|---------|
16	| `RO` | Read-only. Writes are accepted (Successful Completion) and change nothing. |
17	| `RW` | Read-write. Byte-granular: a byte is written only if its Byte Enable is 1. |
18	| `W1C` | Read-write-1-to-clear. Writing 1 to a set bit clears it; writing 0 leaves it unchanged. Only acts if the Byte Enable covering the bit is 1. |
19	| `WO` | Write-only, self-clearing. Reads return 0. The bit acts on the cycle it is written and does not persist. |
20	| `RAZ/WI` | Read as zero, write ignored. |
21	
22	All accesses are 32-bit DWORDs. All offsets are byte offsets from the base address
23	programmed into BAR0 of the PCI configuration space.
24	
25	`N` is the compile-time array dimension (8 in the v1 build). `DW` = 8 (operand width
26	in bits). `ACCW` = 32 (accumulator width in bits).
27	
28	---
29	
30	## 1. BAR0 aperture
31	
32	BAR0 is a **32-bit, non-prefetchable, memory** BAR of **16384 bytes (16 KiB)**. Its
33	size is independent of `N`. Sizing readback (write `0xFFFFFFFF`, read back) is
34	`0xFFFFC000`.
35	
36	| Offset range | Region | Description |
37	|--------------|--------|-------------|
38	| `0x0000` – `0x0FFF` | Register block | §2 below |
39	| `0x1000` – `0x1FFF` | Matrix A | `N*N` signed bytes. Byte at `0x1000 + (i*N + k)` is `A[i][k]`. Offsets `>= 0x1000 + N*N` are RAZ/WI. |
40	| `0x2000` – `0x2FFF` | Matrix B | `N*N` signed bytes. Byte at `0x2000 + (k*N + j)` is `B[k][j]`. Offsets `>= 0x2000 + N*N` are RAZ/WI. |
41	| `0x3000` – `0x3FFF` | Matrix C | `N*N` signed 32-bit words. Word at `0x3000 + 4*(i*N + j)` is `C[i][j]`. Offsets `>= 0x3000 + 4*N*N` are RAZ/WI. |
42	
43	For `N = 8`: A = `0x1000`–`0x103F` (64 B), B = `0x2000`–`0x203F` (64 B),
44	C = `0x3000`–`0x30FF` (256 B).
45	
46	Any offset inside the 16 KiB aperture that is not an implemented register or storage
47	location is **RAZ/WI** and completes with **Successful Completion**, not
48	Unsupported Request.
49	
50	---
51	
52	## 2. Register block summary
53	
54	| Offset | Name | Width | Access

… [truncated, 11,024 more chars]
```

</details>


## 7. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/spec.md",
  "offset": 842,
  "limit": 610
}
```


## 8. Prompt / Result

<details><summary>output</summary>

```
842	- **REQ-062** While `STATUS.BUSY == 1`, writes to `mem_a`, `mem_b` and `mem_c` shall
843	  be discarded and `STATUS.ERR_WRITE_BUSY` shall be set. Writes are posted, so no
844	  Completion is returned either way.
845	- **REQ-063** While `STATUS.BUSY == 1`, reads of `mem_a`, `mem_b` and `mem_c` shall
846	  complete normally with SC status. The data returned from `mem_c` is the current
847	  stored content, which may be partially updated; software must wait for
848	  `STATUS.DONE`.
849	- **REQ-064** Register reads and register writes (region `0x0000`–`0x0FFF`) are
850	  permitted at all times, including while `STATUS.BUSY == 1`.
851	
852	### 9.6 Latency contract
853	
854	- Read: `app_req_valid` accepted at cycle `t` -> first read DWORD available at cycle
855	  `t+2`, then one DWORD per cycle.
856	- Write: payload DWORD accepted at cycle `t` -> storage updated at cycle `t+1`.
857	
858	---
859	
860	## 10. Module: `reg_file`
861	
862	The authoritative bit-level table is `docs/register-map.md`. This section defines
863	behaviour; the two files list the identical set of registers and the identical
864	reset values.
865	
866	### 10.1 Register list
867	
868	| BAR0 offset | Name | Access summary |
869	|-------------|------|----------------|
870	| `0x0000` | `ID` | RO |
871	| `0x0004` | `VERSION` | RO |
872	| `0x0008` | `CONFIG` | RO |
873	| `0x000C` | `CTRL` | WO, self-clearing |
874	| `0x0010` | `STATUS` | mixed RO / W1C |
875	| `0x0014` | `IRQ_ENABLE` | RW |
876	| `0x0018` | `IRQ_STATUS` | RO |
877	| `0x001C` | `PERF_CYCLES` | RO |
878	| `0x0020` | `SCRATCH` | RW |
879	| `0x0024` | `OP_COUNT` | RO |
880	| `0x0028` – `0x0FFF` | reserved | RAZ/WI |
881	
882	### 10.2 Identification registers
883	
884	- **REQ-065** `ID` (0x0000) shall read `0x4D415431` (ASCII "MAT1") at all times.
885	- **REQ-066** `VERSION` (0x0004) shall read `0x00010000`, encoding
886	  `[23:16]` major = 1, `[15:8]` minor = 0, `[7:0]` patch = 0, `[31:24]` = 0.
887	- **REQ-067** `CONFIG` (0x0008) shall read
888	  `{8'h00, ACCW[7:0], DW[7:0], N[7:0]}` — i.e. `[7:0]` = `N`, `[15:8]` = operand
889	  width in bits, `[23:16]` = accumulator width in bits, `[31:24]` = 0. For the v1
890	  build (`N=8, DW=8, ACCW=32`) this is `0x00200808`.
891	
892	### 10.3 `CTRL` (0x000C) — write-only, self-clearing
893	
894	| Bit | Name | Effect |
895	|-----|------|--------|
896	| 0 | `START` | Start one matrix multiply. |
897	| 1 | `SOFT_RESET` | Return the engine to IDLE and clear operational state. |
898	| 31:2 | — |

… [truncated, 34,099 more chars]
```

</details>


## 9. Agent

<details><summary>reasoning</summary>



</details>


## 10. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/decisions.md"
}
```


## 11. Prompt / Result

<details><summary>output</summary>

```
1	
2	## 2026-09-10 — DEC-001: Simulator flips to Icarus Verilog 12.0
3	**Context:** Phase 0 environment check. cocotb 2.1.0 hard-errors on Verilator below
4	5.036 (`cocotb_tools/makefiles/simulators/Makefile.verilator:29`, `VLT_MIN := 5.036`).
5	This machine has Verilator 5.032 and `apt-cache policy verilator` offers no newer
6	candidate. Python 3.14 is the only interpreter, which forces cocotb 2.1.0 (the only
7	release with a cp314 wheel), so downgrading cocotb to dodge the floor is not available.
8	**Decision:** Icarus Verilog 12.0 is the cocotb simulator. Verilator remains the lint
9	tool (`--lint-only -Wall`) — the version floor applies only to cocotb's VPI build, not
10	to linting. Icarus was already required for Phase 4 gate-level sim because Verilator
11	has no SDF support.
12	**Alternatives not taken:** build Verilator 5.038 from source (deferred; revisit only if
13	Icarus is too slow on the chosen array size). Decided by: orchestrator, on
14	validation-specialist evidence.
15	**Consequence:** simulation is slower than Verilator would have been. This is an input
16	to the N=8 vs N=16 array-size decision in Phase 1.
17	
18	## 2026-09-10 — DEC-002: PIPE boundary ruled out; endpoint is TLP-level
19	**Context:** `CLAUDE.md` set the synthesizable boundary at PIPE, and separately required
20	that the endpoint boundary be one `cocotbext-pcie` can attach to. Phase 0 found these
21	two requirements are in direct conflict: `cocotbext-pcie` 0.2.16 contains no PIPE
22	interface whatsoever (`grep -ri pipe` over the package returns nothing). Its RTL-facing
23	devices are `xilinx.us.UltraScalePlusPcieDevice` (AXI-Stream CQ/CC/RQ/RC), `intel.ptile`
24	and `intel.s10`; `core.RootComplex` and `core.MemoryEndpoint` are pure-Python models
25	with no RTL ports.
26	**Decision:** the "attachable by cocotbext-pcie" requirement wins, so the TLP-level
27	endpoint fallback already sanctioned in the "PCIe scope" section of `CLAUDE.md` is
28	**mandatory for v1, not optional**. The DLL is modeled behaviorally.
29	**Open — decided in Phase 1 by spec-writer:** the exact TLP-level boundary. See DEC-003.
30	Decided by: orchestrator, on validation-specialist evidence.
31	
32	## 2026-09-10 — DEC-003: TLP boundary is a raw-TLP DWORD stream (Option B), not Xilinx CQ/CC
33	**Context:** DEC-002 fixed the boundary at TLP level and left the exact form to Phase 1.
34	Two candidates were weighed.
35	*Option A* — attach `cocotbext.pcie.xilinx.us.UltraScalePlusPcieDevice` directly, so the
36	D

… [truncated, 13,612 more chars]
```

</details>


## 12. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/filelist.f"
}
```


## 13. Prompt / Result

<details><summary>output</summary>

```
1	rtl/mm_pe.sv
2	rtl/mm_array.sv
3	rtl/mm_ctrl.sv
4	rtl/matmul_engine.sv
5	rtl/mem_a.sv
6	rtl/mem_b.sv
7	rtl/mem_c.sv
8	rtl/reg_file.sv
9	rtl/app_bar0.sv
10	rtl/pcie_cfg_space.sv
11	rtl/tlp_rx.sv
12	rtl/tlp_tx.sv
13	rtl/pcie_tl.sv
14	rtl/matmul_top.sv
15
```

</details>


## 14. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/README.md"
}
```


## 15. Prompt / Result

<details><summary>output</summary>

````
1	# `rtl/` — synthesizable SystemVerilog
2	
3	Implements `docs/spec.md` v1.0.0 and `docs/register-map.md` v1.0.0.
4	Top module: **`matmul_top`** (port list is spec §6.1, binding).
5	
6	Single clock `clk`, active-high **synchronous** reset `rst`, zero clock-domain
7	crossings (REQ-107, REQ-108). No `initial`, no `#` delays, no `$display`,
8	no `interface`, no unpacked struct ports, no SRAM macros (DEC-010).
9	
10	## Module hierarchy
11	
12	```
13	matmul_top                        top: instantiation + wiring only (REQ-011)
14	├── pcie_tl                       transaction layer container (DEC-007 serialization)
15	│   ├── tlp_rx                    inbound framing, header decode, TLP classification,
16	│   │                             BAR0/config request dispatch, completion descriptor
17	│   ├── pcie_cfg_space            Type 0 config space, BAR0 decode, Completer ID capture
18	│   └── tlp_tx                    Cpl / CplD header build and outbound framing
19	├── app_bar0                      BAR0 region decode + burst sequencer + byte enables
20	│   ├── reg_file                  ID/VERSION/CONFIG/CTRL/STATUS/IRQ_*/PERF/SCRATCH/OP_COUNT
21	│   ├── mem_a                     matrix A, N*N bytes, N engine read ports (flops)
22	│   ├── mem_b                     matrix B, N*N bytes, N engine read ports (flops)
23	│   └── mem_c                     matrix C, N*N 32-bit words, N-word row write (flops)
24	└── matmul_engine                 engine container
25	    ├── mm_ctrl                   IDLE/PRIME/FETCH/COMPUTE/TURN/DRAIN/FINISH, operand
26	    │                             index generation, drain sequencing, PERF counter
27	    └── mm_array                  N x N mesh
28	        └── mm_pe  (N*N)          1-stage MAC PE, output-stationary (DEC-005, DEC-009)
29	```
30	
31	## File list — compile order
32	
33	`rtl/filelist.f` is the single source of truth (used by `tb/` and by the ORFS
34	flow in `flow/`). Order:
35	
36	| # | File | One-line purpose |
37	|---|------|------------------|
38	| 1 | `mm_pe.sv` | One processing element: registers a/b/v east+south, accumulates `a*b`. |
39	| 2 | `mm_array.sv` | `N x N` mesh of `mm_pe`, west/north operand edges, south drain bus. |
40	| 3 | `mm_ctrl.sv` | Operation FSM, operand index generator, drain writes, `4N+2` cycle count. |
41	| 4 | `matmul_engine.sv` | Container for `mm_ctrl` + `mm_array`; wiring only. |
42	| 5 | `mem_a.sv` | Matrix A flop register file; host DWORD port + `N` engine byte ports. |
43	| 6 | `mem_b.sv` | 

… [truncated, 2,301 more chars]
````

</details>


## 16. Agent

Now the RTL, in filelist order.


## 17. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mm_pe.sv"
}
```


## 18. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mm_pe.sv
3	//
4	// Purpose : Output-stationary systolic processing element. Owns the 32-bit
5	//           accumulator for exactly one element of C. Forwards the 8-bit A
6	//           operand east and the 8-bit B operand south, both with exactly one
7	//           cycle of latency, together with a 1-bit valid that travels east.
8	//
9	// Parameters:
10	//   DW    - operand width in bits (8 in v1)
11	//   ACCW  - accumulator width in bits (32 in v1)
12	//
13	// Interface contract:
14	//   clr_acc : synchronous accumulator clear, highest priority after rst.
15	//   drain   : when 1 the accumulator loads acc_in (north neighbour's acc),
16	//             and no multiply-accumulate happens (REQ-100).
17	//   a_in/b_in/v_in : operands and valid for THIS cycle. The MAC uses the
18	//             *inputs*, not the registered copies, so PE(i,j) accumulates
19	//             operand index k = t-i-j (see mm_array header).
20	//   a_out/b_out/v_out : registered copies of a_in/b_in/v_in.
21	//   acc_out : current accumulator value (registered).
22	//
23	// Latency: 1 cycle. This is a single pipeline stage and is FIXED by DEC-009 /
24	//          spec 12.3 because the 4N+2 cycle count (REQ-101/102) depends on it.
25	//
26	// Implements: REQ-093, REQ-094, REQ-095, REQ-100, REQ-105, REQ-106, REQ-108.
27	// ---------------------------------------------------------------------------
28	module mm_pe #(
29	    parameter int DW   = 8,
30	    parameter int ACCW = 32
31	) (
32	    // Clock and reset
33	    input  logic                clk,
34	    input  logic                rst,       // active-high, synchronous
35	
36	    // Control
37	    input  logic                clr_acc,   // clear accumulator this cycle
38	    input  logic                drain,     // shift phase: acc <= acc_in
39	
40	    // Operand inputs
41	    input  logic [DW-1:0]       a_in,      // from west
42	    input  logic [DW-1:0]       b_in,      // from north
43	    input  logic                v_in,      // from west
44	    input  logic [ACCW-1:0]     acc_in,    // from north (drain chain)
45	
46	    // Operand outputs
47	    output logic [DW-1:0]       a_out,     // to east
48	    output logic [DW-1:0]       b_out,     // to south
49	    output logic                v_out,     // to east
50	    output logic [ACCW-1:0]     acc_out    // to south / to drain bus
51	);
52	
53	    logic [DW-1:0]           a_reg;
54	    logic [DW

… [truncated, 1,047 more chars]
```

</details>


## 19. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mm_array.sv"
}
```


## 20. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mm_array.sv
3	//
4	// Purpose : N x N mesh of mm_pe. A and the valid bit flow west -> east,
5	//           B flows north -> south, accumulators shift north -> south during
6	//           the drain phase only.
7	//
8	// Parameters:
9	//   N     - array dimension (power of two, 2..32)
10	//   DW    - operand width in bits
11	//   ACCW  - accumulator width in bits
12	//
13	// Interface contract (spec 12.4):
14	//   Let t = 0 be the first COMPUTE cycle.
15	//     a_west[i] at cycle t = A[i][t-i], v_west[i] = (0 <= t-i < N),
16	//     a_west[i] driven to 0 when v_west[i] = 0.
17	//     b_north[j] at cycle t = B[t-j][j], driven to 0 when t-j is out of range.
18	//   With that skew PE(i,j) sees operand index k = t-i-j on both inputs and its
19	//   v_in (which travelled j hops east) is exactly (0 <= t-i-j < N), so a single
20	//   valid bit propagating east is sufficient.
21	//
22	//   drain   : during drain cycle m, acc_south[j] carries acc(N-1-m, j).
23	//   clr_acc : clears every accumulator.
24	//
25	// Latency: compute phase is exactly 3N-2 cycles (t = 0 .. 3N-3); drain phase
26	//          is exactly N cycles.
27	//
28	// Implements: REQ-096, REQ-097, REQ-098, REQ-099, REQ-100.
29	// ---------------------------------------------------------------------------
30	module mm_array #(
31	    parameter int N    = 8,
32	    parameter int DW   = 8,
33	    parameter int ACCW = 32
34	) (
35	    // Clock and reset
36	    input  logic                clk,
37	    input  logic                rst,
38	
39	    // Control (broadcast to every PE)
40	    input  logic                clr_acc,
41	    input  logic                drain,
42	
43	    // West edge: one operand byte + valid per row
44	    input  logic [N*DW-1:0]     a_west_flat,
45	    input  logic [N-1:0]        v_west,
46	
47	    // North edge: one operand byte per column
48	    input  logic [N*DW-1:0]     b_north_flat,
49	
50	    // South edge: bottom-row accumulator bus (drain)
51	    output logic [N*ACCW-1:0]   acc_south_flat
52	);
53	
54	    // Per-PE registered outputs, flattened as index (i*N + j).
55	    logic [N*N*DW-1:0]   a_o;
56	    logic [N*N*DW-1:0]   b_o;
57	    logic [N*N-1:0]      v_o;
58	    logic [N*N*ACCW-1:0] acc_o;
59	
60	    genvar gi, gj;
61	    generate
62	        for (gi = 0; gi < N; gi = gi + 1) begin : g_row
63	            for (gj = 0; gj < N; gj = gj + 1) begin : g_col
64	
65	                logic [DW-1:0] 

… [truncated, 2,225 more chars]
```

</details>


## 21. Agent

<details><summary>reasoning</summary>



</details>


## 22. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mm_ctrl.sv"
}
```


## 23. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mm_ctrl.sv
3	//
4	// Purpose : Sequencer for one C = A x B operation. Owns the operand-address
5	//           generator for mem_a / mem_b, the array phase controls, the drain
6	//           write sequence into mem_c, the busy/done handshake and the
7	//           performance cycle counter.
8	//
9	// Parameters:
10	//   N     - array dimension (power of two, 2..32)
11	//
12	// Interface contract:
13	//   start        - 1-cycle strobe from reg_file (already gated on !busy).
14	//   soft_reset   - 1-cycle strobe from reg_file; returns the FSM to IDLE and
15	//                  clears the accumulators and the cycle counter.
16	//   busy         - 1 from the cycle after start is accepted through the cycle
17	//                  on which done_set is observed (REQ-074, REQ-103).
18	//   done_set     - 1 for exactly one cycle, on the final DRAIN cycle, so that
19	//                  reg_file's STATUS.DONE register reads 1 during the FINISH
20	//                  cycle, i.e. exactly 4N+2 cycles after start (REQ-101).
21	//   cycle_count  - value to latch into PERF_CYCLES on done_set; equals 4N+2.
22	//   ka_idx/ka_vld, kb_idx/kb_vld - operand indices issued one cycle ahead of
23	//                  the compute cycle that consumes them (mem_* read latency
24	//                  is 1 cycle, REQ-085/REQ-087).
25	//   v_west       - registered copy of ka_vld, aligned with the mem_a data.
26	//   c_wr_en/c_wr_row - drain write strobe and destination row of mem_c.
27	//
28	// State sequence and duration (spec 12.5):
29	//   IDLE -> PRIME(1) -> FETCH(1) -> COMPUTE(3N-2) -> TURN(1) -> DRAIN(N)
30	//        -> FINISH(1) -> IDLE.  Total 4N+2 cycles.
31	//
32	// NOTE ON SPEC INTERPRETATION: spec 12.5 puts "issue the first mem_a/mem_b read
33	//   indices" in PRIME. Issuing there would make the first operand pair arrive
34	//   at the array edge one cycle before COMPUTE t=0 and be accumulated twice.
35	//   The first indices are therefore issued in FETCH, which is the cycle whose
36	//   stated job is "absorb the 1-cycle mem read latency; first operands arrive
37	//   at the array edge". Externally visible behaviour (4N+2 cycles, value of C)
38	//   is unchanged.
39	//
40	// Latency: 4N+2 cycles from start to done_set + 1.
41	//
42	// Implements: REQ-069, REQ-071, REQ-074, REQ-082, REQ-095, REQ-096, REQ-098,
43	//             REQ-099, REQ-101, REQ-102, REQ-103, REQ-104.
44	// ----------------

… [truncated, 6,795 more chars]
```

</details>


## 24. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/matmul_engine.sv"
}
```


## 25. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// matmul_engine.sv
3	//
4	// Purpose : Container for mm_ctrl and mm_array. Presents the start/soft_reset
5	//           inputs and busy/done/cycle_count status to reg_file, the operand
6	//           read indices to mem_a / mem_b, and the drain write bus to mem_c.
7	//           Contains no logic of its own beyond instantiation and wiring.
8	//
9	// Parameters: N, DW, ACCW (see spec section 14). IDXW is derived; do not
10	//             override it.
11	//
12	// Interface contract:
13	//   start / soft_reset are 1-cycle strobes from reg_file.
14	//   a_rd / b_rd arrive one cycle after ka_idx / kb_idx are issued.
15	//   c_wr_en/c_wr_row/c_wr_data write one complete row of C per cycle.
16	//
17	// Latency: 4N+2 cycles from start to the cycle on which STATUS.DONE reads 1.
18	//
19	// Implements: spec section 12.1.
20	// ---------------------------------------------------------------------------
21	module matmul_engine #(
22	    parameter int N    = 8,
23	    parameter int DW   = 8,
24	    parameter int ACCW = 32,
25	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
26	) (
27	    // Clock and reset
28	    input  logic                clk,
29	    input  logic                rst,
30	
31	    // Control / status (reg_file)
32	    input  logic                start,
33	    input  logic                soft_reset,
34	    output logic                busy,
35	    output logic                done_set,
36	    output logic [31:0]         cycle_count,
37	
38	    // mem_a engine read port
39	    output logic [N*IDXW-1:0]   ka_idx,
40	    output logic [N-1:0]        ka_vld,
41	    input  logic [N*DW-1:0]     a_rd,
42	
43	    // mem_b engine read port
44	    output logic [N*IDXW-1:0]   kb_idx,
45	    output logic [N-1:0]        kb_vld,
46	    input  logic [N*DW-1:0]     b_rd,
47	
48	    // mem_c drain write port
49	    output logic                c_wr_en,
50	    output logic [IDXW-1:0]     c_wr_row,
51	    output logic [N*ACCW-1:0]   c_wr_data
52	);
53	
54	    logic             clr_acc;
55	    logic             drain;
56	    logic [N-1:0]     v_west;
57	
58	    mm_ctrl #(
59	        .N    (N),
60	        .IDXW (IDXW)
61	    ) u_ctrl (
62	        .clk         (clk),
63	        .rst         (rst),
64	        .start       (start),
65	        .soft_reset  (soft_reset),
66	        .busy        (busy),
67	        .done_set    (done_set),
68	        .cycle_count (cycle_count),
69	        .ka_idx      (

… [truncated, 722 more chars]
```

</details>


## 26. Agent

<details><summary>reasoning</summary>



</details>


## 27. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mem_a.sv"
}
```


## 28. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mem_a.sv
3	//
4	// Purpose : Storage for matrix A. N*N signed bytes, A[i][k] at byte index
5	//           i*N + k (BAR0 byte 0x1000 + i*N + k). Implemented as a flip-flop
6	//           register file, NOT an SRAM macro (DEC-010), because the systolic
7	//           feed schedule needs N independent byte reads per cycle.
8	//
9	// Parameters: N, DW (8 in v1), IDXW derived - do not override.
10	//
11	// Interface contract:
12	//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB A window
13	//                (BAR0 offset[11:2]). h_rdata is COMBINATIONAL (app_bar0 owns the pipeline
14	//                register that gives the spec 9.6 t+2 read latency). h_wr is a
15	//                single-cycle strobe; bytes with h_be[j] = 0 are not modified.
16	//                Offsets >= N*N are read-as-zero / write-ignored (REQ-086).
17	//   Engine port: read port i returns A[i][e_idx[i]] registered, i.e. valid one
18	//                clock after e_idx/e_vld are applied (REQ-085). When
19	//                e_vld[i] = 0 the port returns 8'h00, which is what the feed
20	//                schedule of spec 12.4 requires outside the operand window.
21	//
22	// Latency: host read 0 cycles (combinational); host write 1 cycle; engine
23	//          read 1 cycle.
24	//
25	// Implements: REQ-085, REQ-086, REQ-059, REQ-060, REQ-061, REQ-111.
26	// ---------------------------------------------------------------------------
27	module mem_a #(
28	    parameter int N    = 8,
29	    parameter int DW   = 8,
30	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
31	) (
32	    // Clock and reset
33	    input  logic                clk,
34	    input  logic                rst,
35	
36	    // Host port (BAR0 region 0x1000-0x1FFF)
37	    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
38	    input  logic                h_wr,
39	    input  logic [3:0]          h_be,
40	    input  logic [31:0]         h_wdata,
41	    output logic [31:0]         h_rdata,
42	
43	    // Engine port: N independent byte reads per cycle
44	    input  logic [N*IDXW-1:0]   e_idx,
45	    input  logic [N-1:0]        e_vld,
46	    output logic [N*DW-1:0]     e_rdata
47	);
48	
49	    localparam int NDWD    = (N*N) / 4;                       // DWORDs stored
50	    localparam int DWIW    = (NDWD <= 1) ? 1 : $clog2(NDWD);  // DWORD index bits
51	    localparam int MEMBITS = (1 << DWIW) * 32;
52	
53	    logic [

… [truncated, 1,852 more chars]
```

</details>


## 29. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mem_c.sv"
}
```


## 30. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mem_c.sv
3	//
4	// Purpose : Storage for matrix C. N*N signed 32-bit words, C[i][j] at word
5	//           index i*N + j (BAR0 DWORD 0x3000 + 4*(i*N + j)). Flip-flop
6	//           register file, not an SRAM macro (DEC-010). Kept separate from the
7	//           PE accumulators (DEC-012) so the host read path never reaches into
8	//           the array.
9	//
10	// Parameters: N, ACCW (32 in v1), IDXW derived - do not override.
11	//
12	// Interface contract:
13	//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB C window.
14	//                h_rdata is COMBINATIONAL. h_wr is a single-cycle strobe with
15	//                byte enables. Indices >= N*N are RAZ/WI (REQ-091).
16	//   Drain port : d_wr_en writes one COMPLETE ROW of C per cycle: word indices
17	//                d_row*N + j for j = 0..N-1, taken from d_data lane j
18	//                (REQ-089). The drain port has priority over the host port;
19	//                host writes to C are discarded while BUSY anyway (REQ-062).
20	//
21	// Latency: host read 0 cycles (combinational); writes take effect 1 cycle
22	//          after the strobe.
23	//
24	// Implements: REQ-089, REQ-090, REQ-091, REQ-092.
25	// ---------------------------------------------------------------------------
26	module mem_c #(
27	    parameter int N    = 8,
28	    parameter int ACCW = 32,
29	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
30	) (
31	    // Clock and reset
32	    input  logic                clk,
33	    input  logic                rst,
34	
35	    // Host port (BAR0 region 0x3000-0x3FFF)
36	    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
37	    input  logic                h_wr,
38	    input  logic [3:0]          h_be,
39	    input  logic [31:0]         h_wdata,
40	    output logic [31:0]         h_rdata,
41	
42	    // Drain port from matmul_engine: one row of C per cycle
43	    input  logic                d_wr_en,
44	    input  logic [IDXW-1:0]     d_row,
45	    input  logic [N*ACCW-1:0]   d_data
46	);
47	
48	    localparam int NW      = N * N;                     // 32-bit words stored
49	    localparam int WIW     = (NW <= 1) ? 1 : $clog2(NW);
50	    localparam int MEMBITS = (1 << WIW) * ACCW;
51	    localparam int BOW     = $clog2(MEMBITS);
52	
53	    logic [MEMBITS-1:0] mem;
54	
55	    // ---- host access -----------------------------------------------------
56	    logic            h_

… [truncated, 1,632 more chars]
```

</details>


## 31. Agent

<details><summary>reasoning</summary>



</details>


## 32. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mem_b.sv"
}
```


## 33. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mem_b.sv
3	//
4	// Purpose : Storage for matrix B. N*N signed bytes, B[k][j] at byte index
5	//           k*N + j (BAR0 byte 0x2000 + k*N + j). Implemented as a flip-flop
6	//           register file, NOT an SRAM macro (DEC-010), because the systolic
7	//           feed schedule needs N independent byte reads per cycle.
8	//
9	// Parameters: N, DW (8 in v1), IDXW derived - do not override.
10	//
11	// Interface contract:
12	//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB B window
13	//                (BAR0 offset[11:2]). h_rdata is COMBINATIONAL (app_bar0 owns the pipeline
14	//                register that gives the spec 9.6 t+2 read latency). h_wr is a
15	//                single-cycle strobe; bytes with h_be[j] = 0 are not modified.
16	//                Offsets >= N*N are read-as-zero / write-ignored (REQ-088).
17	//   Engine port: read port j returns B[e_idx[j]][j] registered, i.e. valid one
18	//                clock after e_idx/e_vld are applied (REQ-087). When
19	//                e_vld[j] = 0 the port returns 8'h00, which is what the feed
20	//                schedule of spec 12.4 requires outside the operand window.
21	//
22	// Latency: host read 0 cycles (combinational); host write 1 cycle; engine
23	//          read 1 cycle.
24	//
25	// Implements: REQ-087, REQ-088, REQ-059, REQ-060, REQ-061, REQ-111.
26	// ---------------------------------------------------------------------------
27	module mem_b #(
28	    parameter int N    = 8,
29	    parameter int DW   = 8,
30	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
31	) (
32	    // Clock and reset
33	    input  logic                clk,
34	    input  logic                rst,
35	
36	    // Host port (BAR0 region 0x1000-0x1FFF)
37	    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
38	    input  logic                h_wr,
39	    input  logic [3:0]          h_be,
40	    input  logic [31:0]         h_wdata,
41	    output logic [31:0]         h_rdata,
42	
43	    // Engine port: N independent byte reads per cycle
44	    input  logic [N*IDXW-1:0]   e_idx,
45	    input  logic [N-1:0]        e_vld,
46	    output logic [N*DW-1:0]     e_rdata
47	);
48	
49	    localparam int NDWD    = (N*N) / 4;                       // DWORDs stored
50	    localparam int DWIW    = (NDWD <= 1) ? 1 : $clog2(NDWD);  // DWORD index bits
51	    localparam int MEMBITS = (1 << DWIW) * 32;
52	
53	    logic [

… [truncated, 1,862 more chars]
```

</details>


## 34. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/reg_file.sv"
}
```


## 35. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// reg_file.sv
3	//
4	// Purpose : BAR0 control/status register block, offsets 0x0000-0x0FFF.
5	//           Implements ID, VERSION, CONFIG, CTRL, STATUS, IRQ_ENABLE,
6	//           IRQ_STATUS, PERF_CYCLES, SCRATCH, OP_COUNT exactly as
7	//           docs/register-map.md v1.0.0 defines them. Everything else in the
8	//           4 KiB window is RAZ/WI.
9	//
10	// Parameters: N, DW, ACCW - reported through CONFIG (REQ-067, REQ-114).
11	//
12	// Interface contract:
13	//   h_dw_addr : DWORD index inside the register window (BAR0 offset[11:2]).
14	//   h_rd_data : COMBINATIONAL read of the addressed register.
15	//   h_wr      : single-cycle write strobe; h_be selects bytes.
16	//   ev_unsup_req / ev_write_busy : single-cycle event pulses from tlp_rx and
17	//               app_bar0 that set the corresponding W1C STATUS bits. A set
18	//               always beats a simultaneous W1C clear (REQ-077).
19	//   eng_busy / eng_done_set / eng_cycles : from matmul_engine. eng_done_set is
20	//               a 1-cycle pulse on the last DRAIN cycle so that STATUS.DONE
21	//               reads 1 exactly 4N+2 cycles after CTRL.START was accepted.
22	//   start / soft_reset : 1-cycle strobes to matmul_engine, produced
23	//               combinationally from the CTRL write so that the engine leaves
24	//               IDLE on the same clock edge that accepts the write.
25	//   irq       : registered, level sensitive; 1 iff STATUS & IRQ_ENABLE != 0.
26	//
27	// Latency: register write visible on the next cycle; read is combinational.
28	//          irq follows IRQ_STATUS with one cycle of latency (REQ-081 allows 2).
29	//
30	// Implements: REQ-012, REQ-064, REQ-065 ... REQ-084, REQ-101 ... REQ-104,
31	//             REQ-111, REQ-114.
32	// ---------------------------------------------------------------------------
33	module reg_file #(
34	    parameter int N    = 8,
35	    parameter int DW   = 8,
36	    parameter int ACCW = 32
37	) (
38	    // Clock and reset
39	    input  logic         clk,
40	    input  logic         rst,
41	
42	    // Host DWORD port (BAR0 region 0x0000-0x0FFF)
43	    input  logic [9:0]   h_dw_addr,
44	    input  logic         h_wr,
45	    input  logic [3:0]   h_be,
46	    input  logic [31:0]  h_wdata,
47	    output logic [31:0]  h_rdata,
48	
49	    // Error event pulses
50	    input  logic         ev_unsup_req,
51	    input  logic         ev_write_busy,
52	
53	    // m

… [truncated, 6,410 more chars]
```

</details>


## 36. Agent

<details><summary>reasoning</summary>



</details>


## 37. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/app_bar0.sv"
}
```


## 38. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// app_bar0.sv
3	//
4	// Purpose : BAR0 application layer. Decodes the 14-bit BAR0 byte offset into
5	//           one of four 4 KiB regions, sequences 1..32 DWORD bursts, applies
6	//           byte enables on writes, and returns read data. Instantiates
7	//           reg_file, mem_a, mem_b and mem_c.
8	//
9	//   BAR0 offset[13:12] -> 00 reg_file, 01 mem_a, 10 mem_b, 11 mem_c.
10	//   Every DWORD of a burst is decoded independently from its own address
11	//   (REQ-057); anything that is not an implemented location is RAZ/WI with SC
12	//   status (REQ-055).
13	//
14	// Parameters: N, DW, ACCW; IDXW derived - do not override.
15	//
16	// Interface contract:
17	//   req_*    : one decoded BAR0 request from tlp_rx. req_ready is high only
18	//              in IDLE and never depends on req_valid (REQ-003).
19	//   req_abort: 1-cycle strobe from tlp_rx when an inbound TLP is abandoned
20	//              mid-payload (REQ-020). Returns this block to IDLE so a truncated
21	//              write burst can never deadlock the request path.
22	//   wdata_*  : write payload, req_len beats, ascending addresses.
23	//   rdata_*  : read payload, req_len beats, ascending addresses.
24	//   eng_*    : engine-side ports of mem_a / mem_b / mem_c and the reg_file
25	//              control/status handshake, brought out for matmul_top to wire to
26	//              matmul_engine.
27	//
28	// Latency (spec 9.6):
29	//   Read  : request accepted at cycle t -> first rdata beat at cycle t+2, then
30	//           one DWORD per cycle when not stalled.
31	//   Write : payload DWORD accepted at cycle t -> storage updated at cycle t+1.
32	//
33	// Implements: REQ-055 ... REQ-064, and hosts REQ-065 ... REQ-092.
34	// ---------------------------------------------------------------------------
35	module app_bar0 #(
36	    parameter int N    = 8,
37	    parameter int DW   = 8,
38	    parameter int ACCW = 32,
39	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
40	) (
41	    // Clock and reset
42	    input  logic                clk,
43	    input  logic                rst,
44	
45	    // Decoded BAR0 request (from tlp_rx)
46	    input  logic                req_valid,
47	    output logic                req_ready,
48	    input  logic                req_write,
49	    input  logic [13:0]         req_addr,
50	    input  logic [5:0]          req_len,
51	    input  logic [3:0]          req_first_be,
52	    input  logi

… [truncated, 8,678 more chars]
```

</details>


## 39. Agent

<details><summary>reasoning</summary>



</details>


## 40. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/tlp_rx.sv"
}
```


## 41. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// tlp_rx.sv
3	//
4	// Purpose : Inbound transaction-layer engine. Frames the 32-bit DWORD stream,
5	//           captures and decodes the three header DWORDs (PCIe wire /
6	//           big-endian order, spec 7.2), classifies the TLP, and either hands
7	//           a decoded request to app_bar0 (memory) or pcie_cfg_space (Type 0
8	//           config), or rejects it. It also owns the completion descriptor and
9	//           completion payload source, and enforces strict in-order, one-at-a-
10	//           time service (DEC-007): rx_tlp_ready is held low from the moment a
11	//           request is dispatched until its completion has been fully
12	//           transferred.
13	//
14	// Parameters: none.
15	//
16	// Interface contract:
17	//   rx_tlp_*      : chip-boundary inbound stream. rx_tlp_ready is 0 during rst
18	//                   (REQ-006) and never depends combinationally on
19	//                   rx_tlp_valid (REQ-003).
20	//   app_req_*     : one decoded BAR0 request, asserted the cycle after header
21	//                   DW2 is accepted (REQ-021).
22	//   app_req_abort : asserted when a mid-payload rx_tlp_sop abandons a partly
23	//                   received MWr (REQ-020), so app_bar0's burst counter cannot
24	//                   be left stranded.
25	//   app_wdata_*   : MWr payload, ascending addresses, exactly Length DWORDs
26	//                   (REQ-022), carried verbatim in host/little-endian order.
27	//   app_rdata_*   : MRd data, forwarded to tlp_tx as the completion payload.
28	//   cfg_*         : single-cycle configuration access strobe plus the
29	//                   combinational read data returned by pcie_cfg_space.
30	//   cpl_*/pld_*   : completion descriptor and payload handed to tlp_tx.
31	//   ev_unsup_req  : 1-cycle pulse that sets STATUS.ERR_UNSUP_REQ.
32	//
33	// Latency: header DW0 accepted at t, DW2 at t+2 (no stalls) -> app_req_valid
34	//          at t+3.
35	//
36	// Implements: REQ-008, REQ-013 ... REQ-022, REQ-028 ... REQ-032, REQ-036 ...
37	//             REQ-044, REQ-050, REQ-052, REQ-053, REQ-054.
38	// ---------------------------------------------------------------------------
39	module tlp_rx (
40	    // Clock and reset
41	    input  logic         clk,
42	    input  logic         rst,
43	
44	    // Inbound TLP stream (chip boundary)
45	    input  logic [31:0]  rx_tlp_data,
46	    input  logic         rx_tlp_sop,
47	    inp

… [truncated, 15,750 more chars]
```

</details>


## 42. Agent

<details><summary>reasoning</summary>



</details>


## 43. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/tlp_tx.sv"
}
```


## 44. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// tlp_tx.sv
3	//
4	// Purpose : Build and transmit Cpl / CplD TLPs on the outbound 32-bit DWORD
5	//           stream. Emits the three header DWORDs in PCIe wire (big-endian)
6	//           order per spec 7.2.4, then cpl_len payload DWORDs taken verbatim
7	//           from the payload port (which is already in host/little-endian
8	//           order, spec 5.3).
9	//
10	// Parameters: none.
11	//
12	// Interface contract:
13	//   cpl_req_valid/ready : one completion descriptor. cpl_req_ready is high
14	//                         only in IDLE and never depends on cpl_req_valid.
15	//   cpl_with_data       : 1 = CplD (Fmt 010), 0 = Cpl (Fmt 000).
16	//   cpl_len             : payload DWORD count, 1..32 (ignored when
17	//                         cpl_with_data = 0; the Length field is then 0).
18	//   pld_*               : payload DWORD stream, exactly cpl_len beats.
19	//   cpl_done            : 1-cycle pulse on the transfer of the eop beat; used
20	//                         by tlp_rx to enforce one completion in flight
21	//                         (REQ-014).
22	//   tx_tlp_*            : chip-boundary stream. valid/sop/eop are forced to 0
23	//                         while rst is asserted (REQ-006). Once asserted,
24	//                         valid/data/sop/eop are held until the beat transfers
25	//                         (REQ-001): the header DWORDs come from registers and
26	//                         the payload source (app_bar0) holds its own outputs.
27	//
28	// Latency: cpl_req accepted at cycle t -> header DW0 presented at cycle t+1,
29	//          then one DWORD per cycle when tx_tlp_ready is high.
30	//
31	// Implements: REQ-006, REQ-007, REQ-023 ... REQ-027, REQ-031, REQ-033 ...
32	//             REQ-035, REQ-009.
33	// ---------------------------------------------------------------------------
34	module tlp_tx (
35	    // Clock and reset
36	    input  logic         clk,
37	    input  logic         rst,
38	
39	    // Completion descriptor (from tlp_rx)
40	    input  logic         cpl_req_valid,
41	    output logic         cpl_req_ready,
42	    input  logic         cpl_with_data,
43	    input  logic [5:0]   cpl_len,
44	    input  logic [11:0]  cpl_byte_count,
45	    input  logic [6:0]   cpl_lower_addr,
46	    input  logic [2:0]   cpl_status,
47	    input  logic [2:0]   cpl_tc,
48	    input  logic [2:0]   cpl_attr,
49	    input  logic [15:0]  cpl_req_id,
50	   

… [truncated, 6,149 more chars]
```

</details>


## 45. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/pcie_cfg_space.sv"
}
```


## 46. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// pcie_cfg_space.sv
3	//
4	// Purpose : Minimal Type 0 PCI configuration space for Function 0. Services
5	//           CfgRd0/CfgWr0 DWORD accesses, supplies the BAR0 base and Memory
6	//           Space Enable used for BAR0 address decoding, and captures the
7	//           device's own Bus/Device/Function number from the Completer ID of
8	//           every accepted configuration request.
9	//
10	// Parameters: none.
11	//
12	// Interface contract:
13	//   req_valid  : single-cycle strobe, asserted by tlp_rx for one accepted
14	//                Type 0 configuration request (Device = 0, Function = 0).
15	//   req_write  : 1 = CfgWr0, 0 = CfgRd0.
16	//   req_dw_addr: configuration DWORD index, i.e. Cfg Addr[11:2] from header
17	//                DW2 (spec 7.2.3).
18	//   req_be     : First DW Byte Enables. Only byte-enabled bytes are written
19	//                (REQ-046). Reads ignore byte enables (REQ-033).
20	//   req_wdata  : the payload DWORD of a CfgWr0, already in host order.
21	//   req_completer_id : header DW2[31:16] of the request; captured on every
22	//                accepted request (REQ-052).
23	//   rdata      : COMBINATIONAL read of req_dw_addr; tlp_rx registers it on
24	//                the same edge that it strobes req_valid.
25	//
26	// Latency: read 0 cycles (combinational); write visible 1 cycle after the
27	//          strobe.
28	//
29	// Implements: REQ-045 ... REQ-054, REQ-112, REQ-115, REQ-121.
30	// ---------------------------------------------------------------------------
31	module pcie_cfg_space (
32	    // Clock and reset
33	    input  logic         clk,
34	    input  logic         rst,
35	
36	    // Configuration request port (from tlp_rx)
37	    input  logic         req_valid,
38	    input  logic         req_write,
39	    input  logic [9:0]   req_dw_addr,
40	    input  logic [3:0]   req_be,
41	    input  logic [31:0]  req_wdata,
42	    input  logic [15:0]  req_completer_id,
43	    output logic [31:0]  rdata,
44	
45	    // Decode outputs
46	    output logic [17:0]  bar0_base,       // BAR0 Address[31:14]
47	    output logic         mem_space_en,    // Command.MSE
48	    output logic [15:0]  completer_id     // captured Bus/Device/Function
49	);
50	
51	    // Configuration DWORD indices
52	    localparam logic [9:0] C_ID       = 10'h000;  // 0x00 Vendor/Device ID
53	    localparam logic [9:0] C_CMDSTS   = 10'h001;  // 0x04 Command/Status
54	

… [truncated, 3,335 more chars]
```

</details>


## 47. Agent

<details><summary>reasoning</summary>



</details>


## 48. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/pcie_tl.sv"
}
```


## 49. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// pcie_tl.sv
3	//
4	// Purpose : PCIe Transaction Layer container. Instantiates tlp_rx, tlp_tx and
5	//           pcie_cfg_space and wires them to each other, to the chip-boundary
6	//           TLP streams and to app_bar0. Contains no logic of its own.
7	//
8	//           Serialization model (DEC-007): inbound TLPs are serviced in strict
9	//           arrival order, one at a time, with at most one Completion in
10	//           flight. tlp_rx holds rx_tlp_ready low from dispatch of a request
11	//           until its Completion has been fully transferred, which is what
12	//           makes an outbound arbiter unnecessary and what guarantees no
13	//           deadlock when tx_tlp_ready is held low (REQ-015).
14	//
15	//           There is NO data link layer in this design: no sequence numbers,
16	//           no LCRC, no ACK/NAK, no credit accounting, and zero DLLPs cross
17	//           this boundary (spec 4.4). There is also no clock domain crossing:
18	//           both streams are synchronous to clk (REQ-107).
19	//
20	// Parameters: none.
21	//
22	// Latency: see tlp_rx and tlp_tx headers.
23	//
24	// Implements: REQ-013, REQ-014, REQ-015 (by construction of its children).
25	// ---------------------------------------------------------------------------
26	module pcie_tl (
27	    // Clock and reset
28	    input  logic         clk,
29	    input  logic         rst,
30	
31	    // Inbound TLP stream (chip boundary)
32	    input  logic [31:0]  rx_tlp_data,
33	    input  logic         rx_tlp_sop,
34	    input  logic         rx_tlp_eop,
35	    input  logic         rx_tlp_valid,
36	    output logic         rx_tlp_ready,
37	
38	    // Outbound TLP stream (chip boundary)
39	    output logic [31:0]  tx_tlp_data,
40	    output logic         tx_tlp_sop,
41	    output logic         tx_tlp_eop,
42	    output logic         tx_tlp_valid,
43	    input  logic         tx_tlp_ready,
44	
45	    // Decoded BAR0 request (to app_bar0)
46	    output logic         app_req_valid,
47	    input  logic         app_req_ready,
48	    output logic         app_req_write,
49	    output logic [13:0]  app_req_addr,
50	    output logic [5:0]   app_req_len,
51	    output logic [3:0]   app_req_first_be,
52	    output logic [3:0]   app_req_last_be,
53	    output logic         app_req_abort,
54	
55	    // Write payload (to app_bar0)
56	    output logic         app_wdata_valid,
57	    input  logic         app_

… [truncated, 5,311 more chars]
```

</details>


## 50. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/matmul_top.sv"
}
```


## 51. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// matmul_top.sv
3	//
4	// Purpose : Top level of the PCIe-attached matrix multiplier. Contains nothing
5	//           but the instantiation and wiring of pcie_tl, app_bar0 and
6	//           matmul_engine (REQ-011).
7	//
8	//           The chip boundary is a raw-TLP, 32-bit synchronous valid/ready
9	//           DWORD stream carrying complete, DLL-stripped TLPs (DEC-003,
10	//           spec 5). Header DWORDs are big-endian (PCIe wire order), payload
11	//           DWORDs are little-endian (host order) - spec 5.3.
12	//
13	// Parameters:
14	//   N    - systolic array dimension; power of two, 2..32. 8 in v1 (DEC-004).
15	//   DW   - operand width in bits; 8 in v1.
16	//   ACCW - accumulator width in bits; 32 in v1.
17	//   IDXW - derived from N; do not override.
18	//
19	// Interface contract: spec 6.1. This port list is binding; the testbench shim
20	//   is built against it. Single clock, active-high SYNCHRONOUS reset, no clock
21	//   domain crossing anywhere in the design (REQ-107, REQ-108).
22	//
23	// Latency:
24	//   Register write accepted at t -> observable at t+1.
25	//   BAR0 read request accepted at t -> first read DWORD at t+2.
26	//   CTRL.START accepted at t -> STATUS.DONE reads 1 at t + 4N + 2.
27	//
28	// Implements: REQ-010, REQ-011, REQ-012, REQ-107, REQ-113.
29	// ---------------------------------------------------------------------------
30	module matmul_top #(
31	    parameter int N    = 8,     // systolic array dimension; power of two, 2..32
32	    parameter int DW   = 8,     // operand width in bits; 8 in v1
33	    parameter int ACCW = 32,    // accumulator width in bits; 32 in v1
34	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)   // derived, do not override
35	) (
36	    // Clock and reset
37	    input  logic        clk,
38	    input  logic        rst,            // active-high, SYNCHRONOUS
39	
40	    // Inbound TLP stream (host -> device)
41	    input  logic [31:0] rx_tlp_data,
42	    input  logic        rx_tlp_sop,
43	    input  logic        rx_tlp_eop,
44	    input  logic        rx_tlp_valid,
45	    output logic        rx_tlp_ready,
46	
47	    // Outbound TLP stream (device -> host)
48	    output logic [31:0] tx_tlp_data,
49	    output logic        tx_tlp_sop,
50	    output logic        tx_tlp_eop,
51	    output logic        tx_tlp_valid,
52	    input  logic        tx_tlp_ready,
53	
54	    // Sideband
55	    output logic        irq           

… [truncated, 5,334 more chars]
```

</details>


## 52. Agent

<details><summary>reasoning</summary>



</details>


## 53. Agent

**Grep**

```json
{
  "pattern": "REQ-\\d+",
  "path": "/home/pgratz/pcie-matmul/rtl",
  "output_mode": "content",
  "-o": true,
  "head_limit": 400
}
```


## 54. Prompt / Result

<details><summary>output</summary>

```
rtl/mm_ctrl.sv:17:REQ-074
rtl/mm_ctrl.sv:17:REQ-103
rtl/mm_ctrl.sv:20:REQ-101
rtl/mm_ctrl.sv:24:REQ-085
rtl/mm_ctrl.sv:24:REQ-087
rtl/mm_ctrl.sv:42:REQ-069
rtl/mm_ctrl.sv:42:REQ-071
rtl/mm_ctrl.sv:42:REQ-074
rtl/mm_ctrl.sv:42:REQ-082
rtl/mm_ctrl.sv:42:REQ-095
rtl/mm_ctrl.sv:42:REQ-096
rtl/mm_ctrl.sv:42:REQ-098
rtl/mm_ctrl.sv:43:REQ-099
rtl/mm_ctrl.sv:43:REQ-101
rtl/mm_ctrl.sv:43:REQ-102
rtl/mm_ctrl.sv:43:REQ-103
rtl/mm_ctrl.sv:43:REQ-104
rtl/mm_array.sv:28:REQ-096
rtl/mm_array.sv:28:REQ-097
rtl/mm_array.sv:28:REQ-098
rtl/mm_array.sv:28:REQ-099
rtl/mm_array.sv:28:REQ-100
rtl/mem_a.sv:16:REQ-086
rtl/mem_a.sv:18:REQ-085
rtl/mem_a.sv:25:REQ-085
rtl/mem_a.sv:25:REQ-086
rtl/mem_a.sv:25:REQ-059
rtl/mem_a.sv:25:REQ-060
rtl/mem_a.sv:25:REQ-061
rtl/mem_a.sv:25:REQ-111
rtl/README.md:7:REQ-107
rtl/README.md:7:REQ-108
rtl/README.md:13:REQ-011
rtl/README.md:64:REQ-113
rtl/README.md:75:REQ-012
rtl/README.md:75:REQ-081
rtl/tlp_rx.sv:18:REQ-006
rtl/tlp_rx.sv:19:REQ-003
rtl/tlp_rx.sv:21:REQ-021
rtl/tlp_rx.sv:23:REQ-020
rtl/tlp_rx.sv:26:REQ-022
rtl/tlp_rx.sv:36:REQ-008
rtl/tlp_rx.sv:36:REQ-013
rtl/tlp_rx.sv:36:REQ-022
rtl/tlp_rx.sv:36:REQ-028
rtl/tlp_rx.sv:36:REQ-032
rtl/tlp_rx.sv:36:REQ-036
rtl/tlp_rx.sv:37:REQ-044
rtl/tlp_rx.sv:37:REQ-050
rtl/tlp_rx.sv:37:REQ-052
rtl/tlp_rx.sv:37:REQ-053
rtl/tlp_rx.sv:37:REQ-054
rtl/tlp_rx.sv:208:REQ-037
rtl/tlp_rx.sv:208:REQ-043
rtl/tlp_rx.sv:328:REQ-020
rtl/reg_file.sv:10:REQ-067
rtl/reg_file.sv:10:REQ-114
rtl/reg_file.sv:18:REQ-077
rtl/reg_file.sv:28:REQ-081
rtl/reg_file.sv:30:REQ-012
rtl/reg_file.sv:30:REQ-064
rtl/reg_file.sv:30:REQ-065
rtl/reg_file.sv:30:REQ-084
rtl/reg_file.sv:30:REQ-101
rtl/reg_file.sv:30:REQ-104
rtl/reg_file.sv:31:REQ-111
rtl/reg_file.sv:31:REQ-114
rtl/reg_file.sv:139:REQ-069
rtl/mem_b.sv:16:REQ-088
rtl/mem_b.sv:18:REQ-087
rtl/mem_b.sv:25:REQ-087
rtl/mem_b.sv:25:REQ-088
rtl/mem_b.sv:25:REQ-059
rtl/mem_b.sv:25:REQ-060
rtl/mem_b.sv:25:REQ-061
rtl/mem_b.sv:25:REQ-111
rtl/pcie_tl.sv:13:REQ-015
rtl/pcie_tl.sv:18:REQ-107
rtl/pcie_tl.sv:24:REQ-013
rtl/pcie_tl.sv:24:REQ-014
rtl/pcie_tl.sv:24:REQ-015
rtl/app_bar0.sv:11:REQ-057
rtl/app_bar0.sv:12:REQ-055
rtl/app_bar0.sv:18:REQ-003
rtl/app_bar0.sv:20:REQ-020
rtl/app_bar0.sv:33:REQ-055
rtl/app_bar0.sv:33:REQ-064
rtl/app_bar0.sv:33:REQ-065
rtl/app_bar0.sv:33:REQ-092
rtl/mm_pe.sv:16:REQ-100
rtl/mm_pe.sv:24:REQ-101
rtl/mm_pe.sv:26:REQ-093
rtl/mm_pe.sv:26:REQ-094
rtl/mm_pe.sv:26:REQ-095
rtl/mm_pe.sv:26:REQ-100
rtl/mm_pe.sv:26:REQ-105
rtl/mm_pe.sv:26:REQ-106
rtl/mm_pe.sv:26:REQ-108

… [truncated, 988 more chars]
```

</details>


## 55. Agent

<details><summary>reasoning</summary>



</details>


## 56. Agent

# Phase 2b RTL Review — `rtl/` v. `docs/spec.md` 1.0.0

## Blocking

**None.** I found no defect that violates a REQ in a way that produces wrong behaviour, no latch, no unreset flop, no CDC, and no synthesis-hostile construct. Sections 2–4 below are advisory.

## Should fix

1. `rtl/mem_c.sv:87-89` — the `WIDTHCONCAT` suppression is **unnecessary**, not masking a bug: `mem <= '0` is a self-determined unsized literal and cannot produce that warning. The justification comment describes a non-problem. Remove the pragma and re-lint; a suppression that covers nothing will silently cover a real warning later.
2. Four dangling "linter sink" nets create logic that exists only to be optimised away: `rtl/mm_array.sv:115-116` (reduction-OR over `N*N*(2*DW+1+ACCW)` = 4 672 bits at N=8, 74 752 at N=32), `rtl/tlp_rx.sv:111,412`, `rtl/pcie_cfg_space.sv:109-110`, `rtl/matmul_top.sv:193-194`. The last is arguably against REQ-011 ("instantiation and wiring only"). Prefer `/* verilator lint_off UNUSEDSIGNAL */` with a justification over synthesised dead cones.
3. `rtl/tlp_rx.sv:212-215` — config TLPs are classified without checking `Length` (§7.2.3 fixes it at 1). A `CfgWr0` with `Length>1` leaves surplus payload DWORDs in the stream; recovery only happens via the REQ-020 restart on the next `sop`. Add `len_raw == 1` to the `is_cfg0` accept condition (else UR).
4. `rtl/tlp_tx.sv:125-158` — `tx_tlp_data` is not forced to 0 while `rst` is asserted, though §13.4 lists its reset value as `0x00000000`. Satisfied after reset deasserts (state is `T_IDLE`); add `tx_tlp_data = '0` to the `if (rst)` override for strictness.
5. Timing risk, for the Phase 4 brief:
   - `rtl/mm_pe.sv:61-79` — 8×8 signed multiply → 32-bit add → `acc_reg`. Known critical path (§13.2, DEC-009); fix is the clock ladder, not a pipe stage.
   - `rtl/mem_c.sv:66-68` — `mem[h_boff +: 32]` is an `N*N`:1 32-bit mux (64:1 at N=8, **1024:1 at N=32**) that then feeds `app_bar0.sv:154-161` `rd_mux` and `rd_data_r` in one cycle. Likely the second-worst path, and dominant at N≥16.
   - `rtl/mem_c.sv:91` / `mm_ctrl.sv:214-215` — `d_wr_en` fans to 2 048 flops (32 768 at N=32); `clr_acc`/`drain` fan to `N*N` PEs. All well past ~32 loads with no buffering stage in RTL.
   - `rtl/reg_file.sv:111-112` — `start`/`soft_reset` are combinational from chip input `rx_tlp_data` through `tlp_rx` → `app_wdata` → address decode → `mm_ctrl` next state. Long pin-to-flop path.
   - `rtl/tlp_rx.sv:200-222` — BAR compare + 13-bit range adder + full classifier, all combinational off `rx_tlp_data`, into the state register.

## Coverage gaps

- **REQs claimed by no module header:** REQ-002, 004, 005, 109, 110, 116–120. 004/005 are genuinely met by `tlp_tx` (sop only in `T_DW0`, eop never before `T_DW2`); the rest are testbench- or system-level. → rtl-designer: add the claims; no code change.
- **§12.5 PRIME vs FETCH (priority item 1): RTL is right, spec is wrong.** I confirmed the double-accumulate: `clr_acc` is asserted only in `PRIME` (`mm_ctrl.sv:214`), so k=0 operands arriving at the array edge during `FETCH` would be accumulated at the end of `FETCH` and again at COMPUTE t=0. Issuing in `FETCH` (`mm_ctrl.sv:103`) preserves 4N+2 and the exact C. → spec-writer: amend the PRIME row.
- **REQ-012 vs REQ-080 (item 3): author is correct, they cannot both hold.** `reg_file.sv:178` gives one cycle of lag, inside REQ-081's two. → spec-writer: reword REQ-080 as "within 2 cycles".
- **REQ-077 (W1C set-vs-clear):** `reg_file.sv:137-155` puts set strictly above clear for all four bits — matches spec intent. Additionally, three of the four collisions are **structurally unreachable**: `ev_unsup_req` fires only in `tlp_rx` state `S_H2` while any register write requires state `S_WDATA`; `ERR_WRITE_BUSY` set and its clear need two different beats of one burst; likewise `ERR_START_BUSY`. Only `DONE` can actually collide. → spec-writer may want to note this.
- **REQ-070 + REQ-072 (item 4):** `reg_file.sv:111-115` — SOFT_RESET wins, START ignored, no `ERR_START_BUSY`. Consistent, because REQ-071 clears all error bits anyway, but no REQ covers the case. → spec-writer: add one.
- **REQ-071 "leaves `mem_c` unchanged"** is unmappable if `SOFT_RESET` lands mid-`DRAIN`: rows already drained stay written. → spec-writer.
- **`app_rdata_last` (item 6)** is dead: driven at `app_bar0.sv:119`, sunk at `matmul_top.sv:194`; `tlp_tx.sv:119` counts from `Length`. Equivalent behaviour. → spec-writer: drop it from the §7.3 table, or rtl-designer: delete the port.
- **§4.3 classifies `IOWr` as posted**; PCIe Base makes it non-posted. `tlp_rx.sv:198` follows the spec. → spec-writer, for the record.

## Verified clean

- **Reset (REQ-108/111):** every `always_ff` in all 14 files has a complete `if (rst)` branch — 4 in `mm_pe`, 6 in `mm_ctrl`, 2+N in each of `mem_a`/`mem_b`, 1 in `mem_c`, 9 in `reg_file`, 9 in `app_bar0`, 5 in `pcie_cfg_space`, 10 in `tlp_rx`, 12 in `tlp_tx`. The author's claim holds; Yosys's 14 removals are dead bits, not missing resets.
- **Latches / cases:** all six `always_comb` blocks assign every output on every path; every `case` has a `default` (`reg_file:195`, `app_bar0:159`, `tlp_rx:298`, `tlp_tx:150,210`, `pcie_cfg_space:121`, `mm_ctrl:174`). No `unique`/`priority` anywhere.
- **CDC:** one `clk`, `posedge` only, synchronous active-high `rst`, no gated/derived clock, no second domain. REQ-107 met.
- **Cycle count:** hand-counted `IDLE→PRIME(1)→FETCH(1)→COMPUTE(3N-2)→TURN(1)→DRAIN(N)→FINISH(1)`; `done_set` on the last DRAIN cycle (t+4N+1) makes `STATUS.DONE` read 1 during t+4N+2 and `busy = state != IDLE` span exactly `[t+1, t+4N+2]`. REQ-074/101/102/103 all exact. `cycle_count = cyc_cnt+1 = 4N+2`.
- **TLP field extraction:** DW0/DW1/DW2 bit slices, `fbo`/`lbo` tables, `byte_count = len*4-fbo-lbo`, `lower_addr = {Addr[6:2], fbo}`, `devfn_ok = dw2[23:16]` (Device[7:3]+Function[2:0] of Completer ID) — all checked by hand against §7.2/§7.5 and correct. Byte-enable mapping `be_now = m_first & m_last` (`app_bar0.sv:127-130`) satisfies REQ-058 including the L=1 case.
- **Handshakes:** `rx_tlp_ready`, `app_req_ready`, `wdata_ready`, `cpl_req_ready` derive only from state registers; `rd_v` deasserts only on a transfer, so REQ-001/003 hold with no combinational valid↔ready loop.
- **REQ-020 abort (item 5):** `app_wdata_valid` is gated by `!rx_tlp_sop` (`tlp_rx.sv:268`) so the restarting beat is never written, and `req_abort` takes priority over the `app_bar0` case (`app_bar0.sv:182`) so no stale write or counter state survives. Cannot corrupt state or drop a legitimate burst.
- **Parameterisation (REQ-113):** checked `FTW`/`CMPW`/`CYCW`/`IDXW`/`DWIW`/`WIW`/`BOW` and every bit-offset expression at N∈{2,4,8,16,32}. The N=32 traps are handled: `mem_c.sv:64` widens the range compare to 11 bits because `NW=1024` overflows the 10-bit index, and `mm_ctrl.sv:190` sizes `FTW` so the `diff < N` wrap test is still a single comparison. No hardcoded 8.


## 57. Prompt / Result

The coordinator sent a message while you were working:
Round 2 re-review — `CLAUDE.md` requires a re-check after structural rework, and the RTL has changed since your review. This is the last gate before Phase 3 validation. Still read-only; do not modify anything.

Your round-1 review returned zero Blocking items and was filed verbatim as `docs/phase-reports/phase2-review.md`. All six "Should fix" items were actioned. Spec is now **v1.1.2** (was 1.0.0 when you reviewed); tests are at 71/71 passing, 126/126 REQs mapped. Re-read `docs/spec.md`'s "What changed" sections — five requirements were reworded and five added since you last saw it.

## Scope: review the deltas, not the whole design again
Do not re-verify what you already verified clean in round 1 (reset coverage, latch-freedom, CDC, TLP field extraction, handshakes, parameterisation) unless a change below plausibly disturbs it. Be economical — you have already done the deep pass.

## What changed in `rtl/`

1. **`mem_c.sv` reset restructured.** You judged the `WIDTHCONCAT` suppression unnecessary, on the grounds that `mem <= '0` is a self-determined unsized literal. **rtl-designer refuted this with evidence:** Verilator 5.032 does emit `WIDTHCONCAT` on that assignment at 32768 bits, and it fires only at `N=32` — which an `N=8` review would never surface. Rather than restore the pragma it rewrote the reset as a static per-row loop (`N*ACCW` bits per fill), clean at every legal `N` with zero suppressions. I confirmed lint exit 0 at N=2/8/32. **Please check the rewritten reset actually still clears every word of `mem_c` at every legal `N`** — a per-row loop is more prone to an off-by-one at the last row than a single wide assignment was, and §13.4 requires the whole array cleared.

2. **Dangling sinks replaced** with narrow `lint_off UNUSEDSIGNAL` pairs wrapping only the declarations: `mm_array.sv:61-65` (`a_o`/`b_o`/`v_o`), `tlp_rx.sv:139-142` (`dw0_r`/`dw2_r`), `pcie_cfg_space.sv:43-45` (`req_wdata`). The `matmul_top` sink is gone entirely with item 5, restoring strict REQ-011. Confirm these suppressions are as narrow as they look and are not hiding a genuinely unconnected signal that *should* be driving something.

3. **`tlp_rx.sv` config `Length` check** — `cfg_len_ok = (len_raw == 1)` added to the `is_cfg0` accept condition (`cfg_len_ok` at line 198, guard at line 221). This is now **REQ-126**. rtl-designer's structural claim, which I want you to verify independently: the malformed case falls through to the terminal `else` at line 229 (`cls_c = posted ? CLS_DROP_ERR : CLS_UR_ERR`), config requests are never posted so it lands on `CLS_UR_ERR`, and `ev_unsup_req` at line 233 pulses on exactly that class. Critically, **the devfn test lives inside the accepted branch**, so malformed `Length` bypasses the REQ-042 bus-scan carve-out — which REQ-126 requires. Check that reasoning holds and that the surplus-payload drain to `eop` cannot desynchronise the parser.

4. **`tlp_tx.sv`** — `tx_tlp_data = 32'h0` added to the `rst` override, per §13.4.

5. **`app_rdata_last` / `rdata_last` port deleted** from `app_bar0` and `matmul_top`.

6. **REQ claims added to module headers** (REQ-002/004/005, 109/110, 116–120, 122, 124, 125). No code change.

## Also worth a look
- Cell count went **up**, 68,970 → 70,148, with flops unchanged at 6,607. rtl-designer attributes this to the sinks having already been dead-code-eliminated at N=8 plus `cfg_len_ok` and mapping variance. That explanation is plausible but unverified — if you think ~1,200 cells is too large a delta for one comparator, say so.
- **REQ-122/123 and the `t_beat` / `t_start` / `t_commit` distinction** are new in §9.6. `D_WR` = 1 in this RTL. Confirm the RTL is consistent with the corrected REQ-123 (`DONE` at `t_beat + 4N + 2`, no `D_WR` term).
- **REQ-124/125** were added to codify behavior you already reviewed; confirm the module headers now claim them accurately.

## Output
Same format, returned in full — I save it verbatim as `docs/phase-reports/phase2-review-round2.md`:
**Blocking** / **Should fix** / **Coverage gaps** / **Verified clean**, with `file:line` for every finding.

Zero Blocking is the gate for Phase 3. If you find nothing blocking, say so plainly — do not manufacture findings. If something in the rework is genuinely wrong, say so just as plainly; 71 passing tests are not proof, and the `mem_c` reset rewrite in particular is the kind of change that passes every functional test while being wrong at a corner the tests do not reach.

Address this before completing your current task.


## 58. Agent

<details><summary>reasoning</summary>



</details>


## 59. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mem_c.sv"
}
```


## 60. Prompt / Result

<details><summary>output</summary>

```
1	// ---------------------------------------------------------------------------
2	// mem_c.sv
3	//
4	// Purpose : Storage for matrix C. N*N signed 32-bit words, C[i][j] at word
5	//           index i*N + j (BAR0 DWORD 0x3000 + 4*(i*N + j)). Flip-flop
6	//           register file, not an SRAM macro (DEC-010). Kept separate from the
7	//           PE accumulators (DEC-012) so the host read path never reaches into
8	//           the array.
9	//
10	// Parameters: N, ACCW (32 in v1), IDXW derived - do not override.
11	//
12	// Interface contract:
13	//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB C window.
14	//                h_rdata is COMBINATIONAL. h_wr is a single-cycle strobe with
15	//                byte enables. Indices >= N*N are RAZ/WI (REQ-091).
16	//   Drain port : d_wr_en writes one COMPLETE ROW of C per cycle: word indices
17	//                d_row*N + j for j = 0..N-1, taken from d_data lane j
18	//                (REQ-089). The drain port has priority over the host port;
19	//                host writes to C are discarded while BUSY anyway (REQ-062).
20	//
21	// Latency: host read 0 cycles (combinational); writes take effect 1 cycle
22	//          after the strobe.
23	//
24	// Implements: REQ-089, REQ-090, REQ-091, REQ-092.
25	// ---------------------------------------------------------------------------
26	module mem_c #(
27	    parameter int N    = 8,
28	    parameter int ACCW = 32,
29	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
30	) (
31	    // Clock and reset
32	    input  logic                clk,
33	    input  logic                rst,
34	
35	    // Host port (BAR0 region 0x3000-0x3FFF)
36	    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
37	    input  logic                h_wr,
38	    input  logic [3:0]          h_be,
39	    input  logic [31:0]         h_wdata,
40	    output logic [31:0]         h_rdata,
41	
42	    // Drain port from matmul_engine: one row of C per cycle
43	    input  logic                d_wr_en,
44	    input  logic [IDXW-1:0]     d_row,
45	    input  logic [N*ACCW-1:0]   d_data
46	);
47	
48	    localparam int NW      = N * N;                     // 32-bit words stored
49	    localparam int WIW     = (NW <= 1) ? 1 : $clog2(NW);
50	    localparam int MEMBITS = (1 << WIW) * ACCW;
51	    localparam int BOW     = $clog2(MEMBITS);
52	
53	    logic [MEMBITS-1:0] mem;
54	
55	    // ---- host access -----------------------------------------------------
56	    logic            h_

… [truncated, 1,912 more chars]
```

</details>


## 61. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/mm_array.sv",
  "offset": 45,
  "limit": 80
}
```


## 62. Prompt / Result

<details><summary>output</summary>

```
45	    input  logic [N-1:0]        v_west,
46	
47	    // North edge: one operand byte per column
48	    input  logic [N*DW-1:0]     b_north_flat,
49	
50	    // South edge: bottom-row accumulator bus (drain)
51	    output logic [N*ACCW-1:0]   acc_south_flat
52	);
53	
54	    // Per-PE registered outputs, flattened as index (i*N + j).
55	    // The east column's a_out/v_out and the south row's b_out leave the mesh and
56	    // have no consumer by construction of the dataflow (spec 12.4): A and the
57	    // valid bit exit to the east, B exits to the south, and only the south
58	    // accumulator bus is read. Suppressed at the declarations rather than sunk
59	    // in a reduction-OR, which would synthesise a dead cone of N*N*(2*DW+1)
60	    // bits (4608 at N = 8, 73728 at N = 32).
61	    // verilator lint_off UNUSEDSIGNAL
62	    logic [N*N*DW-1:0]   a_o;
63	    logic [N*N*DW-1:0]   b_o;
64	    logic [N*N-1:0]      v_o;
65	    // verilator lint_on UNUSEDSIGNAL
66	    logic [N*N*ACCW-1:0] acc_o;
67	
68	    genvar gi, gj;
69	    generate
70	        for (gi = 0; gi < N; gi = gi + 1) begin : g_row
71	            for (gj = 0; gj < N; gj = gj + 1) begin : g_col
72	
73	                logic [DW-1:0]   pe_a_in;
74	                logic [DW-1:0]   pe_b_in;
75	                logic            pe_v_in;
76	                logic [ACCW-1:0] pe_acc_in;
77	
78	                if (gj == 0) begin : g_a_edge
79	                    assign pe_a_in = a_west_flat[gi*DW +: DW];
80	                    assign pe_v_in = v_west[gi];
81	                end else begin : g_a_chain
82	                    assign pe_a_in = a_o[(gi*N + gj - 1)*DW +: DW];
83	                    assign pe_v_in = v_o[gi*N + gj - 1];
84	                end
85	
86	                if (gi == 0) begin : g_b_edge
87	                    assign pe_b_in   = b_north_flat[gj*DW +: DW];
88	                    assign pe_acc_in = '0;
89	                end else begin : g_b_chain
90	                    assign pe_b_in   = b_o[((gi-1)*N + gj)*DW +: DW];
91	                    assign pe_acc_in = acc_o[((gi-1)*N + gj)*ACCW +: ACCW];
92	                end
93	
94	                mm_pe #(
95	                    .DW   (DW),
96	                    .ACCW (ACCW)
97	                ) u_pe (
98	                    .clk     (clk),
99	                    .rst     (rst),
100	                    .clr_acc (clr_acc),
101	                    .drain   (drain),
102	                    .a_in    (pe_a_in),
103	                    .b_in    (pe_b_in)

… [truncated, 639 more chars]
```

</details>


## 63. Agent

<details><summary>reasoning</summary>



</details>


## 64. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/tlp_rx.sv",
  "offset": 105,
  "limit": 130
}
```


## 65. Prompt / Result

<details><summary>output</summary>

```
105	
106	    // Error event (to reg_file via app_bar0)
107	    output logic         ev_unsup_req
108	);
109	
110	    // ---- TLP classification ---------------------------------------------
111	    localparam logic [2:0] CLS_MWR       = 3'd0;  // accepted MWr to BAR0
112	    localparam logic [2:0] CLS_MRD       = 3'd1;  // accepted MRd from BAR0
113	    localparam logic [2:0] CLS_CFGRD     = 3'd2;  // accepted CfgRd0
114	    localparam logic [2:0] CLS_CFGWR     = 3'd3;  // accepted CfgWr0
115	    localparam logic [2:0] CLS_UR_ERR    = 3'd4;  // UR Cpl + ERR_UNSUP_REQ
116	    localparam logic [2:0] CLS_UR_NOERR  = 3'd5;  // UR Cpl, no error bit
117	    localparam logic [2:0] CLS_DROP_ERR  = 3'd6;  // discard + ERR_UNSUP_REQ
118	    localparam logic [2:0] CLS_DROP      = 3'd7;  // discard silently
119	
120	    typedef enum logic [3:0] {
121	        S_H0      = 4'd0,   // awaiting header DW0 (sop)
122	        S_H1      = 4'd1,   // awaiting header DW1
123	        S_H2      = 4'd2,   // awaiting header DW2
124	        S_MEMREQ  = 4'd3,   // presenting the request to app_bar0
125	        S_WDATA   = 4'd4,   // forwarding MWr payload
126	        S_CFGW    = 4'd5,   // awaiting the CfgWr0 payload DWORD
127	        S_CFGACC  = 4'd6,   // one-cycle configuration read / write
128	        S_CPL     = 4'd7,   // presenting the completion descriptor
129	        S_CPLWAIT = 4'd8,   // waiting for the completion to be transmitted
130	        S_DRAIN   = 4'd9    // consuming a rejected TLP up to eop
131	    } state_e;
132	
133	    state_e      state;
134	    // Header bits the design deliberately ignores: DW0 T9[23], T8[19], LN[17],
135	    // TH[16] and AT[11:10] are "ignored on receive" per spec 7.2.1; DW2 PH[1:0]
136	    // is ignored per spec 7.2.2 and DW2 Address[15:14] lies above the 16 KiB
137	    // BAR0 window and is consumed only by the combinational BAR compare on
138	    // rx_tlp_data at decode time.
139	    // verilator lint_off UNUSEDSIGNAL
140	    logic [31:0] dw0_r;
141	    logic [31:0] dw2_r;
142	    // verilator lint_on UNUSEDSIGNAL
143	    logic [31:0] dw1_r;
144	    logic [2:0]  cls_r;
145	    logic [5:0]  len_r;
146	    logic [5:0]  wbeat;
147	    logic [31:0] cfg_wdata_r;
148	    logic [31:0] cfg_data_r;
149	    logic        cfg_pld_v;
150	
151	    logic        beat;          // an inbound beat transfers this cycle
152	    logic        beat_hdr;      // ... and it is not a re-synchronising sop
153	    logic        restart;       // ... and it IS a r

… [truncated, 3,578 more chars]
```

</details>


## 66. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/pcie_cfg_space.sv",
  "offset": 30,
  "limit": 30
}
```


## 67. Prompt / Result

<details><summary>output</summary>

```
30	// ---------------------------------------------------------------------------
31	module pcie_cfg_space (
32	    // Clock and reset
33	    input  logic         clk,
34	    input  logic         rst,
35	
36	    // Configuration request port (from tlp_rx)
37	    input  logic         req_valid,
38	    input  logic         req_write,
39	    input  logic [9:0]   req_dw_addr,
40	    input  logic [3:0]   req_be,
41	    // req_wdata[13:8] lands on Command[15:8] and BAR0[13:8], both RO 0, so those
42	    // bits are deliberately dropped.
43	    // verilator lint_off UNUSEDSIGNAL
44	    input  logic [31:0]  req_wdata,
45	    // verilator lint_on UNUSEDSIGNAL
46	    input  logic [15:0]  req_completer_id,
47	    output logic [31:0]  rdata,
48	
49	    // Decode outputs
50	    output logic [17:0]  bar0_base,       // BAR0 Address[31:14]
51	    output logic         mem_space_en,    // Command.MSE
52	    output logic [15:0]  completer_id     // captured Bus/Device/Function
53	);
54	
55	    // Configuration DWORD indices
56	    localparam logic [9:0] C_ID       = 10'h000;  // 0x00 Vendor/Device ID
57	    localparam logic [9:0] C_CMDSTS   = 10'h001;  // 0x04 Command/Status
58	    localparam logic [9:0] C_CLASS    = 10'h002;  // 0x08 Class/Revision
59	    localparam logic [9:0] C_MISC     = 10'h003;  // 0x0C Cache line/hdr type
```

</details>


## 68. Agent

<details><summary>reasoning</summary>



</details>


## 69. Agent

**Grep**

```json
{
  "pattern": "REQ-12[2-6]|What changed|t_beat|t_commit|D_WR",
  "path": "/home/pgratz/pcie-matmul/docs/spec.md",
  "output_mode": "content",
  "-n": true,
  "head_limit": 120
}
```


## 70. Prompt / Result

<details><summary>output</summary>

```
20:| 1.1.0 | 2026-09-10 | Amendment batch from Phase 2 (rtl-designer, test-writer) and the Phase 2b review. 11 items; no requirement was renumbered or repurposed. | **Reworded:** REQ-071, REQ-080, REQ-119, REQ-120. **Added:** REQ-122 … REQ-125. **Informative notes only, meaning unchanged:** REQ-012, REQ-021, REQ-041, REQ-077, REQ-101. |
22:| 1.1.1 | 2026-09-10 | Fixed an internal inconsistency in the definition of `t_start`, and the REQ-123 off-by-one it caused. §9.6 now names `t_beat`, `t_start` and `t_commit` separately and fixes `t_start = t_beat`. `D_WR` is deliberately excluded from every latency formula. No RTL change required. | **Corrected:** REQ-123 (`t_beat + 4*N + 2`, was `t_beat + D_WR + 4*N + 2`). **Clarified, meaning unchanged:** REQ-074, REQ-101, REQ-122. |
24:| 1.1.2 | 2026-09-10 | REQ-119's v1.1.0 repair was still unsatisfiable at `N`=16 and `N`=32 (one operand is 64 and 256 DW, over the 32-DW burst cap); burst count is now `ceil(ceil(N*N/4)/32)`. REQ-120 re-checked and confirmed correct for all legal `N`. Added REQ-126 for malformed-`Length` configuration requests. | **Corrected:** REQ-119. **Added:** REQ-126. **Re-confirmed, unchanged:** REQ-120. |
26:### What changed in v1.1.0, and what the test writer must re-check
32:| REQ-071 | The `mem_c` clause is narrowed. `SOFT_RESET` no longer claims to leave `mem_c` "unchanged"; it claims only that it does not itself modify `mem_c`. The reachable guarantee moved to the new REQ-125. |
37:**Added — four new tests needed:** REQ-122, REQ-123 (§9.6, the `D_WR` write-path
38:constant and the pin-observable form of the `4N+2` latency), REQ-124, REQ-125
45:REQ-101 (unchanged; REQ-123 is its boundary-observable restatement).
543:       (Length MUST be 1; any other value is malformed -- see REQ-126)
632:observable from the chip pins. §9.6's `D_WR` constant closes that gap; see REQ-122
633:and REQ-123.
737:- **REQ-126** *(new in v1.1.2.)* A `CfgRd0` or `CfgWr0` whose `Length` field is not
931:### 9.6 Latency contract, and the `D_WR` write-path constant
936:  readable from cycle `t + D_WR` onward (`t_commit`), with `D_WR` as defined below.
937:  The write is *taken* at cycle `t`; it becomes *visible* at `t + D_WR`.
945:| `t_beat` | The cycle on which the payload DWORD of a BAR0 write transfers on `rx_tlp_*`, i.e. `rx_tlp_valid` and `rx_tlp_ready` are both 1 for that beat. Externally observable. |
946:| `t_start` | **Identical to `t_beat`** for a write that carries `CTRL.START`. This is the cycle REQ-074 an

… [truncated, 4,318 more chars]
```

</details>


## 71. Agent

<details><summary>reasoning</summary>



</details>


## 72. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/spec.md",
  "offset": 730,
  "limit": 20
}
```


## 73. Prompt / Result

<details><summary>output</summary>

```
730	  shall be answered with a UR Completion and shall **not** set
731	  `STATUS.ERR_UNSUP_REQ` (this happens on every bus scan and is not an error).
732	- **REQ-043** An inbound `Cpl`/`CplD` shall be discarded with no error bit set and no
733	  Completion emitted.
734	- **REQ-044** An `MRd` or `MWr` that would cross the end of the BAR0 window
735	  (`offset + Length*4 > 16384`) shall be treated as not matching BAR0 (REQ-038 /
736	  REQ-039).
737	- **REQ-126** *(new in v1.1.2.)* A `CfgRd0` or `CfgWr0` whose `Length` field is not
738	  exactly 1 is malformed (§7.2.3; PCIe Base r6.0 §2.2.7 fixes Configuration Requests
739	  at one DWORD). The DUT shall:
740	  (a) answer it with a `Cpl` carrying UR status, formatted per REQ-035 — at
741	  `cfg_completer_id` = `0x0000` this is `DW0 = 0x0A000000`, `DW1 = 0x00002004`,
742	  `DW2` per §7.2.4, three beats total;
743	  (b) modify no configuration register;
744	  (c) for a `CfgWr0`, consume and discard all surplus payload DWORDs through
745	  `rx_tlp_eop`, so that framing is preserved and the next TLP is parsed correctly; and
746	  (d) set `STATUS.ERR_UNSUP_REQ`.
747	  This applies regardless of Device and Function number; the REQ-042 carve-out, which
748	  exists only because routine bus scans probe absent devices, does **not** extend to a
749	  malformed `Length`.
```

</details>


## 74. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/spec.md",
  "offset": 940,
  "limit": 30
}
```


## 75. Prompt / Result

<details><summary>output</summary>

```
940	loosely and ended up with two incompatible readings of `t_start`. The following three
941	names are now the only ones used anywhere in this specification:
942	
943	| Name | Definition |
944	|------|------------|
945	| `t_beat` | The cycle on which the payload DWORD of a BAR0 write transfers on `rx_tlp_*`, i.e. `rx_tlp_valid` and `rx_tlp_ready` are both 1 for that beat. Externally observable. |
946	| `t_start` | **Identical to `t_beat`** for a write that carries `CTRL.START`. This is the cycle REQ-074 and REQ-101 measure `4*N + 2` from. "Accepted by `reg_file`" in REQ-074 means *this* cycle — the cycle the write is taken in, **not** the cycle its effect becomes readable. |
947	| `t_commit` | The cycle on which the addressed register or storage location holds the new value, i.e. the first cycle a read would return it. `t_commit = t_beat + D_WR`. |
948	
949	**Definition — `D_WR` = `t_commit - t_beat`.** `D_WR` is a property of the
950	implementation's write path, not a free parameter of each access. Its measured value
951	in the v1 RTL is **1**.
952	
953	`D_WR` describes when a write becomes *visible*. It is deliberately **not** a term in
954	any operation-latency formula: REQ-074, REQ-101 and REQ-123 all measure from `t_beat`,
955	so adding `D_WR` to them would double-count the write path. That double-count was the
956	v1.1.0 defect.
957	
958	- **REQ-122** *(new in v1.1.0.)* `D_WR` shall be a single fixed constant of the
959	  implementation: identical for every BAR0 write regardless of target region
960	  (`reg_file`, `mem_a`, `mem_b`, `mem_c`), regardless of the DWORD's position within
961	  a burst, regardless of Byte Enables, and independent of `N`. Its value shall lie in
962	  the range 1 to 3 inclusive. It may be measured once at the chip boundary — write
963	  `SCRATCH`, then read it back on successive cycles — and reused for every other
964	  timing check.
965	- **REQ-123** *(new in v1.1.0; corrected in v1.1.1.)* Given a `CTRL` write whose
966	  payload DWORD has bit 0 (`START`) set and transfers on `rx_tlp_*` at cycle `t_beat`,
967	  and given that `STATUS.BUSY` was 0 at `t_beat`, `STATUS.DONE` shall be set at
968	  exactly cycle `t_beat + 4*N + 2`, provided neither `rx_tlp_*` nor `tx_tlp_*` stalls
969	  in that interval. This is the boundary-observable form of REQ-101: `t_start` is
```

</details>


## 76. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/docs/spec.md",
  "offset": 1044,
  "limit": 25
}
```


## 77. Prompt / Result

<details><summary>output</summary>

```
1044	  where this happens while `STATUS.BUSY == 1`.
1045	- **REQ-073** A `CTRL` write shall take effect only for bytes whose Byte Enable is 1;
1046	  `CTRL.START` and `CTRL.SOFT_RESET` are in byte 0, so `First BE[0]` must be 1 for
1047	  them to act.
1048	- **REQ-124** *(new in v1.1.0.)* If `START` and `SOFT_RESET` are both written 1 in the
1049	  same DWORD **while `STATUS.BUSY == 1`**, `SOFT_RESET` shall take effect in full per
1050	  REQ-071, the `START` shall be ignored entirely, and `STATUS.ERR_START_BUSY` shall
1051	  **not** be left set. (Whether the RTL suppresses the error at the source or sets it
1052	  and has REQ-071's clear override it in the same cycle is not observable and is not
1053	  constrained; the observable requirement is that `STATUS.ERR_START_BUSY` reads 0
1054	  afterwards.)
1055	- **REQ-125** *(new in v1.1.0.)* `CTRL.SOFT_RESET` asserted while `mm_ctrl` is in the
1056	  `DRAIN` state shall abort the drain immediately. Words of `mem_c` already written by
1057	  the drain retain their newly written values; words not yet reached retain whatever
1058	  they held before the operation. `mem_c` is therefore left in a **defined but mixed**
1059	  state: every word holds either its pre-operation value or its correct new value, and
1060	  no word holds an otherwise-undefined value. Software must treat C as invalid after a
1061	  mid-operation `SOFT_RESET` and must re-run the operation.
1062	
1063	> **Why REQ-125 exists.** v1.0.0's REQ-071 said `SOFT_RESET` "leaves `mem_c`
1064	> unchanged". That is unmappable to hardware if `SOFT_RESET` lands mid-`DRAIN`: the
1065	> rows the drain has already committed are already written, and unwinding them would
1066	> require shadow storage that this design deliberately does not have. REQ-071's
1067	> `mem_c` clause has been narrowed to "`SOFT_RESET` does not itself modify `mem_c`",
1068	> and REQ-125 now states the guarantee that is actually achievable and testable.
```

</details>


## 78. Agent

<details><summary>reasoning</summary>



</details>


## 79. Agent

**Grep**

```json
{
  "pattern": "rst\\) begin|tx_tlp_data  = |tx_tlp_data = |Implements:|rdata_last|unused",
  "path": "/home/pgratz/pcie-matmul/rtl",
  "output_mode": "content",
  "-n": true,
  "-C": 1,
  "glob": "*.sv",
  "head_limit": 150
}
```


## 80. Prompt / Result

<details><summary>output</summary>

```
rtl/mm_ctrl.sv-41-//
rtl/mm_ctrl.sv:42:// Implements: REQ-069, REQ-071, REQ-074, REQ-082, REQ-095, REQ-096, REQ-098,
rtl/mm_ctrl.sv-43-//             REQ-099, REQ-101, REQ-102, REQ-103, REQ-104,
--
rtl/mm_ctrl.sv-114-    always_ff @(posedge clk) begin
rtl/mm_ctrl.sv:115:        if (rst) begin
rtl/mm_ctrl.sv-116-            state   <= ST_IDLE;
--
rtl/mm_ctrl.sv-205-    always_ff @(posedge clk) begin
rtl/mm_ctrl.sv:206:        if (rst) begin
rtl/mm_ctrl.sv-207-            v_west <= '0;
--
rtl/pcie_cfg_space.sv-28-//
rtl/pcie_cfg_space.sv:29:// Implements: REQ-045 ... REQ-054, REQ-112, REQ-115, REQ-121.
rtl/pcie_cfg_space.sv-30-// ---------------------------------------------------------------------------
--
rtl/pcie_cfg_space.sv-74-    always_ff @(posedge clk) begin
rtl/pcie_cfg_space.sv:75:        if (rst) begin
rtl/pcie_cfg_space.sv-76-            cmd        <= 3'b000;
--
rtl/app_bar0.sv-23-//   rdata_*  : read payload, req_len beats, ascending addresses. There is no
rtl/app_bar0.sv:24://              rdata_last: tlp_tx counts payload beats from the Completion
rtl/app_bar0.sv-25-//              Length field (removed from spec 7.3's table in v1.1.0).
--
rtl/app_bar0.sv-34-//
rtl/app_bar0.sv:35:// Implements: REQ-055 ... REQ-064, and hosts REQ-065 ... REQ-092.
rtl/app_bar0.sv-36-// ---------------------------------------------------------------------------
--
rtl/app_bar0.sv-171-    always_ff @(posedge clk) begin
rtl/app_bar0.sv:172:        if (rst) begin
rtl/app_bar0.sv-173-            state     <= S_IDLE;
--
rtl/mem_b.sv-24-//
rtl/mem_b.sv:25:// Implements: REQ-087, REQ-088, REQ-059, REQ-060, REQ-061, REQ-111.
rtl/mem_b.sv-26-// ---------------------------------------------------------------------------
--
rtl/mem_b.sv-74-    always_ff @(posedge clk) begin
rtl/mem_b.sv:75:        if (rst) begin
rtl/mem_b.sv-76-            mem <= '0;
--
rtl/mem_b.sv-94-            always_ff @(posedge clk) begin
rtl/mem_b.sv:95:                if (rst) begin
rtl/mem_b.sv-96-                    e_rdata[gi*DW +: DW] <= '0;
--
rtl/mm_array.sv-27-//
rtl/mm_array.sv:28:// Implements: REQ-096, REQ-097, REQ-098, REQ-099, REQ-100.
rtl/mm_array.sv-29-// ---------------------------------------------------------------------------
--
rtl/reg_file.sv-29-//
rtl/reg_file.sv:30:// Implements: REQ-012, REQ-064, REQ-065 ... REQ-084, REQ-101 ... REQ-104,
rtl/reg_file.sv-31-//             REQ-111, REQ-114,
--
rtl/reg_file.sv-128-    always_ff @(posedge clk) begin
rtl/reg_file.sv:129:        if 

… [truncated, 3,711 more chars]
```

</details>


## 81. Agent

<details><summary>reasoning</summary>



</details>


## 82. Agent

**Grep**

```json
{
  "pattern": "REQ-1(09|10|16|17|18|19|20|22|23|24|25|26)|REQ-00[245]",
  "path": "/home/pgratz/pcie-matmul/rtl",
  "output_mode": "content",
  "-n": true,
  "glob": "*.sv"
}
```


## 83. Prompt / Result

<details><summary>output</summary>

```
rtl/mm_ctrl.sv:44://             REQ-125 (soft_reset is honoured in every state including DRAIN:
rtl/tlp_rx.sv:36:// Implements: REQ-002 (rx_tlp_ready may be held low for an unbounded number of
rtl/tlp_rx.sv:38://             beat is lost), REQ-005 (idle and stall cycles may fall anywhere
rtl/reg_file.sv:32://             REQ-124 (a CTRL write with both bit 1 and bit 0 set drives
rtl/tlp_tx.sv:31:// Implements: REQ-002 (an unbounded tx_tlp_ready-low stall only holds the FSM
rtl/tlp_tx.sv:32://             in its current beat), REQ-004 (sop is asserted only in T_DW0 and
rtl/tlp_tx.sv:34://             and the two are never coincident), REQ-005 (stall cycles may fall
rtl/matmul_top.sv:32://   REQ-109 - every flop in the tree uses the same synchronous reset, so holding
rtl/matmul_top.sv:34://   REQ-110 - no `initial` block, no `#` delay and no `$display` appears
rtl/matmul_top.sv:38://   REQ-116 - the spec 15 operating sequence completes with no UR and no error
rtl/matmul_top.sv:40://   REQ-117 - back-to-back operations: mm_ctrl asserts clr_acc in PRIME on every
rtl/matmul_top.sv:42://   REQ-118 - an all-zero A and B still runs the full 4N+2 sequence and sets DONE.
rtl/matmul_top.sv:43://   REQ-119 - A/B loaded by maximal MWr bursts or by single-DWORD writes are
rtl/matmul_top.sv:46://   REQ-120 - C read by maximal MRd bursts or by single-DWORD reads is identical
rtl/matmul_top.sv:48://   REQ-122 - D_WR = 1 for every BAR0 write: the write strobe into reg_file /
```

</details>


## 84. Agent

<details><summary>reasoning</summary>



</details>


## 85. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/tlp_rx.sv",
  "offset": 36,
  "limit": 18
}
```


## 86. Prompt / Result

<details><summary>output</summary>

```
36	// Implements: REQ-002 (rx_tlp_ready may be held low for an unbounded number of
37	//             cycles - it is low for the whole service+completion window and no
38	//             beat is lost), REQ-005 (idle and stall cycles may fall anywhere
39	//             inside a TLP; the framing FSM only advances on valid && ready),
40	//             REQ-008, REQ-013 ... REQ-022, REQ-028 ... REQ-032,
41	//             REQ-036 ... REQ-044, REQ-050, REQ-052, REQ-053, REQ-054.
42	// ---------------------------------------------------------------------------
43	module tlp_rx (
44	    // Clock and reset
45	    input  logic         clk,
46	    input  logic         rst,
47	
48	    // Inbound TLP stream (chip boundary)
49	    input  logic [31:0]  rx_tlp_data,
50	    input  logic         rx_tlp_sop,
51	    input  logic         rx_tlp_eop,
52	    input  logic         rx_tlp_valid,
53	    output logic         rx_tlp_ready,
```

</details>


## 87. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/matmul_top.sv",
  "offset": 28,
  "limit": 30
}
```


## 88. Prompt / Result

<details><summary>output</summary>

```
28	// Implements: REQ-010, REQ-011, REQ-012, REQ-107, REQ-113.
29	//
30	// Whole-tree properties asserted at this level because no single submodule owns
31	// them:
32	//   REQ-109 - every flop in the tree uses the same synchronous reset, so holding
33	//             rst for >= 2 clk cycles reaches the spec 13.4 reset state.
34	//   REQ-110 - no `initial` block, no `#` delay and no `$display` appears
35	//             anywhere under rtl/; all reset values come from `rst`.
36	// System-level behaviours that emerge from the wiring below rather than from any
37	// one module, and are verified end to end at the chip boundary:
38	//   REQ-116 - the spec 15 operating sequence completes with no UR and no error
39	//             bit set.
40	//   REQ-117 - back-to-back operations: mm_ctrl asserts clr_acc in PRIME on every
41	//             START, so no accumulator residue survives into the next operation.
42	//   REQ-118 - an all-zero A and B still runs the full 4N+2 sequence and sets DONE.
43	//   REQ-119 - A/B loaded by maximal MWr bursts or by single-DWORD writes are
44	//             identical: app_bar0 decodes every DWORD of a burst from its own
45	//             address and applies Byte Enables per beat.
46	//   REQ-120 - C read by maximal MRd bursts or by single-DWORD reads is identical
47	//             for the same reason on the read path.
48	//   REQ-122 - D_WR = 1 for every BAR0 write: the write strobe into reg_file /
49	//             mem_a / mem_b / mem_c is combinational from the accepted payload
50	//             beat, so storage always commits on the edge that ends that beat,
51	//             independently of region, burst position, Byte Enables and N.
52	// ---------------------------------------------------------------------------
53	module matmul_top #(
54	    parameter int N    = 8,     // systolic array dimension; power of two, 2..32
55	    parameter int DW   = 8,     // operand width in bits; 8 in v1
56	    parameter int ACCW = 32,    // accumulator width in bits; 32 in v1
57	    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)   // derived, do not override
```

</details>


## 89. Agent

<details><summary>reasoning</summary>



</details>


## 90. Agent

**Read**

```json
{
  "file_path": "/home/pgratz/pcie-matmul/rtl/app_bar0.sv",
  "offset": 100,
  "limit": 50
}
```


## 91. Prompt / Result

<details><summary>output</summary>

```
100	    logic [13:0] cur_addr;
101	    logic [5:0]  beat_cnt;
102	    logic [5:0]  len_r;
103	    logic [3:0]  fbe_r;
104	    logic [3:0]  lbe_r;
105	
106	    logic [31:0] rd_data_r;
107	    logic        rd_v;
108	    logic        rd_last_r;
109	
110	    logic [1:0]  region;
111	    logic [9:0]  dw_index;
112	
113	    assign region   = cur_addr[13:12];
114	    assign dw_index = cur_addr[11:2];
115	
116	    assign req_ready   = (state == S_IDLE);
117	    assign wdata_ready = (state == S_WR);
118	    assign rdata_valid = rd_v;
119	    assign rdata       = rd_data_r;
120	
121	    // ---- byte enables for the current burst beat -------------------------
122	    logic       last_beat;
123	    logic [3:0] m_first;
124	    logic [3:0] m_last;
125	    logic [3:0] be_now;
126	
127	    assign last_beat = (beat_cnt == (len_r - 6'd1));
128	    assign m_first   = (beat_cnt == 6'd0) ? fbe_r : 4'b1111;
129	    assign m_last    = last_beat ? ((len_r == 6'd1) ? fbe_r : lbe_r) : 4'b1111;
130	    assign be_now    = m_first & m_last;
131	
132	    // ---- write strobes ---------------------------------------------------
133	    logic wr_beat;
134	    logic reg_wr;
135	    logic a_wr;
136	    logic b_wr;
137	    logic c_wr;
138	    logic ev_write_busy;
139	
140	    assign wr_beat       = (state == S_WR) && wdata_valid;
141	    assign reg_wr        = wr_beat && (region == 2'b00);
142	    assign a_wr          = wr_beat && (region == 2'b01) && !eng_busy;
143	    assign b_wr          = wr_beat && (region == 2'b10) && !eng_busy;
144	    assign c_wr          = wr_beat && (region == 2'b11) && !eng_busy;
145	    assign ev_write_busy = wr_beat && (region != 2'b00) && eng_busy;
146	
147	    // ---- read data mux ---------------------------------------------------
148	    logic [31:0] reg_rdata;
149	    logic [31:0] a_rdata;
```

</details>


## 92. Agent

<details><summary>reasoning</summary>



</details>


## 93. Agent

# Phase 2b RTL Review — Round 2 (deltas only) — `rtl/` v. `docs/spec.md` 1.1.2

## Blocking

**None.** All six round-1 items are correctly actioned, the `mem_c` reset rewrite is exhaustively correct at every legal `N`, and the `cfg_len_ok` reasoning holds as claimed. Nothing in the rework disturbs anything I verified clean in round 1.

## Should fix

1. **`rtl/mem_c.sv:92-94` — the +1,178 cell delta is most plausibly here, not in `cfg_len_ok`.** The loop index is `ri[BOW-1:0] * BOW'(N*ACCW)` where `ri` is a module-scope `integer` (`mem_c.sv:81`). That is a *sized arithmetic expression on a variable*, which is exactly the form that discourages constant folding; if Yosys does not fold it, the reset branch synthesises a second variable-offset row-write decoder alongside the existing `d_boff` one at `mem_c.sv:96`. At N=8 that decoder spans 8 rows × 256 bits — the right order of magnitude for ~1,200 combinational cells at unchanged flop count. The alternative explanations do not add up: `cfg_len_ok` is one 10-bit equality (~10 cells) and the deleted sinks were already dead-code-eliminated. Diagnostic: `yosys -p "read_verilog -sv $(cat rtl/filelist.f); hierarchy -top matmul_top; synth; select mem_c; stat"`. Fix, behaviour-identical: declare the variable in the block and drop the casts — `for (int ri = 0; ri < NROW; ri++) mem[ri*N*ACCW +: N*ACCW] <= '0;` — which elaborates to `NROW` constant part-selects. Area only; forward to the Phase 4 brief if not taken now.
2. **REQ-126 and REQ-123 are claimed by no module header.** `tlp_rx.sv:36-41` implements REQ-126 at `tlp_rx.sv:198,221` but does not claim it; `matmul_top.sv:48` claims REQ-122 but not its companion REQ-123 (which `mm_ctrl`/`reg_file` jointly satisfy). Item 6 of the rework added 13 claims and missed the two newest. Comment-only.
3. **`rtl/mm_array.sv:61-65`** — the `UNUSEDSIGNAL` suppression wraps the whole `a_o`/`b_o`/`v_o` declarations, not just the edge bits that are unread by construction. A future mis-index of the chain at `mm_array.sv:82-83,90-91` would no longer be caught by lint. Verilator offers no narrower scope, so accept it, but the loss of coverage on those three vectors is real and should be recorded.

## Coverage gaps

- **REQ-042 vs REQ-126 textual overlap** (`docs/spec.md:729-731` vs `:737-749`). REQ-042's antecedent — "a `CfgRd0`/`CfgWr0` whose Device or Function Number is non-zero" — still literally matches a malformed-`Length` request to a non-zero device and forbids `ERR_UNSUP_REQ`, while REQ-126 requires it. REQ-126's closing sentence asserts precedence and the RTL follows REQ-126, so behaviour is unambiguous; but REQ-042's own text was not amended. → spec-writer: add "with `Length` == 1" to REQ-042's antecedent.
- **`rtl/mem_c.sv:79`** — `NROW = (1<<WIW)/N` is an exact tiling only because `N` is a power of two, so `1<<$clog2(N*N) == N*N`. Guaranteed by §14, but the code carries no note; a non-power-of-two `N` would leave the tail of `mem` unreset with no lint or test failure. → rtl-designer: one-line comment, optional.

## Verified clean

- **`mem_c` reset coverage (item 1) — exhaustive, no off-by-one.** Because `N` is a power of two, `1<<WIW == NW == N*N` exactly, so `NROW == N` and the `N` fills of `N*ACCW` bits tile `MEMBITS` with no gap and no overlap. Checked every legal `N`: N=2 → MEMBITS 128, NROW 2, row 64 b, last fill 64+64=128; N=4 → 512, 4, 128 b, 384+128=512; N=8 → 2048, 8, 256 b, 1792+256=2048; N=16 → 8192, 16, 512 b, 7680+512=8192; N=32 → 32768, 32, 1024 b, 31744+1024=32768. `BOW` (7/9/11/13/15) never truncates the offset product at any `N`. Every word of `mem_c` is cleared; §13.4 and REQ-092 hold.
- **`cfg_len_ok` (item 3) — the structural claim is correct, verified independently.** A config TLP with `Length != 1` fails the guard at `tlp_rx.sv:221`, then fails `is_mem && fmt_3dw` at `:225` (`ttype == 5'b00100`), and lands on the terminal `else` at `:229`. There `posted = is_msg || ((is_mem||is_io) && fmt_wr)` is 0 for `ttype == 00100` on all three terms, so it resolves to `CLS_UR_ERR`, and `ev_unsup_req` at `:233` pulses on exactly that class — REQ-126(a) and (d). `cfg_req_valid` is asserted only in `S_CFGACC`, which is unreachable from `CLS_UR_ERR`, so no config register is touched and `cid` is not captured — REQ-126(b), consistent with REQ-052's "accepted" wording. The devfn test is inside the accepted branch, so the REQ-042 carve-out is bypassed as REQ-126 requires. Drain: `after_hdr` sends a `CfgWr0` (payload present, so no `eop` on DW2) to `S_DRAIN`, which holds `rx_tlp_ready` high and consumes to `eop` before `S_CPL` — REQ-126(c), no desynchronisation; a `CfgRd0` with bad `Length` has `eop` on DW2 and goes straight to `S_CPL`. Checked `Length` = 0 (1024 DW) and `Length` = 1023: both drain correctly. The UR header matches REQ-126's worked example bit-for-bit: `tlp_tx.sv:101-115` yields DW0 `0x0A000000` (Fmt 000/Type 01010, Length 0) and DW1 `0x00002004` (CID 0, Status 001, BCM 0, Byte Count 4).
- **REQ-122 (`D_WR` = 1, invariant).** All four region strobes (`app_bar0.sv:141-144`) are combinational from the accepted payload beat and commit on the edge ending it, so `t_commit = t_beat + 1` regardless of region, burst position, Byte Enables or `N`. The one path that could have made it region-dependent — `mem_c`'s drain-over-host priority at `mem_c.sv:95-97` — cannot drop a host write, because `c_wr` is gated `&& !eng_busy` and `d_wr_en` only asserts while busy.
- **REQ-123 (`t_beat + 4N + 2`, no `D_WR` term).** `reg_file.sv:112` drives `start` combinationally from the write beat, so `t_start == t_beat`; `mm_ctrl` enters `PRIME` on the edge ending `t_beat`, `done_set` asserts on the last `DRAIN` cycle `t_beat+4N+1`, and `STATUS.DONE` reads 1 during `t_beat+4N+2` (34 at N=8). `PERF_CYCLES` independently latches `cyc_cnt+1 = 4N+2`. Agrees with REQ-074/101 with no double-count.
- **REQ-124.** `reg_file.sv:115` suppresses `start_while_busy` at source when bit 1 is also set; `ERR_START_BUSY` reads 0 afterwards, and `soft_reset` takes full effect. Matches REQ-124's "not observable / not constrained" framing.
- **REQ-125.** `clr_acc = (state == ST_PRIME) || soft_reset` (`mm_ctrl.sv:214`) and `c_wr_en = (state == ST_DRAIN)` mean the row in flight on the `soft_reset` cycle still commits, with the correct `acc_south` value (the PE clear happens on the same edge but `acc_out` is the pre-edge register). Rows are written whole, so every `mem_c` word holds either its pre-operation value or its correct new value — never a partial or undefined one.
- **`tlp_tx.sv:160-163`** — `tx_tlp_data` now forced to `32'h0` under `rst` alongside sop/eop/valid; §13.4 reset row satisfied. No latch introduced (all four outputs still have unconditional defaults at `:132-135`).
- **Port removal (item 5)** — `rdata_last` gone from `app_bar0`'s port list; `rd_last_r` retained internally (`app_bar0.sv:108`) and still drives the `S_RD` exit, so the read burst still terminates correctly. `matmul_top` has no sink net left, restoring strict REQ-011.
- **Suppressions (item 2)** are as narrow as described: `mm_array.sv:61-65`, `tlp_rx.sv:139-142`, `pcie_cfg_space.sv:43-45` each wrap declarations only, each has a one-line justification, and each covers a signal that is genuinely unread by construction — `dw0_r`/`dw2_r`'s ignored header bits are the §7.2.1/7.2.2 don't-cares, and `req_wdata[13:8]` lands on RO-0 config fields. None hides a signal that should be driving something.
