# `rtl/` — synthesizable SystemVerilog

Implements `docs/spec.md` v1.0.0 and `docs/register-map.md` v1.0.0.
Top module: **`matmul_top`** (port list is spec §6.1, binding).

Single clock `clk`, active-high **synchronous** reset `rst`, zero clock-domain
crossings (REQ-107, REQ-108). No `initial`, no `#` delays, no `$display`,
no `interface`, no unpacked struct ports, no SRAM macros (DEC-010).

## Module hierarchy

```
matmul_top                        top: instantiation + wiring only (REQ-011)
├── pcie_tl                       transaction layer container (DEC-007 serialization)
│   ├── tlp_rx                    inbound framing, header decode, TLP classification,
│   │                             BAR0/config request dispatch, completion descriptor
│   ├── pcie_cfg_space            Type 0 config space, BAR0 decode, Completer ID capture
│   └── tlp_tx                    Cpl / CplD header build and outbound framing
├── app_bar0                      BAR0 region decode + burst sequencer + byte enables
│   ├── reg_file                  ID/VERSION/CONFIG/CTRL/STATUS/IRQ_*/PERF/SCRATCH/OP_COUNT
│   ├── mem_a                     matrix A, N*N bytes, N engine read ports (flops)
│   ├── mem_b                     matrix B, N*N bytes, N engine read ports (flops)
│   └── mem_c                     matrix C, N*N 32-bit words, N-word row write (flops)
└── matmul_engine                 engine container
    ├── mm_ctrl                   IDLE/PRIME/FETCH/COMPUTE/TURN/DRAIN/FINISH, operand
    │                             index generation, drain sequencing, PERF counter
    └── mm_array                  N x N mesh
        └── mm_pe  (N*N)          1-stage MAC PE, output-stationary (DEC-005, DEC-009)
```

## File list — compile order

`rtl/filelist.f` is the single source of truth (used by `tb/` and by the ORFS
flow in `flow/`). Order:

| # | File | One-line purpose |
|---|------|------------------|
| 1 | `mm_pe.sv` | One processing element: registers a/b/v east+south, accumulates `a*b`. |
| 2 | `mm_array.sv` | `N x N` mesh of `mm_pe`, west/north operand edges, south drain bus. |
| 3 | `mm_ctrl.sv` | Operation FSM, operand index generator, drain writes, `4N+2` cycle count. |
| 4 | `matmul_engine.sv` | Container for `mm_ctrl` + `mm_array`; wiring only. |
| 5 | `mem_a.sv` | Matrix A flop register file; host DWORD port + `N` engine byte ports. |
| 6 | `mem_b.sv` | Matrix B flop register file; host DWORD port + `N` engine byte ports. |
| 7 | `mem_c.sv` | Matrix C flop register file; host DWORD port + one-row-per-cycle drain port. |
| 8 | `reg_file.sv` | BAR0 register block 0x0000-0x0FFF, W1C status, irq generation. |
| 9 | `app_bar0.sv` | BAR0 region decode, 1..32 DWORD burst sequencer, byte enables. |
| 10 | `pcie_cfg_space.sv` | Minimal Type 0 config space, BAR0 base/MSE, Completer ID capture. |
| 11 | `tlp_rx.sv` | Inbound TLP framing/decode/classification and completion descriptor. |
| 12 | `tlp_tx.sv` | Cpl / CplD build and outbound framing. |
| 13 | `pcie_tl.sv` | Transaction-layer container; wiring only. |
| 14 | `matmul_top.sv` | Top level; wiring only. |

## Parameters

| Name | Where | v1 value | Legal | Notes |
|------|-------|----------|-------|-------|
| `N` | `matmul_top` | 8 | power of two, 2..32 | Array/matrix dimension (DEC-004). Nothing hardcodes 8. |
| `DW` | `matmul_top` | 8 | 8 in v1 | Operand width in bits. |
| `ACCW` | `matmul_top` | 32 | 32 in v1 | Accumulator width in bits. |
| `IDXW` | derived | `$clog2(N)` (min 1) | — | Operand index width. **Derived; do not override.** |

Override for a different array size with `-GN=16` (Verilator) /
`-Pmatmul_top.N=16` (Icarus) / `chparam -set N 16` (Yosys). No source edit is
needed (REQ-113).

## Latency summary

| Path | Cycles |
|------|--------|
| header DW2 accepted -> `app_req_valid` | 1 |
| BAR0 read request accepted -> first read DWORD | 2, then 1 DWORD/cycle |
| write payload DWORD accepted -> storage updated | 1 |
| `CTRL.START` accepted -> `STATUS.DONE` reads 1 | `4N+2` (34 at `N=8`) |
| `mm_pe` operand in -> operand out | 1 (fixed by DEC-009) |
| `IRQ_STATUS` change -> `irq` pin | 1 (registered output, REQ-012/REQ-081) |

## Checks

```
verilator --lint-only -Wall -Wno-DECLFILENAME --top-module matmul_top $(cat rtl/filelist.f)
yosys -p "read_verilog -sv $(cat rtl/filelist.f); hierarchy -top matmul_top; synth; stat"
```

The only lint suppression in the tree is one narrow `WIDTHCONCAT` pair around
the `mem_c` reset fill (`mem_c.sv`), which is 32768 bits wide at `N = 32` by
construction; justification is in the source.
