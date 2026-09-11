"""
Smoke tests: reset state, enumeration, an ID read, and one trivial multiply.

Requirements exercised here: REQ-006, REQ-010, REQ-012, REQ-065, REQ-067,
REQ-105, REQ-108, REQ-109, REQ-111, REQ-112, REQ-114, REQ-116.
"""

import cocotb
from cocotb.triggers import ClockCycles

from tb_common import (G, Host, discover_n, make_tb, read_c, run_op,
                       assert_matrix_equal, load_ab)

TOP_PORTS = [
    ("clk", 1), ("rst", 1),
    ("rx_tlp_data", 32), ("rx_tlp_sop", 1), ("rx_tlp_eop", 1),
    ("rx_tlp_valid", 1), ("rx_tlp_ready", 1),
    ("tx_tlp_data", 32), ("tx_tlp_sop", 1), ("tx_tlp_eop", 1),
    ("tx_tlp_valid", 1), ("tx_tlp_ready", 1),
    ("irq", 1),
]


@cocotb.test(timeout_time=100, timeout_unit="us")
async def test_smoke_top_ports_exist(dut):
    """REQ-010: matmul_top has exactly the spec 6.1 ports, with these widths.

    (The "no other port exists" half of REQ-010 is a structural check; it is
    enforced by tb/tools/check_rtl_rules.py, run from `make lint`.)
    """
    missing = []
    for name, width in TOP_PORTS:
        try:
            handle = getattr(dut, name)
        except AttributeError:
            missing.append(f"{name} (absent)")
            continue
        got = len(handle) if width > 1 else 1
        if width > 1 and got != width:
            missing.append(f"{name} is {got} bits, spec 6.1 says {width}")
    assert not missing, (
        "REQ-010: top-level port list does not match docs/spec.md 6.1:\n  "
        + "\n  ".join(missing))


@cocotb.test(timeout_time=100, timeout_unit="us")
async def test_smoke_reset_state(dut):
    """REQ-006/REQ-108/REQ-109/REQ-111: the spec 13.4 reset state.

    The shim's always-on protocol checker verifies rx_tlp_ready,
    tx_tlp_valid/sop/eop are 0 for every cycle rst is asserted; this test adds
    the sideband and the post-reset register values.
    """
    tb = await Host.create(dut)          # includes a >= 2 cycle reset
    assert int(dut.irq.value) == 0, (
        f"REQ-111/REQ-080: irq = {int(dut.irq.value)} after reset, expected 0")

    await tb.enumerate()
    for offset, expect, req in (
        (G.REG_STATUS, 0x00000000, "REQ-074/REQ-111"),
        (G.REG_IRQ_ENABLE, 0x00000000, "REQ-111"),
        (G.REG_IRQ_STATUS, 0x00000000, "REQ-079/REQ-111"),
        (G.REG_PERF_CYCLES, 0x00000000, "REQ-082/REQ-111"),
        (G.REG_SCRATCH, 0x00000000, "REQ-083/REQ-111"),
        (G.REG_OP_COUNT, 0x00000000, "REQ-084/REQ-111"),
        (G.REG_CTRL, 0x00000000, "REQ-068"),
    ):
        got = await tb.read_dword(offset)
        assert got == expect, (
            f"{req}: BAR0+0x{offset:04x} reads 0x{got:08x} after reset, "
            f"spec 13.4 says 0x{expect:08x}")


@cocotb.test(timeout_time=200, timeout_unit="us")
async def test_smoke_enumerate_and_read_id(dut):
    """REQ-112, REQ-065, REQ-066, REQ-067, REQ-114: enumerate, then read IDs."""
    tb = await Host.create(dut)

    # Before any enumeration: cfg offset 0x00 must already identify the device
    ident = await tb.cfg_read_dword(0x00)
    assert ident == G.CFG_ID_DWORD, (
        f"REQ-112: CfgRd0 of cfg 0x00 returned 0x{ident:08x}, spec 13.4 "
        f"requires 0x{G.CFG_ID_DWORD:08x} (Device ID 0x8000, Vendor ID 0x1234)")

    await tb.enumerate()

    got = await tb.read_dword(G.REG_ID)
    assert got == G.ID_VALUE, (
        f"REQ-065: ID (BAR0+0x0000) reads 0x{got:08x}, register-map.md 3.1 "
        f"requires 0x{G.ID_VALUE:08x} (ASCII 'MAT1')")

    got = await tb.read_dword(G.REG_VERSION)
    assert got == G.VERSION_VALUE, (
        f"REQ-066: VERSION reads 0x{got:08x}, expected "
        f"0x{G.VERSION_VALUE:08x}")

    n = await discover_n(tb)
    cfg = await tb.read_dword(G.REG_CONFIG)
    assert cfg == G.config_value(n, 8, 32), (
        f"REQ-067: CONFIG reads 0x{cfg:08x}; for N={n}, DW=8, ACCW=32 the "
        f"spec requires 0x{G.config_value(n, 8, 32):08x}")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_smoke_single_multiply(dut):
    """REQ-116/REQ-105: the spec 15 sequence with a one-product matrix pair.

    A has a single non-zero at [0][0] and B a single non-zero at [0][0], so
    C[0][0] is the only non-zero element -- the NxN equivalent of a 1x1
    multiply.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    a = [[0] * n for _ in range(n)]
    b = [[0] * n for _ in range(n)]
    a[0][0] = 7
    b[0][0] = 6

    await load_ab(tb, a, b, n)
    await run_op(tb)

    exp = G.matmul_golden(a, b, n)
    got = await read_c(tb, n)
    assert_matrix_equal(got, exp, "C = A x B after a single START")

    # REQ-116: the whole sequence completes with no error bit set.
    st = await tb.read_dword(G.REG_STATUS)
    assert st & (G.ST_ERR_UNSUP_REQ | G.ST_ERR_WRITE_BUSY
                 | G.ST_ERR_START_BUSY) == 0, (
        f"REQ-116: STATUS = 0x{st:08x} after the normal operating sequence; "
        "no error bit may be set")
    assert st & G.ST_BUSY == 0, (
        f"REQ-074: STATUS.BUSY still set (0x{st:08x}) after DONE")
