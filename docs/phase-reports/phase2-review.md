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
