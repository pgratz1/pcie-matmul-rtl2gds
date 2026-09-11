"""
Long randomized sequence with a scoreboard.

A `DeviceModel` (tb/models/golden.py) shadows every host-visible piece of
state: the register block, A, B and C.  After each randomly chosen host action
the test compares a randomly chosen readback against the model, never against
an earlier DUT read.

Requirements exercised: REQ-001..REQ-007 (the shim's always-on protocol
checker), REQ-013, REQ-040, REQ-055, REQ-058..REQ-061, REQ-065..REQ-084,
REQ-090, REQ-105, REQ-116, REQ-117.
"""

import os
import random

import cocotb

from tb_common import (G, assert_matrix_equal, discover_n, make_tb, mrd_dword,
                       mwr_dword, read_c, wait_done, wait_for)

# Sequence length; override with STRESS_OPS=<n> for a longer soak.
STRESS_OPS = int(os.environ.get("STRESS_OPS", "120"))


@cocotb.test(timeout_time=8000, timeout_unit="us")
async def test_stress_random_sequence(dut):
    """A randomized host workload checked against the golden device model."""
    tb = await make_tb(dut, rx_gap_prob=0.15, tx_stall_prob=0.15)
    n = await discover_n(tb)
    rng = random.Random(tb.seed ^ 0x57235)
    model = G.DeviceModel(n)

    dut._log.info("stress: %d operations, SEED=%d, N=%d",
                  STRESS_OPS, tb.seed, n)

    reg_offsets = [G.REG_ID, G.REG_VERSION, G.REG_CONFIG, G.REG_CTRL,
                   G.REG_STATUS, G.REG_IRQ_ENABLE, G.REG_IRQ_STATUS,
                   G.REG_PERF_CYCLES, G.REG_SCRATCH, G.REG_OP_COUNT,
                   0x0028, 0x0FFC]

    actions = (["reg_write"] * 3 + ["reg_read"] * 4 + ["ab_write"] * 3
               + ["ab_read"] * 2 + ["c_read"] * 2 + ["start"] * 3
               + ["clear_status"] * 2 + ["ur"] * 1 + ["irq_check"] * 2)

    for step in range(STRESS_OPS):
        action = rng.choice(actions)

        if action == "reg_write":
            offset = rng.choice([G.REG_SCRATCH, G.REG_IRQ_ENABLE,
                                 G.REG_ID, G.REG_PERF_CYCLES, 0x0028])
            value = rng.getrandbits(32)
            be = rng.choice([0xF, 0xF, 0x1, 0x2, 0x4, 0x8, 0x3, 0xC, 0x0])
            await mwr_dword(tb, offset, value, be=be, quiet_cycles=2)
            model.write_dword(offset, value, be)

        elif action == "reg_read":
            offset = rng.choice(reg_offsets)
            got = await tb.read_dword(offset)
            exp = model.read_dword(offset)
            assert got == exp, _msg(step, action,
                                    f"BAR0+0x{offset:04x} reads 0x{got:08x}, "
                                    f"model says 0x{exp:08x}")

        elif action == "ab_write":
            base = rng.choice([G.MEM_A_BASE, G.MEM_B_BASE])
            word = rng.randrange(0, n * n // 4 + 2)     # sometimes past N*N
            value = rng.getrandbits(32)
            be = rng.choice([0xF, 0x1, 0x2, 0x4, 0x8, 0x5, 0xA])
            await mwr_dword(tb, base + 4 * word, value, be=be, quiet_cycles=2)
            model.write_dword(base + 4 * word, value, be)

        elif action == "ab_read":
            base = rng.choice([G.MEM_A_BASE, G.MEM_B_BASE])
            word = rng.randrange(0, n * n // 4 + 2)
            got = await mrd_dword(tb, base + 4 * word)
            exp = model.read_dword(base + 4 * word)
            assert got == exp, _msg(
                step, action,
                f"BAR0+0x{base + 4 * word:04x} reads 0x{got:08x}, model says "
                f"0x{exp:08x}")

        elif action == "c_read":
            got = await read_c(tb, n)
            exp = G.bytes_to_c(model.c, n)
            assert_matrix_equal(got, exp, f"[step {step}] C region")

        elif action == "start":
            await mwr_dword(tb, G.REG_CTRL, G.CTRL_START, quiet_cycles=2)
            await wait_done(tb)
            model.run_matmul()

        elif action == "clear_status":
            bits = rng.getrandbits(5)
            be = rng.choice([0xF, 0x1, 0xE])
            await mwr_dword(tb, G.REG_STATUS, bits, be=be, quiet_cycles=2)
            model.write_dword(G.REG_STATUS, bits, be)

        elif action == "ur":
            # An MRd that misses BAR0: UR completion + ERR_UNSUP_REQ (REQ-038)
            req = tb.make_mem_read(tb.bar0_addr + G.BAR0_SIZE + 0x40, length=1)
            cpl = await tb.raw_request(req)
            assert cpl.status == 1, _msg(
                step, action,
                f"an MRd outside BAR0 returned status {cpl.status!r}, "
                "expected UR (REQ-038)")
            model.regs.set_error(G.ST_ERR_UNSUP_REQ)

        elif action == "irq_check":
            got = await tb.read_dword(G.REG_IRQ_STATUS)
            exp = model.regs.read(G.REG_IRQ_STATUS)
            assert got == exp, _msg(
                step, action,
                f"IRQ_STATUS reads 0x{got:08x}, model says 0x{exp:08x} "
                "(STATUS & IRQ_ENABLE, REQ-079)")
            await wait_for(dut.irq, model.regs.irq, "irq", 8, dut.clk)

    # Final full comparison of every host-visible location.
    for offset in reg_offsets:
        got = await tb.read_dword(offset)
        exp = model.read_dword(offset)
        assert got == exp, _msg("final", "reg_read",
                                f"BAR0+0x{offset:04x} reads 0x{got:08x}, "
                                f"model says 0x{exp:08x}")

    got_a = await tb.mem_read(G.MEM_A_BASE, n * n)
    assert bytes(got_a) == bytes(model.a), (
        "final: A region does not match the scoreboard")
    got_b = await tb.mem_read(G.MEM_B_BASE, n * n)
    assert bytes(got_b) == bytes(model.b), (
        "final: B region does not match the scoreboard")
    got_c = await read_c(tb, n)
    assert_matrix_equal(got_c, G.bytes_to_c(model.c, n), "final C region")

    dut._log.info("stress: %d operations completed, %d TLPs in, %d out",
                  STRESS_OPS, tb.shim.rx_packets, tb.shim.tx_packets)


def _msg(step, action, detail):
    return (f"[stress step {step}, action '{action}', SEED reproducible with "
            f"SEED=$SEED] {detail}")
