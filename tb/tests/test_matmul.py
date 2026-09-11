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
                       wait_for, TbTimeout)


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


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_write_abc_while_busy(dut):
    """REQ-062: A/B/C writes during an operation are discarded + flagged."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x8051)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    await load_ab(tb, a, b, n)
    exp = G.matmul_golden(a, b, n)

    # START, then immediately try to overwrite A, B and C.
    await mwr_burst(tb, [
        (G.REG_CTRL, G.CTRL_START, 0xF),
        (G.MEM_A_BASE, 0xFFFFFFFF, 0xF),
        (G.MEM_B_BASE, 0xFFFFFFFF, 0xF),
        (G.MEM_C_BASE, 0xFFFFFFFF, 0xF),
    ])
    await wait_done(tb)

    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_WRITE_BUSY, (
        f"REQ-062: STATUS = 0x{st:08x} after writing A/B/C while BUSY; "
        "ERR_WRITE_BUSY (bit 3) must be set")

    got_a = await tb.mem_read(G.MEM_A_BASE, 4)
    assert bytes(got_a) == G.a_to_bytes(a, n)[:4], (
        f"REQ-062: A[0][0..3] reads {bytes(got_a)!r} after a write attempted "
        "while BUSY; the write must be discarded")
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C after A/B/C writes were attempted "
                                  "while BUSY")


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


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_matmul_done_timing(dut):
    """REQ-074, REQ-082, REQ-101, REQ-102, REQ-103, REQ-096, REQ-099.

    PERF_CYCLES is the exactly-specified, exactly-observable form of the
    4N+2 latency and is checked as an exact constant.  The chip-boundary
    measurement (START beat -> irq) is bounded rather than exact because the
    spec does not fix the number of cycles between a beat being accepted on
    rx_tlp_* and the CTRL write reaching reg_file (spec 7.3 says "no later
    than", spec 6.2 and 9.6 only give the app_bar0-relative numbers).
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    expected = G.t_mm(n)

    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
    assert int(dut.irq.value) == 0, "irq should be low before the operation"

    start = tb.make_mem_write(tb.bar0_addr + G.REG_CTRL,
                              G.CTRL_START.to_bytes(4, "little"))
    await tb.shim.inject(start)
    await tb.shim.wait_rx_idle()

    delta = 0
    for _ in range(4 * expected + 64):
        await RisingEdge(dut.clk)
        delta += 1
        if int(dut.irq.value) == 1:
            break
    else:
        raise TbTimeout(
            f"irq never asserted within {4 * expected + 64} cycles of the "
            f"CTRL.START write being accepted on rx_tlp_*; REQ-101 requires "
            f"DONE {expected} cycles after START and REQ-080 requires irq to "
            "follow IRQ_STATUS")

    lo, hi = expected, expected + 5
    assert lo <= delta <= hi, (
        f"REQ-101/REQ-012: irq rose {delta} cycles after the CTRL.START beat "
        f"was accepted on rx_tlp_*.  4*N+2 = {expected} cycles for N = {n}, "
        f"plus at most 3 cycles of rx_tlp -> reg_file pipeline (spec 7.3) and "
        f"1 cycle for the registered irq output (REQ-012), so the legal "
        f"window is [{lo}, {hi}]")
    dut._log.info("START beat -> irq: %d cycles (4N+2 = %d)", delta, expected)

    pc = await tb.read_dword(G.REG_PERF_CYCLES)
    assert pc == expected, (
        f"REQ-102/REQ-082: PERF_CYCLES = {pc}; spec 12.5 fixes the operation "
        f"at 1 (PRIME) + 1 (FETCH) + {3 * n - 2} (COMPUTE) + 1 (TURN) + {n} "
        f"(DRAIN) + 1 (FINISH) = 4*N+2 = {expected} cycles, so this register "
        "always reads exactly that")

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


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_matmul_c_addressing_and_persistence(dut):
    """REQ-089, REQ-090, REQ-092, REQ-098: C word placement and persistence.

    A is built so that C[i][j] = (i+1)*1000 + (j+1), which is unique per
    element; if the drain phase wrote rows in the wrong order or lanes in the
    wrong order, the pattern would be permuted.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    # C[i][j] = sum_k A[i][k]*B[k][j].  With B = I, C = A.  Use distinct
    # values per element so that any transposition or row reversal shows up.
    a = [[(i * n + j) - 100 for j in range(n)] for i in range(n)]
    await matmul_case(tb, n, a, identity(n), "C = A x I, element placement")

    # Per-element read at exactly 0x3000 + 4*(i*N + j) (REQ-090)
    exp = G.matmul_golden(a, identity(n), n)
    for i in range(n):
        for j in range(n):
            off = G.MEM_C_BASE + 4 * (i * n + j)
            got = G.to_signed32(await mrd_dword(tb, off))
            assert got == exp[i][j], (
                f"REQ-089/REQ-090/REQ-098: BAR0+0x{off:04x} (C[{i}][{j}]) "
                f"reads {got}, golden says {exp[i][j]}")

    # REQ-092: neither START nor SOFT_RESET clears C.
    await mwr_dword(tb, G.REG_CTRL, G.CTRL_SOFT_RESET)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C after SOFT_RESET",
                        extra="  REQ-092: SOFT_RESET must not clear mem_c.")


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


@cocotb.test(timeout_time=1200, timeout_unit="us")
async def test_matmul_write_granularity_equivalence(dut):
    """REQ-119: burst-written and byte-written operands give the same C.

    (spec 15 REQ-119 says "a single 32-DW MWr burst"; at N = 8 the whole of A
    is 16 DW and the whole of B is another 16 DW, and they live in different
    4 KiB regions, so "one burst per operand" is the largest burst that can
    describe this.  A genuine 32-DW burst is exercised in test_tlp.py.)
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xC0FFEE)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    exp = G.matmul_golden(a, b, n)

    # (1) one burst per operand
    await tb.mem_write(G.MEM_A_BASE, G.a_to_bytes(a, n))
    await tb.mem_write(G.MEM_B_BASE, G.b_to_bytes(b, n))
    await run_op(tb)
    c_burst = await read_c(tb, n)
    assert_matrix_equal(c_burst, exp, "C after burst-written operands")

    # (2) wipe, then write every byte with its own single-DW MWr + byte enable
    await tb.mem_write(G.MEM_A_BASE, bytes(n * n))
    await tb.mem_write(G.MEM_B_BASE, bytes(n * n))

    abytes, bbytes = G.a_to_bytes(a, n), G.b_to_bytes(b, n)
    writes = []
    for m in range(n * n):
        writes.append((G.MEM_A_BASE + (m & ~3), abytes[m] << (8 * (m & 3)),
                       1 << (m & 3)))
        writes.append((G.MEM_B_BASE + (m & ~3), bbytes[m] << (8 * (m & 3)),
                       1 << (m & 3)))
    await mwr_burst(tb, writes)

    await run_op(tb)
    c_bytes = await read_c(tb, n)
    assert_matrix_equal(
        c_bytes, exp, "C after byte-by-byte written operands",
        extra=f"  REQ-119: {2 * n * n} single-DWORD byte-enabled writes must "
              "produce the same result as one burst per operand.")


@cocotb.test(timeout_time=1200, timeout_unit="us")
async def test_matmul_read_granularity_equivalence(dut):
    """REQ-120: C read as bursts and as single DWORDs returns identical data."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0xDECAF)

    a, b = random_matrix(rng, n), random_matrix(rng, n)
    exp = G.matmul_golden(a, b, n)
    await load_ab(tb, a, b, n)
    await run_op(tb)

    burst = await tb.mem_read(G.MEM_C_BASE, 4 * n * n)
    assert bytes(burst) == G.c_to_bytes(exp, n), (
        "REQ-120: the burst read of C does not match the golden model")

    single = bytearray()
    for m in range(n * n):
        val = await mrd_dword(tb, G.MEM_C_BASE + 4 * m)
        single += int(val).to_bytes(4, "little")
    assert bytes(single) == bytes(burst), (
        f"REQ-120: reading C as {n * n} single-DWORD MRds returned different "
        "data from reading it as bursts")


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
