# ---------------------------------------------------------------------------
# flow/constraint.sdc - timing constraints for matmul_top (spec v1.1.4 s13)
#
# Everything in this file is justified inline. Nothing is here that cannot be
# traced to the spec or to a recorded decision.
# ---------------------------------------------------------------------------

current_design matmul_top

# --- Clock ------------------------------------------------------------------
# spec 13.2: target 100 MHz = 10.000 ns, sky130hd, typical corner (DEC-009).
# spec 13.1 / REQ-107: exactly ONE clock input, no generated or gated clock,
# so this is the only create_clock on a real port in the design.
set clk_name      core_clock
set clk_port_name clk
set clk_period    10.000
set clk_io_pct    0.40

set clk_port [get_ports $clk_port_name]
create_clock -name $clk_name -period $clk_period $clk_port

# Virtual clock for the chip-boundary I/O, so that I/O timing is not perturbed
# by the insertion delay of the real (post-CTS, propagated) clock tree. Same
# idiom as every sky130hd example design in ORFS.
set clk_io_name vclk_$clk_name
create_clock -name $clk_io_name -period $clk_period

# Pre-CTS estimate of clock-tree insertion delay. Applied identically to the
# real and the virtual clock so it cancels on both reg-to-reg and I/O paths;
# it exists so that pre-CTS and post-CTS STA see the same arrival reference.
# Value taken from ORFS sky130hd/ibex, which is the same platform at the same
# 10.0 ns period with a comparable (~2k+) sink count.
set_clock_latency 1.095 [get_clocks $clk_name]
set_clock_latency 1.095 [get_clocks $clk_io_name]

# --- I/O delays -------------------------------------------------------------
# Budget 40% of the period outside the chip on each side. The boundary is the
# raw-TLP 32-bit valid/ready DWORD stream (DEC-003, spec 5): rx_tlp_{data,sop,
# eop,valid}, tx_tlp_ready and rst on the way in; tx_tlp_{data,sop,eop,valid},
# rx_tlp_ready and irq on the way out. The spec fixes no external budget, so
# this is the circuit designer's assumption, recorded here and in
# docs/phase-reports/phase4-physical.md. It is deliberately pessimistic: it
# leaves 6.0 ns for the pin-to-flop TLP classifier path (tlp_rx.sv:200-222) and
# for the flop-to-pin handshake outputs.
set non_clock_inputs [all_inputs -no_clocks]
set_input_delay  [expr $clk_period * $clk_io_pct] -clock $clk_io_name $non_clock_inputs
set_output_delay [expr $clk_period * $clk_io_pct] -clock $clk_io_name [all_outputs]

# --- Exceptions -------------------------------------------------------------
# NONE, and that is a positive statement, not an omission:
#
#  * No false paths across clock-domain boundaries, because there are no clock
#    domain boundaries. spec 13.1 REQ-107/REQ-108 and two independent passes of
#    the Phase 2b RTL review confirm a single clock `clk` and zero CDC.
#  * No multicycle paths. Every documented latency in rtl/README.md is a whole
#    number of single-cycle hops; in particular REQ-122 fixes D_WR = 1, so the
#    BAR0 write path must close in one cycle and may not be relaxed here.
#  * No case analysis / disabled arcs. There is no test or bypass mux to
#    constrain away.
#
# In other words, if a path fails setup in this design it is a real failure,
# not something an exception is permitted to hide.
