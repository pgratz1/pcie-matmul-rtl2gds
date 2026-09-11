#!/usr/bin/env python3
"""
Static structural checks on rtl/, run from `make -C tb lint`.

These cover requirements that are structural rather than behavioural and so
cannot be observed from a simulation at the chip boundary:

  REQ-010  matmul_top has exactly the spec 6.1 port list and no other port
  REQ-011  matmul_top contains only instantiation and wiring
  REQ-106  no overflow / saturation / clamp status bit exists anywhere
  REQ-107  exactly one clock input, no generated or gated clock
  REQ-110  no `initial`, no `#` delay and no `$display` in rtl/

The script reads rtl/ for *structure only*; it never infers expected behaviour
from it.  If rtl/ does not exist yet it reports SKIP and exits 0, so the
harness is usable before the RTL lands.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RTL = ROOT / "rtl"

# docs/spec.md 6.1, binding.
EXPECTED_PORTS = [
    ("input", "clk", 1),
    ("input", "rst", 1),
    ("input", "rx_tlp_data", 32),
    ("input", "rx_tlp_sop", 1),
    ("input", "rx_tlp_eop", 1),
    ("input", "rx_tlp_valid", 1),
    ("output", "rx_tlp_ready", 1),
    ("output", "tx_tlp_data", 32),
    ("output", "tx_tlp_sop", 1),
    ("output", "tx_tlp_eop", 1),
    ("output", "tx_tlp_valid", 1),
    ("input", "tx_tlp_ready", 1),
    ("output", "irq", 1),
]

failures = []
notes = []


def fail(req, msg):
    failures.append(f"{req}: {msg}")


def strip_comments(text):
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def sv_files():
    return sorted(RTL.rglob("*.sv")) + sorted(RTL.rglob("*.v"))


def check_forbidden_constructs():
    """REQ-110 (and REQ-107's 'no gated clock' half)."""
    patterns = [
        (r"\binitial\b", "an `initial` block", "REQ-110"),
        (r"#\s*\d", "a `#` delay", "REQ-110"),
        (r"#\s*\(", "a `#` delay", "REQ-110"),
        (r"\$display\b", "a $display", "REQ-110"),
        (r"\$monitor\b", "a $monitor", "REQ-110"),
        (r"\$dumpvars\b", "a $dumpvars", "REQ-110"),
    ]
    for path in sv_files():
        src = strip_comments(path.read_text())
        # `#(` in a module instantiation / declaration is a parameter list,
        # not a delay -- strip those first.
        src_noparam = re.sub(r"\b[A-Za-z_]\w*\s*#\s*\(", " ", src)
        for pat, what, req in patterns:
            target = src_noparam if "#" in pat else src
            if re.search(pat, target):
                fail(req, f"{path.relative_to(ROOT)} contains {what}; "
                          "spec 13.3 forbids it in rtl/")


def check_clocking():
    """REQ-107: one clock input, no internally generated or gated clock."""
    for path in sv_files():
        src = strip_comments(path.read_text())
        for m in re.finditer(r"@\s*\(([^)]*)\)", src):
            sens = m.group(1)
            edges = re.findall(r"(?:posedge|negedge)\s+([A-Za-z_]\w*)", sens)
            for sig in edges:
                if sig not in ("clk", "rst"):
                    fail("REQ-107/REQ-108",
                         f"{path.relative_to(ROOT)} has an edge-sensitive "
                         f"block on '{sig}'; the design has exactly one clock "
                         "`clk` and a synchronous active-high `rst`")
                if sig == "rst":
                    fail("REQ-108",
                         f"{path.relative_to(ROOT)} uses an edge of `rst`; "
                         "reset is SYNCHRONOUS (spec 13.3) so it must not "
                         "appear in a sensitivity list")


def check_no_overflow_bit():
    """REQ-106: no overflow / saturation / clamp status bit anywhere."""
    for path in sv_files():
        src = strip_comments(path.read_text()).lower()
        for word in ("saturat", "overflow", "clamp"):
            if word in src:
                fail("REQ-106",
                     f"{path.relative_to(ROOT)} mentions '{word}'; spec 12.6 "
                     "forbids any overflow/saturation/clamping status bit")


def extract_module(src, name):
    m = re.search(r"\bmodule\s+" + name + r"\b", src)
    if not m:
        return None
    end = re.search(r"\bendmodule\b", src[m.start():])
    return src[m.start():m.start() + (end.end() if end else len(src))]


def check_top_ports(top_src, path):
    """REQ-010: exactly the spec 6.1 ports, no others."""
    header = top_src.split(");", 1)[0]
    found = []
    for m in re.finditer(
            r"\b(input|output|inout)\b\s+(?:wire|logic|reg)?\s*"
            r"(?:(signed|unsigned)\s+)?(\[[^\]]*\]\s*)?([A-Za-z_]\w*)",
            header):
        direction, _sign, rng, name = m.groups()
        width = 1
        if rng:
            hi = rng.strip()[1:-1].split(":")[0].strip()
            try:
                width = int(hi) + 1
            except ValueError:
                width = None            # parameterised width
        found.append((direction, name, width))

    exp_names = [p[1] for p in EXPECTED_PORTS]
    got_names = [p[1] for p in found]

    for name in exp_names:
        if name not in got_names:
            fail("REQ-010", f"matmul_top is missing port '{name}' "
                            f"({path.name})")
    for direction, name, width in found:
        if name not in exp_names:
            fail("REQ-010", f"matmul_top has an extra top-level port "
                            f"'{name}'; spec 6.1 lists exactly "
                            f"{len(exp_names)} ports and no others")
            continue
        exp_dir, _, exp_w = next(p for p in EXPECTED_PORTS if p[1] == name)
        if direction != exp_dir:
            fail("REQ-010", f"port '{name}' is declared `{direction}`, "
                            f"spec 6.1 says `{exp_dir}`")
        if width is not None and exp_w != width:
            fail("REQ-010", f"port '{name}' is {width} bits, spec 6.1 says "
                            f"{exp_w}")

    clk_inputs = [n for d, n, _ in found if d == "input" and "clk" in n]
    if clk_inputs != ["clk"]:
        fail("REQ-107", f"matmul_top's clock inputs are {clk_inputs}; there "
                        "must be exactly one, named `clk`")


def check_top_structural(top_src, path):
    """REQ-011: matmul_top only instantiates and wires."""
    body = top_src.split(");", 1)[1] if ");" in top_src else top_src
    for kw, what in (("always", "an `always` block"),
                     ("always_ff", "an `always_ff` block"),
                     ("always_comb", "an `always_comb` block"),
                     ("function", "a function"),
                     ("case", "a case statement")):
        if re.search(r"\b" + kw + r"\b", body):
            fail("REQ-011",
                 f"{path.name}: matmul_top contains {what}; spec 6.1 says it "
                 "shall contain nothing but instantiation and wiring of "
                 "pcie_tl, app_bar0 and matmul_engine")

    # A continuous `assign` is only wiring if its right-hand side is a plain
    # signal (or a slice / concatenation of them).  Anything with an operator
    # in it is logic, which REQ-011 forbids at the top level.
    for m in re.finditer(r"\bassign\b([^;]*);", body):
        stmt = m.group(1)
        rhs = stmt.split("=", 1)[1] if "=" in stmt else stmt
        if re.search(r"[&|^~+\-*/?<>!%]|==", rhs):
            fail("REQ-011",
                 f"{path.name}: matmul_top contains a continuous assign with "
                 f"logic in it (`assign{stmt};`); spec 6.1 allows only "
                 "instantiation and wiring")


def main():
    if not RTL.is_dir():
        print(f"SKIP: {RTL} does not exist yet; no RTL to check.")
        return 0
    files = sv_files()
    if not files:
        print(f"SKIP: no .sv/.v files under {RTL} yet.")
        return 0

    check_forbidden_constructs()
    check_clocking()
    check_no_overflow_bit()

    top_path = None
    top_src = None
    for path in files:
        src = strip_comments(path.read_text())
        mod = extract_module(src, "matmul_top")
        if mod:
            top_path, top_src = path, mod
            break
    if top_src is None:
        fail("REQ-010", "no module `matmul_top` found anywhere in rtl/")
    else:
        check_top_ports(top_src, top_path)
        check_top_structural(top_src, top_path)

    print(f"checked {len(files)} file(s) under {RTL}")
    for note in notes:
        print(f"  note: {note}")
    if failures:
        print("\nSTRUCTURAL CHECK FAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("structural checks passed (REQ-010, REQ-011, REQ-106, REQ-107, "
          "REQ-110)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
