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

from cocotb.triggers import ClockCycles, RisingEdge          # noqa: E402

from models import golden as G                               # noqa: E402
from models.host import Host, TbTimeout, get_seed, wait_for  # noqa: E402
from cocotbext.pcie.core.tlp import CplStatus               # noqa: E402

__all__ = [
    "G", "Host", "TbTimeout", "get_seed", "wait_for", "make_tb", "discover_n",
    "start_op", "wait_done", "run_op", "load_ab", "read_c", "CplStatus",
    "random_matrix", "clear_status", "ClockCycles", "RisingEdge",
    "mwr_dword", "mrd", "assert_matrix_equal", "fmt_matrix",
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
