#!/usr/bin/env bash
# Compile the post-route netlist for gate-level simulation under Icarus.
#
#   tb/gl/build_gl.sh sdf   -> SDF back-annotated  (zero internal gate delay,
#                              module-path delays supplied by 6_final.sdf)
#   tb/gl/build_gl.sh unit  -> unit-delay cell models, no back-annotation
#
# Include path note: iverilog resolves `include against -I and the CWD, NOT
# against the including file's directory.  The upstream cell files include
# their siblings by bare name and the UDP primitives by ../../models/..., so
# every cells/<name>/ directory has to be on -I; that makes both forms resolve.
set -euo pipefail
PROJ=/home/pgratz/pcie-matmul
MODE=${1:-sdf}
MODELS=$PROJ/tb/gl/models_sdf
NETLIST=${NETLIST:-$PROJ/results/sky130hd/pcie_matmul/base/6_final.v}
SDF=${SDF:-$PROJ/results/sky130hd/pcie_matmul/base/6_final.sdf}
OUT=${OUT:-$PROJ/tb/gl/build/gl_${MODE}.vvp}

[ -d "$MODELS" ] || { echo "run tb/gl/build_sdf_models.py first" >&2; exit 1; }
mkdir -p "$(dirname "$OUT")"

INC=(-I "$MODELS")
for d in "$MODELS"/cells/*/; do INC+=(-I "$d"); done
for d in "$MODELS"/models/*/; do INC+=(-I "$d"); done

DEFS=(-DFUNCTIONAL)
case "$MODE" in
  sdf)  DEFS+=(-DUNIT_DELAY=) ;;
  unit) DEFS+=(-DUNIT_DELAY="#1") ;;
  *) echo "usage: $0 [sdf|unit]" >&2; exit 1 ;;
esac

echo "iverilog -> $OUT  (mode=$MODE, ${#INC[@]} include args)"
exec iverilog -g2012 -gspecify -o "$OUT" -s gl_top "${DEFS[@]}" "${INC[@]}" \
     "$PROJ/tb/gl/gl_top.v" "$MODELS/sky130_fd_sc_hd.v" "$NETLIST"
