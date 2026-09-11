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
                       start_op, wait_done, wait_for, assert_matrix_equal)

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


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_reg_irq_status_and_irq_pin(dut):
    """REQ-012, REQ-079, REQ-080, REQ-081: IRQ_STATUS = STATUS & IRQ_ENABLE."""
    tb = await make_tb(dut)
    await discover_n(tb)

    # DONE set but not enabled -> IRQ_STATUS 0, irq low
    await run_op_no_clear(tb)
    irqs = await tb.read_dword(G.REG_IRQ_STATUS)
    assert irqs == 0, (
        f"REQ-079: IRQ_STATUS = 0x{irqs:08x} with IRQ_ENABLE = 0; it must "
        "read STATUS & IRQ_ENABLE")
    assert int(dut.irq.value) == 0, (
        "REQ-080: irq asserted while IRQ_STATUS is 0")

    # Enable DONE -> IRQ_STATUS reflects it and irq asserts
    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    irqs = await tb.read_dword(G.REG_IRQ_STATUS)
    assert irqs == G.ST_DONE, (
        f"REQ-079: IRQ_STATUS = 0x{irqs:08x}, expected 0x{G.ST_DONE:08x} "
        "(STATUS.DONE & IRQ_ENABLE.DONE_EN)")
    await wait_for(dut.irq, 1, "irq", 8, dut.clk)

    # REQ-081: clearing STATUS.DONE deasserts irq within 2 cycles
    await mwr_dword(tb, G.REG_STATUS, G.ST_DONE, quiet_cycles=2)
    await wait_for(dut.irq, 0, "irq", 8, dut.clk)

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
    assert_matrix_equal(c_after, exp_c, "C after SOFT_RESET",
                        extra="  REQ-092: SOFT_RESET must not clear mem_c.")

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
