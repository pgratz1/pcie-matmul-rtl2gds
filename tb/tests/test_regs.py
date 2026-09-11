"""
BAR0 register block, every register in docs/register-map.md section 2.

Reset values, RO / RW / W1C / WO behaviour, byte enables, IRQ generation,
SOFT_RESET, OP_COUNT and PERF_CYCLES.

Requirements: REQ-012, REQ-055, REQ-058..REQ-061, REQ-064, REQ-065..REQ-084,
REQ-092, REQ-102, REQ-111.
"""

import cocotb
from cocotb.triggers import ClockCycles

from tb_common import (G, clear_status, discover_n, load_ab, make_tb,
                       mrd_dword, mwr_burst, mwr_dword, read_c, run_op,
                       start_op, wait_done, wait_for, assert_matrix_equal,
                       measure_d_wr, measure_d_wr_falling, cycle_now,
                       wait_value_cycle, inject_and_get_beat, TbTimeout)

RESET_VALUES = [
    (G.REG_ID, G.ID_VALUE, "REQ-065"),
    (G.REG_VERSION, G.VERSION_VALUE, "REQ-066"),
    (G.REG_CTRL, 0x00000000, "REQ-068"),
    (G.REG_STATUS, 0x00000000, "REQ-074/REQ-111"),
    (G.REG_IRQ_ENABLE, 0x00000000, "REQ-111"),
    (G.REG_IRQ_STATUS, 0x00000000, "REQ-079"),
    (G.REG_PERF_CYCLES, 0x00000000, "REQ-082"),
    (G.REG_SCRATCH, 0x00000000, "REQ-083"),
    (G.REG_OP_COUNT, 0x00000000, "REQ-084"),
]

# Read-only registers: a write must be accepted and change nothing.
RO_REGS = [
    (G.REG_ID, "REQ-065"),
    (G.REG_VERSION, "REQ-066"),
    (G.REG_CONFIG, "REQ-067"),
    (G.REG_IRQ_STATUS, "REQ-079"),
    (G.REG_PERF_CYCLES, "REQ-082"),
    (G.REG_OP_COUNT, "REQ-084"),
]


@cocotb.test(timeout_time=200, timeout_unit="us")
async def test_reg_reset_values(dut):
    """REQ-111 + register-map.md 2: every register's reset value."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    expected = RESET_VALUES + [(G.REG_CONFIG, G.config_value(n, 8, 32),
                                "REQ-067")]
    for offset, exp, req in expected:
        got = await tb.read_dword(offset)
        assert got == exp, (
            f"{req}: BAR0+0x{offset:04x} reads 0x{got:08x} after reset; "
            f"register-map.md requires 0x{exp:08x}")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_reg_ro_writes_ignored(dut):
    """REQ-065..067, REQ-079, REQ-082, REQ-084: RO registers ignore writes."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    model = G.RegModel(n)

    for offset, req in RO_REGS:
        exp = model.read(offset)
        await mwr_dword(tb, offset, 0xFFFFFFFF)
        got = await tb.read_dword(offset)
        assert got == exp, (
            f"{req}: BAR0+0x{offset:04x} changed to 0x{got:08x} after a write "
            f"of 0xFFFFFFFF; it is read-only and must still read 0x{exp:08x}")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_scratch_rw_and_byte_enables(dut):
    """REQ-083, REQ-058, REQ-059, REQ-060, REQ-061: SCRATCH byte-granularity.

    BE bit j gates data[8j+7:8j], which is byte address (DWORD addr)+j
    (REQ-060).  Bytes whose BE is 0 must not change (REQ-059).  Reads ignore
    byte enables entirely and return the full DWORD (REQ-061).
    """
    tb = await make_tb(dut)
    model = G.RegModel(await discover_n(tb))

    await mwr_dword(tb, G.REG_SCRATCH, 0xDEADBEEF)
    model.write(G.REG_SCRATCH, 0xDEADBEEF)
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == model.scratch, (
        f"REQ-083: SCRATCH reads 0x{got:08x} after writing 0xDEADBEEF")

    for be, value in ((0b0001, 0x11111111), (0b0010, 0x22222222),
                      (0b0100, 0x33333333), (0b1000, 0x44444444),
                      (0b0101, 0x55555555), (0b1010, 0x66666666),
                      (0b0000, 0x77777777), (0b1111, 0x89ABCDEF)):
        await mwr_dword(tb, G.REG_SCRATCH, value, be=be)
        model.write(G.REG_SCRATCH, value, be)
        got = await tb.read_dword(G.REG_SCRATCH)
        assert got == model.scratch, (
            f"REQ-058/059/060: SCRATCH reads 0x{got:08x} after writing "
            f"0x{value:08x} with First BE = 0b{be:04b}; only the enabled "
            f"bytes may change, so the value must be 0x{model.scratch:08x}")

    # REQ-061: a read with restrictive byte enables still returns all 32 bits
    for fbe in (0b0001, 0b1000, 0b0110, 0b1111):
        req, cpl = await _read_with_be(tb, G.REG_SCRATCH, fbe)
        data = int.from_bytes(cpl.get_data(), "little")
        assert data == model.scratch, (
            f"REQ-061: MRd of SCRATCH with First BE = 0b{fbe:04b} returned "
            f"0x{data:08x}; reads ignore byte enables and must return the "
            f"full 0x{model.scratch:08x}")


async def _read_with_be(tb, offset, fbe):
    from tb_common import mrd
    return await mrd(tb, offset, length=1, first_be=fbe)


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_reg_reserved_raz_wi(dut):
    """REQ-055: reserved register offsets 0x0028..0x0FFF are RAZ/WI with SC."""
    tb = await make_tb(dut)
    for offset in (0x0028, 0x002C, 0x0040, 0x0100, 0x0800, 0x0FFC):
        got = await mrd_dword(tb, offset)
        assert got == 0, (
            f"REQ-055: reserved BAR0+0x{offset:04x} reads 0x{got:08x}, "
            "must read as zero")
        await mwr_dword(tb, offset, 0xA5A5A5A5)
        got = await mrd_dword(tb, offset)
        assert got == 0, (
            f"REQ-055: reserved BAR0+0x{offset:04x} reads 0x{got:08x} after a "
            "write; writes must be ignored")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_reg_ctrl_reads_zero_and_be_gated(dut):
    """REQ-068 and REQ-073: CTRL reads 0; CTRL acts only when BE[0] = 1."""
    tb = await make_tb(dut)
    await discover_n(tb)

    got = await tb.read_dword(G.REG_CTRL)
    assert got == 0, f"REQ-068: CTRL reads 0x{got:08x}, must always read 0"

    # START and SOFT_RESET live in byte 0.  A write whose First BE[0] is 0
    # must have no effect at all (REQ-073).
    for be in (0b1110, 0b0010, 0b1000, 0b0000):
        await mwr_dword(tb, G.REG_CTRL, G.CTRL_START, be=be)
        st = await tb.read_dword(G.REG_STATUS)
        assert st & (G.ST_BUSY | G.ST_DONE) == 0, (
            f"REQ-073: writing CTRL=0x{G.CTRL_START:08x} with First BE = "
            f"0b{be:04b} started an operation (STATUS = 0x{st:08x}); byte 0 "
            "is not enabled so the write must be ignored")
        oc = await tb.read_dword(G.REG_OP_COUNT)
        assert oc == 0, (
            f"REQ-073/REQ-084: OP_COUNT = {oc} after a byte-disabled CTRL "
            "write; no operation should have run")

    # With BE[0] = 1 it does start.
    await mwr_dword(tb, G.REG_CTRL, G.CTRL_START, be=0b0001)
    await wait_done(tb)
    got = await tb.read_dword(G.REG_CTRL)
    assert got == 0, (
        f"REQ-068: CTRL reads 0x{got:08x} after a START write; CTRL is "
        "write-only and self-clearing")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_status_w1c(dut):
    """REQ-075, REQ-076, REQ-078: W1C semantics and reserved bits of STATUS."""
    tb = await make_tb(dut)
    await discover_n(tb)

    await run_op_no_clear(tb)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE, (
        f"REQ-075: STATUS = 0x{st:08x}; DONE must be set after an operation")

    # Writing 0 to a W1C bit leaves it unchanged (REQ-076)
    await mwr_dword(tb, G.REG_STATUS, 0x00000000)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE, (
        f"REQ-076: STATUS = 0x{st:08x} after writing 0x00000000; writing 0 to "
        "a W1C bit must leave it set")

    # A write of 1 with the covering byte enable clears it (REQ-076)
    await mwr_dword(tb, G.REG_STATUS, G.ST_DONE, be=0b0001)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE == 0, (
        f"REQ-076: STATUS = 0x{st:08x}; writing DONE=1 with BE[0]=1 must "
        "clear it")

    # Reserved bits 31:5 read 0 and ignore writes (REQ-078)
    await mwr_dword(tb, G.REG_STATUS, 0xFFFFFFFF)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & ~G.ST_IMPLEMENTED_MASK == 0, (
        f"REQ-078: STATUS = 0x{st:08x} after writing 0xFFFFFFFF; bits 31:5 "
        "must read 0")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_status_w1c_byte_enable_gating(dut):
    """REQ-076: a W1C bit clears only if its byte enable is 1.

    All implemented STATUS bits live in byte 0, so a write of 0xFFFFFFFF with
    First BE = 0b1110 must clear nothing.
    """
    tb = await make_tb(dut)
    await discover_n(tb)
    await run_op_no_clear(tb)

    await mwr_dword(tb, G.REG_STATUS, 0xFFFFFFFF, be=0b1110)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE, (
        f"REQ-076: STATUS = 0x{st:08x}; a W1C write whose Byte Enable does "
        "not cover byte 0 must not clear DONE")

    await mwr_dword(tb, G.REG_STATUS, 0xFFFFFFFF, be=0b0001)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_DONE == 0, (
        f"REQ-076: STATUS = 0x{st:08x}; DONE must clear once BE[0] is 1")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_reg_irq_enable_rw_and_reserved(dut):
    """REQ-079 table: IRQ_ENABLE bits 4:1 are RW, bit 0 and 31:5 are RO 0."""
    tb = await make_tb(dut)
    model = G.RegModel(await discover_n(tb))

    await mwr_dword(tb, G.REG_IRQ_ENABLE, 0xFFFFFFFF)
    model.write(G.REG_IRQ_ENABLE, 0xFFFFFFFF)
    got = await tb.read_dword(G.REG_IRQ_ENABLE)
    assert got == model.irq_enable, (
        f"REQ-079: IRQ_ENABLE reads 0x{got:08x} after writing 0xFFFFFFFF; "
        f"only bits 4:1 are implemented, so it must read "
        f"0x{model.irq_enable:08x} (bit 0 is RO 0 -- there is no interrupt "
        "source for BUSY)")

    for value in (0x00000002, 0x00000004, 0x00000008, 0x00000010, 0x00000000):
        await mwr_dword(tb, G.REG_IRQ_ENABLE, value)
        model.write(G.REG_IRQ_ENABLE, value)
        got = await tb.read_dword(G.REG_IRQ_ENABLE)
        assert got == model.irq_enable, (
            f"REQ-079: IRQ_ENABLE reads 0x{got:08x} after writing "
            f"0x{value:08x}, expected 0x{model.irq_enable:08x}")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_reg_irq_status_and_irq_pin(dut):
    """REQ-012, REQ-079, REQ-080, REQ-081: IRQ_STATUS = STATUS & IRQ_ENABLE.

    REQ-080 was reworded in spec v1.1.0: `irq` must *track* `IRQ_STATUS != 0`
    **within 2 clock cycles in both directions**, not match it in the same
    cycle (which would have contradicted REQ-012's registered output).  The
    2-cycle window is measured from the cycle the responsible write commits,
    which is `t_beat + D_WR` (spec 9.6), so this test measures D_WR first.
    """
    tb = await make_tb(dut)
    await discover_n(tb)
    d_wr = await measure_d_wr(tb)
    dut._log.info("D_WR = %d cycles", d_wr)

    # DONE set but not enabled -> IRQ_STATUS 0, irq low
    await run_op_no_clear(tb)
    irqs = await tb.read_dword(G.REG_IRQ_STATUS)
    assert irqs == 0, (
        f"REQ-079: IRQ_STATUS = 0x{irqs:08x} with IRQ_ENABLE = 0; it must "
        "read STATUS & IRQ_ENABLE")
    assert int(dut.irq.value) == 0, (
        "REQ-080: irq asserted while IRQ_STATUS is 0")

    # --- assertion edge: enable DONE_EN, irq must follow within 2 cycles ----
    tlp = tb.make_mem_write(tb.bar0_addr + G.REG_IRQ_ENABLE,
                            G.ST_DONE.to_bytes(4, "little"))
    cap = tb.shim.start_capture()
    try:
        watcher = cocotb.start_soon(
            wait_value_cycle(dut.clk, dut.irq, 1, "irq", 64))
        t_beat = await inject_and_get_beat(tb, tlp)
        t_irq = await watcher
    finally:
        tb.shim.stop_capture()
    lag = t_irq - (t_beat + d_wr)
    assert 1 <= lag <= 2, (
        f"REQ-080: irq asserted {lag} cycles after IRQ_STATUS became "
        f"non-zero (write beat at cycle {t_beat}, D_WR = {d_wr}, irq high "
        f"from cycle {t_irq}).  Spec v1.1.0 requires assertion within 2 "
        "cycles; REQ-012 makes it a registered output, so 1 is expected")

    irqs = await tb.read_dword(G.REG_IRQ_STATUS)
    assert irqs == G.ST_DONE, (
        f"REQ-079: IRQ_STATUS = 0x{irqs:08x}, expected 0x{G.ST_DONE:08x} "
        "(STATUS.DONE & IRQ_ENABLE.DONE_EN)")

    # --- deassertion edge: W1C of STATUS.DONE, REQ-080 / REQ-081 -----------
    tlp = tb.make_mem_write(tb.bar0_addr + G.REG_STATUS,
                            G.ST_DONE.to_bytes(4, "little"))
    cap = tb.shim.start_capture()
    try:
        watcher = cocotb.start_soon(
            wait_value_cycle(dut.clk, dut.irq, 0, "irq", 64))
        t_beat = await inject_and_get_beat(tb, tlp)
        t_irq = await watcher
    finally:
        tb.shim.stop_capture()
    lag = t_irq - (t_beat + d_wr)
    assert 1 <= lag <= 2, (
        f"REQ-080/REQ-081: irq deasserted {lag} cycles after IRQ_STATUS "
        f"became zero (W1C beat at cycle {t_beat}, D_WR = {d_wr}).  Spec "
        "v1.1.0 allows at most 2")

    # REQ-081 again, this time by clearing IRQ_ENABLE
    await start_op(tb)
    await wait_done(tb)
    await wait_for(dut.irq, 1, "irq", 8, dut.clk)
    await mwr_dword(tb, G.REG_IRQ_ENABLE, 0x00000000, quiet_cycles=2)
    await wait_for(dut.irq, 0, "irq", 8, dut.clk)

    # REQ-079: IRQ_STATUS is RO
    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    await mwr_dword(tb, G.REG_IRQ_STATUS, 0xFFFFFFFF)
    irqs = await tb.read_dword(G.REG_IRQ_STATUS)
    st = await tb.read_dword(G.REG_STATUS)
    en = await tb.read_dword(G.REG_IRQ_ENABLE)
    assert irqs == (st & en), (
        f"REQ-079: IRQ_STATUS = 0x{irqs:08x} but STATUS & IRQ_ENABLE = "
        f"0x{st & en:08x}; IRQ_STATUS is read-only and continuously evaluated")


@cocotb.test(timeout_time=900, timeout_unit="us")
async def test_reg_write_path_delay_is_constant(dut):
    """REQ-122: D_WR is one fixed constant in 1..3.

    Spec 9.6 (v1.1.1) defines `D_WR = t_commit - t_beat` as a write-*visibility*
    property only: a write taken at `t` is readable at `t + D_WR`.  It is
    deliberately not a term in any latency formula.

    Two complementary checks:

    1. **Exact value.** Measured at the chip boundary through `irq`, which
       REQ-012 makes a registered (exactly 1 cycle) copy of |IRQ_STATUS, so
       `D_WR = t_irq - t_beat - 1`.  Repeated for a second register offset and
       the opposite direction (W1C of STATUS.DONE, irq falling), for three
       byte-enable patterns, and for the first / middle / last DWORD of a
       multi-DWORD burst.  Every measurement must give the identical value.

    2. **Visibility invariant across regions.** `irq` only reflects
       `reg_file` state, so the exact measurement cannot reach `mem_a`,
       `mem_b` or `mem_c`.  For those the invariant is checked in its
       read-after-write form: an `MRd` of the just-written location, injected
       with zero idle cycles behind the `MWr`, must return the new value --
       for every region, every byte-enable pattern and every position within
       a burst.  If any region's write path committed later than its request
       retires, that read would return stale data.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    measurements = []

    base = await measure_d_wr(tb)
    measurements.append(("IRQ_ENABLE, single DW, BE=1111, irq rising", base))

    measurements.append(
        ("STATUS W1C, single DW, BE=1111, irq falling",
         await measure_d_wr_falling(tb)))

    for be in (0b0011, 0b0001, 0b1111):
        measurements.append(
            (f"IRQ_ENABLE, single DW, BE={be:04b}",
             await measure_d_wr(tb, be=be)))

    # Burst position: IRQ_ENABLE (0x0014) first, middle and last DWORD.
    # 0x000C (CTRL) is deliberately never inside these bursts.
    for burst, where in (((0x0014, 4, 0), "first DWORD of a 4 DW burst"),
                         ((0x0010, 3, 1), "middle DWORD of a 3 DW burst"),
                         ((0x0010, 2, 1), "last DWORD of a 2 DW burst")):
        measurements.append(
            (f"IRQ_ENABLE as the {where}",
             await measure_d_wr(tb, burst=burst)))

    for what, value in measurements:
        dut._log.info("D_WR = %d  (%s)", value, what)

    assert 1 <= base <= 3, (
        f"REQ-122: D_WR measured as {base} cycles; spec 9.6 requires "
        "1 <= D_WR <= 3")

    bad = [(what, v) for what, v in measurements if v != base]
    assert not bad, (
        f"REQ-122: D_WR is not a single constant.  Baseline {base} cycles "
        f"(IRQ_ENABLE, single DW, BE=1111); differing measurements: "
        + "; ".join(f"{what} -> {v}" for what, v in bad) +
        ".  Spec 9.6 requires D_WR to be identical regardless of offset, "
        "byte enables and position within a burst.")

    dut._log.info("REQ-122: D_WR = %d cycles, constant across %d "
                  "measurements at N=%d", base, len(measurements), n)

    # --- part 2: write-visibility invariant, every region ----------------
    regions = [("reg_file (SCRATCH)", G.REG_SCRATCH, 1),
               ("mem_a", G.MEM_A_BASE, n * n // 4),
               ("mem_b", G.MEM_B_BASE, n * n // 4),
               ("mem_c", G.MEM_C_BASE, n * n)]
    patterns = [(0xF, 0xA5A5A5A5), (0x1, 0x000000C3), (0x8, 0xD7000000),
                (0x6, 0x00BEEF00), (0xF, 0x00000000)]

    for name, base_off, n_dwords in regions:
        shadow = {}
        for k, (be, value) in enumerate(patterns):
            word = k % max(1, n_dwords)
            off = base_off + 4 * word
            prev = shadow.get(off, 0)
            expect = 0
            for j in range(4):
                byte = ((value if (be >> j) & 1 else prev) >> (8 * j)) & 0xFF
                expect |= byte << (8 * j)

            # MWr immediately followed by an MRd of the same DWORD, with no
            # idle cycle between eop and the next sop.
            cap = tb.shim.start_capture()
            try:
                await tb.shim.inject(tb.make_mem_write(
                    tb.bar0_addr + off,
                    int(value).to_bytes(4, "little"), first_be=be))
                rd = tb.make_mem_read(tb.bar0_addr + off, length=1)
                await tb.shim.inject(rd)
                cpl = await tb._get_capture(cap, 20000, rd)
            finally:
                tb.shim.stop_capture()

            got = int.from_bytes(cpl.get_data(), "little")
            assert got == expect, (
                f"REQ-122: in {name}, a read of BAR0+0x{off:04x} issued with "
                f"zero idle cycles behind the write returned 0x{got:08x}, "
                f"expected 0x{expect:08x} (wrote 0x{value:08x} with First BE "
                f"= 0b{be:04b} over 0x{prev:08x}).  A write taken at t must "
                "be readable at t + D_WR, and D_WR must be the same in every "
                "region")
            shadow[off] = expect

    # Leave the operand storages as we found them.
    await tb.mem_write(G.MEM_A_BASE, bytes(n * n))
    await tb.mem_write(G.MEM_B_BASE, bytes(n * n))
    await tb.mem_write(G.MEM_C_BASE, bytes(4 * n * n))
    await mwr_dword(tb, G.REG_SCRATCH, 0x00000000)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_start_and_soft_reset_while_busy(dut):
    """REQ-124: START|SOFT_RESET written together while BUSY.

    SOFT_RESET takes full effect, START is ignored entirely, and
    ERR_START_BUSY must read 0 afterwards.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)
    a = [[(i + j) % 5 - 2 for j in range(n)] for i in range(n)]
    b = [[(i * 2 + j) % 7 - 3 for j in range(n)] for i in range(n)]
    await load_ab(tb, a, b, n)

    # Two CTRL writes back-to-back: the second lands inside the 4N+2 window.
    await mwr_burst(tb, [(G.REG_CTRL, G.CTRL_START, 0xF),
                         (G.REG_CTRL, G.CTRL_START | G.CTRL_SOFT_RESET, 0xF)])

    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_START_BUSY == 0, (
        f"REQ-124: STATUS = 0x{st:08x} after writing START|SOFT_RESET while "
        "BUSY; ERR_START_BUSY (bit 2) must NOT be left set")
    assert st == 0, (
        f"REQ-124/REQ-071: STATUS = 0x{st:08x}; SOFT_RESET must take full "
        "effect, clearing BUSY, DONE and every error bit")
    pc = await tb.read_dword(G.REG_PERF_CYCLES)
    assert pc == 0, (
        f"REQ-124/REQ-071: PERF_CYCLES = {pc} after SOFT_RESET, must be 0")
    oc = await tb.read_dword(G.REG_OP_COUNT)
    assert oc == 0, (
        f"REQ-124: OP_COUNT = {oc}; the aborted operation never completed and "
        "the START written alongside SOFT_RESET must be ignored entirely")

    # The device must still work afterwards.
    await run_op(tb)
    got = await read_c(tb, n)
    assert_matrix_equal(got, G.matmul_golden(a, b, n),
                        "C after a START|SOFT_RESET abort and a clean re-run")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_op_count_and_perf_cycles(dut):
    """REQ-082, REQ-084, REQ-102: OP_COUNT counts ops, PERF_CYCLES is 4N+2."""
    tb = await make_tb(dut)
    n = await discover_n(tb)
    expected_cycles = G.t_mm(n)

    for i in range(1, 4):
        await run_op(tb)
        oc = await tb.read_dword(G.REG_OP_COUNT)
        assert oc == i, (
            f"REQ-084: OP_COUNT = {oc} after {i} completed operations, "
            f"expected {i}")
        pc = await tb.read_dword(G.REG_PERF_CYCLES)
        assert pc == expected_cycles, (
            f"REQ-102: PERF_CYCLES = {pc} after operation {i}; spec 12.5 "
            f"fixes the operation at 4*N+2 = {expected_cycles} cycles for "
            f"N = {n}, so this register is a constant")


@cocotb.test(timeout_time=500, timeout_unit="us")
async def test_reg_soft_reset(dut):
    """REQ-071, REQ-072, REQ-084, REQ-092: what SOFT_RESET does and does not."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    # Build up some state: SCRATCH, IRQ_ENABLE, A/B/C, OP_COUNT, DONE, errors.
    rng_a = [[(i + j) % 7 - 3 for j in range(n)] for i in range(n)]
    rng_b = [[(i * 3 + j) % 5 - 2 for j in range(n)] for i in range(n)]
    await load_ab(tb, rng_a, rng_b, n)
    await mwr_dword(tb, G.REG_SCRATCH, 0x0BADF00D)
    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    await run_op_no_clear(tb)

    c_before = await read_c(tb, n)
    exp_c = G.matmul_golden(rng_a, rng_b, n)
    assert_matrix_equal(c_before, exp_c, "C before SOFT_RESET")

    # Raise an error bit too, so we can see it cleared.  The two CTRL writes
    # go out back-to-back so that the second definitely lands inside the
    # 4N+2 cycle window of the first (REQ-070).
    await mwr_burst(tb, [(G.REG_CTRL, G.CTRL_START, 0xF),
                         (G.REG_CTRL, G.CTRL_START, 0xF)])
    await wait_done(tb)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_START_BUSY, (
        f"REQ-070: STATUS = 0x{st:08x}; a second START while BUSY must set "
        "ERR_START_BUSY")

    await mwr_dword(tb, G.REG_CTRL, G.CTRL_SOFT_RESET)

    st = await tb.read_dword(G.REG_STATUS)
    assert st == 0, (
        f"REQ-071: STATUS = 0x{st:08x} after SOFT_RESET; BUSY, DONE and all "
        "error bits must be cleared")
    pc = await tb.read_dword(G.REG_PERF_CYCLES)
    assert pc == 0, (
        f"REQ-071: PERF_CYCLES = {pc} after SOFT_RESET, must be 0")
    sc = await tb.read_dword(G.REG_SCRATCH)
    assert sc == 0x0BADF00D, (
        f"REQ-071: SCRATCH = 0x{sc:08x} after SOFT_RESET; it must be left "
        "unchanged")
    en = await tb.read_dword(G.REG_IRQ_ENABLE)
    assert en == G.ST_DONE, (
        f"REQ-071: IRQ_ENABLE = 0x{en:08x} after SOFT_RESET; it must be left "
        "unchanged")
    oc = await tb.read_dword(G.REG_OP_COUNT)
    assert oc == 2, (
        f"REQ-084: OP_COUNT = {oc} after SOFT_RESET; it counts operations "
        "since rst and is explicitly NOT cleared by SOFT_RESET (expected 2)")
    c_after = await read_c(tb, n)
    assert_matrix_equal(
        c_after, exp_c, "C after SOFT_RESET while the engine was IDLE",
        extra="  REQ-071 (v1.1.0, narrowed): SOFT_RESET shall not itself "
              "modify any word of mem_c.  The engine is IDLE here, so no "
              "drain is in flight and REQ-125's mixed-state case does not "
              "apply: C must be bit-identical.")

    # REQ-121 / REQ-111 check that config space survives SOFT_RESET
    bar0 = await tb.cfg_read_dword(0x10)
    assert bar0 == (tb.bar0_addr & 0xFFFFC000), (
        f"REQ-071: cfg BAR0 = 0x{bar0:08x} after SOFT_RESET; the entire "
        f"configuration space must be untouched (expected "
        f"0x{tb.bar0_addr & 0xFFFFC000:08x})")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_reg_soft_reset_precedence(dut):
    """REQ-072: SOFT_RESET wins when both CTRL bits are written in one DWORD."""
    tb = await make_tb(dut)
    await discover_n(tb)

    await mwr_dword(tb, G.REG_CTRL, G.CTRL_START | G.CTRL_SOFT_RESET)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & (G.ST_BUSY | G.ST_DONE) == 0, (
        f"REQ-072: STATUS = 0x{st:08x} after writing START|SOFT_RESET; "
        "SOFT_RESET takes precedence and no operation may start")
    oc = await tb.read_dword(G.REG_OP_COUNT)
    assert oc == 0, (
        f"REQ-072/REQ-084: OP_COUNT = {oc}; no operation may have been "
        "started by a CTRL write that also set SOFT_RESET")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_access_while_busy(dut):
    """REQ-064: register reads and writes are legal while BUSY is 1."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    await start_op(tb)
    # The operation is 4N+2 cycles; a register access is longer than that, so
    # observing BUSY==1 is not guaranteed.  What REQ-064 demands is that the
    # accesses *work* -- they must complete with SC and the right data.
    st = await tb.read_dword(G.REG_STATUS)
    assert st & ~G.ST_IMPLEMENTED_MASK == 0, (
        f"REQ-064/REQ-078: STATUS read during/after an operation returned "
        f"0x{st:08x}")
    await mwr_dword(tb, G.REG_SCRATCH, 0x12345678)
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0x12345678, (
        f"REQ-064: SCRATCH write while the engine was running did not take "
        f"effect (reads 0x{got:08x})")
    await wait_done(tb)


async def run_op_no_clear(tb):
    """START and wait for DONE, leaving DONE set."""
    await start_op(tb)
    return await wait_done(tb)
