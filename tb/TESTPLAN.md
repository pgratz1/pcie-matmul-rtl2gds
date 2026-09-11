# Test plan — PCIe-Attached Matrix Multiplier

**Against:** `docs/spec.md` **v1.1.4**, `docs/register-map.md` v1.0.0
**Owner:** test-writer · **Phase 2 deliverable, updated for spec v1.1.0 → v1.1.4
and for the five Phase 3 testbench bugs (BUG-001/002/003/005/006)**
**Status:** 72 cocotb tests + 5 static structural checks + 1 elaboration sweep.
**Coverage: 127 of 127 requirements mapped. 126 verified by test, 1 (REQ-077)
verified by review — see "Uncovered" at the bottom.**

Every expected value in this suite comes from `docs/spec.md`,
`docs/register-map.md` or `tb/models/golden.py`. No test asserts against a
value read back from the DUT earlier in the same test.

---

## 1. How to run

```
make -C tb lint                        # verilator --lint-only -Wall + structural checks
make -C tb test                        # all 65 tests
make -C tb test TEST=test_matmul       # one module
make -C tb test TEST=test_smoke::test_smoke_single_multiply
make -C tb test SEED=12345             # reproduce a randomized failure
make -C tb test N=16                   # re-elaborate with a different array size
make -C tb waves TEST=test_smoke       # dumps tb/sim_build/matmul_top.fst
make -C tb elab-sweep                  # REQ-113: elaborate for N in {2,4,8,16,32}
```

`SIM=icarus` is the default (DEC-001: cocotb 2.1.0 refuses Verilator < 5.036 and
this box has 5.032). `SIM=verilator` is wired but will be rejected by cocotb
until Verilator is upgraded; Verilator is used as the *linter* only.

**Seeding.** Every random choice derives from `$SEED`. The default is **1** and
the value in use is printed as `[tb] SEED = <n>` at the top of each test.
`make test SEED=<n>` reproduces any randomized failure exactly.

**Array size.** No test hard-codes `N`. Each reads `CONFIG[7:0]` at run time
(REQ-114) and derives `4N+2`, the A/B/C region sizes and the golden matrices
from it. The suite has been run green at `N=4`, `N=8` and `N=16`.

## 2. Files

| File | Contents |
|------|----------|
| `tb/Makefile` | `lint`, `test`, `test TEST=…`, `waves`, `elab-sweep`, `clean`; sources from `rtl/filelist.f` |
| `tb/models/tlp_stream_shim.py` | `Device` subclass per DEC-003 / spec 5.4; TLP↔DWORD framing per spec 5.3; always-on stream protocol checker |
| `tb/models/pipe_adapter.py` | Alias of the above (the brief's historical name; PIPE was removed by DEC-002) |
| `tb/models/host.py` | Root complex wrapper: `enumerate`, `mem_read/mem_write`, `cfg_read/cfg_write_dword`, raw TLP injection |
| `tb/models/golden.py` | Exact INT8×INT8→INT32 reference (spec 12.6), spec 7.5 byte-enable tables, `RegModel`, `DeviceModel` scoreboard |
| `tb/tests/tb_common.py` | Shared helpers: bring-up, `discover_n`, `run_op`, byte-enabled raw accesses |
| `tb/tests/test_smoke.py` | 4 tests |
| `tb/tests/test_regs.py` | 15 tests |
| `tb/tests/test_tlp.py` | 24 tests |
| `tb/tests/test_cfg.py` | 11 tests |
| `tb/tests/test_matmul.py` | 17 tests |
| `tb/tests/test_stress.py` | 1 test (120 randomized operations, scoreboarded) |
| `tb/tools/check_rtl_rules.py` | 5 static structural checks, run by `make lint` |

`test_dll.py` is deliberately absent: the DUT has **no DLL** (spec 1.3, 4.4 —
zero DLLPs cross the chip boundary), so there is nothing in the DUT to test.
The behavioral DLL lives in `cocotbext-pcie`'s `SimPort` and is exercised
implicitly by every test that goes through the root complex.

## 3. Always-on checks

These run inside `tb/models/tlp_stream_shim.py` on **every** test, so every
simulation in the suite is a test of them:

| Check | Requirement |
|-------|-------------|
| `tx_tlp_data/sop/eop` stable while `tx_tlp_valid && !tx_tlp_ready`; `valid` never retracted | REQ-001 |
| `tx_tlp_sop` and `tx_tlp_eop` never on the same beat | REQ-004 |
| `rx_tlp_ready`, `tx_tlp_valid/sop/eop` all 0 for every cycle `rst` is asserted | REQ-006 |
| One contiguous packet per `sop`…`eop`; no second `sop` mid-packet; no beat before `sop` | REQ-014, REQ-023 |
| Any X/Z on a DUT output is reported as a protocol error naming the signal | REQ-111 support |

---

## 4. Requirement → test map

Rows marked *(new …)* / *(reworded …)* changed in spec v1.1.0 or v1.1.1.
`static:` = `tb/tools/check_rtl_rules.py`, run by `make -C tb lint`.
`shim:` = the always-on checker of section 3.

| REQ | Test(s) | What the test checks |
|-----|---------|----------------------|
| REQ-001 | `shim:` stability checker, `test_tlp_tx_ready_held_low_no_deadlock` | `tx_tlp_*` held stable until the beat transfers; `valid` never retracted |
| REQ-002 | `test_tlp_idle_and_stall_cycles`, `test_tlp_tx_ready_held_low_no_deadlock` | 50% random stall on `tx_tlp_ready`, and 300 consecutive stall cycles, lose nothing |
| REQ-003 | `test_tlp_ready_not_combinational_on_valid` | `rx_tlp_ready` sampled before and after raising `rx_tlp_valid` *within one cycle* is unchanged |
| REQ-004 | `shim:` framing checker | `sop`+`eop` on one beat is a hard error; minimum TLP is 3 DW |
| REQ-005 | `test_tlp_idle_and_stall_cycles`, `test_tlp_back_to_back_tlps_no_idle_cycles` | 50% random idle cycles mid-TLP; and 16 TLPs with **zero** idle cycles between `eop` and the next `sop` give identical results |
| REQ-006 | `shim:` reset checker, `test_smoke_reset_state` | outputs 0 throughout `rst`; `irq` 0 after reset |
| REQ-007 | `test_tlp_tx_ready_held_low_no_deadlock` | `tx_tlp_ready` forced low 300 cycles; the completion arrives intact afterwards and the DUT still services requests |
| REQ-008 | `test_tlp_payload_endianness`, `test_tlp_mrd_completion_fields` | header DW big-endian (address decode lands on the right byte), payload DW little-endian (`11 22 33 44` round-trips in order) |
| REQ-009 | `test_tlp_payload_endianness`, `test_tlp_completion_reserved_fields_and_ids` | every outbound completion decodes with the spec 5.3 inverse mapping and its fields match the request |
| REQ-010 | `test_smoke_top_ports_exist`, `static: check_top_ports` | all 13 ports present with the spec 6.1 direction and width; **no extra top-level port** |
| REQ-011 | `static: check_top_structural` | no `always`/`function`/`case` and no logic-bearing `assign` in `matmul_top` |
| REQ-012 | `test_reg_irq_status_and_irq_pin`, `test_matmul_done_timing` | `irq` follows `\|IRQ_STATUS`, registered (1 cycle) |
| REQ-013 | `test_tlp_requests_serviced_in_order` | 6 back-to-back MRds with distinct tags complete in arrival order with the right data |
| REQ-014 | `test_tlp_requests_serviced_in_order`, `shim:` | never two completions interleaved on `tx_tlp_*` |
| REQ-015 | `test_tlp_tx_ready_held_low_no_deadlock` | service resumes correctly after backpressure is released |
| REQ-016 | `test_tlp_completion_reserved_fields_and_ids`, `test_tlp_mrd_completion_fields`, `test_tlp_payload_endianness` | Fmt/Type/Length/TC/Attr/TD/EP/ReqID/Tag/BEs/Address all extracted per spec 7.2 |
| REQ-017 | `test_tlp_malformed_length_rejected` | `Length` field 0 (= 1024 DW) → UR completion + `ERR_UNSUP_REQ` |
| REQ-018 | `test_tlp_malformed_length_rejected`, `test_tlp_oversize_write_discarded_and_framing_kept` | `Length` 33 / 64 / 1023 rejected for MRd and MWr |
| REQ-019 | `test_tlp_oversize_write_discarded_and_framing_kept` | after a rejected 33 DW MWr, the *next* TLP is parsed correctly (framing kept) |
| REQ-020 | `test_tlp_sop_resynchronisation` | a truncated 2-beat TLP followed by a fresh `sop` — the second TLP is the one that takes effect |
| REQ-021 | `test_tlp_requests_serviced_in_order`, `test_reg_write_path_delay_is_constant` | §9.6's `D_WR` closes the old observability gap: the write path's request-to-effect delay is measured exactly (1 cycle) and shown to be constant |
| REQ-022 | `test_tlp_burst_ascending_and_independent_decode` | a 32 DW MWr lands in ascending address order, exactly `Length` DWORDs |
| REQ-023 | `shim:`, `test_tlp_mrd_completion_fields` | each completion is one contiguous framed packet, 3 header DW + `Length` payload DW |
| REQ-024 | `test_tlp_completion_reserved_fields_and_ids` (and `_check_reserved_fields` in every completion test) | raw DW bits: T9, T8, LN, TH, TD, EP, AT, BCM, DW2[7] all 0 |
| REQ-025 | `test_tlp_completion_reserved_fields_and_ids` | TC ∈ {0,3,7} × Attr ∈ {0,1,2,4,7} copied verbatim |
| REQ-026 | `test_tlp_completion_reserved_fields_and_ids` | Tag ∈ {0x00,0x01,0x5A,0xFF} and Requester ID 12:03.5 copied verbatim |
| REQ-027 | `test_tlp_completion_reserved_fields_and_ids`, `test_tlp_completer_id_capture` | Completer ID equals the captured `cfg_completer_id` |
| REQ-028 | `test_tlp_mrd_completion_fields` | 11 (offset, Length, BE) cases: completion `Length` == request `Length`, payload is `4*Length` bytes |
| REQ-029 | `test_tlp_mrd_completion_fields` | `Byte Count` == `Length*4 − first_be_offset − last_be_offset` from the spec 7.5 tables |
| REQ-030 | `test_tlp_mrd_completion_fields` | `Lower Address` == `(Address + first_be_offset) & 0x7F` |
| REQ-031 | `test_tlp_mrd_completion_fields`, `test_tlp_requests_serviced_in_order` | exactly one completion per MRd, never split |
| REQ-032 | `test_tlp_mrd_payload_is_full_dwords` | full DWORD returned for First BE ∈ {0001,0010,0100,1000,0000,1001} |
| REQ-033 | `test_tlp_cfg_completion_fields` | CfgRd0 → CplD, Length 1, Byte Count 4, Lower Address 0, full DWORD regardless of BE |
| REQ-034 | `test_tlp_cfg_completion_fields` | CfgWr0 → Cpl, Length 0, Byte Count 4, Lower Address 0, SC |
| REQ-035 | `test_tlp_nonposted_unsupported_types`, `test_tlp_malformed_length_rejected`, `test_tlp_bar0_miss_and_window_overrun` | every UR is `Cpl`, Length 0, Byte Count 4, Lower Address 0, status 001 |
| REQ-036 | `test_tlp_posted_unsupported_types` + every `mwr_dword`/`mwr_burst` call in the suite | a posted request never produces a completion (checked after each one) |
| REQ-037 | `test_tlp_inbound_completion_discarded` | inbound Cpl and CplD produce no completion |
| REQ-038 | `test_tlp_bar0_miss_and_window_overrun`, `test_tlp_mse_gates_bar0_only`, `test_stress_random_sequence` | MRd above/below/aside BAR0 and with MSE=0 → UR + `ERR_UNSUP_REQ` |
| REQ-039 | `test_tlp_bar0_miss_and_window_overrun`, `test_tlp_mse_gates_bar0_only` | matching MWr cases → discarded, `ERR_UNSUP_REQ`, no completion |
| REQ-040 | `test_tlp_nonposted_unsupported_types`, `test_tlp_td_ep_treated_as_unsupported` | MRd64, IORd, CfgRd1, CfgWr1, FetchAdd, TD=1, EP=1 → UR + error bit |
| REQ-041 | `test_tlp_posted_unsupported_types`, `test_tlp_td_ep_treated_as_unsupported` | MWr64, IOWr, MWr with TD/EP → discarded + error bit, no completion (see §6 note 3 on Messages) |
| REQ-042 | `test_tlp_cfg_nonzero_device_or_function` | Device ∈ {1,31,5}, Function ∈ {1,7,3} → UR and `ERR_UNSUP_REQ` **stays clear**; Command unmodified |
| REQ-043 | `test_tlp_inbound_completion_discarded` | inbound completion sets no error bit |
| REQ-044 *(antecedent narrowed v1.1.4)* | `test_tlp_bar0_miss_and_window_overrun` | MRd/MWr at BAR0+0x3FFC with `L = 2` → BAR0 miss; the same offset with `L = 1` is serviced. `L = 2` is inside v1.1.4's narrowed `1 ≤ L ≤ 32` antecedent, so the test exercises REQ-044 and not REQ-127 (confirmed, not assumed) |
| REQ-045 | `test_cfg_reset_values`, `test_cfg_unimplemented_offsets_read_zero`, `test_cfg_enumeration_assigns_bar0` | all 16 DWORDs of 0x00–0x3C, and 0x40/0x80/0x100/0x400/0xFFC read 0 |
| REQ-046 | `test_cfg_command_register_rw_bits`, `test_cfg_write_byte_enables` | only Command[2:0], Cache Line Size and Interrupt Line are writable; byte enables respected |
| REQ-047 | `test_cfg_write_to_readonly_is_accepted_and_ignored` | writes to RO / unimplemented cfg offsets return SC and change nothing |
| REQ-048 | `test_cfg_bar0_sizing_and_readonly_low_bits` | write 0xFFFFFFFF → read 0xFFFFC000 |
| REQ-049 | `test_cfg_bar0_sizing_and_readonly_low_bits` | BAR0[13:0] read 0 for five different written values |
| REQ-050 | `test_tlp_mse_gates_bar0_only` | with MSE=0, BAR0 MRd is UR and BAR0 MWr is dropped (SCRATCH unchanged) |
| REQ-051 | `test_tlp_mse_gates_bar0_only`, `test_cfg_reset_values` | config space works with MSE=0 (and before enumeration) |
| REQ-052 | `test_tlp_completer_id_capture` | after a CfgRd0 addressed to bus 0x01 / 0x37 / 0xFF, completions carry that Completer ID |
| REQ-053 | `test_tlp_bar0_miss_and_window_overrun`, `test_tlp_mse_gates_bar0_only` | match requires MSE=1 **and** `Address[31:14] == BAR0[31:14]` |
| REQ-054 | `test_tlp_burst_ascending_and_independent_decode`, `test_tlp_payload_endianness` | `Address[13:0]` with [1:0] forced to 0 selects the right BAR0 location |
| REQ-055 | `test_reg_reserved_raz_wi`, `test_tlp_bar0_miss_and_window_overrun` | reserved offsets 0x0028…0x0FFC and BAR0+0x3FFC are RAZ/WI and complete **SC**, not UR |
| REQ-056 | `test_tlp_burst_ascending_and_independent_decode`, `test_matmul_read_granularity_equivalence` | 1…32 DWORD bursts serviced as consecutive ascending DWORDs |
| REQ-057 | `test_tlp_burst_ascending_and_independent_decode` | a 32 DW burst straddling the end of C: the in-range DWORDs store, the out-of-range ones are RAZ/WI |
| REQ-058 | `test_reg_scratch_rw_and_byte_enables`, `test_tlp_mrd_completion_fields` | First BE → DW0, Last BE → DW L−1, middle DWORDs fully enabled, Last BE ignored when L=1 |
| REQ-059 | `test_reg_scratch_rw_and_byte_enables` | 8 BE patterns incl. 0b0000: disabled bytes never change |
| REQ-060 | `test_reg_scratch_rw_and_byte_enables`, `test_tlp_payload_endianness` | BE bit *j* gates `data[8j+7:8j]` at byte address DWORD+*j* |
| REQ-061 | `test_tlp_mrd_payload_is_full_dwords`, `test_reg_scratch_rw_and_byte_enables` | reads ignore byte enables entirely |
| REQ-062 | `test_matmul_write_abc_while_busy` | A/B/C writes issued back-to-back with START are discarded and set `ERR_WRITE_BUSY`; C still matches the golden model |
| REQ-063 | `test_matmul_read_abc_while_busy` | A/B/C reads issued during the operation complete SC and do not set `ERR_WRITE_BUSY`; result unaffected |
| REQ-064 | `test_reg_access_while_busy` | register read/write during an operation works |
| REQ-065 | `test_smoke_enumerate_and_read_id`, `test_reg_reset_values`, `test_reg_ro_writes_ignored` | `ID` == 0x4D415431, unaffected by a write of 0xFFFFFFFF |
| REQ-066 | `test_reg_reset_values`, `test_reg_ro_writes_ignored` | `VERSION` == 0x00010000 |
| REQ-067 | `test_smoke_enumerate_and_read_id`, `test_reg_reset_values` | `CONFIG` == `{0, ACCW, DW, N}`, cross-checked at N=4, 8, 16 |
| REQ-068 | `test_reg_ctrl_reads_zero_and_be_gated` | `CTRL` reads 0 before and after a START write |
| REQ-069 | `test_smoke_single_multiply`, `test_matmul_back_to_back` | START runs one multiply, sets BUSY, clears DONE, clears accumulators |
| REQ-070 | `test_matmul_start_while_busy`, `test_reg_soft_reset` | 3 back-to-back STARTs → `ERR_START_BUSY`, `OP_COUNT` == 1, C still correct |
| REQ-071 *(reworded v1.1.0)* | `test_reg_soft_reset`, `test_matmul_soft_reset_during_operation`, `test_matmul_soft_reset_during_drain` | clears STATUS/PERF_CYCLES/accumulators; leaves A, B, SCRATCH, IRQ_ENABLE, OP_COUNT, cfg space (incl. BAR0) alone. The `mem_c` clause is now the narrowed one: with the engine IDLE, SOFT_RESET must not itself modify any word of C (checked bit-identical); the mid-`DRAIN` case moved to REQ-125 |
| REQ-072 | `test_reg_soft_reset_precedence` | `START\|SOFT_RESET` in one DWORD starts nothing (`OP_COUNT` stays 0) |
| REQ-073 | `test_reg_ctrl_reads_zero_and_be_gated` | CTRL writes with First BE ∈ {1110,0010,1000,0000} do nothing; BE 0001 works |
| REQ-074 *(`t_start` pinned in v1.1.1)* | `test_matmul_done_timing`, `test_matmul_busy_is_zero_when_idle` | BUSY 0 before START and after DONE; with `t_start = t_beat` the operation's length is now checked exactly, both via `PERF_CYCLES` and via REQ-123's pin-observable `t_beat + 4N + 2` |
| REQ-075 | `test_reg_status_w1c` | DONE set on completion and persists across a read and a write of 0 |
| REQ-076 | `test_reg_status_w1c`, `test_reg_status_w1c_byte_enable_gating` | writing 0 leaves it set; writing 1 with BE 0b1110 leaves it set; writing 1 with BE 0b0001 clears it |
| REQ-077 | **not verifiable at the chip boundary** — see "Uncovered" | |
| REQ-078 | `test_reg_status_w1c` | after writing 0xFFFFFFFF, STATUS[31:5] read 0 |
| REQ-079 | `test_reg_irq_status_and_irq_pin`, `test_reg_irq_enable_rw_and_reserved` | `IRQ_STATUS == STATUS & IRQ_ENABLE`, RO; IRQ_ENABLE bit 0 and 31:5 are RO 0 |
| REQ-080 *(reworded v1.1.0)* | `test_reg_irq_status_and_irq_pin` | `irq` **tracks** `IRQ_STATUS != 0` within 2 cycles in both directions. The lag is measured exactly: the responsible write commits at `t_beat + D_WR` (D_WR measured per REQ-122), and `irq` must change 1–2 cycles later. Checked on both the assertion and the deassertion edge |
| REQ-081 | `test_reg_irq_status_and_irq_pin` | `irq` deasserts within 8 cycles of W1C-ing STATUS, and of clearing IRQ_ENABLE |
| REQ-082 | `test_reg_op_count_and_perf_cycles`, `test_matmul_done_timing` | `PERF_CYCLES` after each of 3 operations |
| REQ-083 | `test_reg_scratch_rw_and_byte_enables` | SCRATCH RW, byte-granular, reset 0, no side effects |
| REQ-084 | `test_reg_op_count_and_perf_cycles`, `test_reg_soft_reset`, `test_matmul_zeros` | increments once per DONE; **not** cleared by SOFT_RESET (checked == 2) |
| REQ-085 | `test_matmul_random`, `test_matmul_extreme_operands` | indirect: a wrong `mem_a` engine read index or latency changes C (see §6 note 2) |
| REQ-086 | `test_matmul_storage_raz_wi_beyond_nn` | A bytes at/past `N*N` are RAZ/WI |
| REQ-087 | `test_matmul_random`, `test_matmul_extreme_operands` | indirect, as REQ-085 for `mem_b` |
| REQ-088 | `test_matmul_storage_raz_wi_beyond_nn` | B bytes at/past `N*N` are RAZ/WI |
| REQ-089 | `test_matmul_c_addressing_and_persistence` | every `C[i][j]` read individually at `0x3000 + 4*(i*N+j)` matches the golden model |
| REQ-090 | `test_matmul_c_addressing_and_persistence`, `test_matmul_c_cleared_by_rst_only` | host reads and host writes of C words |
| REQ-091 | `test_matmul_storage_raz_wi_beyond_nn`, `test_tlp_burst_ascending_and_independent_decode` | C words at/past `4*N*N` are RAZ/WI |
| REQ-092 | `test_matmul_c_cleared_by_rst_only`, `test_matmul_c_addressing_and_persistence`, `test_reg_soft_reset` | `rst` clears C; neither START nor SOFT_RESET does |
| REQ-093 | `test_matmul_extreme_operands`, `test_matmul_random` | MAC verified at ±128/±127 extremes and on random operands |
| REQ-094 | `test_matmul_done_timing` + all matmul result tests | indirect: any change to the 1-cycle forward latency breaks both `4N+2` and the skew, so C would differ |
| REQ-095 | `test_matmul_back_to_back`, `test_matmul_soft_reset_during_operation` | an explicit check that C₂ ≠ C₁+C₂ (the classic residue failure) |
| REQ-096 | `test_matmul_done_timing` | indirect: `PERF_CYCLES == 1+1+(3N−2)+1+N+1`; a wrong compute-phase length changes it |
| REQ-097 | `test_matmul_random`, `test_matmul_extreme_operands`, `test_matmul_identity` | exact dot product for 6 random pairs, 4 extreme pairs, A×I and I×B |
| REQ-098 | `test_matmul_c_addressing_and_persistence` | C[i][j] = distinct value per element, so any row-order or lane-order error in the drain shows up |
| REQ-099 | `test_matmul_done_timing` | indirect, as REQ-096 |
| REQ-100 | `test_matmul_random`, `test_matmul_back_to_back` | indirect: accumulation during drain would add extra products to C |
| REQ-101 | `test_matmul_done_timing` | **now exact at the boundary** (v1.1.1): `t_start = t_beat`, DONE observed at exactly `t_beat + 4N + 2` via the registered `irq`, and independently `PERF_CYCLES == 4N+2` |
| REQ-102 | `test_reg_op_count_and_perf_cycles`, `test_matmul_done_timing` | `PERF_CYCLES` is the constant `4N+2` after every operation (verified at N=4 and N=8) |
| REQ-103 | `test_matmul_done_timing`, `test_matmul_busy_is_zero_when_idle` | BUSY asserted through DONE, deasserted after |
| REQ-104 | `test_matmul_start_while_busy`, `test_matmul_soft_reset_during_operation` | a START outside IDLE is ignored |
| REQ-105 | `test_matmul_random`, `test_matmul_extreme_operands`, `test_matmul_zeros`, `test_matmul_identity`, `test_stress_random_sequence` | exact integer dot product, no saturation, no truncation |
| REQ-106 | `static: check_no_overflow_bit`, `test_reg_status_w1c` | no `saturat`/`overflow`/`clamp` anywhere in `rtl/`; STATUS[31:5] read 0 so no such bit is host-visible |
| REQ-107 | `static: check_clocking`, `static: check_top_ports` | only `posedge clk` sensitivity lists; exactly one clock input named `clk` |
| REQ-108 | `static: check_clocking`, `test_smoke_reset_state` | `rst` never appears in a sensitivity list (synchronous); reset state observed |
| REQ-109 | `test_smoke_reset_state` | `Host.reset()` holds `rst` for exactly 2 cycles and the full reset state is then checked |
| REQ-110 | `static: check_forbidden_constructs` | no `initial`, `#` delay, `$display`, `$monitor`, `$dumpvars` in `rtl/` |
| REQ-111 | `test_smoke_reset_state`, `test_reg_reset_values`, `test_cfg_reset_values`, `test_matmul_c_cleared_by_rst_only` | the whole spec 13.4 table: registers, cfg space, A/B/C, `irq` |
| REQ-112 | `test_smoke_enumerate_and_read_id`, `test_cfg_reset_values` | CfgRd0 of cfg 0x00 returns 0x80001234 with no prior configuration |
| REQ-113 | `make -C tb elab-sweep` | `matmul_top` elaborates for N ∈ {2,4,8,16,32}; the suite itself was run green at N=4, 8, 16 |
| REQ-114 | `test_smoke_enumerate_and_read_id` + `discover_n()` in every test | every test discovers N from `CONFIG[7:0]` at run time |
| REQ-115 | `test_cfg_bar0_sizing_and_readonly_low_bits`, `test_cfg_enumeration_assigns_bar0` | the host decodes a 16384-byte BAR0; sizing readback 0xFFFFC000 |
| REQ-116 | `test_smoke_single_multiply`, `test_cfg_enumeration_assigns_bar0` | the full spec 15 sequence with no UR and no error bit set |
| REQ-117 | `test_matmul_back_to_back` | three operations in a row, each compared to the golden model, plus an explicit no-residue check |
| REQ-118 | `test_matmul_zeros` | all-zero A and B → all-zero C, DONE set, OP_COUNT 1 |
| REQ-119 *(reworded v1.1.0, corrected v1.1.2)* | `test_matmul_write_granularity_equivalence` | `ceil(DW_op/32)` maximal bursts per operand (`DW_op = ceil(N*N/4)`) vs `2*DW_op` single-DW `MWr` TLPs: identical `mem_a`/`mem_b` bytes **and** identical C. TLP counts on both sides are asserted, so the two paths provably differ in granularity (§6 note 4) |
| REQ-120 *(reworded v1.1.0)* | `test_matmul_read_granularity_equivalence` | all of C read with `ceil(N*N/32)` maximal (32 DW) `MRd` bursts vs `N*N` single-DW `MRd`s: byte-for-byte identical, both sides covering all `4*N*N` bytes. TLP counts on both sides are asserted |
| REQ-122 *(new v1.1.0)* | `test_reg_write_path_delay_is_constant` | D_WR measured exactly through the registered `irq` (REQ-012) and shown to be the **same value** for two register offsets, both irq directions, byte enables 1111/0011/0001, and the first/middle/last DWORD of a burst; asserted to lie in 1..3. Region invariance is checked in read-after-write form across `reg_file`, `mem_a`, `mem_b` and `mem_c` (§6 note 9) |
| REQ-123 *(new v1.1.0, corrected v1.1.1)* | `test_matmul_done_timing` | `STATUS.DONE` set at **exactly** `t_beat + 4N + 2`, where `t_beat` is the cycle the `CTRL.START` payload DWORD transferred on `rx_tlp_*`; DONE is read off the registered `irq` (`t_done = t_irq − 1`). No `D_WR` term (§6 note 1) |
| REQ-124 *(new v1.1.0)* | `test_reg_start_and_soft_reset_while_busy` | `START\|SOFT_RESET` in one DWORD while BUSY: STATUS reads 0 afterwards (so `ERR_START_BUSY` is **not** left set), PERF_CYCLES 0, OP_COUNT 0 (the START was ignored entirely), and the device still computes correctly afterwards |
| REQ-127 *(new v1.1.4)* | `test_tlp_over_length_memory_request` | `L > 32` for `Length` ∈ {0 (= 1024 DW), 33, 100, 1023}, at two in-aperture addresses, one out-of-aperture address, and with `Command.MSE` both 1 and 0. **(a)** each `MRd` → a `Cpl` with UR, Length 0/ByteCount 4/LowerAddress 0 and REQ-024's reserved fields clear. **(b)** each `MWr` → no Completion at all. **(c)** framing preserved after every malformed `MWr`, checked through configuration space **and** BAR0; two framing shapes are used — payload matching the `Length` field (33, 100) and payload *shorter* than it claims (0, 1023), the harder reframe case. **(d)** `mem_a`, `mem_b`, `mem_c` and `SCRATCH` compared byte-for-byte against pre-loaded images after every case. **(e)** `ERR_UNSUP_REQ` cleared then re-checked for the read **and** the posted-write path, including with MSE = 0 |
| REQ-126 *(new v1.1.2)* | `test_cfg_malformed_length_completion_fields`, `test_cfg_malformed_length_framing_preserved`, `test_cfg_malformed_length_sets_unsup_req` | **(a)** `CfgRd0`/`CfgWr0` with `Length` in {0,2,3,4,5,8,32} → a 3-beat `Cpl`, UR, Length 0/ByteCount 4/LowerAddress 0; the first transaction after reset checks the exact `DW0 = 0x0A000000`, `DW1 = 0x00002004` the spec quotes for `cfg_completer_id = 0x0000`. **(b)** a 7-offset configuration snapshot is unchanged across every malformed case. **(c)** after each malformed `CfgWr0` the next TLP parses correctly — checked in config space *and* through BAR0 (`ID` = `0x4D415431`), including two malformed TLPs back-to-back. **(d)** `ERR_UNSUP_REQ` set for malformed `Length` at Device/Function 0 **and** non-zero, paired with a negative control (identical request, `Length = 1`) that must leave the bit clear so REQ-042's bus-scan carve-out stays intact (§6 note 10) |
| REQ-125 *(new v1.1.0)* | `test_matmul_soft_reset_during_drain` | SOFT_RESET swept across the whole drain window (`3N−1` … `4N+3` cycles after the START beat). For every landing: every `mem_c` word holds either its pre-operation value or its correct new value and never anything else; no row is part-old part-new; and the new rows form the contiguous suffix REQ-098's drain order requires. The sweep must produce at least one partially drained C, else it reports that it never landed inside `DRAIN` |
| REQ-121 | `test_cfg_reenumerable_after_reset` | after `rst`: BAR0 == 0, MSE == 0, cfg 0x00 still identifies; re-enumeration works and BAR0 is usable |

---

## 5. Uncovered / verified by other means

| REQ | Disposition |
|-----|-------------|
| **REQ-077** — "if a W1C bit's set condition and a clearing write occur on the same clock edge, the set wins" | **Verified by review, not by test.** Not verifiable at the chip boundary: the two possible outcomes are individually legal (a clear that lands before the set leaves the bit at 1; one that lands after leaves it at 0), so no single pin observation distinguishes "set wins" from "the clear arrived a cycle late". The Phase 2b reviewer settled it by inspection — set wins over clear for all four W1C bits, and three of the four collisions are structurally unreachable, so only `DONE` can actually collide. Recorded here so it is not mistaken for a coverage hole. |

Requirements marked "indirect" in the table above (REQ-021, REQ-085, REQ-087,
REQ-094, REQ-096, REQ-099, REQ-100) are internal to modules whose signal names
the spec calls advisory, so they are verified through their observable
consequence (the exact `4N+2` cycle count and the exact product) rather than by
probing. A violation of any of them changes either `PERF_CYCLES` or C, both of
which are checked exactly.

---

## 6. Notes, ambiguities and environment findings

**Note 1 — START→DONE is now exactly observable (REQ-123, spec v1.1.1).**
The v1.0.0 gap I reported (§7.3 stated the internal request latency only as an
upper bound, so REQ-101's exact `4N+2` could be checked only through
`PERF_CYCLES`) is closed. Spec v1.1.0 added REQ-122/REQ-123 and v1.1.1 fixed
`t_start = t_beat` and removed `D_WR` from every latency formula — the v1.1.0
text added `D_WR` on top of a window that already measured from `t_beat`, which
double-counted the write path by one cycle. `test_matmul_done_timing` now
asserts `t_done == t_beat + 4N + 2` **exactly**, reading DONE off the
registered `irq` (REQ-012 gives exactly one cycle of lag, so
`t_done = t_irq − 1`). Measured: DONE at `t_beat + 34` at N=8 and `t_beat + 18`
at N=4, both exact, with `PERF_CYCLES` independently `4N+2`.

Exact cycle accounting is provided by `models/host.cycle_now()`, derived from
sim time rather than from a counting task so it cannot lose a race at a clock
edge, and by the shim recording the cycle of **every** inbound beat
(`last_packet_beat_cycles`) so a test can name the beat that carried a
particular payload DWORD rather than the end-of-packet beat.

**Note 2 — internal latency requirements.** REQ-085/087/094/096/099/100
describe internal module behaviour; spec 3 says "internal signal names are
advisory". Probing them would couple the tests to names the rtl-designer is free
to change, which defeats the independence the test writer exists for. They are
covered through `PERF_CYCLES` and C, both exact.

**Note 3 — Message TLPs cannot be encoded by the reference library.**
`cocotbext-pcie` 0.2.16's `Tlp.pack_header()` raises `Exception("Unknown TLP
type")` for every `Msg`/`MsgD` format. Since `CLAUDE.md` forbids hand-writing
TLP bytes, REQ-041's "any Message" clause is covered by `MWr64` and `IOWr`,
which exercise the same posted-unsupported decode path in the DUT. Flagging so
it is not mistaken for an omission.

**Note 4 — REQ-119 and REQ-120 (corrected through v1.1.2).** Both are
expressed in terms of `N`, and the tests derive their TLP counts from `N` and
assert them, so the two sides provably differ in granularity. REQ-119 took two
rounds: the v1.1.0 repair ("one maximal burst per operand") was still
unsatisfiable for `N >= 16`, because `DW_op = ceil(N*N/4)` is 64 DW at N=16 and
256 DW at N=32, both over the 32-DW cap of REQ-018/REQ-056. v1.1.2 states it as
`ceil(DW_op/32)` bursts per operand, which is what the test already computed —
only its documentation changed. REQ-120 was re-checked and is correct at every
legal `N`: C is `N*N` DW, so `ceil(N*N/32)` is 1/1/2/8/32 for N = 2/4/8/16/32
and no burst exceeds 32 DW.

**Note 5 — NumPy is not installed in `.venv`.** The agent brief asks for a NumPy
golden model; `tb/models/golden.py` uses pure-Python integers instead. This is
strictly better for spec 12.6's "exact two's-complement arithmetic, no
truncation": Python ints cannot silently wrap the way a NumPy `int64`
accumulator can. No install was requested. If the orchestrator wants NumPy for
other reasons, say so; nothing in this suite needs it.

**Note 6 — host-model quirk on re-enumeration (testbench, not DUT).** The DUT
correctly accepts a Type 0 config request with Device 0 / Function 0 on *any*
bus number (spec 4.2 and REQ-042 constrain only Device and Function). A second
`rc.enumerate()` on the same `RootComplex` therefore discovers the same physical
device again behind the same root port on a fresh secondary bus, and the last
BAR0 write wins inside the DUT. `Host.enumerate()` handles this by selecting the
`PciDevice` whose assigned BAR0 matches the value actually programmed into the
device. Documented here so nobody later reads it as a DUT bug.

**Note 7 — posted writes must be drained before injecting raw TLPs.**
`region.write()` returns as soon as the TLP is handed to the behavioral link
model, which then delays it by `SimPort.port_delay` before the shim sees it.
`Host.mem_write()` therefore waits for the shim's rx-idle event before
returning. Without this, a following `shim.inject()` overtakes the write and the
test silently exercises a different order of operations. (This bit the first run
of four `test_matmul` tests; the failures were testbench races, not RTL bugs.)

**Note 8 — spec 7.5's byte-enable tables are self-checked.**
`test_tlp_be_tables_match_reference_library` compares the spec's
`first_be_offset` / `last_be_offset` / `be_byte_count` tables against
`cocotbext-pcie` for all 4 × 16 × 16 combinations, because spec 7.5 claims they
match "bit-for-bit". If that test ever fails, the *expected values* used
throughout `test_tlp.py` are wrong and it is a spec issue, not a DUT issue.
It passes today. Note that `Tlp.get_lower_address()` is **not** used as a
reference: spec 5.4 records that it is buggy in 0.2.16 (operator precedence).

---

**Note 9 — REQ-122's region clause, and why D_WR is measured through `irq`.**
Spec 9.6 suggests measuring `D_WR` by writing `SCRATCH` and reading it back on
successive cycles. That is not possible here: DEC-007 makes the DUT strictly
serialized, so it holds `rx_tlp_ready` low until the write has retired and a
read-back can never sample the location early. The usable channel is `irq`,
because REQ-012 makes it a *registered* copy of `|IRQ_STATUS` — exactly one
cycle of lag, not a bound — so writing `IRQ_ENABLE` while `STATUS.DONE` is
already set gives `D_WR = t_irq − t_beat − 1`. That channel only reaches
`reg_file`, so REQ-122's "regardless of target region" clause is covered in its
read-after-write form instead: an `MRd` of the just-written location injected
with zero idle cycles behind the `MWr` must return the new value, for
`reg_file`, `mem_a`, `mem_b` and `mem_c` and for five byte-enable patterns.
`D_WR` measures **1** on the current RTL, matching rtl-designer's independent
measurement. Its independence of `N` is exercised by running the test at
N = 4, 8 and 16 rather than asserted inside one simulation.

**Note 10 — REQ-126 and its negative control.** The config-TLP `Length != 1`
behaviour I flagged as having no requirement behind it is now REQ-126
(spec v1.1.2). Clause (d) — "shall set `STATUS.ERR_UNSUP_REQ`" — was written
into the spec before the RTL had been checked, so it was deliberately left
unasserted for one round until rtl-designer confirmed the behaviour existed; it
is now tested. The test asserts (d) **together with a negative control**: the
same request with `Length = 1` to the same non-zero Device/Function must return
UR and leave `ERR_UNSUP_REQ` clear. Without that control, a test of (d) would
pass on an implementation that set the bit on *every* absent-device probe,
which would break REQ-042 and make ordinary enumeration noisy.

**Note 11 — what the v1.1.0 → v1.1.2 updates changed in `tb/`.** New tests:
`test_reg_write_path_delay_is_constant` (REQ-122),
`test_reg_start_and_soft_reset_while_busy` (REQ-124),
`test_matmul_soft_reset_during_drain` (REQ-125),
`test_cfg_malformed_length_completion_fields`,
`test_cfg_malformed_length_framing_preserved`,
`test_cfg_malformed_length_sets_unsup_req` (REQ-126 a/b/c/d). Rewritten:
`test_matmul_done_timing` (REQ-123, now exact), `test_reg_irq_status_and_irq_pin`
(REQ-080's 2-cycle tracking window, measured rather than bounded at 8 cycles),
`test_matmul_write_granularity_equivalence` (REQ-119),
`test_matmul_read_granularity_equivalence` (REQ-120). Assertion message only:
`test_reg_soft_reset` (REQ-071's narrowed `mem_c` clause). New infrastructure:
`cycle_now()`, `wait_value_cycle()`, per-beat cycle recording in the shim, and
`measure_d_wr()` / `measure_d_wr_falling()` in `tb_common.py`.

---

**Note 12 — the five Phase 3 testbench bugs, and what changed.** All five were
in `tb/`; `rtl/` was byte-identical throughout.

* **BUG-001 (`make test N=<n>` reused a stale binary).** `N` reached the
  compiler through `COMPILE_ARGS`, which is not a prerequisite of cocotb's
  `$(SIM_BUILD)/sim.vvp: $(VERILOG_SOURCES)` rule, so changing `N` alone never
  triggered a rebuild and every "N sweep" was the `N = 8` binary re-run. Fixed
  by making the parameterisation part of the build identity:
  `SIM_BUILD := $(TB_DIR)/sim_build/$(SIM)-n$(N)`, with
  `COCOTB_RESULTS_FILE` inside it so parallel `N` runs cannot clobber each
  other. A `check-build-id` target now fails the build if `SIM_BUILD` ever
  stops encoding `N`, so the hazard cannot silently return; `make build-id`
  prints the directory. Verified by hashing: `sim.vvp` differs for every `N`
  (see §7). This bug hid BUG-002, BUG-003 and BUG-005.
* **BUG-002.** `test_tlp_back_to_back_tlps_no_idle_cycles` wrote 16 consecutive
  C words, but C holds `N*N` = 4 words at `N = 2` and the rest is RAZ/WI by
  REQ-091 — the DUT was right. The 16 writes now cycle through the implemented
  words (`word = k mod N*N`), so the TLP count, and therefore the amount of
  back-to-back stress, is identical at every `N`, and several of the
  back-to-back TLPs now hit the *same* address, which is the harder case. No
  assertion was relaxed.
* **BUG-003.** `test_matmul_write_abc_while_busy` fired CTRL.START and three
  region writes as one burst and relied on the operation outlasting the TLP
  stream; at `N = 2` an operation is 10 cycles and the C write correctly
  arrived after BUSY fell. Each region is now raced separately against a fresh
  START, and the shim's recorded beat cycles are used to **assert** the write
  committed inside `[t_start + 1, t_start + 4N + 2]`. If it lands outside, the
  test fails as a positioning error rather than silently testing nothing.
* **BUG-005.** `test_matmul_c_addressing_and_persistence` built
  `A[i][j] = i*N + j − 100`, which leaves INT8 range at `N >= 16` and was
  rejected by the golden model before the DUT saw it. A fully distinct `N*N`
  INT8 pattern is impossible at `N = 32` (256 values, 1024 elements), so
  distinctness is replaced by three complementary INT8-legal patterns —
  row-varying, lane-varying, and two-index-varying — which between them still
  detect any row permutation, lane permutation, transposition or drain-order
  reversal.
* **BUG-006.** `OP_TIMEOUT_NS` was a flat 20 us for a whole multi-completion
  transfer. It is now `BASE + 40 ns/byte`, applied in `mem_read`, `mem_write`
  and `raw_request` (scaled by the completion's DWORD length). The
  backpressure probabilities were not lowered.

---

## 7. Status as of this plan

`make -C tb lint` — clean (Verilator 5.032 `--lint-only -Wall`, 0 warnings; 5/5
structural checks pass).
`make -C tb test` — **72 / 72 pass** at every `N` tested, on two seeds, each
with a genuine rebuild (BUG-001 fixed):

| `N` | SEED=1 | SEED=424242 | `sim_build/icarus-n<N>/sim.vvp` md5 |
|-----|--------|-------------|--------------------------------------|
| 2 | 72/72 | 72/72 | `688715e0a6ab7266c48f7536caa36e6b` |
| 4 | 72/72 | 72/72 | `b3a594814a145874161b6b2676c5ed91` |
| 8 | 72/72 | 72/72 | `0f7196821ba8dfbfde0fad0e88a864aa` |
| 16 | 72/72 | 72/72 | `63f5e516913028cd564418d683bc020e` |

Each `N` builds into its own `sim_build/icarus-n<N>/` directory. **Caveat on
the hashes:** `iverilog` output is not byte-reproducible — two rebuilds of the
identical source at the identical `N` give different hashes — so *distinct*
hashes across `N` do not by themselves prove a genuine per-`N` build. (The
converse is sound, which is why BUG-001's original evidence held: *identical*
output from a non-reproducible compiler does prove no recompile happened.) The
real evidence that each run used its own binary is behavioural: REQ-123
measures `DONE` at exactly `t_beat + 4N + 2` — 10 at N=2, 18 at N=4, 34 at N=8,
66 at N=16 — and the two tests that BUG-001 had been hiding (BUG-002, BUG-003)
now fail-then-pass only against a real N=2 build. `N = 32` was **not run**: a single pass is
estimated at 6–8 h under Icarus. Its elaboration is covered by
`make -C tb elab-sweep`, and `test_matmul_c_addressing_and_persistence`'s
operand patterns were chosen to stay INT8-legal and permutation-sensitive at
`N = 32` (BUG-005) so the suite is ready for it whenever someone has the time.
`make -C tb elab-sweep` — passes for N in {2,4,8,16,32}.
Fail-ability confirmed: breaking the expected `ID` value in `test_smoke.py`
produced `TESTS=4 PASS=3 FAIL=1`; the value was restored and re-verified. The
REQ-123 test also demonstrated its own fail-ability for real — written to the
v1.1.0 formula it failed by exactly one cycle, which is the defect v1.1.1 fixed.
