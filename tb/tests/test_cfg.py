"""
PCI Type 0 configuration space (docs/spec.md section 8, register-map.md 4).

Requirements: REQ-045, REQ-046, REQ-047, REQ-048, REQ-049, REQ-050, REQ-051,
REQ-052, REQ-111, REQ-112, REQ-115, REQ-121.
"""

import cocotb

from cocotbext.pcie.core.tlp import CplStatus
from cocotbext.pcie.core.utils import PcieId

from tb_common import G, make_tb, mwr_dword, Host

# (offset, expected DWORD, requirement) for the reset state, spec 8.2.
CFG_RESET = [
    (0x00, 0x80001234, "REQ-112"),   # Device ID 0x8000, Vendor ID 0x1234
    (0x04, 0x00000000, "REQ-045"),   # Status 0x0000, Command 0x0000
    (0x08, 0x12000001, "REQ-045"),   # Class 0x120000, Revision 0x01
    (0x0C, 0x00000000, "REQ-045"),   # BIST/HdrType/LatTimer/CacheLineSize
    (0x10, 0x00000000, "REQ-111"),   # BAR0
    (0x14, 0x00000000, "REQ-045"),   # BAR1
    (0x18, 0x00000000, "REQ-045"),
    (0x1C, 0x00000000, "REQ-045"),
    (0x20, 0x00000000, "REQ-045"),
    (0x24, 0x00000000, "REQ-045"),   # BAR5
    (0x28, 0x00000000, "REQ-045"),   # Cardbus CIS Pointer
    (0x2C, 0x00011234, "REQ-045"),   # Subsystem ID 0x0001 / Vendor 0x1234
    (0x30, 0x00000000, "REQ-045"),   # Expansion ROM
    (0x34, 0x00000000, "REQ-045"),   # Capabilities Pointer = 0 (DEC-008)
    (0x38, 0x00000000, "REQ-045"),
    (0x3C, 0x00000000, "REQ-045"),   # Max Lat/Min Gnt/Int Pin/Int Line
]

# Offsets that are RO 0 and must stay 0 after any write.
CFG_RO_ZERO = [0x14, 0x18, 0x1C, 0x20, 0x24, 0x28, 0x30, 0x34, 0x38]


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_cfg_reset_values(dut):
    """REQ-045, REQ-111, REQ-112: the spec 8.2 table, read before enumeration."""
    tb = await Host.create(dut)
    for offset, exp, req in CFG_RESET:
        got = await tb.cfg_read_dword(offset)
        assert got == exp, (
            f"{req}: CfgRd0 of cfg 0x{offset:02x} returned 0x{got:08x}, "
            f"spec 8.2 requires 0x{exp:08x}")


@cocotb.test(timeout_time=300, timeout_unit="us")
async def test_cfg_unimplemented_offsets_read_zero(dut):
    """REQ-045: configuration offsets 0x40..0xFFF read 0x00000000."""
    tb = await Host.create(dut)
    for offset in (0x40, 0x44, 0x80, 0xC0, 0x100, 0x400, 0xFFC):
        got = await tb.cfg_read_dword(offset)
        assert got == 0, (
            f"REQ-045: CfgRd0 of cfg 0x{offset:03x} returned 0x{got:08x}, "
            "must be 0x00000000 (there is no capability list -- DEC-008)")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_bar0_sizing_and_readonly_low_bits(dut):
    """REQ-048, REQ-049, REQ-115: sizing readback and the RO low bits."""
    tb = await Host.create(dut)

    await tb.cfg_write_dword(0x10, 0xFFFFFFFF)
    got = await tb.cfg_read_dword(0x10)
    assert got == G.BAR0_SIZE_READBACK, (
        f"REQ-048/REQ-115: after writing 0xFFFFFFFF to BAR0 it reads "
        f"0x{got:08x}; a 16 KiB, 32-bit, non-prefetchable memory BAR must "
        f"read back 0x{G.BAR0_SIZE_READBACK:08x}")

    for value in (0xFFFFFFFF, 0x00003FFF, 0xDEADBEEF, 0x0000000F, 0x80004000):
        await tb.cfg_write_dword(0x10, value)
        got = await tb.cfg_read_dword(0x10)
        assert got & 0x3FFF == 0, (
            f"REQ-049: BAR0 reads 0x{got:08x} after writing 0x{value:08x}; "
            "bits [13:0] must always read 0")
        assert got == (value & 0xFFFFC000), (
            f"REQ-049: BAR0 reads 0x{got:08x} after writing 0x{value:08x}; "
            f"bits [31:14] are RW and [13:0] are RO 0, so it must read "
            f"0x{value & 0xFFFFC000:08x}")

    await tb.cfg_write_dword(0x10, 0x00000000)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_command_register_rw_bits(dut):
    """REQ-046: only Command[2:0] are writable; Status is RO 0."""
    tb = await Host.create(dut)

    for value in (0x0000, 0x0001, 0x0002, 0x0004, 0x0007, 0xFFFF):
        await tb.cfg_write_dword(0x04, value)
        got = await tb.cfg_read_dword(0x04)
        exp_cmd = value & 0x0007
        assert got & 0xFFFF == exp_cmd, (
            f"REQ-046: Command reads 0x{got & 0xFFFF:04x} after writing "
            f"0x{value:04x}; only bits 2:0 (IOSE, MSE, BME) are RW, so it "
            f"must read 0x{exp_cmd:04x}")
        assert got >> 16 == 0, (
            f"REQ-045: Status (cfg 0x06) reads 0x{got >> 16:04x}; it is RO "
            "and always 0, in particular bit 4 (Capabilities List) is 0 "
            "because the Capabilities Pointer is 0x00")
    await tb.cfg_write_dword(0x04, 0x0000)


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_write_byte_enables(dut):
    """REQ-046: a CfgWr0 updates only bytes whose First BE bit is 1."""
    tb = await Host.create(dut)

    # Cache Line Size is cfg 0x0C byte 0 (RW); the rest of that DWORD is RO.
    await tb.cfg_write_dword(0x0C, 0x000000AA, be=0b0001)
    got = await tb.cfg_read_dword(0x0C)
    assert got == 0x000000AA, (
        f"REQ-046: cfg 0x0C reads 0x{got:08x} after writing 0x000000AA with "
        "First BE = 0b0001; Cache Line Size (byte 0) is RW and the other "
        "three bytes are RO 0")

    await tb.cfg_write_dword(0x0C, 0x000000BB, be=0b1110)
    got = await tb.cfg_read_dword(0x0C)
    assert got == 0x000000AA, (
        f"REQ-046: cfg 0x0C reads 0x{got:08x} after a write with First BE = "
        "0b1110; byte 0 is not enabled so Cache Line Size must stay 0xAA")

    # Interrupt Line is cfg 0x3C byte 0 (RW); Interrupt Pin (byte 1) is RO 0.
    await tb.cfg_write_dword(0x3C, 0xFFFFFFFF)
    got = await tb.cfg_read_dword(0x3C)
    assert got == 0x000000FF, (
        f"REQ-046: cfg 0x3C reads 0x{got:08x} after writing 0xFFFFFFFF; only "
        "Interrupt Line (byte 0) is RW, so it must read 0x000000FF "
        "(Interrupt Pin = 0x00, no INTx)")

    # Command with a byte enable that excludes byte 0
    await tb.cfg_write_dword(0x04, 0x00000000)
    await tb.cfg_write_dword(0x04, 0x00000007, be=0b1110)
    got = await tb.cfg_read_dword(0x04)
    assert got & 0xFFFF == 0, (
        f"REQ-046: Command reads 0x{got & 0xFFFF:04x} after a write with "
        "First BE = 0b1110; IOSE/MSE/BME are in byte 0 and must not change")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_write_to_readonly_is_accepted_and_ignored(dut):
    """REQ-047: a CfgWr0 to an RO or unimplemented offset returns SC, no change."""
    tb = await Host.create(dut)

    for offset, exp, req in CFG_RESET:
        if offset in (0x04, 0x0C, 0x10, 0x3C):
            continue                        # these have RW fields
        await tb.cfg_write_dword(offset, 0xFFFFFFFF)   # asserts SC internally
        got = await tb.cfg_read_dword(offset)
        assert got == exp, (
            f"REQ-047: cfg 0x{offset:02x} reads 0x{got:08x} after writing "
            f"0xFFFFFFFF; it is read-only and must still read 0x{exp:08x}")

    for offset in CFG_RO_ZERO + [0x40, 0x100, 0xFFC]:
        await tb.cfg_write_dword(offset, 0xA5A5A5A5)
        got = await tb.cfg_read_dword(offset)
        assert got == 0, (
            f"REQ-047: cfg 0x{offset:03x} reads 0x{got:08x} after a write; "
            "unimplemented configuration offsets are RO 0")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_enumeration_assigns_bar0(dut):
    """REQ-045, REQ-048, REQ-115, REQ-116: rc.enumerate() finds and maps us."""
    tb = await make_tb(dut)

    assert tb.dev.bar_size[0] == G.BAR0_SIZE, (
        f"REQ-115: the host decoded a BAR0 size of {tb.dev.bar_size[0]} bytes;"
        f" spec 2 fixes the aperture at {G.BAR0_SIZE} bytes for every legal N")
    assert tb.bar0_addr % G.BAR0_SIZE == 0, (
        f"BAR0 was assigned 0x{tb.bar0_addr:08x}, which is not 16 KiB aligned")
    assert tb.dev.class_code == 0x120000, (
        f"REQ-045: Class Code reads 0x{tb.dev.class_code:06x}, expected "
        "0x120000 (Processing Accelerators, DEC-011)")
    assert tb.dev.revision_id == 0x01, (
        f"REQ-045: Revision ID reads 0x{tb.dev.revision_id:02x}, expected 0x01")
    assert tb.dev.subsystem_vendor_id == 0x1234 and \
        tb.dev.subsystem_id == 0x0001, (
            f"REQ-045: Subsystem IDs read "
            f"0x{tb.dev.subsystem_id:04x}/0x{tb.dev.subsystem_vendor_id:04x}, "
            "expected 0x0001/0x1234")
    assert tb.dev.capabilities == [], (
        f"DEC-008/REQ-045: the device advertised capabilities "
        f"{tb.dev.capabilities}; the Capabilities Pointer is 0x00 and there "
        "is no capability list")

    got = await tb.read_dword(G.REG_ID)
    assert got == G.ID_VALUE, (
        f"REQ-065: BAR0 was mapped at 0x{tb.bar0_addr:08x} but ID reads "
        f"0x{got:08x}, not 0x{G.ID_VALUE:08x}")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_cfg_reenumerable_after_reset(dut):
    """REQ-121: after rst, BAR0 = 0 and Command.MSE = 0, and re-enumeration
    works without a power cycle."""
    tb = await make_tb(dut)
    first_bar = tb.bar0_addr
    await tb.write_dword(G.REG_SCRATCH, 0xFEEDBEEF)

    await tb.reset()

    bar0 = await tb.cfg_read_dword(0x10)
    assert bar0 == 0x00000000, (
        f"REQ-121: cfg BAR0 reads 0x{bar0:08x} after rst, must be 0x00000000")
    cmd = await tb.cfg_read_dword(0x04)
    assert cmd & G.CMD_MSE == 0, (
        f"REQ-121: Command reads 0x{cmd & 0xFFFF:04x} after rst; MSE must be "
        "0 so BAR0 does not decode")
    ident = await tb.cfg_read_dword(0x00)
    assert ident == G.CFG_ID_DWORD, (
        f"REQ-112: cfg 0x00 reads 0x{ident:08x} after rst")

    await tb.enumerate()
    assert tb.bar0_addr is not None
    got = await tb.read_dword(G.REG_ID)
    assert got == G.ID_VALUE, (
        f"REQ-121: after re-enumeration (BAR0 at 0x{tb.bar0_addr:08x}, "
        f"previously 0x{first_bar:08x}) ID reads 0x{got:08x}")
    got = await tb.read_dword(G.REG_SCRATCH)
    assert got == 0, (
        f"REQ-111: SCRATCH reads 0x{got:08x} after rst; spec 13.4 gives it a "
        "reset value of 0x00000000")


# ---------------------------------------------------------------------------
# REQ-126 (new in spec v1.1.2): malformed Length on a configuration request.
#
# Clauses: (a) UR completion formatted per REQ-035, (b) no configuration
# register modified, (c) surplus payload drained through rx_tlp_eop so framing
# survives, (d) STATUS.ERR_UNSUP_REQ set.
#
# Clause (d) -- "shall set STATUS.ERR_UNSUP_REQ" -- is covered by
# test_cfg_malformed_length_sets_unsup_req below, together with the negative
# control that keeps REQ-042's bus-scan carve-out intact.
# ---------------------------------------------------------------------------

CFG_SNAPSHOT_OFFSETS = [0x00, 0x04, 0x08, 0x0C, 0x10, 0x2C, 0x3C]

# A Cpl with UR status, Length 0, Byte Count 4, Lower Address 0 and
# Completer ID 0x0000 (spec 7.2.4 / REQ-035 / REQ-126(a)).
UR_DW0_LEN0 = 0x0A000000
UR_DW1_CID0_UR_BC4 = 0x00002004


def _make_malformed_cfg(tb, write, offset, length, dev_id=None, tag=None):
    """CfgRd0/CfgWr0 with a Length field that is not 1."""
    if write:
        tlp = tb.make_cfg_write(offset, 0xFFFFFFFF, dev_id=dev_id, tag=tag)
        # Surplus payload: `length` DWORDs, each a value that would be very
        # visible if the DUT wrongly executed the write.
        tlp.set_data(b"".join((0xFFFFFFFF).to_bytes(4, "little")
                              for _ in range(length)))
    else:
        tlp = tb.make_cfg_read(offset, dev_id=dev_id, tag=tag)
    tlp.length = length
    return tlp


async def _snapshot_cfg(tb):
    return {off: await tb.cfg_read_dword(off) for off in CFG_SNAPSHOT_OFFSETS}


async def _check_ur_cpl(tb, cpl, what, exact_dwords=False):
    """REQ-126(a): a Cpl, UR status, REQ-035 shape, exactly 3 DWORDs."""
    assert len(cpl.raw_dwords) == 3, (
        f"REQ-126(a): the completion for {what} was "
        f"{len(cpl.raw_dwords)} DWORDs; a UR Cpl carries no payload, so it is "
        "exactly three beats")
    dw0 = cpl.raw_dwords[0]
    fmt, typ = (dw0 >> 29) & 0x7, (dw0 >> 24) & 0x1F
    assert (fmt, typ) == (0b000, 0b01010), (
        f"REQ-126(a): {what} -> Fmt/Type = {fmt:#05b}/{typ:#07b}, expected a "
        "Cpl (000/01010)")
    assert cpl.status == CplStatus.UR, (
        f"REQ-126(a): {what} -> completion status {cpl.status!r}, expected UR")
    assert cpl.length == 0 and cpl.byte_count == 4 and cpl.lower_address == 0, (
        f"REQ-126(a)/REQ-035: {what} -> Length={cpl.length}, "
        f"ByteCount={cpl.byte_count}, LowerAddress={cpl.lower_address}; "
        "must be 0 / 4 / 0")
    if exact_dwords:
        assert cpl.raw_dwords[0] == UR_DW0_LEN0, (
            f"REQ-126(a): {what} -> DW0 = 0x{cpl.raw_dwords[0]:08x}, the spec "
            f"gives 0x{UR_DW0_LEN0:08x}")
        assert cpl.raw_dwords[1] == UR_DW1_CID0_UR_BC4, (
            f"REQ-126(a): {what} -> DW1 = 0x{cpl.raw_dwords[1]:08x}, the spec "
            f"gives 0x{UR_DW1_CID0_UR_BC4:08x} for cfg_completer_id = 0x0000 "
            "(Completer ID 0, status UR, BCM 0, Byte Count 4)")


@cocotb.test(timeout_time=400, timeout_unit="us")
async def test_cfg_malformed_length_completion_fields(dut):
    """REQ-126(a)(b): malformed-Length config requests -> UR, no state change.

    Run before any well-formed configuration access, so `cfg_completer_id` is
    still its reset value 0x0000 (spec 13.4) and the completion's exact header
    DWORDs can be checked against the values REQ-126 quotes.
    """
    tb = await Host.create(dut)

    # First transaction after reset: the exact-DWORD check.
    req = _make_malformed_cfg(tb, write=False, offset=0x00, length=2)
    cpl = await tb.raw_request(req)
    await _check_ur_cpl(tb, cpl, "CfgRd0 of cfg 0x00 with Length = 2",
                        exact_dwords=True)

    # A malformed request is not an accepted Type 0 request, so it must not
    # have captured a Completer ID either (REQ-052 applies to accepted ones).
    req = _make_malformed_cfg(tb, write=True, offset=0x04, length=2)
    cpl = await tb.raw_request(req)
    await _check_ur_cpl(tb, cpl, "CfgWr0 of cfg 0x04 with Length = 2",
                        exact_dwords=True)

    before = await _snapshot_cfg(tb)

    cases = []
    for length in (0, 2, 4, 32):
        cases.append((False, 0x00, length, None))
        cases.append((True, 0x04, length, None))   # Command: RW, very visible
        cases.append((True, 0x10, length, None))   # BAR0: RW
    # "regardless of Device and Function number" -- the REQ-042 carve-out for
    # routine bus scans does not extend to a malformed Length.
    cases.append((False, 0x00, 2, PcieId(tb.dev_id.bus, 5, 0)))
    cases.append((True, 0x04, 2, PcieId(tb.dev_id.bus, 0, 3)))

    for write, offset, length, dev_id in cases:
        what = (f"Cfg{'Wr' if write else 'Rd'}0 of cfg 0x{offset:02x} with "
                f"Length = {length}"
                + (f" to Device {dev_id.device} Function {dev_id.function}"
                   if dev_id is not None else ""))
        req = _make_malformed_cfg(tb, write, offset, length, dev_id=dev_id)
        cpl = await tb.raw_request(req)
        await _check_ur_cpl(tb, cpl, what)

    after = await _snapshot_cfg(tb)
    changed = {f"0x{off:02x}": (f"0x{before[off]:08x}", f"0x{after[off]:08x}")
               for off in CFG_SNAPSHOT_OFFSETS if before[off] != after[off]}
    assert not changed, (
        "REQ-126(b): a malformed-Length configuration request modified "
        f"configuration state: {changed} (offset: before -> after).  No "
        "configuration register may be modified.")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_cfg_malformed_length_framing_preserved(dut):
    """REQ-126(c): surplus payload is drained through rx_tlp_eop.

    This is the clause that matters most: a parser that stops consuming a
    malformed TLP early desynchronizes, and every following TLP -- and so
    every following test -- fails for a misleading reason.  After each
    malformed `CfgWr0` the very next TLP must be parsed correctly, checked
    both in configuration space and through BAR0.
    """
    tb = await make_tb(dut)

    for length in (2, 3, 4, 8, 32):
        req = _make_malformed_cfg(tb, write=True, offset=0x04, length=length)
        framed_before = tb.shim.rx_packets
        cpl = await tb.raw_request(req)
        await _check_ur_cpl(tb, cpl, f"CfgWr0 with Length = {length}")
        assert tb.shim.rx_packets - framed_before == 1, (
            "internal: the malformed TLP was not framed as exactly one packet")

        # The next TLP must parse correctly -- config space ...
        ident = await tb.cfg_read_dword(0x00)
        assert ident == G.CFG_ID_DWORD, (
            f"REQ-126(c): after a CfgWr0 with Length = {length} and "
            f"{length} payload DWORDs, the next CfgRd0 of cfg 0x00 returned "
            f"0x{ident:08x} instead of 0x{G.CFG_ID_DWORD:08x}.  The DUT must "
            "consume and discard the surplus payload through rx_tlp_eop so "
            "that framing is preserved")

        # ... and BAR0, which is a different decode path entirely.
        got = await tb.read_dword(G.REG_ID)
        assert got == G.ID_VALUE, (
            f"REQ-126(c): after a CfgWr0 with Length = {length}, a BAR0 read "
            f"of ID returned 0x{got:08x} instead of 0x{G.ID_VALUE:08x}; the "
            "transaction layer lost framing")

        # Command must still be what enumerate() left it.
        cmd = await tb.cfg_read_dword(0x04)
        assert cmd & 0xFFFF == (G.CMD_MSE | G.CMD_BME), (
            f"REQ-126(b): Command = 0x{cmd & 0xFFFF:04x} after a malformed "
            f"CfgWr0 with Length = {length}; it must be unmodified")

    # A malformed CfgRd0 immediately followed by a malformed CfgWr0, then a
    # well-formed access: back-to-back malformed TLPs must not desynchronize.
    for req in (_make_malformed_cfg(tb, False, 0x08, 2),
                _make_malformed_cfg(tb, True, 0x3C, 5)):
        cpl = await tb.raw_request(req)
        await _check_ur_cpl(tb, cpl, "back-to-back malformed config request")
    got = await tb.read_dword(G.REG_VERSION)
    assert got == G.VERSION_VALUE, (
        f"REQ-126(c): VERSION reads 0x{got:08x} after two consecutive "
        f"malformed configuration requests, expected 0x{G.VERSION_VALUE:08x}")


@cocotb.test(timeout_time=600, timeout_unit="us")
async def test_cfg_malformed_length_sets_unsup_req(dut):
    """REQ-126(d): a malformed `Length` sets `STATUS.ERR_UNSUP_REQ`.

    Paired with its negative control.  REQ-042 deliberately exempts a
    *well-formed* Type 0 request to a non-zero Device or Function from setting
    the error bit, because routine bus scans probe absent devices on every
    enumeration.  REQ-126 says that carve-out does **not** extend to a
    malformed `Length`.

    Testing only the positive half would pass even on an implementation that
    set `ERR_UNSUP_REQ` on every absent-device probe -- which would make
    ordinary enumeration noisy and would break REQ-042.  So each positive case
    is checked against a control that differs only in having `Length = 1`.
    """
    tb = await make_tb(dut)
    other_devfn = PcieId(tb.dev_id.bus, 1, 0)      # devfn 0x08

    async def _clear_and_check():
        await mwr_dword(tb, G.REG_STATUS, G.ST_ERR_UNSUP_REQ)
        st = await tb.read_dword(G.REG_STATUS)
        assert st & G.ST_ERR_UNSUP_REQ == 0, (
            f"REQ-076: STATUS = 0x{st:08x}; ERR_UNSUP_REQ did not clear, so "
            "the REQ-126(d) check cannot start from a known state")

    # --- positive: malformed Length, with and without a matching devfn -----
    positives = [
        (True, 0x04, 2, None, "CfgWr0 cfg 0x04 Length=2, Device 0 Function 0"),
        (False, 0x00, 2, None, "CfgRd0 cfg 0x00 Length=2, Device 0 Function 0"),
        (False, 0x00, 0, None, "CfgRd0 cfg 0x00 Length=0"),
        (False, 0x00, 2, other_devfn,
         "CfgRd0 cfg 0x00 Length=2 to Device 1 Function 0 (devfn 0x08)"),
        (True, 0x04, 4, PcieId(tb.dev_id.bus, 0, 3),
         "CfgWr0 cfg 0x04 Length=4 to Device 0 Function 3"),
    ]
    for write, offset, length, dev_id, what in positives:
        await _clear_and_check()
        req = _make_malformed_cfg(tb, write, offset, length, dev_id=dev_id)
        cpl = await tb.raw_request(req)
        await _check_ur_cpl(tb, cpl, what)
        st = await tb.read_dword(G.REG_STATUS)
        assert st & G.ST_ERR_UNSUP_REQ, (
            f"REQ-126(d): {what} was answered UR (correct) but STATUS = "
            f"0x{st:08x}; ERR_UNSUP_REQ (bit 4) must be set.  A malformed "
            "Length is an unsupported request, and the REQ-042 carve-out for "
            "bus scans does not apply to it")

    # --- negative control: identical request, but Length = 1 ---------------
    controls = [
        (False, 0x00, other_devfn,
         "CfgRd0 cfg 0x00 Length=1 to Device 1 Function 0 (devfn 0x08)"),
        (True, 0x04, other_devfn,
         "CfgWr0 cfg 0x04 Length=1 to Device 1 Function 0"),
        (False, 0x00, PcieId(tb.dev_id.bus, 0, 5),
         "CfgRd0 cfg 0x00 Length=1 to Device 0 Function 5"),
    ]
    for write, offset, dev_id, what in controls:
        await _clear_and_check()
        if write:
            req = tb.make_cfg_write(offset, 0xFFFFFFFF, dev_id=dev_id)
        else:
            req = tb.make_cfg_read(offset, dev_id=dev_id)
        assert req.length == 1, "the control must be a well-formed Length = 1"
        cpl = await tb.raw_request(req)
        assert cpl.status == CplStatus.UR, (
            f"REQ-042: {what} -> status {cpl.status!r}, expected UR")
        st = await tb.read_dword(G.REG_STATUS)
        assert st & G.ST_ERR_UNSUP_REQ == 0, (
            f"REQ-042: {what} returned UR and also set ERR_UNSUP_REQ "
            f"(STATUS = 0x{st:08x}).  A *well-formed* Type 0 request to a "
            "non-zero Device or Function happens on every bus scan and must "
            "not set the error bit -- only the malformed-Length path does "
            "(REQ-126(d))")

    # Config space must still be untouched by any of the above.
    cmd = await tb.cfg_read_dword(0x04)
    assert cmd & 0xFFFF == (G.CMD_MSE | G.CMD_BME), (
        f"REQ-126(b)/REQ-042: Command = 0x{cmd & 0xFFFF:04x} after the "
        "malformed and control requests; none of them may modify it")
