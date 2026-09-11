# Bug ledger — PCIe-attached matrix multiplier

Owner: validation-specialist (CLAUDE.md "Ownership and independence rules").
Opened during Phase 3 validation.

Format: `BUG-nnn | test | REQ ids | status | symptom | root cause | fix | files`

Status values: `OPEN`, `ROUTED-rtl`, `ROUTED-test`, `ROUTED-spec`, `CLOSED`,
`CLOSED-nofix` (investigated, no defect).

---

## BUG-001 — `make test N=<n>` silently reuses a stale `sim.vvp`

| field | value |
|---|---|
| **test** | whole suite; `tb/Makefile` |
| **REQ ids** | REQ-113 (`matmul_top` parameterizable for every legal `N`), and the Phase 3 gate's "100% of tests pass" (which was only ever measured at `N` = 8) |
| **status** | `ROUTED-test` (harness fix belongs to test-writer; CLAUDE.md reserves `tb/` to them) |
| **found by** | Noticing that 16 consecutive `make -C tb test N=<2,4,8,16>` runs all took 19–20 s and never changed `tb/sim_build/sim.vvp`'s mtime. |

**Symptom.** `make -C tb test N=2` reports `TESTS=71 PASS=71 FAIL=0`. After
`make -C tb clean`, the identical command reports `PASS=69 FAIL=2`. The `N`
override had no effect at all; every "sweep" run was the previously built
`N = 8` binary.

**Root cause.** cocotb's `Makefile.icarus` declares
`$(SIM_BUILD)/sim.vvp: $(VERILOG_SOURCES) ...`. `N` reaches the compile through
`COMPILE_ARGS += -P$(COCOTB_TOPLEVEL).N=$(N)` (tb/Makefile line ~76), which is
**not** a prerequisite of that rule. When the RTL sources are unchanged, make
considers `sim.vvp` up to date and re-runs the old binary under the new `N=`
variable. The same hazard applies to `SEED` (harmless, `SEED` is read at
runtime) and to any future `COMPILE_ARGS` knob (not harmless).

This is why `rtl/README.md` can truthfully say "clean at N = 2, 4, 8, 16 and
32" — `make lint` and `make elab-sweep` re-invoke verilator/iverilog every time
and are unaffected — while the *simulation* at those `N` had never actually
run.

**Fix (recommended, for test-writer).** Make the build depend on the
parameterization, e.g. stamp `N` into the build directory
(`SIM_BUILD := $(TB_DIR)/sim_build/n$(N)`), or add an order-only prerequisite
file whose contents are `$(N)`. A `SIM_BUILD` per `N` also lets the `N` sweep
run in parallel.

**Files.** `tb/Makefile`.

**Impact.** This bug is what hid BUG-002 and BUG-003. It is the single most
important finding of Phase 3: the gate criterion "100% of tests pass" was being
evaluated against a binary that did not correspond to the requested
configuration.

---

## BUG-002 — `test_tlp_back_to_back_tlps_no_idle_cycles` hard-codes 16 DWORDs into `mem_c`

| field | value |
|---|---|
| **test** | `tb/tests/test_tlp.py::test_tlp_back_to_back_tlps_no_idle_cycles` (line ~771) |
| **REQ ids** | test cites REQ-005/REQ-013/REQ-022; the behaviour it trips over is REQ-091 |
| **status** | `ROUTED-test` — **the RTL is correct; the test's expectation contradicts REQ-091** |
| **found by** | Full suite at `N = 2` after `make clean` (BUG-001), SEED = 1, 7, 424242, 20260910 — fails on all four, so it is deterministic, not seed-dependent. |

**Symptom.**
```
AssertionError: REQ-022: DWORD(s) [4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
did not land when the 16 single-DWORD MWr TLPs were issued one at a time ...
read back 0000111101001111020011110300111100000000...0
```
DWORDs 0–3 land correctly; 4–15 read back as zero.

**Root cause — in the test, not the DUT.** The test does
`pattern = [0x11110000 + k for k in range(16)]` and `base = G.MEM_C_BASE`,
i.e. it writes 16 DWORDs into the C region unconditionally. `mem_c` holds
`N*N` words (spec §9.2, §11.3). At `N = 2` that is **4** words, so DWORDs 4–15
are at BAR0 offsets ≥ `0x3010` which REQ-091 makes RAZ/WI. The DUT is doing
exactly what REQ-091 requires. The constant 16 happens to be ≤ `N*N` for
`N` ≥ 4, which is why the bug only appears at `N = 2`.

**Fix (recommended, for test-writer).** The test already calls `discover_n(tb)`
and throws the result away. Scale the burst: `count = min(16, n * n)` (or pick
a region that is `N`-independent — the `reg_file` region is 4 KiB for every
`N`). **Do not** relax the assertion.

**Files.** `tb/tests/test_tlp.py`.

---

## BUG-003 — `test_matmul_write_abc_while_busy` assumes the operation outlives the TLP stream

| field | value |
|---|---|
| **test** | `tb/tests/test_matmul.py::test_matmul_write_abc_while_busy` (line ~167) |
| **REQ ids** | REQ-062, REQ-101/REQ-123 |
| **status** | `ROUTED-test` — **the RTL is correct; the test's timing assumption is unsound at small `N`** |
| **found by** | Full suite at `N = 2` after `make clean`; root-caused from an FST dump correlating `rx_tlp_*` beats with `eng_busy` and `eng_c_wr_en`. |

**Symptom.** `C after A/B/C writes were attempted while BUSY: 1 of 4 elements
differ: [0][0]: DUT -1 != golden -5720`. `-1` is `0xFFFFFFFF`, the value the
test wrote. The companion assertions in the same test (`ERR_WRITE_BUSY` set,
`mem_a` preserved) both **pass**.

**Root cause — in the test, not the DUT.** The test issues one burst of four
TLPs: `CTRL.START`, then `MWr` to A, B and C. Each single-DWORD `MWr` is 4
beats, so the payload beats land roughly 4 cycles apart. An operation takes
`4N + 2` cycles (REQ-101), which at `N = 2` is **10** cycles — shorter than the
TLP stream that is trying to race it. Waveform, `N = 2`, SEED = 7
(period 10 ns):

| time | event | `eng_busy` |
|---|---|---|
| 4250 ns | `CTRL.START` payload beat | 0 → 1 next cycle |
| 4300 ns | `MWr` A payload beat (`addr 0xc0001000`, `0xFFFFFFFF`) | **1** → discarded, `ERR_WRITE_BUSY` set |
| 4350 ns | `MWr` B payload beat (`addr 0xc0002000`) | **1** → discarded |
| 4330, 4340 ns | `eng_c_wr_en` — both rows of C drained | 1 |
| 4350 ns | `eng_busy` → 0 (operation complete, `4N+2 = 10` cycles after 4250) | |
| 4400 ns | `MWr` C payload beat (`addr 0xc0003000`, `0xFFFFFFFF`) | **0** |

The C write arrives 5 cycles **after** `BUSY` fell. REQ-062 gates the discard
on `STATUS.BUSY == 1`; `BUSY` was 0, so accepting the write is the specified
behaviour, and it lands on top of the already-drained `C[0][0]`. At `N = 8`
the operation is 34 cycles and still running when the C write arrives, which
is why the test passes there.

**Fix (recommended, for test-writer).** Make "still busy" an explicit
precondition rather than an accident of `N`: either hold `rx_tlp_ready`-side
pacing so all three writes are in flight before `4N+2` elapses, or read
`STATUS` between the writes and assert `BUSY == 1` at the moment of each write,
or drive the three A/B/C writes as **one** multi-DWORD burst instead of three
TLPs. **Do not** drop the C check or widen the tolerance.

**Files.** `tb/tests/test_matmul.py`.

---

## BUG-004 — spec has no requirement for `Length` > 32 or `Length` field = 0 inside the BAR0 window

| field | value |
|---|---|
| **test** | none exists; found by scratchpad probe `p_length_over_32_and_zero` |
| **REQ ids** | gap between REQ-044, REQ-056 and §4.5 |
| **status** | `ROUTED-spec` — **spec ambiguity, no side taken** |
| **found by** | Directed probing of boundary arithmetic (Phase 3 task b). |

**The gap.** Three statements do not compose:

- **§4.5** makes `max_read_request_size = 0` (≤ 32 DW) an obligation on the
  *testbench*, not on the DUT.
- **REQ-056** says `app_bar0` "shall accept bursts of 1 to 32 DWORDs" — it does
  not say what happens to a 33rd.
- **REQ-044** makes a request Unsupported only when
  `offset + Length*4 > 16384`.

So an `MRd` at BAR0+`0x3000` with `Length` = 33 (132 B, ends at `0x3084`) or
with the `Length` field = 0, which PCIe Base r6.0 §2.2.1 defines as **1024
DWORDs** (4096 B, ends at exactly `0x4000` = 16384, so REQ-044's strict `>`
is *not* satisfied) is inside the window by REQ-044's own arithmetic, and no
requirement says the DUT may refuse it.

**What the RTL does** (`rtl/tlp_rx.sv:200`):
```systemverilog
assign len_ok = (len_raw != 10'd0) && (len_raw <= 10'd32);
```
`len_ok` false ⇒ `CLS_UR_ERR` for non-posted / `CLS_DROP_ERR` for posted.
Measured at `N = 8`: `Length` = 33, 64 and 0 all return
`status = UR, length = 0, byte_count = 4`, and framing is preserved (the next
TLP parses correctly). Note `Length` field 0 is treated as *zero* DWORDs by
the `len_raw != 0` term, not as 1024, but the outcome is the same UR.

**Why it matters beyond pedantry.** REQ-126 was added in v1.1.2 for exactly
this shape of problem on the *configuration* path (`CfgRd0`/`CfgWr0` with
`Length` != 1). The memory path has the same hole and no equivalent
requirement, so the RTL's behaviour here is unverified by construction — the
suite cannot test it because the spec never states it.

**Recommendation (not a decision).** Add a REQ that states the DUT's existing
behaviour: a memory request whose `Length` field is 0 or greater than 32 is
Unsupported — UR Completion for non-posted, discard for posted, `ERR_UNSUP_REQ`
set in both cases — and note that `Length` = 0 is handled as out-of-range
rather than decoded as 1024 DW. That is a one-line spec amendment and **no RTL
change**. spec-writer decides; validation does not.

**Files.** `docs/spec.md` §7.6 (and §9.2/REQ-056 cross-reference);
`rtl/tlp_rx.sv:200` for reference only.

---

## BUG-005 — `test_matmul_c_addressing_and_persistence` builds an A matrix outside INT8 range at `N` >= 16

| field | value |
|---|---|
| **test** | `tb/tests/test_matmul.py::test_matmul_c_addressing_and_persistence` (line 338) |
| **REQ ids** | spec §12.6 (operands are INT8, `-128 <= v <= 127`); test cites REQ-089/090/092/098 |
| **status** | `ROUTED-test` — **the RTL is never reached; the test aborts in its own golden model** |
| **found by** | Full suite at `N` = 16 after `make clean` (BUG-001). Deterministic, seed-independent. |

**Symptom.**
```
File "tb/models/golden.py", line 130, in matmul_golden
  assert all(-128 <= v <= 127 for v in row), "A outside INT8 range (spec 12.6)"
AssertionError: A outside INT8 range (spec 12.6)
```
The DUT is never stimulated; `matmul_golden` rejects the stimulus first. The
testbench's own guard caught this correctly — that guard is working as designed.

**Root cause — in the test, not the DUT.** Line 338:
```python
a = [[(i * n + j) - 100 for j in range(n)] for i in range(n)]
```
`i*n + j` ranges over `0 .. N*N-1`, so the values run `-100 .. N*N-101`:

| `N` | max A value | INT8 legal? |
|---|---|---|
| 2 | -97 | yes |
| 4 | -85 | yes |
| 8 | -37 | yes |
| 16 | **155** | **no** |
| 32 | **923** | **no** |

The constant `100` is tuned for `N` = 8 and nothing scales it.

**Note for the fix — the test's premise also breaks at `N` = 32.** The
docstring's argument is "distinct values per element so that any transposition
or row reversal shows up". INT8 has exactly 256 distinct values, so a
fully-distinct `N*N` element pattern exists at `N` <= 16 (`(i*n + j) - 128` is
exact at `N` = 16) but is **impossible** at `N` = 32, where `N*N` = 1024.
The permutation-sensitivity argument needs restating for `N` = 32 — for example
`A[i][j] = ((i * 37 + j * 5) % 251) - 125`, which is not fully distinct but is
still sensitive to any row or lane permutation, or check the placement property
directly with `A[i][j] = i - 128` in one pass and `A[i][j] = j - 128` in a
second. **Do not** simply clamp or modulo the existing expression without
re-establishing that the permutation check still has teeth.

**Files.** `tb/tests/test_matmul.py` line 338.

---

## BUG-006 — `Host.OP_TIMEOUT_NS` is a fixed 20 us and does not scale with `N`

| field | value |
|---|---|
| **test** | `tb/models/host.py:38`; affects every helper that calls `mem_read`/`mem_write`/`enumerate` |
| **REQ ids** | REQ-002, REQ-007 (the DUT is allowed to be stalled for an *unbounded* number of cycles; the harness is not prepared for it) |
| **status** | `ROUTED-test` — latent fragility, **not** a DUT defect |
| **found by** | Scratchpad probe `p_heavy_random_backpressure` at `N` = 16. |

**Symptom.** `Exception: Timeout` from `cocotbext.axi.address_space.read`,
raised inside `read_c()`, during a 90%/90% random-backpressure run at `N` = 16.

**Root cause — in the harness, not the DUT.** `read_c(tb, n)` issues a single
`window.read(0x3000, 4*N*N)` under one `OP_TIMEOUT_NS = 20000` ns budget.
`cocotbext-axi` splits that into `ceil(4*N*N / 128)` sequential 32-DWORD
requests *inside the same timeout*. At `N` = 16 that is 1024 bytes = 8
completions = ~280 beats; at 10% effective throughput it needs well over
2000 cycles = 20 us, so the fixed budget expires.

**Proof that the DUT is not at fault.** Same design, same `N` = 16, same seed:

| stimulus | result |
|---|---|
| 50% / 50% backpressure, whole-C read | **PASS** |
| 75% / 75% backpressure, whole-C read | **PASS** |
| 90% / 90% backpressure, C read in 32-byte chunks | **PASS** |
| 90% / 90% backpressure, whole-C read in one call | Timeout |

Only the shape of the *readback* changes between the last two rows. The DUT
delivers every byte correctly in all four.

**Why it is worth fixing anyway.** The margin shrinks as `N` grows. At `N` = 32
a whole-C read is 4096 bytes = 32 back-to-back completions ≈ 1120 beats
≈ 11.2 us at **zero** backpressure, against a 20 us budget; `test_stress`
already runs at 15% stall by default. This is a flake waiting to happen in the
one configuration that takes an hour per run to reproduce.

**Fix (recommended, for test-writer).** Scale the budget with the transfer,
e.g. `timeout = OP_TIMEOUT_NS + 40 * length` ns, or make `OP_TIMEOUT_NS` a
function of `N`. Do **not** lower the backpressure probabilities to fit the
timeout.

**Files.** `tb/models/host.py` line 38 and its three call sites (lines 194,
257, 267).
