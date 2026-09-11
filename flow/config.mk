# ---------------------------------------------------------------------------
# flow/config.mk - OpenROAD-flow-scripts configuration for matmul_top
#
# Phase 4 physical design. Derived from
#   ${ORFS}/flow/designs/sky130hd/gcd/config.mk   (structure)
#   ${ORFS}/flow/designs/sky130hd/aes/config.mk   (congestion-oriented knobs)
#
# Run from ${ORFS}/flow with:
#   make DESIGN_CONFIG=/home/pgratz/pcie-matmul/flow/config.mk \
#        WORK_HOME=/home/pgratz/pcie-matmul
# so that results/, logs/, reports/ and objects/ land in the project tree.
# ---------------------------------------------------------------------------

export DESIGN_NICKNAME = pcie_matmul
export DESIGN_NAME     = matmul_top
export PLATFORM        = sky130hd

PROJ_HOME = /home/pgratz/pcie-matmul

# RTL: rtl/filelist.f is the single source of truth for file set + compile order
# (rtl/README.md). Read it here so the flow can never drift from simulation.
export VERILOG_FILES = $(addprefix $(PROJ_HOME)/,$(shell cat $(PROJ_HOME)/rtl/filelist.f))

export SDC_FILE      = $(PROJ_HOME)/flow/constraint.sdc

# ---------------------------------------------------------------------------
# Parameters (spec 14). N=8 for the v1 full-flow pass per DEC-004/DEC-009.
# Nothing in rtl/ hardcodes 8; N is overridden at elaboration, not by a source
# edit (REQ-113). IDXW is derived - do NOT override it.
# ---------------------------------------------------------------------------
export SYNTH_PARAMETERS = N=8 DW=8 ACCW=32

# ---------------------------------------------------------------------------
# Floorplan
#
# This design is flip-flop dominated: A, B and C are flop register files, not
# SRAM macros (DEC-010). ~6,600 flops and a 64:1 32-bit read mux in mem_c mean
# the binding constraint is ROUTING CONGESTION, not standard-cell area. Hence a
# deliberately low utilisation, as sky130hd/aes (35%) does for the same reason.
# No macros anywhere, so no macro placement file is needed.
# ---------------------------------------------------------------------------
export CORE_UTILIZATION   = 35
export CORE_ASPECT_RATIO  = 1
export CORE_MARGIN        = 2

# ---------------------------------------------------------------------------
# Place
# ---------------------------------------------------------------------------
export PLACE_DENSITY_LB_ADDON = 0.20

# ---------------------------------------------------------------------------
# Synthesis / ABC
#
# ABC_CLOCK_PERIOD_IN_PS is derived from constraint.sdc by ORFS itself
# (flow/scripts/synth.tcl reads the SDC), so it is intentionally not forced
# here; forcing it would let the SDC and ABC disagree.
#
# ABC_AREA=0 (the default) keeps ABC in delay mode. The PE MAC is the expected
# critical path (spec 13.2) and DEC-009 forbids adding a pipeline stage, so
# every picosecond of pre-place optimisation matters more than area here.
# ---------------------------------------------------------------------------
export ABC_AREA = 0

# Let TNS optimisation work on the whole endpoint population, not just the
# worst 10%: this design has thousands of near-identical PE paths.
export TNS_END_PERCENT = 100

export REMOVE_ABC_BUFFERS = 1

# Let Yosys substitute parallel-prefix (Han-Carlson) adders for the ripple
# adders it would otherwise infer. This directly targets the predicted critical
# path: mm_pe's 32-bit accumulate (spec 13.2). Measured effect on the N=8
# netlist: 64 ALU_16 + 64 ALU_32 Han-Carlson submodules, one pair per PE.
# ORFS requires OPENROAD_HIERARCHICAL alongside it (synth_odb.tcl enforces
# this); all three sky130hd reference designs - gcd, aes, ibex - set both.
export SWAP_ARITH_OPERATORS = 1
export OPENROAD_HIERARCHICAL = 1

# ---------------------------------------------------------------------------
# CTS - ~6,600 sinks on one clock. Smaller clusters give better skew at the
# cost of more buffers; same settings sky130hd/ibex and /aes use.
# ---------------------------------------------------------------------------
export CTS_CLUSTER_SIZE     = 20
export CTS_CLUSTER_DIAMETER = 50
