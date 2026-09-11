#!/usr/bin/env python3
"""Build SDF-annotatable sky130_fd_sc_hd models for Icarus gate-level sim.

Why this is needed (measured, not assumed)
------------------------------------------
The upstream sky130 cell models come in two flavours:

  * `behavioral` (the default) drives its flop from `D_delayed`/`CLK_delayed`,
    nets that are only ever driven as the *delayed-signal outputs* of
    `$setuphold`. Icarus prints
        "Timing checks are not supported and delayed signal ... will not be
         driven"
    and leaves them undriven, so **every flop output is X forever**. Verified
    with a 20-line testcase before touching the real netlist.
  * `functional` (selected by `-DFUNCTIONAL`) wires D/CLK straight through and
    works under Icarus -- but ships no `specify` block, so `$sdf_annotate` has
    nothing to attach delays to and the run silently degrades to zero delay.

Neither flavour alone gives an SDF-annotated run on Icarus. This script builds
a third: the **functional** model body with a `specify` block containing only
the *module path* declarations from the cell's own `.specify.v`, with the
timing checks (`$setuphold`, `$width`, ...) filtered out because Icarus
implements none of them. That is exactly the subset `$sdf_annotate` needs to
back-annotate `IOPATH` delays.

The specify block is inserted into the **strength-qualified** wrapper modules
(`..._1`, `..._8`, ...) because that is what the netlist instantiates and what
the SDF's `(CELLTYPE ...)` names.

Source (read-only): flow/gl_models/   -- produced by flow/make_gl_models.sh
Output:             tb/gl/models_sdf/
Nothing under flow/ or rtl/ is modified.
"""
import re
import shutil
import sys
from pathlib import Path

PROJ = Path("/home/pgratz/pcie-matmul")
SRC = PROJ / "flow" / "gl_models"
OUT = PROJ / "tb" / "gl" / "models_sdf"

# Icarus implements no timing checks; these would be dropped anyway, and
# several reference nets (notifier, *_delayed) the functional model lacks.
TIMING_CHECKS = ("$setuphold", "$width", "$setup", "$hold", "$recrem",
                 "$recovery", "$removal", "$period", "$skew", "$nochange",
                 "$timeskew", "$fullskew")


def path_lines(specify_file: Path):
    """Module-path declarations from a .specify.v, timing checks removed."""
    if not specify_file.exists():
        return []
    body, inside = [], False
    for raw in specify_file.read_text().splitlines():
        line = raw.strip()
        if line == "specify":
            inside = True
            continue
        if line == "endspecify":
            inside = False
            continue
        if not inside or not line or line.startswith("//"):
            continue
        if any(tc in line for tc in TIMING_CHECKS):
            continue
        body.append(line)
    return body


def main():
    if not SRC.is_dir():
        sys.exit(f"missing {SRC}; run flow/make_gl_models.sh first")
    if OUT.exists():
        shutil.rmtree(OUT)
    shutil.copytree(SRC, OUT)

    patched = skipped = 0
    for cell_dir in sorted((OUT / "cells").iterdir()):
        if not cell_dir.is_dir():
            continue
        base = cell_dir.name
        paths = path_lines(cell_dir / f"sky130_fd_sc_hd__{base}.specify.v")
        if not paths:
            skipped += 1
            continue
        block = ("\n    specify\n"
                 + "".join(f"    {ln}\n" for ln in paths)
                 + "    endspecify\n")
        # Strength-qualified wrappers only: ..._1.v, ..._8.v -- not the
        # umbrella sky130_fd_sc_hd__<base>.v and not the .functional/.behavioral
        # fragments, which are `included into the wrappers.
        for f in sorted(cell_dir.glob(f"sky130_fd_sc_hd__{base}_*.v")):
            if re.search(r"\.(functional|behavioral|specify|blackbox|symbol|pp)\.",
                         f.name):
                continue
            text = f.read_text()
            if "specify" in text:
                continue
            new, n = re.subn(r"\nendmodule\n", "\n" + block + "endmodule\n",
                             text)
            if n:
                f.write_text(new)
                patched += 1
    print(f"patched {patched} strength-qualified wrapper file(s); "
          f"{skipped} base cell(s) had no module paths to annotate")
    print(f"output: {OUT}")


if __name__ == "__main__":
    main()
