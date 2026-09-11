"""
Shared helpers for the matmul_top cocotb suite.

Everything here is spec-derived.  No helper reads a value back from the DUT and
then treats it as an expectation: expectations come from docs/spec.md,
docs/register-map.md or tb/models/golden.py only.
"""

import random
import sys
from pathlib import Path

# tb/ on the path so `models` imports work under cocotb's module loader
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cocotb                                                # noqa: E402
from cocotb.triggers import ClockCycles, RisingEdge          # noqa: E402

from models import golden as G                               # noqa: E402
from models.host import (Host, TbTimeout, get_seed, wait_for,        # noqa: E402
                         cycle_now, wait_value_cycle)
from cocotbext.pcie.core.tlp import CplStatus               # noqa: E402

__all__ = [
    "G", "Host", "TbTimeout", "get_seed", "wait_for", "make_tb", "discover_n",
    "start_op", "wait_done", "run_op", "load_ab", "read_c", "CplStatus",
    "random_matrix", "clear_status", "ClockCycles", "RisingEdge",
    "mwr_dword", "mrd", "assert_matrix_equal", "fmt_matrix",
    "cycle_now", "wait_value_cycle", "measure_d_wr", "measure_d_wr_falling",
    "inject_and_get_beat", "mrd_dword", "mwr_burst",
]

# Polling bound for "the operation should have finished by now".  One STATUS
# read is ~10 cycles of TLP traffic, and the operation itself is 4N+2 = 34
# cycles at N=8 (REQ-101), so 64 polls is far past any legal latency.
DONE_POLL_LIMIT = 64


async def make_tb(dut, enumerate_=True, **kwargs):
    """Standard bring-up: clock, reset, root complex, shim, enumeration."""
    tb = await Host.create(dut, **kwargs)
    if enumerate_:
        await tb.enumerate()
    return tb


async def discover_n(tb):
    """Read N from CONFIG[7:0] instead of hard-coding it (REQ-114)."""
    cfg = await tb.read_dword(G.REG_CONFIG)
    n = cfg & 0xFF
    assert n in (2, 4, 8, 16, 32), (
        f"CONFIG[7:0] = {n}, which is not a legal N (spec 14: power of two, "
        f"2..32).  CONFIG read 0x{cfg:08x}")
    tb.n = n
    return n


async def start_op(tb):
    """Write CTRL.START (REQ-069)."""
    await tb.write_dword(G.REG_CTRL, G.CTRL_START)


async def wait_done(tb, limit=DONE_POLL_LIMIT):
    """Poll STATUS until DONE is set (REQ-075); fail naming the register."""
    for _ in range(limit):
        st = await tb.read_dword(G.REG_STATUS)
        if st & G.ST_DONE:
            return st
    raise TbTimeout(
        f"STATUS.DONE (BAR0+0x{G.REG_STATUS:04x} bit 1) never set after "
        f"{limit} polls; the operation should complete in 4N+2 cycles "
        f"(REQ-101)")


async def clear_status(tb, bits=G.ST_W1C_MASK):
    """W1C the given STATUS bits (REQ-076)."""
    await tb.write_dword(G.REG_STATUS, bits)


async def run_op(tb):
    """START, wait for DONE, clear DONE.  Returns the STATUS seen at DONE."""
    await start_op(tb)
    st = await wait_done(tb)
    await clear_status(tb, G.ST_DONE)
    return st


async def load_ab(tb, a, b, n, chunk=None):
    """Write A and B through BAR0 (spec 15 step 4)."""
    await tb.mem_write(G.MEM_A_BASE, G.a_to_bytes(a, n))
    await tb.mem_write(G.MEM_B_BASE, G.b_to_bytes(b, n))


async def read_c(tb, n):
    """Read back the whole C region and decode it (spec 9.2)."""
    raw = await tb.mem_read(G.MEM_C_BASE, 4 * n * n)
    return G.bytes_to_c(raw, n)


def random_matrix(rng, n, lo=-128, hi=127):
    return [[rng.randint(lo, hi) for _ in range(n)] for _ in range(n)]


def fmt_matrix(m):
    return "\n".join("  " + " ".join(f"{v:>12d}" for v in row) for row in m)


def assert_matrix_equal(got, exp, what, extra=""):
    if got == exp:
        return
    n = len(exp)
    diffs = [(i, j, got[i][j], exp[i][j])
             for i in range(n) for j in range(n) if got[i][j] != exp[i][j]]
    head = "\n".join(f"    [{i}][{j}]: DUT {g} != golden {e}"
                     for i, j, g, e in diffs[:8])
    raise AssertionError(
        f"{what}: {len(diffs)} of {n * n} elements differ (REQ-105).{extra}\n"
        f"{head}\n  golden:\n{fmt_matrix(exp)}\n  DUT:\n{fmt_matrix(got)}")


# ---------------------------------------------------------------------------
# Raw single-DWORD BAR0 accesses with test-controlled byte enables.
# The RootComplex only ever generates "natural" BE patterns, so byte-enable
# requirements (REQ-058 .. REQ-061, REQ-073, REQ-076) need hand-built TLPs.
# Encoding is still done by cocotbext-pcie's Tlp class.
# ---------------------------------------------------------------------------

async def mwr_dword(tb, offset, value, be=0xF, quiet_cycles=8):
    """Posted single-DWORD MWr to BAR0+offset with First BE = `be`.

    Also proves REQ-036 on every call: a posted request gets no Completion.
    """
    tlp = tb.make_mem_write(tb.bar0_addr + offset,
                            int(value & 0xFFFFFFFF).to_bytes(4, "little"),
                            first_be=be)
    await tb.raw_request(tlp, expect_completion=False, quiet_cycles=quiet_cycles)


async def mrd(tb, offset, length=1, first_be=0xF, last_be=0, **kwargs):
    """Non-posted MRd to BAR0+offset; returns the raw Completion TLP."""
    tlp = tb.make_mem_read(tb.bar0_addr + offset, length=length,
                           first_be=first_be, last_be=last_be, **kwargs)
    cpl = await tb.raw_request(tlp)
    return tlp, cpl


async def mrd_dword(tb, offset):
    """Single-DWORD read returning the 32-bit value, checking SC status."""
    req, cpl = await mrd(tb, offset)
    assert cpl.status == CplStatus.SC, (
        f"MRd of BAR0+0x{offset:04x} returned status {cpl.status!r}, "
        "expected SC (REQ-055 says implemented-but-unused offsets are "
        "RAZ/WI with SC, not UR)")
    return int.from_bytes(cpl.get_data(), "little")


async def mwr_burst(tb, writes, quiet_cycles=8):
    """Inject several posted MWrs back-to-back with no host-side gap.

    Needed wherever the *relative* timing of two writes matters (for example
    START-while-BUSY, REQ-070): a normal `mwr_dword` call waits for quiet
    before returning, by which time a 4N+2 cycle operation has finished.
    """
    cap = tb.shim.start_capture()
    try:
        for offset, value, be in writes:
            tlp = tb.make_mem_write(
                tb.bar0_addr + offset,
                int(value & 0xFFFFFFFF).to_bytes(4, "little"), first_be=be)
            await tb.shim.inject(tlp)
        await tb.shim.wait_rx_idle()
        await ClockCycles(tb.dut.clk, quiet_cycles)
        stray = []
        while True:
            try:
                stray.append(cap.get_nowait())
            except Exception:
                break
        assert not stray, (
            "REQ-036: the DUT returned a Completion for a posted Memory "
            f"Write: {stray[0]!r}")
    finally:
        tb.shim.stop_capture()


# ---------------------------------------------------------------------------
# D_WR, the BAR0 write-path constant (spec 9.6, REQ-122)
# ---------------------------------------------------------------------------
#
# D_WR = t_commit - t_beat, where t_beat is the cycle the payload DWORD of a
# BAR0 write transfers on rx_tlp_* and t_commit is the cycle the addressed
# location holds the new value.
#
# The spec suggests "write SCRATCH, then read it back on successive cycles".
# That is not usable here: DEC-007 makes the DUT strictly serialized, so it
# holds rx_tlp_ready low until the write has retired and a read-back can never
# sample the location early.  The observable channel is `irq`, because REQ-012
# makes it a *registered* copy of |IRQ_STATUS -- exactly one cycle of lag, not
# a bound.  Writing IRQ_ENABLE while STATUS.DONE is already set therefore
# gives:
#
#     IRQ_ENABLE commits during cycle t_beat + D_WR
#     IRQ_STATUS (combinational) is non-zero during the same cycle
#     irq (registered) is 1 during cycle t_beat + D_WR + 1     [REQ-012]
#
#     =>  D_WR = t_irq - t_beat - 1
#
# The same relation run backwards (W1C of STATUS.DONE, irq falling) gives a
# second, independent measurement.

async def _ctrl_write_tlp(tb, offset, value, be=0xF):
    return tb.make_mem_write(tb.bar0_addr + offset,
                             int(value & 0xFFFFFFFF).to_bytes(4, "little"),
                             first_be=be)


async def inject_and_get_beat(tb, tlp, payload_index=None, limit=2000):
    """Inject one TLP; return the cycle a chosen payload beat transferred.

    `payload_index` selects which payload DWORD's beat to report (0 = the
    first payload DWORD).  `None` means the final beat, which is the same
    thing for a single-DWORD write.  REQ-122's burst-position clause needs
    the per-DWORD cycle, not the end-of-packet cycle.
    """
    tb.shim.last_eop_cycle = None
    tb.shim.last_packet_beat_cycles = []
    await tb.shim.inject(tlp)
    for _ in range(limit):
        await RisingEdge(tb.dut.clk)
        if tb.shim.last_eop_cycle is not None and tb.shim.rx_queue.empty():
            if payload_index is None:
                return tb.shim.last_eop_cycle
            hdr_dw = tlp.get_header_size() // 4
            beats = tb.shim.last_packet_beat_cycles
            assert len(beats) > hdr_dw + payload_index, (
                f"internal: packet had {len(beats)} beats, cannot index "
                f"payload DWORD {payload_index}")
            return beats[hdr_dw + payload_index]
    raise TbTimeout(
        "the injected TLP's eop beat never transferred on rx_tlp_valid/"
        f"rx_tlp_ready within {limit} cycles")


def _burst_tlp(tb, start, ndw, index, value, be):
    """MWr of `ndw` DWORDs at `start`, carrying `value` at DWORD `index`."""
    payload = bytearray()
    for k in range(ndw):
        payload += (value if k == index else 0).to_bytes(4, "little")
    tlp = tb.make_mem_write(tb.bar0_addr + start, bytes(payload))
    tlp.first_be = be if index == 0 else 0xF
    tlp.last_be = be if index == ndw - 1 else 0xF
    if ndw == 1:
        tlp.first_be, tlp.last_be = be, 0
    return tlp


async def _arm_for_d_wr(tb):
    """STATUS.DONE set, IRQ_ENABLE clear, irq low."""
    await mwr_dword(tb, G.REG_IRQ_ENABLE, 0x00000000)
    await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
    await start_op(tb)
    await wait_done(tb)
    assert int(tb.dut.irq.value) == 0, (
        "irq is high before IRQ_ENABLE was written; the D_WR measurement "
        "needs it low (REQ-079/REQ-080)")


async def measure_d_wr(tb, be=0xF, burst=None, limit=64):
    """Measure D_WR once, at the chip boundary (spec 9.6, REQ-122).

    `burst`, if given, is `(start_offset, n_dwords, index)`, placing the
    IRQ_ENABLE DWORD at a chosen position inside a multi-DWORD MWr so that
    REQ-122's "regardless of the DWORD's position within a burst" clause can
    be checked.  `be` sets the byte enable covering that DWORD.

    The irq watcher is started *before* the TLP is injected so that the
    transition cannot be missed by a task-ordering race at a clock edge.
    """
    await _arm_for_d_wr(tb)

    if burst is None:
        tlp = _burst_tlp(tb, G.REG_IRQ_ENABLE, 1, 0, G.ST_DONE, be)
    else:
        start, ndw, index = burst
        assert start + 4 * index == G.REG_IRQ_ENABLE, (
            "the burst must place IRQ_ENABLE at the requested index")
        tlp = _burst_tlp(tb, start, ndw, index, G.ST_DONE, be)

    cap = tb.shim.start_capture()
    try:
        watcher = cocotb.start_soon(
            wait_value_cycle(tb.dut.clk, tb.dut.irq, 1, "irq", limit))
        t_beat = await inject_and_get_beat(
            tb, tlp, payload_index=(0 if burst is None else burst[2]))
        t_irq = await watcher
    finally:
        tb.shim.stop_capture()

    # REQ-012: irq is a registered copy of |IRQ_STATUS, so exactly one cycle
    # of lag between IRQ_ENABLE committing and irq rising.
    d_wr = t_irq - t_beat - 1

    await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
    await mwr_dword(tb, G.REG_IRQ_ENABLE, 0x00000000)
    return d_wr


async def measure_d_wr_falling(tb, limit=64):
    """Second, independent D_WR measurement: W1C of STATUS.DONE, irq falling."""
    await _arm_for_d_wr(tb)
    await mwr_dword(tb, G.REG_IRQ_ENABLE, G.ST_DONE)
    await wait_for(tb.dut.irq, 1, "irq", 8, tb.dut.clk)

    tlp = _burst_tlp(tb, G.REG_STATUS, 1, 0, G.ST_DONE, 0xF)
    cap = tb.shim.start_capture()
    try:
        watcher = cocotb.start_soon(
            wait_value_cycle(tb.dut.clk, tb.dut.irq, 0, "irq", limit))
        t_beat = await inject_and_get_beat(tb, tlp)
        t_irq = await watcher
    finally:
        tb.shim.stop_capture()

    d_wr = t_irq - t_beat - 1
    await mwr_dword(tb, G.REG_IRQ_ENABLE, 0x00000000)
    await mwr_dword(tb, G.REG_STATUS, G.ST_W1C_MASK)
    return d_wr
