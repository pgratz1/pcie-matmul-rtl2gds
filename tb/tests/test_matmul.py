"""
Matrix-multiply engine, seen from the host.

Requirements: REQ-062, REQ-063, REQ-069, REQ-070, REQ-074, REQ-082, REQ-086,
REQ-088..REQ-092, REQ-093, REQ-095..REQ-105, REQ-116..REQ-120.

Every expected C comes from tb/models/golden.py, never from the DUT.
"""

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from tb_common import (G, assert_matrix_equal, clear_status, discover_n,
                       load_ab, make_tb, mrd, mrd_dword, mwr_burst, mwr_dword,
                       random_matrix, read_c, run_op, start_op, wait_done,
                       wait_for, TbTimeout, measure_d_wr, cycle_now,
                       wait_value_cycle, inject_and_get_beat)

MAX_BURST_DW = 32          # REQ-018 / REQ-056 cap on any single MRd or MWr


def ceil_div(a, b):
    return -(-a // b)


def zeros(n):
    return [[0] * n for _ in range(n)]


def identity(n):
    return [[1 if i == j else 0 for j in range(n)] for i in range(n)]


async def matmul_case(tb, n, a, b, what):
    """Load A/B, run one operation, compare C against the golden model."""
    await load_ab(tb, a, b, n)
    await run_op(tb)
    exp = G.matmul_golden(a, b, n)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, what)
    return exp


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_zeros(dut):
    """REQ-118: all-zero operands give all-zero C and DONE is set normally."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    await matmul_case(tb, n, zeros(n), zeros(n), "C for all-zero A and B")
    oc = await tb.read_dword(G.REG_OP_COUNT)
    assert oc == 1, (
        f"REQ-118/REQ-084: OP_COUNT = {oc} after one all-zero operation; the "
        "operation must complete normally")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_identity(dut):
    """REQ-105: A x I = A and I x B = B."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed)

    a = random_matrix(rng, n)
    await matmul_case(tb, n, a, identity(n), "C for A x I")
    b = random_matrix(rng, n)
    await matmul_case(tb, n, identity(n), b, "C for I x B")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_extreme_operands(dut):
    """REQ-093, REQ-097, REQ-105: min/max INT8 operands, exact arithmetic.

    -128 * -128 = +16384 is the largest magnitude single product (spec 12.6);
    an all -128 by all -128 pair produces N * 16384 in every element, which is
    the worst case the accumulator ever sees.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    cases = [
        ([[-128] * n for _ in range(n)], [[-128] * n for _ in range(n)],
         "C for A = B = -128 (worst-case positive accumulation)"),
        ([[-128] * n for _ in range(n)], [[127] * n for _ in range(n)],
         "C for A = -128, B = +127 (worst-case negative accumulation)"),
        ([[127] * n for _ in range(n)], [[127] * n for _ in range(n)],
         "C for A = B = +127"),
        ([[-128 if (i + j) % 2 else 127 for j in range(n)] for i in range(n)],
         [[127 if (i + j) % 2 else -128 for j in range(n)] for i in range(n)],
         "C for a checkerboard of the INT8 extremes"),
    ]
    for a, b, what in cases:
        await matmul_case(tb, n, a, b, what)


@cocotb.test(timeout_time=1000, timeout_unit="us")
async def test_matmul_random(dut):
    """REQ-097, REQ-105: random operands against the golden model."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xA11CE)

    for k in range(6):
        a = random_matrix(rng, n)
        b = random_matrix(rng, n)
        await matmul_case(tb, n, a, b, f"C for random operand pair #{k}")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_back_to_back(dut):
    """REQ-069, REQ-095, REQ-117: two operations, no accumulator residue."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xB2B)

    a1, b1 = random_matrix(rng, n), random_matrix(rng, n)
    exp1 = await matmul_case(tb, n, a1, b1, "C after the first operation")

    a2, b2 = random_matrix(rng, n), random_matrix(rng, n)
    exp2 = await matmul_case(tb, n, a2, b2, "C after the second operation")

    # The classic residue failure: C2 == C1 + C2_expected.
    residue = [[exp1[i][j] + exp2[i][j] for j in range(n)] for i in range(n)]
    got = await read_c(tb, n)
    assert got != residue or exp1 == zeros(n), (
        "REQ-095/REQ-117: C after the second operation equals "
        "C1 + C2_expected, i.e. the PE accumulators were not cleared on START")

    # And a third operation with the *same* operands as the first.
    await matmul_case(tb, n, a1, b1,
                      "C after re-running the first operand pair")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_start_while_busy(dut):
    """REQ-070, REQ-104: a second START during an operation is ignored."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x5741)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    await load_ab(tb, a, b, n)

    await mwr_burst(tb, [(G.REG_CTRL, G.CTRL_START, 0xF),
                         (G.REG_CTRL, G.CTRL_START, 0xF),
                         (G.REG_CTRL, G.CTRL_START, 0xF)])
    await wait_done(tb)

    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_START_BUSY, (
        f"REQ-070: STATUS = 0x{st:08x} after three back-to-back STARTs; "
        "ERR_START_BUSY (bit 2) must be set")

    oc = await tb.read_dword(G.REG_OP_COUNT)
    assert oc == 1, (
        f"REQ-070/REQ-104: OP_COUNT = {oc} after three back-to-back STARTs; "
        "the extra STARTs must be ignored, so exactly one operation runs")

    exp = G.matmul_golden(a, b, n)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C after START-while-BUSY",
                        extra="  REQ-070: the running operation must be "
                              "unaffected by the ignored STARTs.")


@cocotb.test(timeout_time=900, timeout_unit="us")
async def test_matmul_write_abc_while_busy(dut):
    """REQ-062: A/B/C writes during an operation are discarded + flagged.

    "While BUSY" is made an explicit, *checked* precondition rather than an
    accident of `N`.  The original test fired one burst of four TLPs --
    CTRL.START, then writes to A, B and C -- and relied on the operation
    outlasting the TLP stream.  Each single-DWORD MWr is 4 beats, so the C
    write's payload beat lands roughly 12 cycles after START's; an operation
    is `4N + 2` cycles, which is 34 at N=8 but only **10** at N=2, so at N=2
    the C write arrived after BUSY had fallen and was correctly accepted.
    The RTL was right and the test's timing assumption was wrong (BUG-003).

    Each region is now raced separately against a freshly started operation,
    and the beat cycles recorded by the shim are used to assert that the write
    really did commit inside `[t_start + 1, t_start + 4N + 2]`, the window
    REQ-074 defines for BUSY (spec 9.6 v1.1.1 fixes `t_start = t_beat`).  If
    the write lands outside that window the test fails as a positioning error
    instead of silently testing nothing.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x8051)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    exp = G.matmul_golden(a, b, n)
    a_bytes, b_bytes = G.a_to_bytes(a, n), G.b_to_bytes(b, n)

    for region, base, label in ((0, G.MEM_A_BASE, "mem_a"),
                                (1, G.MEM_B_BASE, "mem_b"),
                                (2, G.MEM_C_BASE, "mem_c")):
        await load_ab(tb, a, b, n)
        await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
        st = await tb.read_dword(G.REG_STATUS)
        assert st == 0, (
            f"precondition: STATUS = 0x{st:08x} before the {label} race")

        start = tb.make_mem_write(tb.bar0_addr + G.REG_CTRL,
                                  G.CTRL_START.to_bytes(4, "little"))
        poison = tb.make_mem_write(tb.bar0_addr + base,
                                   (0xFFFFFFFF).to_bytes(4, "little"))
        cap = tb.shim.start_capture()
        try:
            t_start = await inject_and_get_beat(tb, start, payload_index=0)
            t_write = await inject_and_get_beat(tb, poison, payload_index=0)
        finally:
            tb.shim.stop_capture()

        delta = t_write - t_start
        assert 1 <= delta <= G.t_mm(n), (
            f"test positioning: the {label} write's payload beat transferred "
            f"{delta} cycles after the CTRL.START beat, outside the BUSY "
            f"window [1, 4*N+2 = {G.t_mm(n)}] that REQ-074 defines.  REQ-062 "
            "only applies while STATUS.BUSY is 1, so this run would not have "
            "exercised it.  (This is the failure mode BUG-003 described: at "
            "small N the operation finishes before the TLP stream does.)")

        await wait_done(tb)
        st = await tb.read_dword(G.REG_STATUS)
        assert st & G.ST_ERR_WRITE_BUSY, (
            f"REQ-062: STATUS = 0x{st:08x} after a write to {label} whose "
            f"payload beat landed {delta} cycles into a {G.t_mm(n)}-cycle "
            "operation; ERR_WRITE_BUSY (bit 3) must be set")

        if region == 0:
            got = bytes(await tb.mem_read(G.MEM_A_BASE, 4))
            assert got == a_bytes[:4], (
                f"REQ-062: A[0][0..3] reads {got!r} after a write attempted "
                f"{delta} cycles into the operation; the write must be "
                f"discarded, leaving {a_bytes[:4]!r}")
        elif region == 1:
            got = bytes(await tb.mem_read(G.MEM_B_BASE, 4))
            assert got == b_bytes[:4], (
                f"REQ-062: B[0][0..3] reads {got!r} after a write attempted "
                f"{delta} cycles into the operation; the write must be "
                f"discarded, leaving {b_bytes[:4]!r}")

        got = await read_c(tb, n)
        assert_matrix_equal(
            got, exp, f"C after a write to {label} was attempted "
                      f"{delta} cycles into the operation",
            extra="  REQ-062: the write is discarded, so C must be exactly "
                  "the golden product.")
        await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_read_abc_while_busy(dut):
    """REQ-063: reads of A/B/C during an operation complete with SC."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x9EAD)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    await load_ab(tb, a, b, n)

    cap = tb.shim.start_capture()
    try:
        start = tb.make_mem_write(tb.bar0_addr + G.REG_CTRL,
                                  G.CTRL_START.to_bytes(4, "little"))
        reads = [tb.make_mem_read(tb.bar0_addr + G.MEM_A_BASE, length=1),
                 tb.make_mem_read(tb.bar0_addr + G.MEM_B_BASE, length=1),
                 tb.make_mem_read(tb.bar0_addr + G.MEM_C_BASE, length=4,
                                  first_be=0xF, last_be=0xF)]
        await tb.shim.inject(start)
        for r in reads:
            await tb.shim.inject(r)
        cpls = [await tb._get_capture(cap, 20000, r) for r in reads]
    finally:
        tb.shim.stop_capture()

    for r, cpl in zip(reads, cpls):
        assert cpl.status == 0, (
            f"REQ-063: a read of BAR0+0x{r.address - tb.bar0_addr:04x} while "
            f"the engine was running returned status {cpl.status!r}; reads of "
            "A/B/C during an operation must complete with SC")

    await wait_done(tb)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_WRITE_BUSY == 0, (
        f"REQ-063: STATUS = 0x{st:08x}; reading A/B/C while BUSY is legal and "
        "must not set ERR_WRITE_BUSY")

    exp = G.matmul_golden(a, b, n)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C after reads were issued while BUSY")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_done_timing(dut):
    """REQ-123 (spec v1.1.1) and REQ-074, REQ-082, REQ-101, REQ-102, REQ-103.

    REQ-123 is the boundary-observable form of REQ-101: with a CTRL write
    whose payload DWORD carries bit 0 and transfers at cycle `t_beat` while
    BUSY is 0, `STATUS.DONE` is set at exactly `t_beat + 4*N + 2`.  Spec
    v1.1.1 fixes `t_start = t_beat` and deliberately excludes `D_WR` from
    every latency formula -- adding it would double-count the write path.

    DONE is observed through `irq`, which REQ-012 makes a registered copy of
    |IRQ_STATUS: exactly one cycle of lag, so `t_done = t_irq - 1`.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    expected = G.t_mm(n)

    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
    assert int(dut.irq.value) == 0, "irq should be low before the operation"
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_BUSY == 0, (
        f"REQ-074: STATUS = 0x{st:08x}; BUSY must be 0 at t_beat for REQ-123 "
        "to apply")

    start = tb.make_mem_write(tb.bar0_addr + G.REG_CTRL,
                              G.CTRL_START.to_bytes(4, "little"))
    cap = tb.shim.start_capture()
    try:
        watcher = cocotb.start_soon(
            wait_value_cycle(dut.clk, dut.irq, 1, "irq", 8 * expected + 64))
        t_beat = await inject_and_get_beat(tb, start, payload_index=0)
        t_irq = await watcher
    finally:
        tb.shim.stop_capture()

    t_done = t_irq - 1                       # REQ-012: irq lags by one cycle
    exp_done = t_beat + expected
    dut._log.info("REQ-123: t_beat=%d, 4N+2=%d -> DONE at %d (expected %d), "
                  "irq at %d", t_beat, expected, t_done, exp_done, t_irq)
    assert t_done == exp_done, (
        f"REQ-123: STATUS.DONE was set at cycle {t_done}, but the CTRL.START "
        f"payload DWORD transferred at cycle {t_beat}, so spec 9.6 (v1.1.1) "
        f"requires it at exactly t_beat + 4*N + 2 = {t_beat} + {expected} = "
        f"{exp_done}.  Off by {t_done - exp_done}.\n"
        f"  DONE is inferred from irq rising at cycle {t_irq}; REQ-012 makes "
        "irq a registered copy of |IRQ_STATUS, so DONE is exactly one cycle "
        "earlier.  Note that D_WR is deliberately NOT a term here (spec 9.6: "
        "t_start = t_beat); adding it would double-count the write path.")

    pc = await tb.read_dword(G.REG_PERF_CYCLES)
    assert pc == expected, (
        f"REQ-102/REQ-082: PERF_CYCLES = {pc}; spec 12.5 fixes the operation "
        f"at 1 (PRIME) + 1 (FETCH) + {3 * n - 2} (COMPUTE) + 1 (TURN) + {n} "
        f"(DRAIN) + 1 (FINISH) = 4*N+2 = {expected} cycles.  REQ-123 and "
        "REQ-101 must agree with it.")

    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE, f"REQ-075: STATUS = 0x{st:08x}, DONE must be set"
    assert st & G.ST_BUSY == 0, (
        f"REQ-074/REQ-103: STATUS = 0x{st:08x}; BUSY must be 0 after the "
        "cycle on which DONE was set")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_busy_is_zero_when_idle(dut):
    """REQ-074: BUSY reads 0 outside [t_start+1, t_done]."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_BUSY == 0, (
        f"REQ-074: STATUS = 0x{st:08x} before any START; BUSY must be 0")

    await run_op(tb)
    for _ in range(3):
        st = await tb.read_dword(G.REG_STATUS)
        assert st & G.ST_BUSY == 0, (
            f"REQ-074: STATUS = 0x{st:08x} after the operation finished; "
            "BUSY must be 0")


@cocotb.test(timeout_time=1500, timeout_unit="us")
async def test_matmul_c_addressing_and_persistence(dut):
    """REQ-089, REQ-090, REQ-092, REQ-098: C word placement and persistence.

    Three operand patterns, all INT8-legal for every legal `N` (2..32), chosen
    so that between them any permutation of C is detected:

      * ``A[i][j] = i - 128``  -- every **row** of C differs, so any row
        permutation or reversal of the drain order (REQ-098) shows up.
      * ``A[i][j] = j - 128``  -- every **lane** of C differs, so any lane
        permutation or a transposition shows up.
      * ``A[i][j] = ((i*37 + j*5) % 251) - 125`` -- varies in both indices at
        once, so it also catches interactions the two single-index patterns
        would miss.

    The original single pattern was ``(i*N + j) - 100``, which is distinct per
    element but leaves INT8 range at `N >= 16` (155 at N=16, 923 at N=32) and
    was rejected by the golden model before the DUT was ever stimulated
    (BUG-005).  A fully distinct `N*N` pattern is impossible at `N = 32` --
    INT8 has 256 values and C has 1024 elements -- so distinctness is dropped
    in favour of the three complementary patterns above, which keep the
    permutation check's teeth at every `N`.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    row_pattern = [[i - 128 for _ in range(n)] for i in range(n)]
    lane_pattern = [[j - 128 for j in range(n)] for _ in range(n)]
    mixed = [[((i * 37 + j * 5) % 251) - 125 for j in range(n)]
             for i in range(n)]

    for a, what in ((row_pattern, "row-varying A (detects row permutation "
                                  "and drain-order reversal, REQ-098)"),
                    (lane_pattern, "lane-varying A (detects lane permutation "
                                   "and transposition)"),
                    (mixed, "two-index-varying A")):
        await matmul_case(tb, n, a, identity(n), f"C = A x I with {what}")

    # Per-element read at exactly 0x3000 + 4*(i*N + j) (REQ-090), using the
    # two-index pattern that is still in C from the loop above.
    exp = G.matmul_golden(mixed, identity(n), n)
    for i in range(n):
        for j in range(n):
            off = G.MEM_C_BASE + 4 * (i * n + j)
            got = G.to_signed32(await mrd_dword(tb, off))
            assert got == exp[i][j], (
                f"REQ-089/REQ-090/REQ-098: BAR0+0x{off:04x} (C[{i}][{j}]) "
                f"reads {got}, golden says {exp[i][j]}")

    # REQ-092 / REQ-071 (narrowed in v1.1.0): with the engine IDLE, SOFT_RESET
    # must not itself modify any word of mem_c.
    await mwr_dword(tb, G.REG_CTRL, G.CTRL_SOFT_RESET)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C after SOFT_RESET with the engine IDLE",
                        extra="  REQ-092/REQ-071: SOFT_RESET must not itself "
                              "modify mem_c.")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_c_cleared_by_rst_only(dut):
    """REQ-092: rst clears mem_c; a host write to C sticks until then."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    pattern = b"".join(int(0x1000 + k).to_bytes(4, "little")
                       for k in range(n * n))
    await tb.mem_write(G.MEM_C_BASE, pattern)
    back = await tb.mem_read(G.MEM_C_BASE, len(pattern))
    assert bytes(back) == pattern, (
        "REQ-090: a host write to C did not read back unchanged")

    await tb.reset()
    await tb.enumerate()
    back = await tb.mem_read(G.MEM_C_BASE, len(pattern))
    assert bytes(back) == bytes(len(pattern)), (
        "REQ-092/REQ-111: mem_c must be cleared to 0 by rst")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_storage_raz_wi_beyond_nn(dut):
    """REQ-086, REQ-088, REQ-091: A/B bytes and C words past N*N are RAZ/WI."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    for base, limit, req in ((G.MEM_A_BASE, n * n, "REQ-086"),
                             (G.MEM_B_BASE, n * n, "REQ-088"),
                             (G.MEM_C_BASE, 4 * n * n, "REQ-091")):
        for delta in (0, 4, 0x100, 0xFFC - (limit & 0xFFC)):
            off = base + ((limit + delta) & ~3)
            if off >= base + 0x1000:
                continue
            await mwr_dword(tb, off, 0xA5A5A5A5)
            got = await mrd_dword(tb, off)
            assert got == 0, (
                f"{req}: BAR0+0x{off:04x} reads 0x{got:08x} after a write; "
                f"offsets at or past {limit} bytes into the region are RAZ/WI")


@cocotb.test(timeout_time=1500, timeout_unit="us")
async def test_matmul_write_granularity_equivalence(dut):
    """REQ-119 (reworded v1.1.0, corrected v1.1.2).

    Loading A and B with the minimum number of maximal bursts must leave
    `mem_a` and `mem_b` holding exactly the same bytes as loading the same
    data with `2*DW_op` single-DW `MWr` TLPs, and the operation afterwards
    must produce identical C.

    Spec v1.1.2 states this as the minimum number of maximal bursts,
    `ceil(DW_op/32)` per operand where `DW_op = ceil(N*N/4)`, which is what
    this test computes: one 16-DW burst per operand at N=8, two 32-DW bursts
    at N=16, eight at N=32 -- always versus `2*DW_op` single-DW writes.
    (v1.1.0's "one maximal burst per operand" was unsatisfiable for N >= 16
    because DW_op exceeds the 32-DW cap of REQ-018/REQ-056; reported and
    fixed in v1.1.2.)
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xC0FFEE)

    dw_per_operand = ceil_div(n * n, 4)
    bursts_per_operand = ceil_div(dw_per_operand, MAX_BURST_DW)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    exp = G.matmul_golden(a, b, n)
    a_bytes, b_bytes = G.a_to_bytes(a, n), G.b_to_bytes(b, n)

    # --- (1) maximal bursts, counted -------------------------------------
    await tb.mem_write(G.MEM_A_BASE, bytes(n * n))
    await tb.mem_write(G.MEM_B_BASE, bytes(n * n))
    before = tb.shim.rx_packets
    cap = tb.shim.start_capture()
    try:
        for base, data in ((G.MEM_A_BASE, a_bytes), (G.MEM_B_BASE, b_bytes)):
            off = 0
            while off < dw_per_operand:
                ndw = min(MAX_BURST_DW, dw_per_operand - off)
                await tb.shim.inject(tb.make_mem_write(
                    tb.bar0_addr + base + 4 * off,
                    data[4 * off:4 * (off + ndw)],
                    first_be=0xF, last_be=0xF))
                off += ndw
        await tb.shim.wait_rx_idle()
        await ClockCycles(dut.clk, 8)
    finally:
        tb.shim.stop_capture()
    framed = tb.shim.rx_packets - before
    assert framed == 2 * bursts_per_operand, (
        f"internal: {framed} burst TLPs were framed, expected "
        f"{2 * bursts_per_operand} ({bursts_per_operand} per operand)")

    a_burst = bytes(await tb.mem_read(G.MEM_A_BASE, n * n))
    b_burst = bytes(await tb.mem_read(G.MEM_B_BASE, n * n))
    assert a_burst == a_bytes and b_burst == b_bytes, (
        "REQ-119: the burst-written A/B bytes do not match what was sent")
    await run_op(tb)
    c_burst = await read_c(tb, n)
    assert_matrix_equal(c_burst, exp, "C after burst-written operands")

    # --- (2) 2*ceil(N*N/4) single-DWORD writes ---------------------------
    await tb.mem_write(G.MEM_A_BASE, bytes(n * n))
    await tb.mem_write(G.MEM_B_BASE, bytes(n * n))
    before = tb.shim.rx_packets
    writes = []
    for k in range(dw_per_operand):
        writes.append((G.MEM_A_BASE + 4 * k,
                       int.from_bytes(a_bytes[4 * k:4 * k + 4], "little"), 0xF))
        writes.append((G.MEM_B_BASE + 4 * k,
                       int.from_bytes(b_bytes[4 * k:4 * k + 4], "little"), 0xF))
    await mwr_burst(tb, writes)
    framed = tb.shim.rx_packets - before
    assert framed == 2 * dw_per_operand, (
        f"internal: {framed} single-DWORD TLPs were framed, expected "
        f"{2 * dw_per_operand}")

    a_single = bytes(await tb.mem_read(G.MEM_A_BASE, n * n))
    b_single = bytes(await tb.mem_read(G.MEM_B_BASE, n * n))
    assert a_single == a_burst, (
        f"REQ-119: mem_a differs between {bursts_per_operand} maximal "
        f"burst(s) and {dw_per_operand} single-DWORD writes\n"
        f"  burst : {a_burst.hex()}\n  single: {a_single.hex()}")
    assert b_single == b_burst, (
        f"REQ-119: mem_b differs between {bursts_per_operand} maximal "
        f"burst(s) and {dw_per_operand} single-DWORD writes\n"
        f"  burst : {b_burst.hex()}\n  single: {b_single.hex()}")

    await run_op(tb)
    c_single = await read_c(tb, n)
    assert_matrix_equal(
        c_single, exp, "C after single-DWORD written operands",
        extra=f"  REQ-119: {2 * dw_per_operand} single-DWORD writes must "
              f"produce the same result as {2 * bursts_per_operand} maximal "
              "burst(s).")
    assert c_single == c_burst, (
        "REQ-119: C differs between the burst-written and the "
        "single-DWORD-written load of identical data")


@cocotb.test(timeout_time=1500, timeout_unit="us")
async def test_matmul_read_granularity_equivalence(dut):
    """REQ-120 (reworded in spec v1.1.0).

    Reading the whole of C with the minimum number of maximal bursts,
    `ceil(N*N/32)` MRd TLPs of up to 32 DWORDs each, must return byte-for-byte
    the same data as `N*N` single-DW MRds.  Both sides cover all `4*N*N`
    bytes of C -- the v1.0.0 wording compared one 32-DW burst (half of C at
    N=8) against 64 single-DW reads (all of C).
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xDECAF)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    exp = G.matmul_golden(a, b, n)
    await load_ab(tb, a, b, n)
    await run_op(tb)

    total_dw = n * n
    exp_bursts = ceil_div(total_dw, MAX_BURST_DW)

    # --- (1) ceil(N*N/32) maximal bursts, counted ------------------------
    before = tb.shim.rx_packets
    burst = bytearray()
    off = 0
    while off < total_dw:
        ndw = min(MAX_BURST_DW, total_dw - off)
        req, cpl = await mrd(tb, G.MEM_C_BASE + 4 * off, length=ndw,
                             first_be=0xF, last_be=0xF if ndw > 1 else 0)
        assert cpl.status == 0, (
            f"REQ-120: burst read of C at DWORD {off} returned status "
            f"{cpl.status!r}, expected SC")
        assert cpl.length == ndw, (
            f"REQ-028: completion Length {cpl.length} != request {ndw}")
        burst += cpl.get_data()
        off += ndw
    framed = tb.shim.rx_packets - before
    assert framed == exp_bursts, (
        f"REQ-120: {framed} MRd TLPs were used to read all of C; the minimum "
        f"number of maximal (32 DW) bursts is ceil(N*N/32) = {exp_bursts}")
    assert bytes(burst) == G.c_to_bytes(exp, n), (
        "REQ-120/REQ-105: the burst read of C does not match the golden model")

    # --- (2) N*N single-DWORD reads --------------------------------------
    before = tb.shim.rx_packets
    single = bytearray()
    for m in range(total_dw):
        single += int(await mrd_dword(tb, G.MEM_C_BASE + 4 * m)
                      ).to_bytes(4, "little")
    framed = tb.shim.rx_packets - before
    assert framed == total_dw, (
        f"internal: {framed} single-DWORD MRds were framed, expected "
        f"{total_dw}")
    assert bytes(single) == bytes(burst), (
        f"REQ-120: reading all {4 * total_dw} bytes of C as {total_dw} "
        f"single-DWORD MRds returned different data from reading it as "
        f"{exp_bursts} maximal burst(s)\n  burst : {bytes(burst).hex()}\n"
        f"  single: {bytes(single).hex()}")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_soft_reset_during_operation(dut):
    """REQ-071, REQ-095, REQ-104: SOFT_RESET mid-operation returns to IDLE."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x5F7)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    await load_ab(tb, a, b, n)

    await mwr_burst(tb, [(G.REG_CTRL, G.CTRL_START, 0xF),
                         (G.REG_CTRL, G.CTRL_SOFT_RESET, 0xF)])

    st = await tb.read_dword(G.REG_STATUS)
    assert st == 0, (
        f"REQ-071: STATUS = 0x{st:08x} after SOFT_RESET during an operation; "
        "BUSY, DONE and the error bits must all be clear")
    pc = await tb.read_dword(G.REG_PERF_CYCLES)
    assert pc == 0, (
        f"REQ-071: PERF_CYCLES = {pc} after SOFT_RESET, must be 0")

    # A fresh operation must still produce the exact product: the aborted run
    # must not have left anything in the accumulators (REQ-095).
    await run_op(tb)
    got = await read_c(tb, n)
    assert_matrix_equal(got, G.matmul_golden(a, b, n),
                        "C after an aborted operation and a clean re-run",
                        extra="  REQ-095: START must clear every PE "
                              "accumulator.")


async def _wait_until_cycle(dut, target, limit=4000):
    """Spin on the clock until `cycle_now()` reaches `target`."""
    for _ in range(limit):
        if cycle_now() >= target:
            return
        await RisingEdge(dut.clk)
    raise TbTimeout(
        f"never reached cycle {target} (now {cycle_now()}) while waiting on "
        "dut.clk")


@cocotb.test(timeout_time=3000, timeout_unit="us")
async def test_matmul_soft_reset_during_drain(dut):
    """REQ-125 (new in spec v1.1.0): SOFT_RESET during DRAIN.

    The drain is aborted immediately.  Words of `mem_c` already written by the
    drain keep their new values; words not yet reached keep their prior
    values.  The result is *defined but mixed*, so the check is "every word is
    one or the other, never something else" -- not a single expected array.

    REQ-098 additionally fixes the drain order: on drain cycle `m` the bottom
    row output carries `acc(N-1-m, j)`, so C is written row `N-1` first.  A
    partially drained C must therefore have its **new** rows forming a
    contiguous suffix `{N-1, N-2, ...}`; anything else means rows were drained
    in the wrong order or a row was half-written.

    The SOFT_RESET is swept across the whole drain window because the exact
    cycle the drain starts is internal.  Spec 9.6 (v1.1.1) fixes
    `t_start = t_beat`, so the sweep is aimed directly in beat cycles.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    # Pre-operation pattern: large values that no legal product can equal
    # (|C| <= N * 16384 = 131072 for every legal N), so "old" and "new" are
    # never ambiguous.
    old = [[0x40000000 + i * n + j for j in range(n)] for i in range(n)]
    old_bytes = G.c_to_bytes(old, n)

    rng = random.Random(tb.seed ^ 0xD3A12)
    a = [[rng.randint(-128, 127) or 1 for _ in range(n)] for _ in range(n)]
    b = [[rng.randint(-128, 127) or 1 for _ in range(n)] for _ in range(n)]
    new = G.matmul_golden(a, b, n)
    await load_ab(tb, a, b, n)

    # PRIME + FETCH + COMPUTE + TURN = 1 + 1 + (3N-2) + 1 = 3N+1 cycles, so
    # DRAIN runs over t_start + 3N+1 .. t_start + 4N.  Sweep a little wider.
    lo, hi = 3 * n - 1, 4 * n + 3
    profile = []

    for offset in range(lo, hi + 1):
        await tb.mem_write(G.MEM_C_BASE, old_bytes)
        await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
        back = bytes(await tb.mem_read(G.MEM_C_BASE, 4 * n * n))
        assert back == old_bytes, (
            "REQ-090: the pre-operation C pattern did not stick")

        start = tb.make_mem_write(tb.bar0_addr + G.REG_CTRL,
                                  G.CTRL_START.to_bytes(4, "little"))
        srst = tb.make_mem_write(
            tb.bar0_addr + G.REG_CTRL,
            G.CTRL_SOFT_RESET.to_bytes(4, "little"))

        cap = tb.shim.start_capture()
        try:
            t_start_beat = await inject_and_get_beat(tb, start, payload_index=0)
            # Aim the SOFT_RESET payload beat at t_start + offset.  Spec 9.6
            # gives t_start = t_beat, so the offset is a plain beat-to-beat
            # distance.  The TLP is 4 beats long, so start driving it 4
            # cycles early.
            await _wait_until_cycle(dut, t_start_beat + offset - 4)
            t_srst_beat = await inject_and_get_beat(tb, srst, payload_index=0)
        finally:
            tb.shim.stop_capture()

        landed = t_srst_beat - t_start_beat
        await tb.settle()

        st = await tb.read_dword(G.REG_STATUS)
        assert st == 0, (
            f"REQ-071: STATUS = 0x{st:08x} after a SOFT_RESET aimed at drain "
            f"offset {offset} (landed at +{landed}); BUSY, DONE and every "
            "error bit must be clear")

        got = G.bytes_to_c(await tb.mem_read(G.MEM_C_BASE, 4 * n * n), n)

        undefined = []
        row_state = []
        for i in range(n):
            kinds = set()
            for j in range(n):
                if got[i][j] == new[i][j]:
                    kinds.add("new")
                elif got[i][j] == old[i][j]:
                    kinds.add("old")
                else:
                    undefined.append((i, j, got[i][j]))
            row_state.append(kinds)

        assert not undefined, (
            f"REQ-125: with the SOFT_RESET beat landing {landed} cycles "
            f"after the CTRL.START beat, {len(undefined)} word(s) of mem_c "
            "hold neither their pre-operation value nor their correct new "
            "value.  Spec 10.3 requires mem_c to be left in a *defined but "
            "mixed* state.  First offenders (i, j, value): "
            + ", ".join(f"({i},{j},{v})" for i, j, v in undefined[:6]))

        new_rows = [i for i in range(n) if "new" in row_state[i]]
        mixed_rows = [i for i in range(n) if len(row_state[i]) > 1]
        assert not mixed_rows, (
            f"REQ-098/REQ-125: rows {mixed_rows} of mem_c are part old and "
            f"part new after a SOFT_RESET at +{landed}.  The drain writes one "
            "complete row of C per cycle (REQ-089), so a row is either fully "
            "written or not written at all")
        if new_rows:
            expected_suffix = list(range(n - len(new_rows), n))
            assert new_rows == expected_suffix, (
                f"REQ-098/REQ-125: the drained rows are {new_rows} after a "
                f"SOFT_RESET at +{landed}; REQ-098 drains row N-1 first, so "
                f"the new rows must be the contiguous suffix "
                f"{expected_suffix}")
        profile.append((offset, landed, len(new_rows)))

    dut._log.info("REQ-125 drain-abort profile (aimed offset, landed, rows "
                  "drained): %s", profile)

    counts = sorted({rows for _, _, rows in profile})
    assert len(counts) > 1, (
        f"REQ-125: every SOFT_RESET in the sweep [{lo}, {hi}] left the same "
        f"{counts[0]} of {n} rows drained, so the sweep never actually landed "
        "inside DRAIN and the requirement was not exercised.  Widen the "
        "sweep or re-derive the drain window from spec 12.5.")
    assert any(0 < rows < n for _, _, rows in profile), (
        f"REQ-125: no SOFT_RESET in the sweep produced a partially drained C "
        f"(row counts seen: {counts}); the mid-DRAIN abort path was never "
        "exercised")

    # After all that, the device must still compute correctly.
    await run_op(tb)
    got = await read_c(tb, n)
    assert_matrix_equal(got, new,
                        "C after re-running the operation following a "
                        "mid-drain SOFT_RESET",
                        extra="  REQ-125: software must re-run the operation; "
                              "the re-run must produce the exact product.")
