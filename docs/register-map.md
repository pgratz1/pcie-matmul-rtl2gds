# BAR0 Register Map — PCIe-Attached Matrix Multiplier

**Version: 1.1.3 — matches `docs/spec.md` v1.1.3**
**Date: 2026-09-10**
**Owner: spec-writer**

This file and `docs/spec.md` are two views of one source of truth. Every register
listed here appears in `docs/spec.md` §10; every register in `docs/spec.md` §10
appears here. If they ever disagree, that is a bug — report it to spec-writer, do not
guess.

Conventions used below:

| Access | Meaning |
|--------|---------|
| `RO` | Read-only. Writes are accepted (Successful Completion) and change nothing. |
| `RW` | Read-write. Byte-granular: a byte is written only if its Byte Enable is 1. |
| `W1C` | Read-write-1-to-clear. Writing 1 to a set bit clears it; writing 0 leaves it unchanged. Only acts if the Byte Enable covering the bit is 1. |
| `WO` | Write-only, self-clearing. Reads return 0. The bit acts on the cycle it is written and does not persist. |
| `RAZ/WI` | Read as zero, write ignored. |

All accesses are 32-bit DWORDs. All offsets are byte offsets from the base address
programmed into BAR0 of the PCI configuration space.

`N` is the compile-time array dimension (8 in the v1 build). `DW` = 8 (operand width
in bits). `ACCW` = 32 (accumulator width in bits).

---

## 1. BAR0 aperture

BAR0 is a **32-bit, non-prefetchable, memory** BAR of **16384 bytes (16 KiB)**. Its
size is independent of `N`. Sizing readback (write `0xFFFFFFFF`, read back) is
`0xFFFFC000`.

| Offset range | Region | Description |
|--------------|--------|-------------|
| `0x0000` – `0x0FFF` | Register block | §2 below |
| `0x1000` – `0x1FFF` | Matrix A | `N*N` signed bytes. Byte at `0x1000 + (i*N + k)` is `A[i][k]`. Offsets `>= 0x1000 + N*N` are RAZ/WI. |
| `0x2000` – `0x2FFF` | Matrix B | `N*N` signed bytes. Byte at `0x2000 + (k*N + j)` is `B[k][j]`. Offsets `>= 0x2000 + N*N` are RAZ/WI. |
| `0x3000` – `0x3FFF` | Matrix C | `N*N` signed 32-bit words. Word at `0x3000 + 4*(i*N + j)` is `C[i][j]`. Offsets `>= 0x3000 + 4*N*N` are RAZ/WI. |

For `N = 8`: A = `0x1000`–`0x103F` (64 B), B = `0x2000`–`0x203F` (64 B),
C = `0x3000`–`0x30FF` (256 B).

Any offset inside the 16 KiB aperture that is not an implemented register or storage
location is **RAZ/WI** and completes with **Successful Completion**, not
Unsupported Request.

---

## 2. Register block summary

| Offset | Name | Width | Access | Reset value |
|--------|------|-------|--------|-------------|
| `0x0000` | `ID` | 32 | RO | `0x4D415431` |
| `0x0004` | `VERSION` | 32 | RO | `0x00010000` |
| `0x0008` | `CONFIG` | 32 | RO | `0x00200808` (for `N=8, DW=8, ACCW=32`) |
| `0x000C` | `CTRL` | 32 | WO (self-clearing) | reads `0x00000000` |
| `0x0010` | `STATUS` | 32 | mixed RO / W1C | `0x00000000` |
| `0x0014` | `IRQ_ENABLE` | 32 | RW | `0x00000000` |
| `0x0018` | `IRQ_STATUS` | 32 | RO | `0x00000000` |
| `0x001C` | `PERF_CYCLES` | 32 | RO | `0x00000000` |
| `0x0020` | `SCRATCH` | 32 | RW | `0x00000000` |
| `0x0024` | `OP_COUNT` | 32 | RO | `0x00000000` |
| `0x0028` – `0x0FFF` | reserved | — | RAZ/WI | `0x00000000` |

---

## 3. Register detail

### 3.1 `ID` — 0x0000 — RO — reset `0x4D415431`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:0 | `MAGIC` | RO | `0x4D415431` | Fixed identifier, ASCII `"MAT1"` (`0x4D`='M', `0x41`='A', `0x54`='T', `0x31`='1'). A host reading this value has correctly located BAR0. Never changes. |

Spec cross-reference: REQ-065.

### 3.2 `VERSION` — 0x0004 — RO — reset `0x00010000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:24 | — | RO | `0x00` | Reserved, reads 0. |
| 23:16 | `MAJOR` | RO | `0x01` | Specification major version. |
| 15:8 | `MINOR` | RO | `0x00` | Specification minor version. |
| 7:0 | `PATCH` | RO | `0x00` | Specification patch version. |

Spec cross-reference: REQ-066.

### 3.3 `CONFIG` — 0x0008 — RO — reset `0x00200808` for the v1 build

Reports the compile-time parameters so tests can discover them at run time instead
of hard-coding them.

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:24 | — | RO | `0x00` | Reserved, reads 0. |
| 23:16 | `ACC_BITS` | RO | `0x20` (32) | Accumulator width in bits (`ACCW`). |
| 15:8 | `OP_BITS` | RO | `0x08` (8) | Operand width in bits (`DW`). |
| 7:0 | `ARRAY_N` | RO | `0x08` (8) | Systolic array dimension `N`. |

Spec cross-reference: REQ-067, REQ-114.

### 3.4 `CTRL` — 0x000C — WO, self-clearing — always reads `0x00000000`

Bits act on the cycle the write DWORD is applied and do not persist. Both bits live
in byte 0, so a write only has effect if `First BE[0]` = 1.

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:2 | — | WO | — | Reserved. Writes ignored. |
| 1 | `SOFT_RESET` | WO | — | Writing 1 returns `mm_ctrl` to IDLE, clears `STATUS.BUSY`, `STATUS.DONE`, all `STATUS` error bits, `PERF_CYCLES`, and all PE accumulators, within 2 clock cycles. Leaves matrices A and B, `SCRATCH`, `IRQ_ENABLE`, `OP_COUNT` and the entire PCI configuration space (including BAR0) unchanged, and does not itself modify C. Takes precedence over `START` if both are written 1 in the same DWORD, including while `STATUS.BUSY` = 1, in which case `START` is ignored entirely and `STATUS.ERR_START_BUSY` reads 0 afterwards. **If `SOFT_RESET` lands mid-drain, C is left in a defined but mixed state: every word holds either its pre-operation value or its correct new value. Software must treat C as invalid and re-run the operation.** |
| 0 | `START` | WO | — | Writing 1 while `STATUS.BUSY` = 0 starts one `C = A x B` operation: `STATUS.BUSY` sets, `STATUS.DONE` clears, all PE accumulators clear to 0. Writing 1 while `STATUS.BUSY` = 1 has no effect on the running operation and sets `STATUS.ERR_START_BUSY`. |

Spec cross-reference: REQ-068 … REQ-073, REQ-124, REQ-125.

### 3.5 `STATUS` — 0x0010 — mixed — reset `0x00000000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:5 | — | RO | 0 | Reserved. Reads 0, writes ignored. |
| 4 | `ERR_UNSUP_REQ` | W1C | 0 | Set when the device receives an Unsupported Request: a Memory Read/Write that misses BAR0 or arrives with `Command.MSE` = 0, an `MRd`/`MWr` longer than 32 DW, a 64-bit-address or I/O or atomic or Message or Type 1 config request, a Type 0 config request whose `Length` is not 1 (spec REQ-126), or any TLP with `TD` = 1 or `EP` = 1. **Not** set by a Type 0 config request to a non-zero Device or Function number (which happens on every bus scan). |
| 3 | `ERR_WRITE_BUSY` | W1C | 0 | Set when a host write targets region A, B or C while `STATUS.BUSY` = 1. The write is discarded. |
| 2 | `ERR_START_BUSY` | W1C | 0 | Set when `CTRL.START` is written 1, **and `CTRL.SOFT_RESET` is written 0 in the same DWORD**, while `STATUS.BUSY` = 1. The running operation is unaffected. If both bits are written 1, `SOFT_RESET` wins and this bit reads 0 afterwards (spec REQ-124). |
| 1 | `DONE` | W1C | 0 | Set on the cycle the operation completes, `4*N + 2` cycles after `CTRL.START` was accepted. Persists until written with 1, or until `CTRL.SOFT_RESET` or `rst`. |
| 0 | `BUSY` | RO | 0 | 1 while an operation is in progress: reads 1 on every cycle from the cycle after `START` is accepted through the cycle on which `DONE` is set, and 0 otherwise. |

Behaviour of the W1C bits:

- A bit clears only if the write data has that bit = 1 **and** the Byte Enable
  covering that bit position is 1. Writing 0 to a W1C bit leaves it unchanged.
- If a bit's set condition and a clearing write land on the same clock edge, the
  **set** wins and the bit remains 1.

Spec cross-reference: REQ-074 … REQ-078, and REQ-038 … REQ-042, REQ-062, REQ-070.

### 3.6 `IRQ_ENABLE` — 0x0014 — RW — reset `0x00000000`

Bit positions mirror `STATUS` exactly.

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:5 | — | RO | 0 | Reserved. Reads 0, writes ignored. |
| 4 | `ERR_UNSUP_REQ_EN` | RW | 0 | 1 = `STATUS.ERR_UNSUP_REQ` contributes to `irq`. |
| 3 | `ERR_WRITE_BUSY_EN` | RW | 0 | 1 = `STATUS.ERR_WRITE_BUSY` contributes to `irq`. |
| 2 | `ERR_START_BUSY_EN` | RW | 0 | 1 = `STATUS.ERR_START_BUSY` contributes to `irq`. |
| 1 | `DONE_EN` | RW | 0 | 1 = `STATUS.DONE` contributes to `irq`. |
| 0 | — | RO | 0 | Reserved. There is no interrupt source for `STATUS.BUSY`. Reads 0, writes ignored. |

Spec cross-reference: REQ-079 … REQ-081.

### 3.7 `IRQ_STATUS` — 0x0018 — RO — reset `0x00000000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:0 | `MASKED` | RO | `0x00000000` | Bitwise `STATUS & IRQ_ENABLE`, evaluated continuously. Writes are ignored. The top-level output `irq` is a **registered** signal that tracks `MASKED != 0` within 2 clock cycles in both directions (it cannot be exactly equal, because it is registered — see spec REQ-012 and REQ-080). |

There is **no MSI and no MSI-X**. The PCI configuration space contains no capability
list, so the host cannot enable message-signalled interrupts. Software must either
poll `STATUS` or observe the `irq` pin. See `docs/decisions.md` DEC-008.

Spec cross-reference: REQ-079, REQ-080, REQ-081, REQ-012.

### 3.8 `PERF_CYCLES` — 0x001C — RO — reset `0x00000000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:0 | `CYCLES` | RO | `0x00000000` | Number of clock cycles taken by the most recently completed operation, counted from the cycle after `CTRL.START` was accepted through the cycle on which `STATUS.DONE` was set, inclusive. Equals `4*N + 2` (34 for `N = 8`). Cleared by `rst` and by `CTRL.SOFT_RESET`. Reads `0` if no operation has completed since the last reset. |

Spec cross-reference: REQ-082, REQ-101, REQ-102, REQ-123.

### 3.9 `SCRATCH` — 0x0020 — RW — reset `0x00000000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:0 | `DATA` | RW | `0x00000000` | General-purpose read/write storage with no side effects. Supports byte-granular writes via Byte Enables. Intended as the smoke test for the BAR0 datapath and for byte-enable behaviour. Not affected by `CTRL.SOFT_RESET`. |

Spec cross-reference: REQ-083.

### 3.10 `OP_COUNT` — 0x0024 — RO — reset `0x00000000`

| Bits | Name | Access | Reset | Description |
|------|------|--------|-------|-------------|
| 31:0 | `COUNT` | RO | `0x00000000` | Number of operations completed since `rst`. Increments by 1 on each cycle that `STATUS.DONE` is set by the engine. Wraps modulo 2^32. **Not** cleared by `CTRL.SOFT_RESET`. |

Spec cross-reference: REQ-084.

---

## 4. PCI configuration space (Type 0) — for completeness

This is not BAR0 space; it is reached with `CfgRd0`/`CfgWr0` TLPs. Full description
in `docs/spec.md` §8. Reproduced here so that all host-visible state is in one file.

| Cfg offset | Name | Width | Access | Reset value |
|------------|------|-------|--------|-------------|
| `0x00` | Vendor ID | 16 | RO | `0x1234` |
| `0x02` | Device ID | 16 | RO | `0x8000` |
| `0x04` | Command | 16 | RW (bits 2:0 only) | `0x0000` |
| `0x06` | Status | 16 | RO | `0x0000` |
| `0x08` | Revision ID | 8 | RO | `0x01` |
| `0x09` | Class Code | 24 | RO | `0x120000` |
| `0x0C` | Cache Line Size | 8 | RW | `0x00` |
| `0x0D` | Latency Timer | 8 | RO | `0x00` |
| `0x0E` | Header Type | 8 | RO | `0x00` |
| `0x0F` | BIST | 8 | RO | `0x00` |
| `0x10` | BAR0 | 32 | RW bits 31:14, RO 0 bits 13:0 | `0x00000000` |
| `0x14` – `0x24` | BAR1 … BAR5 | 32 each | RO | `0x00000000` |
| `0x28` | Cardbus CIS Pointer | 32 | RO | `0x00000000` |
| `0x2C` | Subsystem Vendor ID | 16 | RO | `0x1234` |
| `0x2E` | Subsystem ID | 16 | RO | `0x0001` |
| `0x30` | Expansion ROM Base Address | 32 | RO | `0x00000000` |
| `0x34` | Capabilities Pointer | 8 | RO | `0x00` (no capability list) |
| `0x35` – `0x3B` | reserved | — | RO | `0x00` |
| `0x3C` | Interrupt Line | 8 | RW | `0x00` |
| `0x3D` | Interrupt Pin | 8 | RO | `0x00` (no INTx) |
| `0x3E` | Min Gnt | 8 | RO | `0x00` |
| `0x3F` | Max Lat | 8 | RO | `0x00` |
| `0x40` – `0xFFF` | unimplemented | — | RAZ/WI | `0x00000000` |

### 4.1 Command register bit detail (cfg 0x04)

| Bit | Name | Access | Reset | Description |
|-----|------|--------|-------|-------------|
| 15:3 | — | RO | 0 | Reads 0, writes ignored. |
| 2 | Bus Master Enable (BME) | RW | 0 | Stored and readable. Has **no effect** in v1: the device is never a requester. |
| 1 | Memory Space Enable (MSE) | RW | 0 | **Functional.** When 0, every Memory Read/Write to BAR0 is answered as an Unsupported Request and sets `STATUS.ERR_UNSUP_REQ`. Must be set to 1 before any BAR0 access. |
| 0 | I/O Space Enable (IOSE) | RW | 0 | Stored and readable. Has no effect: there are no I/O BARs. |

### 4.2 BAR0 bit detail (cfg 0x10)

| Bit | Name | Access | Reset | Description |
|-----|------|--------|-------|-------------|
| 31:14 | Base Address | RW | 0 | Upper bits of the 16 KiB-aligned base address. |
| 13:4 | — | RO | 0 | Always 0. Encodes the 16 KiB aperture during BAR sizing. |
| 3 | Prefetchable | RO | 0 | Non-prefetchable. |
| 2:1 | Type | RO | 00 | 32-bit address decoder. |
| 0 | Space Indicator | RO | 0 | Memory space. |

Sizing: write `0xFFFFFFFF`, read back `0xFFFFC000`.

Spec cross-reference: REQ-045 … REQ-054, REQ-112, REQ-115, REQ-121.
