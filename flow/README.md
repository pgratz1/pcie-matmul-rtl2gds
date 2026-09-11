# `flow/` — OpenROAD-flow-scripts physical implementation

Owner: circuit-designer. Implements Phase 4 of `CLAUDE.md`.

| Item | Value |
|------|-------|
| Design (top) | `matmul_top` (**not** `pcie_matmul_top`; `DESIGN_NICKNAME` is `pcie_matmul`) |
| Platform | `sky130hd` |
| Parameters | `N=8`, `DW=8`, `ACCW=32` (spec §14, DEC-004) |
| Target clock | 10.000 ns / 100 MHz (spec §13.2, DEC-009) |
| ORFS | `/home/pgratz/openroad/OpenROAD-flow-scripts` |
| Macros | none — A/B/C are flop register files (DEC-010) |

## Files

| File | What it is |
|------|-----------|
| `config.mk` | ORFS design config. Reads `rtl/filelist.f` so the flow can never drift from the simulated file set. |
| `constraint.sdc` | One `create_clock` + virtual I/O clock + input/output delays. **No timing exceptions** — see the comment block at the bottom of the file for why each category is absent. |

## Running it

```bash
export ORFS=/home/pgratz/openroad/OpenROAD-flow-scripts
export PROJ=/home/pgratz/pcie-matmul
source ${ORFS}/env.sh          # puts openroad + the ORFS yosys fork on PATH
cd ${ORFS}/flow

# whole flow, RTL -> GDS.  DO NOT pass -j: ORFS's 2_floorplan.sdc rule depends
# on 2_1_floorplan.sdc, which is a side product of the rule whose declared
# target is 2_1_floorplan.odb (Makefile:450,452,468).  Parallel make races and
# dies with "No rule to make target .../2_1_floorplan.sdc".  OpenROAD already
# multi-threads internally and uses the whole machine.
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ}

# a single stage (each depends on the previous, so this also builds what it needs)
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} synth
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} floorplan
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} place
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} cts
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} route
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} finish

# sign-off checks
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} drc          # KLayout sign-off DRC
make DESIGN_CONFIG=${PROJ}/flow/config.mk WORK_HOME=${PROJ} gui_final     # needs a display
```

`WORK_HOME=${PROJ}` is what redirects ORFS's outputs out of the ORFS tree and
into this repo. Omit it and everything lands under `${ORFS}/flow/` instead.
Magic is not installed, so the Magic DRC/LVS targets are unavailable; sky130hd's
sign-off deck in ORFS is KLayout (0.30.0, on the system PATH) anyway.

`magic` is **not installed** on this machine, so the Magic DRC/LVS targets are
unavailable; sky130hd's sign-off deck here is KLayout (0.30.0, on the system
PATH), which is what ORFS uses for this platform anyway.

## Where results land

All paths relative to `/home/pgratz/pcie-matmul`, with
`<P> = sky130hd/pcie_matmul/base`:

| Path | Contents |
|------|----------|
| `results/<P>/1_synth.v` | synthesized netlist |
| `results/<P>/6_final.v` | **final netlist — this is what gate-level sim uses** |
| `results/<P>/6_final.sdf` | SDF timing for the GL sim (see below) |
| `results/<P>/6_final.gds` | **the deliverable layout** |
| `results/<P>/6_final.def`, `.spef`, `.cdl` | DEF / parasitics / netlist for LVS |
| `reports/<P>/synth_stat.txt` | cell and flop counts, chip area |
| `reports/<P>/*_final_report.rpt`, `6_finish.rpt` | setup/hold WNS/TNS, area, power |
| `reports/<P>/5_route_drc.rpt` | detailed-router DRC violations |
| `reports/<P>/drc.lyrdb` | KLayout sign-off DRC database |
| `logs/<P>/*.log` | per-stage logs, numbered by stage |

Stage numbering: `1_*` synth, `2_*` floorplan, `3_*` place, `4_*` cts,
`5_*` route, `6_*` finish.

## Pre-flight: ALWAYS run this before a full flow on changed RTL

```bash
tb/gl/postsyn_replay.sh 8          # 72/72 in ~86 s, no PDK needed
```

BUG-007 was a Yosys `peepopt` mis-transformation that produced a functionally
wrong netlist from correct, lint-clean, 72/72-passing RTL. A full P&R run on
that netlist cost 110 minutes and was clean but worthless. `postsyn_replay.sh`
simulates the synthesized netlist and catches that entire class in ~1/75th of
the time. Do not start `make` on changed RTL without it.

## Runtimes on this machine (24C/32T, serial make)

| Stage | Elapsed |
|-------|---------|
| `1_2_yosys` synthesis | 122 s |
| `2_*` floorplan + tapcell + PDN | 5 s |
| `3_*` place | 134 s |
| `4_1_cts` | 34 s |
| `5_1_grt` global route | 338 s |
| `5_2_route` detailed route + antenna repair | **5,837 s (97 min)** |
| `6_*` fill, merge, report | 54 s |
| **Total `make`** | **6,526 s (1 h 49 min)** |
| `make drc` (KLayout sign-off) | 535 s |

Peak memory 8.1 GB, during detailed routing. Budget ~2 hours for a full
re-spin; detailed routing dominates and is the reason not to re-run casually.

## SDF

ORFS writes no SDF at any stage. `results/<P>/6_final.sdf` was generated
separately:

```bash
openroad -exit <<'EOF'
set R /home/pgratz/pcie-matmul/results/sky130hd/pcie_matmul/base
read_liberty ${ORFS}/flow/platforms/sky130hd/lib/sky130_fd_sc_hd__tt_025C_1v80.lib
read_db   $R/6_final.odb
read_sdc  $R/6_final.sdc
read_spef $R/6_final.spef
write_sdf -divider / $R/6_final.sdf
EOF
```

Re-run it after any re-spin, or the SDF will describe the previous layout.

## Gate-level simulation input — read this before Phase 4 sign-off

**sky130hd in ORFS ships no standard-cell Verilog models.**
`${ORFS}/flow/platforms/sky130hd/` contains only `cells_adders_hd.v`,
`cells_clkgate_hd.v` and `cells_latch_hd.v`, which are Yosys *mapping* files,
not simulation models. No sky130 PDK is installed anywhere on this machine
(searched; `volare` is absent, `magic` is absent).

`6_final.v` therefore cannot be simulated as-is. The models must be fetched
from `github.com/google/skywater-pdk-libs-sky130_fd_sc_hd` (default branch
`main`). `make_gl_models.sh` in this directory collects exactly the cells the
final netlist instantiates, into `flow/gl_models/`.

Three things that recipe has to get right:

* Upstream cell files `include their siblings by **repo-relative** path
  (`../../models/udp_dff_p/...`), so the upstream layout is mirrored, not
  flattened.
* Icarus resolves `` `include `` relative to the **cwd**, not the including
  file, so every `cells/*/` and `models/*/` needs its own `-I`.
* The netlist instantiates **strength-qualified** cells (`..__fa_1`), which are
  separate upstream files; the base `..__fa` alone leaves instances unresolved.

Verified: this compiles clean under Icarus 12.0.

```bash
cd flow/gl_models
INC=$(for d in cells/*/ models/*/; do printf -- "-I%s " "$d"; done)
iverilog -g2012 -DFUNCTIONAL -DUNIT_DELAY="" $INC \
    -o gl.vvp -s matmul_top \
    sky130_fd_sc_hd.v \
    ../../results/sky130hd/pcie_matmul/base/6_final.v <testbench files>
```

For SDF back-annotation drop `-DFUNCTIONAL` (the `specify` blocks live in the
non-functional variant) and `$sdf_annotate` with `6_final.sdf`.
