"""
Host-side wrapper over `cocotbext.pcie.core.RootComplex`.

Tests are meant to read like host driver code:

    tb = await Host.create(dut)
    await tb.enumerate()
    await tb.write_dword(REG_SCRATCH, 0xDEADBEEF)
    v = await tb.read_dword(REG_ID)

Everything host-visible goes through cocotbext-pcie, which is the reference for
TLP encoding.  Hand-built TLPs (for negative tests the root complex will never
generate) still use the library's `Tlp` class; only the *framing* is ours.
"""

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.queue import QueueEmpty
from cocotb.triggers import (ClockCycles, RisingEdge, SimTimeoutError,
                             with_timeout)

from cocotbext.pcie.core import RootComplex
from cocotbext.pcie.core.tlp import Tlp, TlpType, TlpAttr, TlpTc, CplStatus
from cocotbext.pcie.core.utils import PcieId

from . import golden as G
from .tlp_stream_shim import TlpStreamShim

# 100 MHz, spec 13.2 / DEC-009
CLK_PERIOD_NS = 10

# Generous per-operation timeout: a 32 DW burst on a strictly serialized DUT
# (DEC-007) is well under 100 cycles, so 2000 cycles means "hung", not "slow".
OP_TIMEOUT_NS = 20000

DEFAULT_SEED = 1


def get_seed():
    """Seed every random choice from $SEED; print the value used."""
    raw = os.environ.get("SEED")
    if raw is None or raw == "":
        seed = DEFAULT_SEED
        src = "default (export SEED=<n> to change)"
    else:
        seed = int(raw, 0)
        src = "$SEED"
    print(f"[tb] SEED = {seed}  [{src}]")
    return seed


class TbTimeout(AssertionError):
    pass


async def wait_for(sig, value, name, cycles, clk):
    """Wait until `sig == value`, or fail with a message naming the signal.

    No fixed `sleep`-style waits exist anywhere in this testbench (agent rule).
    """
    for _ in range(cycles):
        await RisingEdge(clk)
        try:
            if int(sig.value) == value:
                return
        except Exception:
            continue                       # X during reset; keep waiting
    raise TbTimeout(
        f"timeout after {cycles} clock cycles waiting for {name} == {value} "
        f"(last observed {sig.value!r})"
    )


class Host:
    """Root complex + shim + clock/reset, wrapped as a host driver."""

    def __init__(self, dut, seed=None, rx_gap_prob=0.0, tx_stall_prob=0.0,
                 n=None):
        self.dut = dut
        self.seed = seed if seed is not None else get_seed()
        self.rng = random.Random(self.seed)
        self.rx_gap_prob = rx_gap_prob
        self.tx_stall_prob = tx_stall_prob

        self.rc = None
        self.shim = None
        self.dev = None
        self.bar0_addr = None
        self.window = None
        self.n = n

        # Completer ID captured by the DUT from the last accepted Type 0
        # config request (REQ-052); reset value 0x0000 (spec 13.4).
        self.dev_id = PcieId(1, 0, 0)
        self.expected_completer_id = PcieId(0, 0, 0)

        self._tag = 0

    # ------------------------------------------------------------------
    @classmethod
    async def create(cls, dut, **kwargs):
        self = cls(dut, **kwargs)
        await self.start()
        return self

    async def start(self):
        """Start the clock, reset the DUT, then build the PCIe environment.

        `RootComplex()` calls `cocotb.start_soon()` in its constructor, so it
        must be built inside a running test -- never at module import.
        """
        cocotb.start_soon(Clock(self.dut.clk, CLK_PERIOD_NS, unit="ns").start())

        self.dut.rst.value = 1
        self.dut.rx_tlp_data.value = 0
        self.dut.rx_tlp_sop.value = 0
        self.dut.rx_tlp_eop.value = 0
        self.dut.rx_tlp_valid.value = 0
        self.dut.tx_tlp_ready.value = 0
        await ClockCycles(self.dut.clk, 5)

        self.rc = RootComplex()
        # spec 4.5 / DEC-006: bound inbound MWr payload and MRd length to
        # 32 DW.  max_read_request_size defaults to 2 (512 B) -- a real change.
        self.rc.max_payload_size = 0
        self.rc.max_read_request_size = 0

        self.shim = TlpStreamShim(
            self.dut, rng=random.Random(self.seed ^ 0x5EED),
            rx_gap_prob=self.rx_gap_prob, tx_stall_prob=self.tx_stall_prob)
        self.rc.make_port().connect(self.shim.upstream_port)

        await self.reset()

    async def reset(self, cycles=2):
        """Assert `rst` for >= 2 cycles (REQ-108, REQ-109)."""
        self.dut.rst.value = 1
        await ClockCycles(self.dut.clk, cycles)
        self.dut.rst.value = 0
        await RisingEdge(self.dut.clk)
        # Every host-visible register returns to its spec 13.4 reset value.
        self.bar0_addr = None
        self.window = None
        self.expected_completer_id = PcieId(0, 0, 0)

    # ------------------------------------------------------------------
    # Enumeration (spec 15 steps 1-3)
    # ------------------------------------------------------------------
    async def enumerate(self, enable_mse=True, enable_bme=True):
        await self.rc.enumerate(timeout=OP_TIMEOUT_NS, timeout_unit="ns")

        # Find the DUT among the enumerated devices.
        #
        # Host-model quirk, not a DUT bug: the DUT accepts a Type 0 config
        # request with Device 0 / Function 0 on *any* bus number (spec 4.2 and
        # REQ-042 constrain only Device and Function).  A second
        # `rc.enumerate()` on the same RootComplex therefore discovers it again
        # behind the same root port on a fresh secondary bus, and the *last*
        # BAR0 write wins inside the DUT.  Select the PciDevice whose assigned
        # BAR0 matches the value actually programmed into the device.
        candidates = []
        for bus in range(0, 16):
            d = self.rc.find_device(PcieId(bus, 0, 0))
            if d is not None and d.vendor_id == G.CFG_VENDOR_ID \
                    and d.device_id == G.CFG_DEVICE_ID:
                candidates.append((bus, d))

        self.dev = None
        if candidates:
            probe_bus = candidates[-1][0]
            live_bar0 = (await self.cfg_read_dword(
                0x10, dev_id=PcieId(probe_bus, 0, 0))) & 0xFFFFC000
            match = [(b, d) for b, d in candidates
                     if d.bar_addr[0] == live_bar0]
            bus, self.dev = (match[-1] if match else candidates[-1])
            self.dev_id = PcieId(bus, 0, 0)
        assert self.dev is not None, (
            "enumeration did not find the DUT: expected vendor "
            f"0x{G.CFG_VENDOR_ID:04x} device 0x{G.CFG_DEVICE_ID:04x} at "
            "device 0, function 0 (REQ-112, DEC-011)"
        )
        assert self.dev.bar_window[0] is not None, (
            "the root complex did not assign BAR0; check the 16 KiB sizing "
            "readback 0xFFFFC000 (REQ-048, REQ-115)"
        )
        self.window = self.dev.bar_window[0]
        self.bar0_addr = self.dev.bar_addr[0]
        self.expected_completer_id = self.dev_id

        cmd = 0
        if enable_mse:
            cmd |= G.CMD_MSE
        if enable_bme:
            cmd |= G.CMD_BME
        if cmd:
            await self.cfg_write_dword(0x04, cmd)
        return self.dev

    # ------------------------------------------------------------------
    # BAR0 access (goes through the root complex's TLP region model)
    # ------------------------------------------------------------------
    async def mem_write(self, offset, data):
        """Posted write to BAR0+offset, returning only once it is on the wire.

        `region.write()` returns as soon as the TLP has been handed to the
        behavioral link model, which delays it by `SimPort.port_delay` before
        the shim ever sees it.  Without the drain below, a subsequent
        `shim.inject()` would overtake the write and the test would silently
        exercise the wrong order of operations.
        """
        assert self.window is not None, "call enumerate() first"
        await self.window.write(offset, bytes(data),
                                timeout=OP_TIMEOUT_NS, timeout_unit="ns")
        await self.drain()

    async def drain(self):
        """Wait until every host-issued TLP has been transferred to the DUT."""
        await ClockCycles(self.dut.clk, 3)
        await self.shim.wait_rx_idle()

    async def mem_read(self, offset, length):
        assert self.window is not None, "call enumerate() first"
        return await self.window.read(offset, length,
                                      timeout=OP_TIMEOUT_NS, timeout_unit="ns")

    async def write_dword(self, offset, value):
        await self.mem_write(offset, int(value & 0xFFFFFFFF).to_bytes(4, "little"))

    async def read_dword(self, offset):
        return int.from_bytes(await self.mem_read(offset, 4), "little")

    # ------------------------------------------------------------------
    # Configuration space.  Always via raw Type 0 TLPs so that the tests work
    # before enumeration too (REQ-051, REQ-112, REQ-121) and so that byte
    # enables are under test control (REQ-046).
    # ------------------------------------------------------------------
    def next_tag(self):
        self._tag = (self._tag + 1) & 0xFF
        return self._tag

    def make_cfg_read(self, offset, be=0xF, dev_id=None, tag=None, type1=False):
        tlp = Tlp()
        tlp.fmt_type = TlpType.CFG_READ_1 if type1 else TlpType.CFG_READ_0
        tlp.requester_id = PcieId(0, 0, 0)
        tlp.completer_id = dev_id if dev_id is not None else self.dev_id
        tlp.tag = self.next_tag() if tag is None else tag
        tlp.length = 1
        tlp.first_be = be
        tlp.last_be = 0
        tlp.address = offset & 0xFFC
        return tlp

    def make_cfg_write(self, offset, value, be=0xF, dev_id=None, tag=None,
                       type1=False):
        tlp = Tlp()
        tlp.fmt_type = TlpType.CFG_WRITE_1 if type1 else TlpType.CFG_WRITE_0
        tlp.requester_id = PcieId(0, 0, 0)
        tlp.completer_id = dev_id if dev_id is not None else self.dev_id
        tlp.tag = self.next_tag() if tag is None else tag
        tlp.length = 1
        tlp.first_be = be
        tlp.last_be = 0
        tlp.address = offset & 0xFFC
        tlp.set_data(int(value & 0xFFFFFFFF).to_bytes(4, "little"))
        return tlp

    async def cfg_read_dword(self, offset, be=0xF, dev_id=None):
        cpl = await self.raw_request(self.make_cfg_read(offset, be, dev_id))
        assert cpl is not None, (
            f"no completion for CfgRd0 of cfg offset 0x{offset:03x} (REQ-031)")
        assert cpl.status == CplStatus.SC, (
            f"CfgRd0 of cfg offset 0x{offset:03x} returned status "
            f"{cpl.status!r}, expected SC (REQ-045)")
        if dev_id is None or (dev_id.device == 0 and dev_id.function == 0):
            self.expected_completer_id = \
                dev_id if dev_id is not None else self.dev_id
        return int.from_bytes(cpl.get_data(), "little")

    async def cfg_write_dword(self, offset, value, be=0xF, dev_id=None):
        cpl = await self.raw_request(
            self.make_cfg_write(offset, value, be, dev_id))
        assert cpl is not None, (
            f"no completion for CfgWr0 of cfg offset 0x{offset:03x} (REQ-034)")
        assert cpl.status == CplStatus.SC, (
            f"CfgWr0 of cfg offset 0x{offset:03x} returned status "
            f"{cpl.status!r}, expected SC (REQ-046/REQ-047)")
        if dev_id is None or (dev_id.device == 0 and dev_id.function == 0):
            self.expected_completer_id = \
                dev_id if dev_id is not None else self.dev_id
        return cpl

    # ------------------------------------------------------------------
    # Raw TLP injection: full control of every header field, for the negative
    # tests in test_tlp.py.  Encoding is still done by cocotbext-pcie.
    # ------------------------------------------------------------------
    def make_mem_read(self, addr, length=1, first_be=0xF, last_be=0,
                      tag=None, tc=TlpTc.TC0, attr=TlpAttr(0), dw64=False):
        tlp = Tlp()
        tlp.fmt_type = TlpType.MEM_READ_64 if dw64 else TlpType.MEM_READ
        tlp.requester_id = PcieId(0, 0, 0)
        tlp.tag = self.next_tag() if tag is None else tag
        tlp.tc = tc
        tlp.attr = attr
        tlp.length = length
        tlp.first_be = first_be
        tlp.last_be = last_be if length > 1 else 0
        tlp.address = addr & ~3
        return tlp

    def make_mem_write(self, addr, data, first_be=0xF, last_be=None,
                       tag=None, tc=TlpTc.TC0, attr=TlpAttr(0), dw64=False):
        tlp = Tlp()
        tlp.fmt_type = TlpType.MEM_WRITE_64 if dw64 else TlpType.MEM_WRITE
        tlp.requester_id = PcieId(0, 0, 0)
        tlp.tag = self.next_tag() if tag is None else tag
        tlp.tc = tc
        tlp.attr = attr
        tlp.address = addr & ~3
        tlp.set_data(bytes(data))
        tlp.first_be = first_be
        if last_be is None:
            last_be = 0xF if tlp.length > 1 else 0
        tlp.last_be = last_be if tlp.length > 1 else 0
        return tlp

    async def raw_request(self, tlp, expect_completion=True,
                          timeout_ns=OP_TIMEOUT_NS, quiet_cycles=8):
        """Inject `tlp` and return the DUT's Completion (or None).

        Outbound TLPs are captured rather than forwarded upstream, because the
        root complex never issued these requests and would log them as
        unexpected completions.
        """
        cap = self.shim.start_capture()
        try:
            await self.shim.inject(tlp)
            if expect_completion:
                cpl = await self._get_capture(cap, timeout_ns, tlp)
                return cpl
            # Prove the *absence* of a completion (REQ-036, REQ-037, REQ-039,
            # REQ-041): drain the inbound stream, then wait a fixed, generous
            # number of idle cycles and require nothing came back.
            await self.shim.wait_rx_idle()
            await ClockCycles(self.dut.clk, quiet_cycles)
            try:
                stray = cap.get_nowait()
            except QueueEmpty:
                return None
            raise AssertionError(
                f"DUT emitted a Completion for a request that must not get "
                f"one: request {tlp!r} -> completion {stray!r}")
        finally:
            self.shim.stop_capture()

    async def _get_capture(self, cap, timeout_ns, tlp):
        try:
            return await with_timeout(cap.get(), timeout_ns, "ns")
        except SimTimeoutError:
            raise TbTimeout(
                f"no Completion appeared on tx_tlp_valid within {timeout_ns} "
                f"ns for request {tlp!r}") from None

    async def settle(self, cycles=8):
        """Let the inbound stream drain and the DUT come to rest.

        This is not a fixed 'sleep': it waits on the shim's rx-idle Event and
        then allows a bounded number of cycles for the DUT's serialized
        pipeline (spec 7.1) to finish the last request.

        The leading ClockCycles covers `SimPort.port_delay` (2 x 5 ns): a
        posted write returns from `region.write()` before its TLP has even
        reached the shim, so sampling rx-idle immediately would see a stale
        "idle".
        """
        await ClockCycles(self.dut.clk, 3)
        await self.shim.wait_rx_idle()
        await ClockCycles(self.dut.clk, cycles)


def sign8(v):
    return G._as_signed8(v)
