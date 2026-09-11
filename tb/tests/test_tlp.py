"""
Transaction-layer tests: stream contract, header decode, completion fields,
unsupported requests, byte enables and bursts.

Requirements: REQ-001..REQ-009, REQ-013..REQ-044, REQ-050..REQ-061.
"""

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer

from cocotbext.pcie.core.tlp import Tlp, TlpType, TlpAttr, TlpTc, CplStatus
from cocotbext.pcie.core.utils import PcieId

from tb_common import (G, make_tb, mrd, mrd_dword, mwr_dword, discover_n,
                       wait_for, TbTimeout)

CPL_FMT_TYPE = (0b000, 0b01010)
CPLD_FMT_TYPE = (0b010, 0b01010)


# ---------------------------------------------------------------------------
# Self-check of the spec's byte-enable tables against the reference library
# ---------------------------------------------------------------------------
@cocotb.test(timeout_time=50, timeout_unit="us")
async def test_tlp_be_tables_match_reference_library(dut):
    """spec 7.5 claims its BE tables match cocotbext-pcie bit-for-bit.

    If this fails, the spec and the reference library disagree and the
    *expected values* used everywhere else in this file are wrong; report it to
    spec-writer rather than touching the DUT.
    """
    for length in (1, 2, 5, 32):
        for fbe in range(16):
            for lbe in range(16):
                t = Tlp()
                t.fmt_type = TlpType.MEM_READ
                t.length = length
                t.first_be = fbe
                t.last_be = lbe if length > 1 else 0
                assert G.first_be_offset(fbe) == t.get_first_be_offset(), (
                    f"spec 7.5 first_be_offset({fbe:#06b}) = "
                    f"{G.first_be_offset(fbe)} but cocotbext-pcie says "
                    f"{t.get_first_be_offset()}")
                assert G.last_be_offset(fbe, lbe, length) == \
                    t.get_last_be_offset(), (
                        f"spec 7.5 last_be_offset(fbe={fbe:#06b}, "
                        f"lbe={lbe:#06b}, len={length}) disagrees with "
                        "cocotbext-pcie")
                assert G.be_byte_count(length, fbe, t.last_be) == \
                    t.get_be_byte_count(), "spec 7.5 be_byte_count disagrees"


# ---------------------------------------------------------------------------
# Stream contract (spec 5.2)
# ---------------------------------------------------------------------------
@cocotb.test(timeout_time=100, timeout_unit="us")
async def test_tlp_ready_not_combinational_on_valid(dut):
    """REQ-003: rx_tlp_ready must not depend combinationally on rx_tlp_valid."""
    tb = await make_tb(dut)
    await tb.settle()

    tb.shim.rx_paused = True
    try:
        for _ in range(8):
            await RisingEdge(dut.clk)
            dut.rx_tlp_valid.value = 0
            dut.rx_tlp_sop.value = 0
            dut.rx_tlp_eop.value = 0
            dut.rx_tlp_data.value = 0
            await Timer(1, "ns")
            before = int(dut.rx_tlp_ready.value)

            dut.rx_tlp_valid.value = 1
            dut.rx_tlp_sop.value = 1
            dut.rx_tlp_data.value = 0x40000001
            await Timer(1, "ns")        # deliberately no clock edge
            after = int(dut.rx_tlp_ready.value)

            assert before == after, (
                f"REQ-003: rx_tlp_ready changed from {before} to {after} "
                "within the same clock cycle in response to rx_tlp_valid "
                "rising; ready must not depend combinationally on valid")

            dut.rx_tlp_valid.value = 0
            dut.rx_tlp_sop.value = 0
            await Timer(1, "ns")
    finally:
        dut.rx_tlp_valid.value = 0
        dut.rx_tlp_sop.value = 0
        dut.rx_tlp_eop.value = 0
        await RisingEdge(dut.clk)
        tb.shim.rx_paused = False


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_idle_and_stall_cycles(dut):
    """REQ-002, REQ-005: idle and stall cycles anywhere, no data loss.

    Runs the whole bring-up and a register read/write sequence with a 50%
    chance of an idle inbound cycle and a 50% chance of outbound backpressure.
    """
    tb = await make_tb(dut, rx_gap_prob=0.5, tx_stall_prob=0.5)
    await discover_n(tb)
    for value in (0x00000000, 0xFFFFFFFF, 0x0F0F0F0F, 0x12345678):
        await mwr_dword(tb, G.REG_SCRATCH, value)
        got = await tb.read_dword(G.REG_SCRATCH)
        assert got == value, (
            f"REQ-002/REQ-005: SCRATCH reads 0x{got:08x} after writing "
            f"0x{value:08x} with random idle/stall cycles; the stream "
            "contract must be lossless")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_tx_ready_held_low_no_deadlock(dut):
    """REQ-007, REQ-015: tx_tlp_ready low indefinitely loses nothing."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0xCAFEBABE)

    tb.shim.tx_force_stall = True
    cap = tb.shim.start_capture()
    try:
        req = tb.make_mem_read(tb.bar0_addr + G.REG_SCRATCH, length=1)
        await tb.shim.inject(req)
        await ClockCycles(dut.clk, 300)       # 300 cycles of hard backpressure
        assert cap.empty(), (
            "internal: a completion was captured while tx_tlp_ready was "
            "forced low")
        tb.shim.tx_force_stall = False
        cpl = await tb._get_capture(cap, 20000, req)
    finally:
        tb.shim.tx_force_stall = False
        tb.shim.stop_capture()

    assert cpl.status == CplStatus.SC, (
        f"REQ-007: completion status {cpl.status!r} after 300 cycles of "
        "tx_tlp_ready backpressure")
    data = int.from_bytes(cpl.get_data(), "little")
    assert data == 0xCAFEBABE, (
        f"REQ-007: completion payload 0x{data:08x} after prolonged "
        "backpressure, expected 0xCAFEBABE -- the completion was corrupted")

    # And the DUT still works afterwards (REQ-015: no deadlock).
    await mwr_dword(tb, G.REG_SCRATCH, 0x5A5A5A5A)
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0x5A5A5A5A, (
        f"REQ-015: SCRATCH reads 0x{got:08x} after backpressure was released; "
        "the transaction layer did not resume correctly")


# ---------------------------------------------------------------------------
# Completion header fields (spec 7.4, 7.5)
# ---------------------------------------------------------------------------
def _check_reserved_fields(cpl, what):
    """REQ-024: every Completion has T9=T8=LN=TH=TD=EP=0, AT=00, BCM=0,
    DW2 bit 7 = 0."""
    dw0, dw1, dw2 = cpl.raw_dwords[0], cpl.raw_dwords[1], cpl.raw_dwords[2]
    checks = [
        ("T9 (DW0[23])", (dw0 >> 23) & 1),
        ("T8 (DW0[19])", (dw0 >> 19) & 1),
        ("LN (DW0[17])", (dw0 >> 17) & 1),
        ("TH (DW0[16])", (dw0 >> 16) & 1),
        ("TD (DW0[15])", (dw0 >> 15) & 1),
        ("EP (DW0[14])", (dw0 >> 14) & 1),
        ("AT (DW0[11:10])", (dw0 >> 10) & 3),
        ("BCM (DW1[12])", (dw1 >> 12) & 1),
        ("R (DW2[7])", (dw2 >> 7) & 1),
    ]
    bad = [f"{n} = {v}" for n, v in checks if v != 0]
    assert not bad, (
        f"REQ-024: reserved/fixed fields non-zero in the Completion for "
        f"{what}: " + ", ".join(bad) +
        f"\n  raw header DWORDs: {[hex(d) for d in cpl.raw_dwords[:3]]}")


def _check_fmt_type(cpl, expect, what):
    dw0 = cpl.raw_dwords[0]
    fmt = (dw0 >> 29) & 0x7
    typ = (dw0 >> 24) & 0x1F
    assert (fmt, typ) == expect, (
        f"{what}: Fmt/Type = {fmt:#05b}/{typ:#07b}, expected "
        f"{expect[0]:#05b}/{expect[1]:#07b} (spec 7.2.4)")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_completion_reserved_fields_and_ids(dut):
    """REQ-024, REQ-025, REQ-026, REQ-027, REQ-052."""
    tb = await make_tb(dut)

    for tag in (0x00, 0x01, 0x5A, 0xFF):
        for tc in (TlpTc.TC0, TlpTc.TC3, TlpTc.TC7):
            for attr in (TlpAttr(0), TlpAttr(0x1), TlpAttr(0x2), TlpAttr(0x4),
                         TlpAttr(0x7)):
                req = tb.make_mem_read(tb.bar0_addr + G.REG_ID, length=1,
                                       tag=tag, tc=tc, attr=attr)
                req.requester_id = PcieId(0x12, 0x03, 0x05)
                cpl = await tb.raw_request(req)
                what = (f"MRd tag=0x{tag:02x} TC={int(tc)} "
                        f"Attr=0b{int(attr):03b}")
                _check_fmt_type(cpl, CPLD_FMT_TYPE, what)
                _check_reserved_fields(cpl, what)
                assert cpl.tag == tag, (
                    f"REQ-026: completion Tag = 0x{cpl.tag:02x}, request had "
                    f"0x{tag:02x}")
                assert int(cpl.requester_id) == int(req.requester_id), (
                    f"REQ-026: completion Requester ID = {cpl.requester_id}, "
                    f"request had {req.requester_id}")
                assert int(cpl.tc) == int(tc), (
                    f"REQ-025: completion TC = {int(cpl.tc)}, request had "
                    f"{int(tc)}")
                assert int(cpl.attr) == int(attr), (
                    f"REQ-025: completion Attr = 0b{int(cpl.attr):03b}, "
                    f"request had 0b{int(attr):03b}")
                assert int(cpl.completer_id) == int(tb.expected_completer_id), (
                    f"REQ-027/REQ-052: completion Completer ID = "
                    f"{cpl.completer_id}, but the last accepted Type 0 config "
                    f"request carried {tb.expected_completer_id}")


@cocotb.test(timeout_time=200, timeout_unit="us")
async def test_tlp_completer_id_capture(dut):
    """REQ-052: cfg_completer_id follows the last accepted Type 0 request."""
    tb = await make_tb(dut)

    for bus in (0x01, 0x37, 0xFF):
        dev_id = PcieId(bus, 0, 0)
        await tb.cfg_read_dword(0x00, dev_id=dev_id)
        req = tb.make_mem_read(tb.bar0_addr + G.REG_ID, length=1)
        cpl = await tb.raw_request(req)
        assert int(cpl.completer_id) == int(dev_id), (
            f"REQ-052: after a CfgRd0 addressed to {dev_id}, the DUT's "
            f"completions carry Completer ID {cpl.completer_id}; it must "
            "capture the request's Completer ID")
    tb.dev_id = PcieId(tb.dev.pcie_id.bus, 0, 0)
    await tb.cfg_read_dword(0x00)


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_tlp_mrd_completion_fields(dut):
    """REQ-028..REQ-032, REQ-061: Length, Byte Count, Lower Address, payload."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0x89ABCDEF)

    cases = [
        # (offset, length, first_be, last_be)
        (G.REG_SCRATCH, 1, 0b1111, 0b0000),
        (G.REG_SCRATCH, 1, 0b0001, 0b0000),
        (G.REG_SCRATCH, 1, 0b1000, 0b0000),
        (G.REG_SCRATCH, 1, 0b0110, 0b0000),
        (G.REG_SCRATCH, 1, 0b0000, 0b0000),
        (0x0000, 2, 0b1111, 0b1111),
        (0x0000, 2, 0b1110, 0b0111),
        (0x0000, 4, 0b1100, 0b0011),
        (0x0000, 8, 0b1111, 0b0001),
        (G.MEM_C_BASE, 32, 0b1111, 0b1111),
        (G.MEM_C_BASE + 0x40, 16, 0b1000, 0b0001),
    ]

    for offset, length, fbe, lbe in cases:
        req, cpl = await mrd(tb, offset, length=length,
                             first_be=fbe, last_be=lbe)
        what = (f"MRd BAR0+0x{offset:04x} Length={length} "
                f"FirstBE=0b{fbe:04b} LastBE=0b{lbe:04b}")
        _check_fmt_type(cpl, CPLD_FMT_TYPE, what)
        assert cpl.status == CplStatus.SC, (
            f"{what}: status {cpl.status!r}, expected SC")
        assert cpl.length == length, (
            f"REQ-028: {what} -> completion Length = {cpl.length}, must equal "
            f"the request Length {length}")
        assert len(cpl.data) == 4 * length, (
            f"REQ-028/REQ-032: {what} -> {len(cpl.data)} payload bytes, "
            f"expected {4 * length} (full DWORDs, including BE=0 bytes)")
        exp_bc = G.be_byte_count(length, fbe, req.last_be)
        assert cpl.byte_count == exp_bc, (
            f"REQ-029: {what} -> Byte Count = {cpl.byte_count}, spec 7.5 "
            f"gives Length*4 - first_be_offset - last_be_offset = {exp_bc}")
        exp_la = G.lower_address(req.address, fbe)
        assert cpl.lower_address == exp_la, (
            f"REQ-030: {what} -> Lower Address = 0x{cpl.lower_address:02x}, "
            f"spec 7.5 gives (Address + first_be_offset) & 0x7F = "
            f"0x{exp_la:02x}")
        _check_reserved_fields(cpl, what)

    # REQ-031: exactly one completion per MRd -- the shim's capture queue must
    # be empty after each request (raw_request would have left extras behind).
    assert tb.shim.capture is None
    assert tb.shim.tx_in_packet is False, (
        "REQ-023: the DUT left a completion half-transmitted")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_mrd_payload_is_full_dwords(dut):
    """REQ-032, REQ-061: bytes with BE = 0 are still returned."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0xA1B2C3D4)
    for fbe in (0b0001, 0b0010, 0b0100, 0b1000, 0b0000, 0b1001):
        req, cpl = await mrd(tb, G.REG_SCRATCH, length=1, first_be=fbe)
        data = int.from_bytes(cpl.get_data(), "little")
        assert data == 0xA1B2C3D4, (
            f"REQ-032/REQ-061: MRd of SCRATCH with First BE = 0b{fbe:04b} "
            f"returned payload 0x{data:08x}; the full DWORD 0xA1B2C3D4 must "
            "be returned regardless of byte enables")


@cocotb.test(timeout_time=200, timeout_unit="us")
async def test_tlp_cfg_completion_fields(dut):
    """REQ-033, REQ-034: CfgRd0 and CfgWr0 completion shapes."""
    tb = await make_tb(dut)

    for fbe in (0b1111, 0b0001, 0b1000, 0b0000):
        req = tb.make_cfg_read(0x00, be=fbe)
        cpl = await tb.raw_request(req)
        what = f"CfgRd0 cfg 0x00 First BE = 0b{fbe:04b}"
        _check_fmt_type(cpl, CPLD_FMT_TYPE, what)
        assert cpl.status == CplStatus.SC, f"{what}: status {cpl.status!r}"
        assert cpl.length == 1, (
            f"REQ-033: {what} -> Length = {cpl.length}, must be 1")
        assert cpl.byte_count == 4, (
            f"REQ-033: {what} -> Byte Count = {cpl.byte_count}, must be 4")
        assert cpl.lower_address == 0, (
            f"REQ-033: {what} -> Lower Address = {cpl.lower_address}, must "
            "be 0")
        val = int.from_bytes(cpl.get_data(), "little")
        assert val == G.CFG_ID_DWORD, (
            f"REQ-033: {what} -> 0x{val:08x}; the full 32-bit DWORD "
            f"0x{G.CFG_ID_DWORD:08x} must be returned regardless of BE")
        _check_reserved_fields(cpl, what)

    cpl = await tb.cfg_write_dword(0x0C, 0x00000040)   # Cache Line Size, RW
    what = "CfgWr0 cfg 0x0C"
    _check_fmt_type(cpl, CPL_FMT_TYPE, what)
    assert cpl.length == 0, (
        f"REQ-034: {what} -> Length = {cpl.length}; a CfgWr0 completion is a "
        "Cpl with no data, Length 0")
    assert cpl.byte_count == 4, (
        f"REQ-034: {what} -> Byte Count = {cpl.byte_count}, must be 4")
    assert cpl.lower_address == 0, (
        f"REQ-034: {what} -> Lower Address = {cpl.lower_address}, must be 0")
    assert cpl.status == CplStatus.SC, f"REQ-034: {what} status {cpl.status!r}"
    _check_reserved_fields(cpl, what)


# ---------------------------------------------------------------------------
# Unsupported requests (spec 4.3, 7.6)
# ---------------------------------------------------------------------------
async def _expect_ur(tb, req, what, expect_error=True):
    await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)    # clear first
    cpl = await tb.raw_request(req)
    _check_fmt_type(cpl, CPL_FMT_TYPE, what)
    assert cpl.status == CplStatus.UR, (
        f"REQ-035/REQ-040: {what} -> completion status {cpl.status!r}, "
        "expected UR (001)")
    assert cpl.length == 0, (
        f"REQ-035: {what} -> UR completion Length = {cpl.length}, must be 0")
    assert cpl.byte_count == 4, (
        f"REQ-035: {what} -> UR completion Byte Count = {cpl.byte_count}, "
        "must be 4")
    assert cpl.lower_address == 0, (
        f"REQ-035: {what} -> UR completion Lower Address = "
        f"{cpl.lower_address}, must be 0")
    _check_reserved_fields(cpl, what)
    st = await tb.read_dword(G.REG_STATUS)
    if expect_error:
        assert st & G.ST_ERR_UNSUP_REQ, (
            f"REQ-040: {what} returned UR but STATUS = 0x{st:08x}; "
            "ERR_UNSUP_REQ (bit 4) must be set")
    else:
        assert st & G.ST_ERR_UNSUP_REQ == 0, (
            f"REQ-042: {what} returned UR and also set ERR_UNSUP_REQ "
            f"(STATUS = 0x{st:08x}); a config request to a non-zero Device or "
            "Function number happens on every bus scan and is not an error")
    return cpl


async def _expect_discard(tb, req, what, expect_error=True):
    await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)
    await tb.raw_request(req, expect_completion=False)
    st = await tb.read_dword(G.REG_STATUS)
    if expect_error:
        assert st & G.ST_ERR_UNSUP_REQ, (
            f"REQ-041: {what} was discarded (correct) but STATUS = "
            f"0x{st:08x}; ERR_UNSUP_REQ must be set")
    else:
        assert st & G.ST_ERR_UNSUP_REQ == 0, (
            f"REQ-043: {what} must be discarded silently, but STATUS = "
            f"0x{st:08x} has ERR_UNSUP_REQ set")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_malformed_length_rejected(dut):
    """REQ-017, REQ-018: Length 0 means 1024 DW; > 32 DW is unsupported."""
    tb = await make_tb(dut)

    req = tb.make_mem_read(tb.bar0_addr + 0x0000, length=1)
    req.length = 0                       # encodes 1024 DW (PCIe r6.0 2.2.1)
    await _expect_ur(tb, req, "MRd with Length field = 0 (1024 DW)")

    for length in (33, 64, 1023):
        req = tb.make_mem_read(tb.bar0_addr + 0x0000, length=length,
                               first_be=0xF, last_be=0xF)
        await _expect_ur(tb, req, f"MRd with Length = {length} DW (> 32)")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_oversize_write_discarded_and_framing_kept(dut):
    """REQ-018, REQ-019, REQ-041: a rejected MWr's payload is consumed."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0x11112222)

    req = tb.make_mem_write(tb.bar0_addr + 0x0000, bytes(33 * 4),
                            first_be=0xF, last_be=0xF)
    assert req.length == 33
    await _expect_discard(tb, req, "MWr with Length = 33 DW (> 32)")

    # REQ-019: framing survived -- the very next TLP must be parsed correctly.
    await mwr_dword(tb, G.REG_SCRATCH, 0x33334444)
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0x33334444, (
        f"REQ-019: SCRATCH reads 0x{got:08x} after an oversize MWr was "
        "rejected; the DUT must consume the whole rejected payload and stay "
        "framed, so the following write must land")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_sop_resynchronisation(dut):
    """REQ-020: a mid-packet sop abandons the partial TLP."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0x00000000)

    good = tb.make_mem_write(tb.bar0_addr + G.REG_SCRATCH,
                             (0xFEEDFACE).to_bytes(4, "little"))
    good_beats = tb.shim.tlp_to_beats(good)

    partial = tb.make_mem_write(tb.bar0_addr + G.REG_SCRATCH,
                                (0xDEADDEAD).to_bytes(4, "little"))
    partial_beats = tb.shim.tlp_to_beats(partial)[:2]   # DW0, DW1, no eop

    await tb.shim.inject_beats(partial_beats + good_beats)
    await tb.settle()

    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0xFEEDFACE, (
        f"REQ-020: SCRATCH reads 0x{got:08x}; after a truncated TLP the DUT "
        "must abandon it on the next rx_tlp_sop and parse the new TLP from "
        "that beat (expected 0xFEEDFACE)")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_nonposted_unsupported_types(dut):
    """REQ-040, REQ-035: unsupported non-posted TLPs get a UR completion."""
    tb = await make_tb(dut)

    req = tb.make_mem_read(0x0000_0001_0000_0000 + 0x40, length=1, dw64=True)
    await _expect_ur(tb, req, "MRd64 (Fmt 001, 4 DW header)")

    req = Tlp()
    req.fmt_type = TlpType.IO_READ
    req.requester_id = PcieId(0, 0, 0)
    req.tag = tb.next_tag()
    req.length = 1
    req.first_be = 0xF
    req.address = 0x1000
    await _expect_ur(tb, req, "IORd")

    req = tb.make_cfg_read(0x00, type1=True)
    await _expect_ur(tb, req, "CfgRd1 (Type 00101)")

    req = Tlp()
    req.fmt_type = TlpType.FETCH_ADD
    req.requester_id = PcieId(0, 0, 0)
    req.tag = tb.next_tag()
    req.first_be = 0xF
    req.address = tb.bar0_addr
    req.set_data((1).to_bytes(4, "little"))
    await _expect_ur(tb, req, "FetchAdd (atomic)")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_posted_unsupported_types(dut):
    """REQ-036, REQ-041: unsupported posted TLPs are discarded, no completion.

    NOTE: Message TLPs (Msg/MsgD) cannot be exercised here -- cocotbext-pcie
    0.2.16's `Tlp.pack_header()` raises "Unknown TLP type" for every message
    format, so there is no way to encode one without hand-writing TLP bytes,
    which CLAUDE.md forbids.  MWr64 and IOWr cover the same DUT decode path.
    """
    tb = await make_tb(dut)

    req = tb.make_mem_write(0x0000_0001_0000_0000 + 0x40,
                            (0xDEADBEEF).to_bytes(4, "little"), dw64=True)
    await _expect_discard(tb, req, "MWr64 (Fmt 011, 4 DW header)")

    req = Tlp()
    req.fmt_type = TlpType.IO_WRITE
    req.requester_id = PcieId(0, 0, 0)
    req.tag = tb.next_tag()
    req.first_be = 0xF
    req.address = 0x1000
    req.set_data((0x12345678).to_bytes(4, "little"))
    await _expect_discard(tb, req, "IOWr")

    req = Tlp()
    req.fmt_type = TlpType.CFG_WRITE_1
    req.requester_id = PcieId(0, 0, 0)
    req.completer_id = tb.dev_id
    req.tag = tb.next_tag()
    req.length = 1
    req.first_be = 0xF
    req.address = 0x04
    req.set_data((0).to_bytes(4, "little"))
    await _expect_ur(tb, req, "CfgWr1 (Type 00101, non-posted)")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_td_ep_treated_as_unsupported(dut):
    """spec 4.3 / REQ-040, REQ-041: TD = 1 or EP = 1 is unsupported.

    Note the TD = 1 case: the DUT must not try to consume a TLP digest DWORD,
    because the spec classifies the TLP as unsupported before that matters.
    The TLPs below carry no digest, so framing is defined by sop/eop.
    """
    tb = await make_tb(dut)

    for field in ("td", "ep"):
        req = tb.make_mem_read(tb.bar0_addr + G.REG_ID, length=1)
        setattr(req, field, True)
        await _expect_ur(tb, req, f"MRd with {field.upper()} = 1")

        req = tb.make_mem_write(tb.bar0_addr + G.REG_SCRATCH,
                                (0x99887766).to_bytes(4, "little"))
        setattr(req, field, True)
        await _expect_discard(tb, req, f"MWr with {field.upper()} = 1")

    # The poisoned/digest writes must not have modified SCRATCH.
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got != 0x99887766, (
        "REQ-041: an MWr with TD or EP set is unsupported and must be "
        f"discarded, but SCRATCH now reads 0x{got:08x}")


@cocotb.test(timeout_time=200, timeout_unit="us")
async def test_tlp_inbound_completion_discarded(dut):
    """REQ-037, REQ-043: an inbound Cpl/CplD is dropped silently."""
    tb = await make_tb(dut)

    for has_data in (False, True):
        cpl = Tlp()
        cpl.fmt_type = TlpType.CPL_DATA if has_data else TlpType.CPL
        cpl.requester_id = PcieId(0, 0, 0)
        cpl.completer_id = tb.dev_id
        cpl.tag = tb.next_tag()
        cpl.byte_count = 4
        cpl.lower_address = 0
        if has_data:
            cpl.set_data((0x11223344).to_bytes(4, "little"))
        await _expect_discard(
            tb, cpl,
            f"inbound {'CplD' if has_data else 'Cpl'}",
            expect_error=False)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_bar0_miss_and_window_overrun(dut):
    """REQ-038, REQ-039, REQ-044, REQ-053: BAR0 decode and window overrun."""
    tb = await make_tb(dut)
    base = tb.bar0_addr

    for addr, what in (
        (base + G.BAR0_SIZE, "MRd one DWORD past the top of BAR0"),
        (base - 4, "MRd one DWORD below BAR0"),
        (base ^ 0x0004_0000, "MRd with a different Address[31:14]"),
    ):
        req = tb.make_mem_read(addr, length=1)
        await _expect_ur(tb, req, what)

        req = tb.make_mem_write(addr, (0x5A5A5A5A).to_bytes(4, "little"))
        await _expect_discard(tb, req, what.replace("MRd", "MWr"))

    # REQ-044: offset + L*4 > 16384 is a BAR0 miss even though the start
    # address is inside the window.  v1.1.4 narrowed REQ-044's antecedent to
    # 1 <= L <= 32 so that it is disjoint from REQ-127; L = 2 here is inside
    # that range, so this test still exercises REQ-044 and not REQ-127.
    req = tb.make_mem_read(base + G.BAR0_SIZE - 4, length=2,
                           first_be=0xF, last_be=0xF)
    await _expect_ur(tb, req, "MRd starting at BAR0+0x3FFC with Length 2")

    req = tb.make_mem_write(base + G.BAR0_SIZE - 4, bytes(8),
                            first_be=0xF, last_be=0xF)
    await _expect_discard(tb, req, "MWr starting at BAR0+0x3FFC with Length 2")

    # ... and the last legal DWORD of the window is still serviced.
    got = await mrd_dword(tb, G.BAR0_SIZE - 4)
    assert got == 0, (
        f"REQ-055: the last DWORD of BAR0 (offset 0x3FFC) reads 0x{got:08x}; "
        "it is unimplemented, so RAZ with SC")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_mse_gates_bar0_only(dut):
    """REQ-050, REQ-051, REQ-053: MSE=0 kills BAR0 decode, not config space."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0x13579BDF)

    await tb.cfg_write_dword(0x04, 0x0000)        # MSE = 0
    cmd = await tb.cfg_read_dword(0x04)
    assert cmd & 0xFFFF == 0, (
        f"REQ-046: Command reads 0x{cmd & 0xFFFF:04x} after writing 0x0000")

    req = tb.make_mem_read(tb.bar0_addr + G.REG_SCRATCH, length=1)
    await _expect_ur_no_reg(tb, req, "MRd to BAR0 while Command.MSE = 0")

    req = tb.make_mem_write(tb.bar0_addr + G.REG_SCRATCH,
                            (0xFFFFFFFF).to_bytes(4, "little"))
    await tb.raw_request(req, expect_completion=False)

    # REQ-051: configuration space still works with MSE = 0
    ident = await tb.cfg_read_dword(0x00)
    assert ident == G.CFG_ID_DWORD, (
        f"REQ-051: CfgRd0 of cfg 0x00 returned 0x{ident:08x} while MSE = 0; "
        "configuration space is accessible regardless of MSE")

    await tb.cfg_write_dword(0x04, G.CMD_MSE | G.CMD_BME)
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0x13579BDF, (
        f"REQ-050: SCRATCH reads 0x{got:08x}; the MWr issued while MSE = 0 "
        "must have been discarded, leaving 0x13579BDF")
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_UNSUP_REQ, (
        f"REQ-038/REQ-039: STATUS = 0x{st:08x} after memory requests with "
        "MSE = 0; ERR_UNSUP_REQ must be set")
    await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)


async def _expect_ur_no_reg(tb, req, what):
    """UR check that does not read STATUS (BAR0 is unreachable right now)."""
    cpl = await tb.raw_request(req)
    _check_fmt_type(cpl, CPL_FMT_TYPE, what)
    assert cpl.status == CplStatus.UR, (
        f"REQ-038: {what} -> status {cpl.status!r}, expected UR")
    assert cpl.length == 0 and cpl.byte_count == 4 and cpl.lower_address == 0, (
        f"REQ-035: {what} -> UR completion Length={cpl.length}, "
        f"ByteCount={cpl.byte_count}, LowerAddress={cpl.lower_address}; "
        "must be 0 / 4 / 0")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_tlp_cfg_nonzero_device_or_function(dut):
    """REQ-042: Type 0 config to Device != 0 or Function != 0 -> UR, no error."""
    tb = await make_tb(dut)

    for dev, fn in ((1, 0), (31, 0), (0, 1), (0, 7), (5, 3)):
        req = tb.make_cfg_read(0x00, dev_id=PcieId(tb.dev_id.bus, dev, fn))
        await _expect_ur(tb, req,
                         f"CfgRd0 to Device {dev} Function {fn}",
                         expect_error=False)
        req = tb.make_cfg_write(0x04, 0xFFFFFFFF,
                                dev_id=PcieId(tb.dev_id.bus, dev, fn))
        await _expect_ur(tb, req,
                         f"CfgWr0 to Device {dev} Function {fn}",
                         expect_error=False)

    # ... and the CfgWr0s above must not have modified Command.
    cmd = await tb.cfg_read_dword(0x04)
    assert cmd & 0xFFFF == (G.CMD_MSE | G.CMD_BME), (
        f"REQ-042: Command = 0x{cmd & 0xFFFF:04x}; a config write to a "
        "non-zero Device/Function must not be executed")


# ---------------------------------------------------------------------------
# Byte mapping, bursts and ordering
# ---------------------------------------------------------------------------
@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_payload_endianness(dut):
    """REQ-008, REQ-009, REQ-060: payload DWORD byte lanes.

    Writes four distinguishable bytes into consecutive A bytes with a single
    DWORD write, then reads them back one byte at a time through separate
    DWORD reads of the C region image and of A itself.  If the payload lane
    mapping were byte-swapped, A[0][0..3] would come back reversed.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    await tb.mem_write(G.MEM_A_BASE, bytes([0x11, 0x22, 0x33, 0x44]))
    back = await tb.mem_read(G.MEM_A_BASE, 4)
    assert bytes(back) == bytes([0x11, 0x22, 0x33, 0x44]), (
        f"REQ-008/REQ-009/REQ-060: A[0][0..3] read back as {bytes(back)!r}, "
        "expected 11 22 33 44; payload DWORDs are little-endian (spec 5.3) "
        "so data[8j+7:8j] is the byte at DWORD address + j")

    # The header mapping is big-endian: if it were not, the address in DW2
    # would be nonsense and none of the above would have reached A at all.
    # Prove the address decode explicitly by hitting the last byte of A.
    last = n * n - 1
    await tb.mem_write(G.MEM_A_BASE + last, bytes([0x7F]))
    back = await tb.mem_read(G.MEM_A_BASE + (last & ~3), 4)
    assert back[last & 3] == 0x7F, (
        f"REQ-008: byte at BAR0+0x{G.MEM_A_BASE + last:04x} reads "
        f"0x{back[last & 3]:02x}, expected 0x7f")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_tlp_burst_ascending_and_independent_decode(dut):
    """REQ-022, REQ-054, REQ-056, REQ-057: multi-DWORD burst behaviour."""
    tb = await make_tb(dut)
    n = await discover_n(tb)

    # A 32 DW write that starts inside C's implemented area and runs past it
    # (REQ-057: each DWORD is decoded from its own address; the ones past
    # 4*N*N are RAZ/WI, the ones inside are stored).
    words = 4 * n * n // 4
    start_word = max(0, words - 8)
    payload = b"".join(int(0xC0DE0000 + k).to_bytes(4, "little")
                       for k in range(32))
    req = tb.make_mem_write(tb.bar0_addr + G.MEM_C_BASE + 4 * start_word,
                            payload, first_be=0xF, last_be=0xF)
    await tb.raw_request(req, expect_completion=False)

    back = await tb.mem_read(G.MEM_C_BASE + 4 * start_word,
                             4 * (words - start_word))
    for k in range(words - start_word):
        got = int.from_bytes(back[4 * k:4 * k + 4], "little")
        exp = 0xC0DE0000 + k
        assert got == exp, (
            f"REQ-022/REQ-056: C word {start_word + k} reads 0x{got:08x} "
            f"after a 32 DW burst write; payload DWORDs must be applied in "
            f"ascending address order, so it should be 0x{exp:08x}")

    # DWORDs of the same burst that fell past the end of C must be RAZ/WI.
    got = await mrd_dword(tb, G.MEM_C_BASE + 4 * words)
    assert got == 0, (
        f"REQ-057/REQ-091: BAR0+0x{G.MEM_C_BASE + 4 * words:04x} reads "
        f"0x{got:08x} after a burst that ran past the end of C; offsets "
        ">= 4*N*N are RAZ/WI")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_tlp_requests_serviced_in_order(dut):
    """REQ-013, REQ-014, REQ-031: strict arrival order, one completion each."""
    tb = await make_tb(dut)
    await mwr_dword(tb, G.REG_SCRATCH, 0x0000BEEF)

    offsets = [G.REG_ID, G.REG_VERSION, G.REG_SCRATCH, G.REG_OP_COUNT,
               G.REG_ID, G.REG_SCRATCH]
    expect = [G.ID_VALUE, G.VERSION_VALUE, 0x0000BEEF, 0x00000000,
              G.ID_VALUE, 0x0000BEEF]

    cap = tb.shim.start_capture()
    reqs = []
    try:
        for k, off in enumerate(offsets):
            r = tb.make_mem_read(tb.bar0_addr + off, length=1, tag=0x20 + k)
            reqs.append(r)
            await tb.shim.inject(r)
        cpls = []
        for _ in offsets:
            cpls.append(await tb._get_capture(cap, 20000, reqs[0]))
    finally:
        tb.shim.stop_capture()

    assert len(cpls) == len(offsets), (
        f"REQ-031: {len(cpls)} completions for {len(offsets)} MRds")
    for k, (cpl, off, exp) in enumerate(zip(cpls, offsets, expect)):
        assert cpl.tag == 0x20 + k, (
            f"REQ-013: completion {k} carries Tag 0x{cpl.tag:02x}, expected "
            f"0x{0x20 + k:02x}; requests are serviced in strict arrival order "
            "(DEC-007) so completions come back in the same order")
        val = int.from_bytes(cpl.get_data(), "little")
        assert val == exp, (
            f"REQ-013: completion {k} (BAR0+0x{off:04x}) returned "
            f"0x{val:08x}, expected 0x{exp:08x}")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_tlp_back_to_back_tlps_no_idle_cycles(dut):
    """REQ-005, REQ-013, REQ-020: consecutive TLPs with zero idle cycles.

    Spec 5.2 allows *any* number of idle cycles between beats, including none:
    the next TLP's `sop` may be presented on the very cycle after the previous
    TLP's `eop` transferred.  This test writes the same 16 DWORDs twice --
    once with the shim idling between packets, once with the packets pushed
    back to back -- and requires identical results.

    The 16 writes are spread over the **implemented** words of C only,
    `word = k mod N*N`, so the count of TLPs (and therefore the amount of
    back-to-back stress) is the same at every `N` while every write targets a
    real storage location.  Writing 16 consecutive C words unconditionally,
    as this test originally did, lands outside `mem_c` at `N = 2`, where C
    holds `N*N = 4` words and everything above is RAZ/WI by REQ-091 -- the
    DUT was right and the test was wrong (BUG-002).  Cycling through the
    words also means several of the back-to-back TLPs hit the *same* address,
    which is the harder case for a write pipeline.
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    words = n * n                      # implemented C words (REQ-091)
    count = 16                         # TLPs issued, independent of N
    pattern = [(k % words, 0x11110000 + k) for k in range(count)]

    # Expected image: for each word, the value of the last write to it.
    def expected_image():
        img = [0] * words
        for word, value in pattern:
            img[word] = value
        return b"".join(v.to_bytes(4, "little") for v in img)

    exp = expected_image()
    base = G.MEM_C_BASE

    def diff(got):
        return [w for w in range(words)
                if got[4 * w:4 * w + 4] != exp[4 * w:4 * w + 4]]

    # --- (1) one TLP at a time, with the stream idling in between ---------
    await tb.mem_write(base, bytes(4 * words))
    await tb.settle()
    for word, value in pattern:
        await mwr_dword(tb, base + 4 * word, value, quiet_cycles=4)
    spaced = bytes(await tb.mem_read(base, 4 * words))
    bad = diff(spaced)
    assert not bad, (
        f"REQ-022: C word(s) {bad} did not land when the {count} "
        "single-DWORD MWr TLPs were issued one at a time with idle cycles "
        f"between them; read back {spaced.hex()}")

    # --- (2) the identical TLPs, injected with no gap at all --------------
    await tb.mem_write(base, bytes(4 * words))
    await tb.settle()
    before = tb.shim.rx_packets
    cap = tb.shim.start_capture()
    try:
        for word, value in pattern:
            await tb.shim.inject(tb.make_mem_write(
                tb.bar0_addr + base + 4 * word,
                value.to_bytes(4, "little")))
        await tb.shim.wait_rx_idle()
        await ClockCycles(dut.clk, 8)
    finally:
        tb.shim.stop_capture()

    framed = tb.shim.rx_packets - before
    assert framed == count, (
        f"internal: only {framed} of {count} TLPs were framed onto "
        "rx_tlp_*; the testbench driver, not the DUT, is at fault")

    packed = bytes(await tb.mem_read(base, 4 * words))
    bad = diff(packed)
    assert not bad, (
        f"REQ-005/REQ-013: C word(s) {bad} of {words} did not take effect "
        f"when {count} single-DWORD MWr TLPs were presented back-to-back "
        "with no idle cycle between eop and the next sop (the identical "
        "writes with idle cycles between them all landed).\n"
        f"  expected {exp.hex()}\n  read back {packed.hex()}")
    assert packed == spaced, (
        "REQ-005: the back-to-back and the idle-separated write sequences "
        f"left different contents in C\n  spaced: {spaced.hex()}\n"
        f"  packed: {packed.hex()}")


# ---------------------------------------------------------------------------
# REQ-127 (new in spec v1.1.4): over-length memory requests.
#
# `L` is the *decoded* DWORD length: a Length field of 0 decodes to 1024 DW,
# not zero (§7.2.1, REQ-017).  Any `L > 32` is rejected regardless of address
# and regardless of Command.MSE, with five observable clauses (a)..(e).
#
# Note on framing: two shapes are exercised deliberately.  For Length 33 and
# 100 the MWr carries exactly that many payload DWORDs, so the drain consumes
# a payload that matches the header.  For the Length field 0 (= 1024 DW) and
# 1023 the TLP carries a *shorter* framed payload than its Length claims,
# which is the harder case -- the parser must reframe on `rx_tlp_eop` and not
# sit waiting for DWORDs that never come.
# ---------------------------------------------------------------------------

OVER_LENGTH_CASES = [
    # (Length field, framed payload DWORDs for an MWr, description)
    (0, 16, "Length field 0 (decodes to 1024 DW, REQ-017)"),
    (33, 33, "Length 33 (one over the 32 DW cap)"),
    (100, 100, "Length 100"),
    (1023, 16, "Length 1023 (maximum encodable)"),
]


def _over_length_mrd(tb, addr, length):
    tlp = tb.make_mem_read(addr, length=1, first_be=0xF)
    tlp.length = length
    tlp.last_be = 0xF if length != 1 else 0
    return tlp


def _over_length_mwr(tb, addr, length, framed_dwords):
    tlp = tb.make_mem_write(
        addr,
        b"".join((0xFFFFFFFF).to_bytes(4, "little")
                 for _ in range(framed_dwords)),
        first_be=0xF, last_be=0xF)
    tlp.length = length                      # header claims `length` DWORDs
    return tlp


@cocotb.test(timeout_time=2000, timeout_unit="us")
async def test_tlp_over_length_memory_request(dut):
    """REQ-127 (a)..(e): `L > 32` memory requests, in and out of BAR0.

    Clause (c) -- the surplus payload of a malformed `MWr` is drained through
    `rx_tlp_eop` so the next TLP still parses -- is the one that matters: a
    parser that desynchronizes here makes every later test fail for a
    misleading reason.  It is checked after every malformed write, through two
    independent decode paths (configuration space and BAR0).
    """
    tb = await make_tb(dut)
    n = await discover_n(tb)

    # Known contents for clause (d).
    a_img = bytes((0x40 + k) & 0x7F for k in range(n * n))
    b_img = bytes((0x10 + k) & 0x7F for k in range(n * n))
    c_img = b"".join(int(0x0BAD0000 + k).to_bytes(4, "little")
                     for k in range(n * n))
    await tb.mem_write(G.MEM_A_BASE, a_img)
    await tb.mem_write(G.MEM_B_BASE, b_img)
    await tb.mem_write(G.MEM_C_BASE, c_img)
    await mwr_dword(tb, G.REG_SCRATCH, 0x1234ABCD)

    inside = [tb.bar0_addr + 0x0000, tb.bar0_addr + G.MEM_C_BASE]
    outside = [tb.bar0_addr + G.BAR0_SIZE + 0x40]

    async def _check_untouched(what):
        got = bytes(await tb.mem_read(G.MEM_A_BASE, n * n))
        assert got == a_img, f"REQ-127(d): mem_a modified by {what}"
        got = bytes(await tb.mem_read(G.MEM_B_BASE, n * n))
        assert got == b_img, f"REQ-127(d): mem_b modified by {what}"
        got = bytes(await tb.mem_read(G.MEM_C_BASE, 4 * n * n))
        assert got == c_img, f"REQ-127(d): mem_c modified by {what}"
        got = await tb.read_dword(G.REG_SCRATCH)
        assert got == 0x1234ABCD, (
            f"REQ-127(d): SCRATCH reads 0x{got:08x} after {what}; no register "
            "may be modified")

    async def _check_framing(what):
        ident = await tb.cfg_read_dword(0x00)
        assert ident == G.CFG_ID_DWORD, (
            f"REQ-127(c): after {what}, the next CfgRd0 of cfg 0x00 returned "
            f"0x{ident:08x} instead of 0x{G.CFG_ID_DWORD:08x}; the surplus "
            "payload must be consumed through rx_tlp_eop so framing survives")
        got = await tb.read_dword(G.REG_ID)
        assert got == G.ID_VALUE, (
            f"REQ-127(c): after {what}, a BAR0 read of ID returned "
            f"0x{got:08x} instead of 0x{G.ID_VALUE:08x}; the transaction "
            "layer lost framing")

    for length, framed, desc in OVER_LENGTH_CASES:
        for addr in inside + outside:
            where = ("inside BAR0" if addr - tb.bar0_addr < G.BAR0_SIZE
                     else "outside BAR0")
            what = f"MRd, {desc}, address {where}"

            # --- (a) MRd -> UR Cpl per REQ-035, and (e) -------------------
            await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)
            cpl = await tb.raw_request(_over_length_mrd(tb, addr, length))
            _check_fmt_type(cpl, CPL_FMT_TYPE, what)
            assert cpl.status == CplStatus.UR, (
                f"REQ-127(a): {what} -> status {cpl.status!r}, expected UR")
            assert cpl.length == 0 and cpl.byte_count == 4 \
                and cpl.lower_address == 0, (
                    f"REQ-127(a)/REQ-035: {what} -> Length={cpl.length}, "
                    f"ByteCount={cpl.byte_count}, "
                    f"LowerAddress={cpl.lower_address}; must be 0 / 4 / 0")
            _check_reserved_fields(cpl, what)
            st = await tb.read_dword(G.REG_STATUS)
            assert st & G.ST_ERR_UNSUP_REQ, (
                f"REQ-127(e): {what} was answered UR but STATUS = "
                f"0x{st:08x}; ERR_UNSUP_REQ must be set")

            # --- (b)(c) MWr -> no Completion, framing preserved -----------
            what = f"MWr, {desc} with {framed} framed payload DWORDs, {where}"
            await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)
            before = tb.shim.rx_packets
            await tb.raw_request(
                _over_length_mwr(tb, addr, length, framed),
                expect_completion=False)
            assert tb.shim.rx_packets - before == 1, (
                "internal: the malformed MWr was not framed as one packet")
            await _check_framing(what)
            st = await tb.read_dword(G.REG_STATUS)
            assert st & G.ST_ERR_UNSUP_REQ, (
                f"REQ-127(e): STATUS = 0x{st:08x} after {what}; "
                "ERR_UNSUP_REQ must be set for the posted case too")
            await _check_untouched(what)

    # --- the same, with Command.MSE = 0 ---------------------------------
    await tb.cfg_write_dword(0x04, 0x0000)
    cap_desc = "Length 33 MRd with Command.MSE = 0"
    cpl = await tb.raw_request(_over_length_mrd(tb, inside[0], 33))
    _check_fmt_type(cpl, CPL_FMT_TYPE, cap_desc)
    assert cpl.status == CplStatus.UR, (
        f"REQ-127(a): {cap_desc} -> status {cpl.status!r}, expected UR "
        "(rejection is independent of Command.MSE)")
    await tb.raw_request(_over_length_mwr(tb, inside[0], 0, 16),
                         expect_completion=False)
    ident = await tb.cfg_read_dword(0x00)
    assert ident == G.CFG_ID_DWORD, (
        "REQ-127(c): framing lost after an over-length MWr with MSE = 0")
    await tb.cfg_write_dword(0x04, G.CMD_MSE | G.CMD_BME)
    st = await tb.read_dword(G.REG_STATUS)
    assert st & G.ST_ERR_UNSUP_REQ, (
        f"REQ-127(e): STATUS = 0x{st:08x} after over-length requests issued "
        "with Command.MSE = 0; the error bit must be set regardless of MSE")
    await _check_untouched("over-length requests with MSE = 0")
    await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)
