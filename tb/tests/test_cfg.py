"""
PCI Type 0 configuration space (docs/spec.md section 8, register-map.md 4).

Requirements: REQ-045, REQ-046, REQ-047, REQ-048, REQ-049, REQ-050, REQ-051,
REQ-052, REQ-111, REQ-112, REQ-115, REQ-121.
"""

import cocotb

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
