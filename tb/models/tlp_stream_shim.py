"""
TLP <-> DWORD-stream shim (DEC-003 Option B, docs/spec.md section 5).

This is the *only* piece of testbench that touches the DUT's PCIe pins.  It is
deliberately mechanical: it moves already-encoded DWORDs and never interprets
TLP contents.  All TLP encode/decode is done by `cocotbext.pcie.core.tlp.Tlp`
(CLAUDE.md rule: "the testbench never hand-writes TLP encode/decode").

Attach model, per spec 5.4:
  * subclass `cocotbext.pcie.core.device.Device`
  * override `upstream_recv(tlp)` to serialize onto `rx_tlp_*`
  * run a task deserializing `tx_tlp_*` and calling `upstream_send(tlp)`
  * connect with `rc.make_port().connect(shim.upstream_port)`
  * never call `append_function()` / `make_function()`: the DUT owns config space

It also contains an always-on protocol checker for spec 5.2 (REQ-001 ..
REQ-007) and 7.4 (REQ-023) on the DUT-driven signals, so every test in the
suite exercises those requirements.
"""

import os
import random

import cocotb
from cocotb.queue import Queue
from cocotb.triggers import Event, RisingEdge, Timer

from cocotb.utils import get_sim_time

from cocotbext.pcie.core.device import Device
from cocotbext.pcie.core.tlp import Tlp

from .golden import tlp_to_dwords, dwords_to_bytes


class ProtocolError(AssertionError):
    """A DUT violation of the spec 5.2 stream contract."""


CLK_PERIOD_NS = 10          # must match models.host.CLK_PERIOD_NS


def _cycle_now():
    return int(round(get_sim_time("ns") / CLK_PERIOD_NS))


def _i(sig, name):
    """int() a cocotb 2.x LogicArray with a useful message on X/Z."""
    try:
        return int(sig.value)
    except Exception as exc:                      # X or Z present
        raise ProtocolError(
            f"signal {name} is not a clean 0/1 value: {sig.value!r} ({exc}). "
            "X-propagation is a DUT bug, not a testbench nuisance."
        ) from None


class TlpStreamShim(Device):
    """Serializes Tlp objects onto rx_tlp_* and deserializes tx_tlp_*.

    Parameters
    ----------
    dut : the `matmul_top` handle (ports per spec 6.1)
    clk, rst : handles, defaulting to `dut.clk` / `dut.rst`
    rng : a `random.Random`, seeded from SEED by the Host wrapper
    rx_gap_prob : probability of an idle cycle between inbound beats (REQ-005)
    tx_stall_prob : probability of deasserting `tx_tlp_ready` (REQ-002/REQ-007)
    """

    def __init__(self, dut, clk=None, rst=None, rng=None,
                 rx_gap_prob=0.0, tx_stall_prob=0.0):
        super().__init__()

        self.dut = dut
        self.clk = clk if clk is not None else dut.clk
        self.rst = rst if rst is not None else dut.rst
        self.rng = rng if rng is not None else random.Random(0)
        self.rx_gap_prob = rx_gap_prob
        self.tx_stall_prob = tx_stall_prob

        # Inbound (host -> DUT).  Queue items are (beats, tlp) where `beats`
        # is a list of (data, sop, eop) tuples.  Keeping beats rather than
        # TLPs lets a test inject deliberately malformed framing (REQ-020).
        self.rx_queue = Queue()
        self.rx_idle = Event()
        self.rx_idle.set()
        self._rx_valid = 0
        # When set, the rx driver stops touching rx_tlp_* entirely so a test
        # can drive the pins itself (used for the REQ-003 combinational check).
        self.rx_paused = False
        # When set, tx_tlp_ready is forced low regardless of tx_stall_prob
        # (used for the REQ-007 / REQ-015 indefinite-backpressure check).
        self.tx_force_stall = False

        # Outbound (DUT -> host).  Every TLP the DUT emits lands in
        # `tx_monitor` as well as being forwarded upstream, so tests and
        # scoreboards can inspect raw completion header fields.
        self.tx_monitor = Queue()
        # When `capture` is non-None, outbound TLPs are diverted to it instead
        # of being forwarded to the root complex.  Used for raw-injection tests
        # whose requests the RootComplex never issued and would not route.
        self.capture = None

        # Exact cycle of the most recent inbound beat / end-of-packet beat,
        # in the numbering of models.host.cycle_now().  `last_eop_cycle` is
        # `t_beat` for the payload DWORD of a single-DWORD write (spec 9.6).
        self.last_beat_cycle = None
        self.last_eop_cycle = None
        # Per-beat cycle list of the most recently completed inbound packet,
        # so a test can name the exact beat that carried a given payload
        # DWORD (REQ-122's burst-position clause needs that, not the eop).
        self.last_packet_beat_cycles = []

        # Counters/flags for the protocol checker
        self.tx_packets = 0
        self.rx_packets = 0
        self.tx_in_packet = False
        self.checks_enabled = True

        self.dut.rx_tlp_data.value = 0
        self.dut.rx_tlp_sop.value = 0
        self.dut.rx_tlp_eop.value = 0
        self.dut.rx_tlp_valid.value = 0
        self.dut.tx_tlp_ready.value = 0

        cocotb.start_soon(self._run_rx())
        cocotb.start_soon(self._run_tx())

    # ------------------------------------------------------------------
    # Device hooks (spec 5.4)
    # ------------------------------------------------------------------
    async def upstream_recv(self, tlp):
        """Host -> device.  Queue the TLP for serialization; do NOT route it
        to a Python Function (there is none; the DUT owns config space)."""
        self.rx_idle.clear()
        await self.rx_queue.put((self.tlp_to_beats(tlp), tlp))

    async def inject(self, tlp):
        """Push a hand-built TLP straight onto the stream, bypassing the DLL.

        Legitimate because zero DLLPs cross the chip boundary (spec 4.4): from
        the DUT's point of view an injected TLP is indistinguishable from one
        that arrived through the link model.  Used for negative tests the
        RootComplex will not generate (bad Length, TD/EP set, Type 1 config,
        MRd64, inbound completions, ...).
        """
        self.rx_idle.clear()
        await self.rx_queue.put((self.tlp_to_beats(tlp), tlp))

    async def inject_beats(self, beats):
        """Push raw (data, sop, eop) beats onto rx_tlp_*.

        The only way to present framing that no legal TLP produces -- a
        truncated packet followed by a fresh `sop` (REQ-020).
        """
        self.rx_idle.clear()
        await self.rx_queue.put((list(beats), None))

    @staticmethod
    def tlp_to_beats(tlp):
        dws = tlp_to_dwords(tlp)
        return [(dw, 1 if k == 0 else 0, 1 if k == len(dws) - 1 else 0)
                for k, dw in enumerate(dws)]

    async def wait_rx_idle(self):
        """Block until every queued inbound TLP has been fully transferred."""
        await self.rx_idle.wait()

    # ------------------------------------------------------------------
    # DWORD conversion (spec 5.3) -- the two mappings, and nothing else
    # ------------------------------------------------------------------
    @staticmethod
    def tlp_to_dwords(tlp):
        return tlp_to_dwords(tlp)

    @staticmethod
    def dwords_to_tlp(dws):
        """Inverse of `tlp_to_dwords`, then `Tlp.unpack()`.

        The header size is discovered by unpacking a provisional header from
        the first 3 DWORDs (12 bytes -- correct for every TLP in this design,
        spec 5.3); if the DUT ever emitted a 4 DW header this picks it up and
        re-converts.
        """
        if len(dws) < 3:
            raise ProtocolError(
                f"TLP with only {len(dws)} DWORD(s) on tx_tlp_*; the minimum "
                "TLP is 3 header DWORDs (REQ-004)"
            )
        probe = Tlp.unpack_header(dwords_to_bytes(dws[:3], 3))
        hdr_dw = probe.get_header_size() // 4
        if hdr_dw > len(dws):
            raise ProtocolError(
                f"TLP claims a {hdr_dw} DWORD header but only {len(dws)} "
                "DWORDs were framed"
            )
        return Tlp.unpack(dwords_to_bytes(dws, hdr_dw))

    # ------------------------------------------------------------------
    # Inbound driver
    # ------------------------------------------------------------------
    async def _run_rx(self):
        beats = []
        idx = 0
        tlp = None
        beat_cycles = []

        while True:
            await RisingEdge(self.clk)

            if self.rx_paused:
                continue

            if _i(self.rst, "rst"):
                self.dut.rx_tlp_valid.value = 0
                self.dut.rx_tlp_sop.value = 0
                self.dut.rx_tlp_eop.value = 0
                self._rx_valid = 0
                beats, idx, tlp = [], 0, None
                beat_cycles = []
                continue

            ready = _i(self.dut.rx_tlp_ready, "rx_tlp_ready")

            if self._rx_valid and ready:
                # valid && ready held during the cycle just ended, so that is
                # the cycle the beat transferred on (spec 9.6 wording).
                self.last_beat_cycle = _cycle_now() - 1
                beat_cycles.append(self.last_beat_cycle)
                if beats[idx][2]:                       # eop
                    self.last_eop_cycle = self.last_beat_cycle
                idx += 1
                if idx >= len(beats):
                    self.last_packet_beat_cycles = beat_cycles
                    beat_cycles = []
                    # whole TLP transferred: release flow-control credit so a
                    # long test cannot starve the behavioral DLL (spec 4.4)
                    if tlp is not None:
                        tlp.release_fc()
                    self.rx_packets += 1
                    beats, idx, tlp = [], 0, None

            if self._rx_valid and not ready:
                continue                       # hold the beat stable (REQ-001)

            if not beats:
                if self.rx_queue.empty():
                    self._drive_rx_idle()
                    if not self.rx_idle.is_set():
                        self.rx_idle.set()
                    continue
                beats, tlp = self.rx_queue.get_nowait()
                idx = 0

            if self.rx_gap_prob and self.rng.random() < self.rx_gap_prob:
                self._drive_rx_idle()          # idle cycle mid-TLP (REQ-005)
                continue

            data, sop, eop = beats[idx]
            self.dut.rx_tlp_data.value = data
            self.dut.rx_tlp_sop.value = sop
            self.dut.rx_tlp_eop.value = eop
            self.dut.rx_tlp_valid.value = 1
            self._rx_valid = 1

    def _drive_rx_idle(self):
        self.dut.rx_tlp_valid.value = 0
        self.dut.rx_tlp_sop.value = 0
        self.dut.rx_tlp_eop.value = 0
        self._rx_valid = 0

    # ------------------------------------------------------------------
    # Outbound sink + protocol checker (REQ-001..007, REQ-023)
    # ------------------------------------------------------------------
    async def _run_tx(self):
        pkt = []
        held = None

        while True:
            await RisingEdge(self.clk)

            if _i(self.rst, "rst"):
                # REQ-006: these must be 0 for the whole time rst is asserted
                if self.checks_enabled:
                    for name in ("tx_tlp_valid", "tx_tlp_sop", "tx_tlp_eop"):
                        v = _i(getattr(self.dut, name), name)
                        if v != 0:
                            raise ProtocolError(
                                f"REQ-006: {name} = {v} while rst is asserted"
                            )
                    r = _i(self.dut.rx_tlp_ready, "rx_tlp_ready")
                    if r != 0:
                        raise ProtocolError(
                            f"REQ-006: rx_tlp_ready = {r} while rst is asserted"
                        )
                self.dut.tx_tlp_ready.value = 0
                pkt, held = [], None
                self.tx_in_packet = False
                continue

            valid = _i(self.dut.tx_tlp_valid, "tx_tlp_valid")
            ready = _i(self.dut.tx_tlp_ready, "tx_tlp_ready")

            if valid:
                data = _i(self.dut.tx_tlp_data, "tx_tlp_data")
                sop = _i(self.dut.tx_tlp_sop, "tx_tlp_sop")
                eop = _i(self.dut.tx_tlp_eop, "tx_tlp_eop")
                beat = (data, sop, eop)

                if self.checks_enabled:
                    if sop and eop:
                        raise ProtocolError(
                            "REQ-004: tx_tlp_sop and tx_tlp_eop asserted on "
                            "the same beat; the minimum TLP is 3 DWORDs"
                        )
                    if held is not None and held != beat:
                        raise ProtocolError(
                            "REQ-001: tx_tlp_data/sop/eop changed while "
                            f"tx_tlp_valid was held and tx_tlp_ready was low: "
                            f"{held!r} -> {beat!r}"
                        )
                    if sop and self.tx_in_packet:
                        raise ProtocolError(
                            "REQ-023: tx_tlp_sop asserted while a completion "
                            "was already in progress (packets must be "
                            "contiguous and non-interleaved)"
                        )
                    if not sop and not self.tx_in_packet:
                        raise ProtocolError(
                            "REQ-023: first beat of a completion did not "
                            "assert tx_tlp_sop"
                        )

                if ready:
                    held = None
                    pkt.append(data)
                    self.tx_in_packet = not eop
                    if eop:
                        self.tx_packets += 1
                        cocotb.start_soon(self._dispatch(pkt))
                        pkt = []
                else:
                    held = beat                 # must be stable next edge
            else:
                if self.checks_enabled and held is not None:
                    raise ProtocolError(
                        "REQ-001: tx_tlp_valid was retracted before the beat "
                        f"transferred (held beat {held!r})"
                    )
                held = None

            if self.tx_force_stall:
                self.dut.tx_tlp_ready.value = 0
            elif self.tx_stall_prob and self.rng.random() < self.tx_stall_prob:
                self.dut.tx_tlp_ready.value = 0
            else:
                self.dut.tx_tlp_ready.value = 1

    async def _dispatch(self, dws):
        tlp = self.dwords_to_tlp(list(dws))
        # Keep the raw DWORDs so tests can check reserved bits that
        # Tlp.unpack_header() discards (REQ-024: T9, T8, LN, TH, AT, BCM,
        # DW2 bit 7).
        tlp.raw_dwords = list(dws)
        self.tx_monitor.put_nowait(tlp)
        if self.capture is not None:
            self.capture.put_nowait(tlp)
            return
        await self.upstream_send(tlp)

    # ------------------------------------------------------------------
    # Raw capture helper for negative tests
    # ------------------------------------------------------------------
    def start_capture(self):
        self.capture = Queue()
        return self.capture

    def stop_capture(self):
        self.capture = None


def seed_from_env(default=1):
    """Every random choice in this testbench derives from SEED (printed)."""
    s = os.environ.get("SEED")
    if s is None:
        return default, True
    return int(s, 0), False
