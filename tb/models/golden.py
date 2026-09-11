"""
Golden reference models, written from docs/spec.md v1.0.0 only.

Nothing in this file may be derived from rtl/.  Every constant carries the
REQ / section of the spec it comes from.

Contents
--------
  * `matmul_golden`      - exact INT8 x INT8 -> INT32 matrix product (spec 12.6)
                           (pure Python: numpy is not installed in the venv)
  * BE offset helpers    - spec 7.5 tables (first_be_offset / last_be_offset /
                           be_byte_count / lower_address)
  * `RegModel`           - shadow of the BAR0 register block (register-map.md 2)
  * `DeviceModel`        - shadow of A/B/C storage + registers, used by the
                           scoreboard in test_stress.py
"""

# NumPy is NOT installed in the project venv (checked 2026-09-10).  Pure-Python
# integers are used instead, which is strictly better here anyway: spec 12.6
# demands *exact* two's-complement arithmetic with no truncation, and Python
# ints cannot silently wrap the way a numpy int64 accumulator can.

# ---------------------------------------------------------------------------
# Fixed parameters (spec 2). N is discoverable at run time from CONFIG[7:0]
# (REQ-114) so tests never hard-code it; these are only the v1 defaults.
# ---------------------------------------------------------------------------
N_DEFAULT = 8
DW_DEFAULT = 8
ACCW_DEFAULT = 32

# BAR0 aperture, spec 9.2 / register-map.md 1
BAR0_SIZE = 16384
REG_BASE = 0x0000
MEM_A_BASE = 0x1000
MEM_B_BASE = 0x2000
MEM_C_BASE = 0x3000
REGION_SIZE = 0x1000

# BAR0 register offsets (register-map.md 2)
REG_ID = 0x0000
REG_VERSION = 0x0004
REG_CONFIG = 0x0008
REG_CTRL = 0x000C
REG_STATUS = 0x0010
REG_IRQ_ENABLE = 0x0014
REG_IRQ_STATUS = 0x0018
REG_PERF_CYCLES = 0x001C
REG_SCRATCH = 0x0020
REG_OP_COUNT = 0x0024

# Reset / fixed values (REQ-065, REQ-066, REQ-067)
ID_VALUE = 0x4D415431          # ASCII "MAT1"
VERSION_VALUE = 0x00010000     # major 1, minor 0, patch 0


def config_value(n=N_DEFAULT, dw=DW_DEFAULT, accw=ACCW_DEFAULT):
    """CONFIG = {8'h00, ACCW[7:0], DW[7:0], N[7:0]} (REQ-067)."""
    return ((accw & 0xFF) << 16) | ((dw & 0xFF) << 8) | (n & 0xFF)


# CTRL bits (register-map.md 3.4)
CTRL_START = 1 << 0
CTRL_SOFT_RESET = 1 << 1

# STATUS / IRQ_ENABLE bits (register-map.md 3.5, 3.6)
ST_BUSY = 1 << 0
ST_DONE = 1 << 1
ST_ERR_START_BUSY = 1 << 2
ST_ERR_WRITE_BUSY = 1 << 3
ST_ERR_UNSUP_REQ = 1 << 4
ST_W1C_MASK = ST_DONE | ST_ERR_START_BUSY | ST_ERR_WRITE_BUSY | ST_ERR_UNSUP_REQ
ST_IMPLEMENTED_MASK = 0x1F
# IRQ_ENABLE bit 0 is RO 0: there is no interrupt source for BUSY (REQ-079 table)
IRQ_ENABLE_MASK = ST_DONE | ST_ERR_START_BUSY | ST_ERR_WRITE_BUSY | ST_ERR_UNSUP_REQ

# PCI configuration space constants (spec 8.2, DEC-011)
CFG_VENDOR_ID = 0x1234
CFG_DEVICE_ID = 0x8000
CFG_ID_DWORD = 0x80001234      # cfg 0x00 (REQ-112)
CFG_CLASS_REV = 0x12000001     # cfg 0x08
CFG_SUBSYS = 0x00011234        # cfg 0x2C
BAR0_SIZE_READBACK = 0xFFFFC000  # REQ-048, REQ-115
CMD_IOSE = 1 << 0
CMD_MSE = 1 << 1
CMD_BME = 1 << 2


def t_mm(n):
    """Cycles from START accepted to DONE set, spec 12.5 (REQ-101/102)."""
    return 4 * n + 2


# ---------------------------------------------------------------------------
# Matmul reference (spec 12.6, REQ-097, REQ-105)
# ---------------------------------------------------------------------------

def _as_signed8(v):
    v &= 0xFF
    return v - 256 if v >= 128 else v


def _as_unsigned32(v):
    return v & 0xFFFFFFFF


def to_signed32(v):
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v >= (1 << 31) else v


def matmul_golden(a, b, n=None):
    """C = A x B, exact two's-complement arithmetic on ACCW=32 bits.

    Spec 12.6: signed 8-bit operands, 32-bit accumulator, **no saturation, no
    truncation, no overflow detection** (REQ-105, REQ-106).  Overflow is proven
    unreachable for every legal N, so this model asserts it never happens
    rather than modelling a wrap that cannot occur -- if the assert ever fires,
    the spec's non-overflow proof is wrong and spec-writer must be told.

    `a` and `b` are N x N sequences of signed ints in [-128, 127].
    Returns an N x N list of lists of exact Python ints.
    """
    a = [list(row) for row in a]
    b = [list(row) for row in b]
    if n is None:
        n = len(a)
    assert len(a) == n and all(len(r) == n for r in a), f"A must be {n}x{n}"
    assert len(b) == n and all(len(r) == n for r in b), f"B must be {n}x{n}"
    for row in a:
        assert all(-128 <= v <= 127 for v in row), "A outside INT8 range (spec 12.6)"
    for row in b:
        assert all(-128 <= v <= 127 for v in row), "B outside INT8 range (spec 12.6)"

    c = [[sum(a[i][k] * b[k][j] for k in range(n)) for j in range(n)]
         for i in range(n)]

    flat = [v for row in c for v in row]
    assert min(flat) >= -(1 << 31) and max(flat) <= (1 << 31) - 1, (
        "reference product overflows INT32; spec 12.6 claims this is "
        "unreachable for legal N -- report to spec-writer"
    )
    return c


def c_to_bytes(c, n):
    """C matrix -> the exact byte image the host must read at BAR0+0x3000.

    Word at 0x3000 + 4*(i*N + j) is C[i][j], little-endian on the wire
    (spec 9.2 / register-map.md 1, payload byte mapping of spec 5.3).
    """
    out = bytearray()
    for i in range(n):
        for j in range(n):
            out += int(_as_unsigned32(int(c[i][j]))).to_bytes(4, "little")
    return bytes(out)


def a_to_bytes(a, n):
    """A -> BAR0+0x1000 image: byte (i*N + k) is A[i][k] (spec 9.2)."""
    return bytes(int(a[i][k]) & 0xFF for i in range(n) for k in range(n))


def b_to_bytes(b, n):
    """B -> BAR0+0x2000 image: byte (k*N + j) is B[k][j] (spec 9.2)."""
    return bytes(int(b[k][j]) & 0xFF for k in range(n) for j in range(n))


def bytes_to_a(data, n):
    return [[_as_signed8(data[i * n + k]) for k in range(n)] for i in range(n)]


def bytes_to_b(data, n):
    return [[_as_signed8(data[k * n + j]) for j in range(n)] for k in range(n)]


def bytes_to_c(data, n):
    return [[to_signed32(int.from_bytes(
        data[4 * (i * n + j):4 * (i * n + j) + 4], "little"))
        for j in range(n)] for i in range(n)]


# ---------------------------------------------------------------------------
# Byte-enable tables (spec 7.5, normative).  Implemented from the spec's own
# tables; test_tlp.py cross-checks them against cocotbext-pcie, which the spec
# claims they match bit-for-bit.
# ---------------------------------------------------------------------------

def first_be_offset(fbe):
    """spec 7.5: xxx1->0, xx10->1, x100->2, 1000->3, 0000->3."""
    fbe &= 0xF
    if fbe & 0x7 == 0:      # 1000 or 0000
        return 3
    if fbe & 0x3 == 0:      # x100
        return 2
    if fbe & 0x1 == 0:      # xx10
        return 1
    return 0                # xxx1


def last_be_offset(fbe, lbe, length):
    """spec 7.5: `lbe` is Last BE if Length > 1, else First BE."""
    be = (lbe if length > 1 else fbe) & 0xF
    if be == 0x1:
        return 3
    if be & 0xE == 0x2:
        return 2
    if be & 0xC == 0x4:
        return 1
    return 0


def be_byte_count(length, fbe, lbe):
    """spec 7.5: Length*4 - first_be_offset - last_be_offset (REQ-029)."""
    return length * 4 - first_be_offset(fbe) - last_be_offset(fbe, lbe, length)


def lower_address(addr, fbe):
    """spec 7.5 / REQ-030: (Address + first_be_offset) & 0x7F.

    NOTE: cocotbext-pcie 0.2.16's Tlp.get_lower_address() is buggy (operator
    precedence) -- spec 5.4 says do not use it as a reference.
    """
    return (addr + first_be_offset(fbe)) & 0x7F


def be_mask_for_dword(index, length, fbe, lbe):
    """Which BE applies to DWORD `index` of an L-DWORD burst (REQ-058)."""
    if length == 1:
        return fbe & 0xF          # Last BE ignored when L == 1
    if index == 0:
        return fbe & 0xF
    if index == length - 1:
        return lbe & 0xF
    return 0xF                    # intermediate DWORDs fully enabled


def apply_byte_enables(old_dword_bytes, new_dword_bytes, be):
    """REQ-059/REQ-060: BE bit j gates byte j of the DWORD."""
    return bytes(new_dword_bytes[j] if (be >> j) & 1 else old_dword_bytes[j]
                 for j in range(4))


# ---------------------------------------------------------------------------
# DWORD <-> byte-lane mapping of spec 5.3.  This is the reference conversion
# printed in the spec; the shim uses it and nothing else.
# ---------------------------------------------------------------------------

def tlp_to_dwords(tlp):
    """Host -> DUT.  Header DWORDs big-endian, payload DWORDs little-endian."""
    b = tlp.pack()
    hdr = tlp.get_header_size()
    assert hdr % 4 == 0 and len(b) % 4 == 0, f"TLP not DWORD-aligned: {tlp!r}"
    return ([int.from_bytes(b[i:i + 4], "big") for i in range(0, hdr, 4)]
            + [int.from_bytes(b[i:i + 4], "little") for i in range(hdr, len(b), 4)])


def dwords_to_bytes(dws, header_dw):
    """DUT -> host, the exact inverse of `tlp_to_dwords`."""
    out = bytearray()
    for k, dw in enumerate(dws):
        out += int(dw & 0xFFFFFFFF).to_bytes(4, "big" if k < header_dw else "little")
    return bytes(out)


# ---------------------------------------------------------------------------
# Register-block shadow model, used by test_stress.py's scoreboard.
# Only host-visible behaviour is modelled; no micro-architecture.
# ---------------------------------------------------------------------------

class RegModel:
    """Shadow of the BAR0 register block (register-map.md 2).

    The model is *event driven*: the test tells it what the host did and what
    the device reported doing (operation completed, error raised).  It never
    models cycle-level timing -- exact timing is checked separately in
    test_matmul.py against the spec's 4N+2 number.
    """

    def __init__(self, n=N_DEFAULT, dw=DW_DEFAULT, accw=ACCW_DEFAULT):
        self.n = n
        self.dw = dw
        self.accw = accw
        self.reset()

    def reset(self):
        """Hard reset, spec 13.4."""
        self.status = 0
        self.irq_enable = 0
        self.perf_cycles = 0
        self.scratch = 0
        self.op_count = 0

    def soft_reset(self):
        """CTRL.SOFT_RESET, REQ-071: clears BUSY/DONE/errors/PERF_CYCLES only."""
        self.status = 0
        self.perf_cycles = 0
        # SCRATCH, IRQ_ENABLE, OP_COUNT, A/B/C explicitly unchanged.

    def complete_operation(self):
        """Engine finished one op: REQ-075, REQ-082, REQ-084."""
        self.status |= ST_DONE
        self.status &= ~ST_BUSY
        self.perf_cycles = t_mm(self.n)
        self.op_count = (self.op_count + 1) & 0xFFFFFFFF

    def set_error(self, bit):
        self.status |= bit

    def write(self, offset, value, be=0xF):
        """Model a host DWORD write with byte enables (REQ-058/059/060)."""
        value &= 0xFFFFFFFF
        bemask = 0
        for j in range(4):
            if (be >> j) & 1:
                bemask |= 0xFF << (8 * j)

        if offset == REG_SCRATCH:
            self.scratch = (self.scratch & ~bemask) | (value & bemask)
        elif offset == REG_IRQ_ENABLE:
            wr = value & bemask & IRQ_ENABLE_MASK
            keep = self.irq_enable & ~(bemask & IRQ_ENABLE_MASK)
            self.irq_enable = keep | wr
        elif offset == REG_STATUS:
            # W1C: clear only bits written 1 whose BE covers them (REQ-076)
            self.status &= ~(value & bemask & ST_W1C_MASK)
        # CTRL is handled by the test (it has side effects, not state).
        # Everything else is RO or RAZ/WI (REQ-047, REQ-055).

    def read(self, offset):
        if offset == REG_ID:
            return ID_VALUE
        if offset == REG_VERSION:
            return VERSION_VALUE
        if offset == REG_CONFIG:
            return config_value(self.n, self.dw, self.accw)
        if offset == REG_CTRL:
            return 0x00000000                       # REQ-068
        if offset == REG_STATUS:
            return self.status & ST_IMPLEMENTED_MASK  # REQ-078
        if offset == REG_IRQ_ENABLE:
            return self.irq_enable & IRQ_ENABLE_MASK
        if offset == REG_IRQ_STATUS:
            return (self.status & self.irq_enable) & ST_IMPLEMENTED_MASK  # REQ-079
        if offset == REG_PERF_CYCLES:
            return self.perf_cycles
        if offset == REG_SCRATCH:
            return self.scratch
        if offset == REG_OP_COUNT:
            return self.op_count
        return 0x00000000                           # RAZ/WI (REQ-055)

    @property
    def irq(self):
        """REQ-012 / REQ-080: irq == (IRQ_STATUS != 0)."""
        return 1 if self.read(REG_IRQ_STATUS) != 0 else 0


class DeviceModel:
    """Full host-visible shadow: registers + A/B/C storage.

    Used by test_stress.py.  Byte-level so that byte-enable behaviour and the
    RAZ/WI regions are modelled exactly (REQ-055, REQ-086, REQ-088, REQ-091).
    """

    def __init__(self, n=N_DEFAULT):
        self.n = n
        self.regs = RegModel(n)
        self.a = bytearray(n * n)
        self.b = bytearray(n * n)
        self.c = bytearray(4 * n * n)

    def reset(self):
        self.regs.reset()
        self.a = bytearray(self.n * self.n)
        self.b = bytearray(self.n * self.n)
        self.c = bytearray(4 * self.n * self.n)   # REQ-092: rst clears C

    # -- storage ----------------------------------------------------------
    def _region(self, offset):
        if MEM_A_BASE <= offset < MEM_A_BASE + REGION_SIZE:
            return self.a, offset - MEM_A_BASE
        if MEM_B_BASE <= offset < MEM_B_BASE + REGION_SIZE:
            return self.b, offset - MEM_B_BASE
        if MEM_C_BASE <= offset < MEM_C_BASE + REGION_SIZE:
            return self.c, offset - MEM_C_BASE
        return None, 0

    def read_dword(self, offset):
        if offset < REGION_SIZE:
            return self.regs.read(offset)
        store, idx = self._region(offset)
        if store is None:
            return 0
        out = 0
        for j in range(4):
            byte = store[idx + j] if idx + j < len(store) else 0  # RAZ
            out |= byte << (8 * j)
        return out

    def write_dword(self, offset, value, be=0xF, busy=False):
        """Returns True if the write was applied, False if discarded."""
        if offset < REGION_SIZE:
            self.regs.write(offset, value, be)
            return True
        if busy:
            # REQ-062: A/B/C writes while BUSY are discarded and set the error
            self.regs.set_error(ST_ERR_WRITE_BUSY)
            return False
        store, idx = self._region(offset)
        if store is None:
            return False
        for j in range(4):
            if ((be >> j) & 1) and idx + j < len(store):   # WI beyond N*N
                store[idx + j] = (value >> (8 * j)) & 0xFF
        return True

    def run_matmul(self):
        """REQ-105 / REQ-117: overwrite C completely from current A and B."""
        n = self.n
        a = bytes_to_a(self.a, n)
        b = bytes_to_b(self.b, n)
        c = matmul_golden(a, b, n)
        self.c = bytearray(c_to_bytes(c, n))
        self.regs.complete_operation()
