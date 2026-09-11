#!/usr/bin/env bash
# Replay the cocotb RTL suite against a YOSYS-SYNTHESIZED netlist.
#
# Why: BUG-007 was a Yosys `peepopt` mis-transformation. It simulated correctly
# at RTL, passed `verilator --lint-only -Wall`, passed `yosys check` with 0
# problems, and passed all 72 RTL tests -- and still produced a netlist that
# computed a whole row of C as zero. The only thing that catches that class is
# simulating the *post-synthesis* netlist.
#
# This needs no PDK: `synth -flatten` leaves Yosys's own `$_AND_`/`$_DFF_P_`
# internal cells, and Yosys ships simcells.v which defines them, so Icarus can
# run the netlist directly. Minutes, not the two hours a full ORFS flow costs.
#
#   tb/gl/postsyn_replay.sh <N> [<rtl-dir>] [<test-modules>]
set -euo pipefail
PROJ=/home/pgratz/pcie-matmul
YOSYS=/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys
SIMCELLS=$(dirname "$YOSYS")/../share/yosys/simcells.v

N=${1:-8}
RTLDIR=${2:-$PROJ/rtl}
MODULES=${3:-test_smoke,test_regs,test_tlp,test_cfg,test_matmul,test_stress}
WORK=${WORK:-$PROJ/tb/gl/postsyn/$(basename "$RTLDIR")-n$N}
mkdir -p "$WORK"

SRC=$(sed -e 's:#.*::' -e '/^[[:space:]]*$/d' "$PROJ/rtl/filelist.f" \
      | sed -e "s:^rtl/:$RTLDIR/:" | tr '\n' ' ')

echo "[postsyn] synthesizing $RTLDIR at N=$N"
"$YOSYS" -p "read_verilog -sv $SRC; chparam -set N $N matmul_top; \
             hierarchy -top matmul_top; synth -flatten; \
             write_verilog -noattr $WORK/syn.v" > "$WORK/synth.log" 2>&1

echo "[postsyn] running $MODULES against the synthesized netlist"
cd "$PROJ/tb"
exec make -f "$PROJ/tb/Makefile" test \
     N="$N" SEED="${SEED:-1}" \
     COCOTB_TEST_MODULES="$MODULES" TEST=__postsyn__ \
     VERILOG_SOURCES="$PROJ/tb/gl/postsyn_timescale.v $WORK/syn.v $SIMCELLS" \
     COMPILE_ARGS= \
     SIM_BUILD="$WORK/build-n$N"
