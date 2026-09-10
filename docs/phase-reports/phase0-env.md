# Phase 0 — Environment Check

Date: 2026-09-10
Owner: validation-specialist
Host OS: Ubuntu 26.04.1 LTS, kernel 7.0.0-31-generic

**Gate status: MET.** (Updated 2026-09-10 after the orchestrator installed the
cocotb venv.) A cocotb test runs end-to-end against the hello-world module and
reports `TESTS=1 PASS=1 FAIL=0`, reproducibly across three seeds.

Two findings from that run change project defaults and are binding on other agents:

1. **The simulator is Icarus, not Verilator.** cocotb 2.1.0 hard-refuses Verilator
   older than 5.036; this box has 5.032 and apt offers nothing newer. Verilator is
   still used for `--lint-only` (the Phase 2 gate). See section 5.
2. **cocotbext-pcie cannot attach at PIPE.** The package contains no PIPE interface
   at all. The endpoint boundary must be a TLP-level AXI-Stream interface. See
   section 9. This makes `CLAUDE.md`'s stated fallback mandatory rather than optional.

---

## 1. Tool inventory

| Tool | Version | Full path | Reachable how |
|------|---------|-----------|---------------|
| `verilator` | 5.032 2025-01-01 (Debian 5.032-1) | `/usr/bin/verilator` | system `PATH` |
| `iverilog` | 12.0 (stable) | `/usr/bin/iverilog` | system `PATH` |
| `yosys` | 0.68+ (git a5af9d690, OpenROAD-Project fork) | `/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/yosys/bin/yosys` | **only after `source ${ORFS}/env.sh`** |
| `openroad` | 26Q3-1985-gc3e680b01b | `/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/openroad` | **only after `source ${ORFS}/env.sh`** |
| `sta` (OpenSTA) | bundled with OpenROAD build | `/home/pgratz/openroad/OpenROAD-flow-scripts/tools/install/OpenROAD/bin/sta` | after `env.sh` |
| `klayout` | 0.30.0 | `/usr/bin/klayout` | system `PATH` |
| `magic` | — | — | **NOT INSTALLED** (not required; ORFS uses KLayout for DRC/LVS on sky130hd and nangate45) |
| `python3` | 3.14.4 | `/usr/bin/python3` | system `PATH`. **Only interpreter on the box** — no 3.11/3.12/3.13, and apt has no candidate for them. |
| `pip3` | present | `/usr/bin/pip3` | system `PATH`; `/usr/lib/python3.14/EXTERNALLY-MANAGED` is present (PEP 668) so system-wide `pip install` is refused — **a venv is mandatory** |
| `cocotb` | **2.1.0** | `/home/pgratz/pcie-matmul/.venv/bin/cocotb-config` | project venv only |
| `cocotbext-pcie` | **0.2.16** | venv `site-packages/cocotbext/pcie` | project venv only |
| `cocotbext-axi` | **0.1.28** | venv | project venv only |
| `cocotb-bus` / `scapy` | **0.3.0** / 2.7.0 | venv | pulled in by cocotbext-pcie; imports cleanly under cocotb 2.x |
| `pytest` / `find-libpython` | 9.1.1 / 0.5.1 | venv | cocotb runtime deps |
| `make` / `gcc` / `g++` | GNU make, GCC 15.2.0 | `/usr/bin/…` | system `PATH` |
| `python3-venv` | 3.14.3-0ubuntu2 | installed | `python3 -m venv` + `ensurepip` confirmed importable |

Networking to `pypi.org` is up (HTTP 200), so a pip install would succeed once approved.

### How each consumer should reach its tools

- **circuit-designer / flow scripts**: must `source /home/pgratz/openroad/OpenROAD-flow-scripts/env.sh`
  in every shell. Neither `openroad` nor `yosys` is on the default `PATH`.
- **test-writer / tb Makefile**: Verilator, Icarus and Python are on the system `PATH`
  and need *no* ORFS env. But the Phase-3 Yosys synth check *does* need `env.sh`,
  so `tb/Makefile` should source it (or use the absolute yosys path) for that target only.
  Do not blanket-source `env.sh` in the tb flow: it prepends an OpenROAD Python/lib
  environment that can shadow the cocotb venv.

---

## 2. OpenROAD-flow-scripts

```
ORFS root : /home/pgratz/openroad/OpenROAD-flow-scripts
env       : source /home/pgratz/openroad/OpenROAD-flow-scripts/env.sh
flow dir  : /home/pgratz/openroad/OpenROAD-flow-scripts/flow
Makefile  : /home/pgratz/openroad/OpenROAD-flow-scripts/flow/Makefile   (34.9 kB, present)
platforms : /home/pgratz/openroad/OpenROAD-flow-scripts/flow/platforms/
designs   : /home/pgratz/openroad/OpenROAD-flow-scripts/flow/designs/
```

Platforms present: `asap7  common  gf180  gt2n  ihp-sg13g2  nangate45  sky130hd
sky130hs  sky130io  sky130ram`.

Typical invocation for this project (circuit-designer):

```bash
source /home/pgratz/openroad/OpenROAD-flow-scripts/env.sh
cd /home/pgratz/openroad/OpenROAD-flow-scripts/flow
make DESIGN_CONFIG=/home/pgratz/pcie-matmul/flow/config.mk
```

`flow/designs/sky130hd/` already contains reference designs (`aes`, `gcd`, `ibex`,
`jpeg`, `microwatt`, `riscv32i`, …) that can be used as config.mk templates and as a
sanity run before the matmul design is ready.

### 2.1 Platform completeness

**sky130hd — complete, flow-ready** (20 MB):
- `lef/sky130_fd_sc_hd.tlef` (tech LEF), `lef/sky130_fd_sc_hd_merged.lef` (std cells)
- `lib/sky130_fd_sc_hd__tt_025C_1v80.lib`
- `gds/` present, `cdl/`, `lvs/`, `drc/sky130hd.lydrc`, `sky130hd.lyt`/`.lyp`
- `pdn.tcl`, `tapcell.tcl`, `make_tracks.tcl`, `fastroute.tcl`, `setRC.tcl`, `fill.json`
- `PLACE_SITE = unithd`

**nangate45 — complete, flow-ready** (11 MB), and richer: 30 LEF / 27 LIB files
(multiple corners), `magic.tech`, and **`fakeram.tcl` + `fakeram.cfg`**, i.e. an
SRAM-macro generator. `PLACE_SITE = FreePDK45_38x28_10R_NP_162NW_34O`.

Both are viable. If the spec wants a fast first full-flow pass, nangate45 is the
better choice not only for runtime but because `fakeram` makes the A/B/C SRAM
macros trivial to produce. For sky130hd the SRAM equivalent is the separate
`sky130ram` platform, which ships pre-built OpenRAM macros:
`sky130_sram_1rw1r_44x64_8`, `_64x256_8`, `_80x64_8`, `_128x256_8`.
**Note for spec-writer:** an 8x8 INT8 array needs at most 64 B per operand matrix,
so `sky130_sram_1rw1r_44x64_8`/`_80x64_8` sized macros are plausible; a 16x16 array
with INT32 accumulators needs 1 kB for C. If none of the four fit, the fallback is
flop/latch-based arrays, which will dominate area.

---

## 3. Machine resources (ORFS runtime budget)

| Resource | Value |
|----------|-------|
| CPU | 13th Gen Intel Core i9-13950HX — 24 cores / 32 threads, 800 MHz–5.5 GHz |
| RAM | 93 GiB total, ~86 GiB available |
| Disk | `/dev/nvme0n1p4` mounted at `/`, 466 G total, **134 G free (70 % used)** |
| GPU | NVIDIA RTX 4090 Laptop (AD103M) + Intel Raptor Lake-S UHD. **`nvidia-smi` fails: "Driver/library version mismatch" (NVML 595.91)** — treat the GPU as unavailable. Irrelevant to ORFS, which is CPU-only. |

Implication: this is a fast machine. Use `make -j16` or higher for ORFS; a small
sky130hd design should close in tens of minutes, nangate45 faster. 134 G free disk
is adequate but not unlimited — ORFS `results/`+`logs/`+`reports/` for several
iterations can reach tens of GB. Watch it; `CLAUDE.md` forbids `rm -rf results/`
without asking.

---

## 4. Hello-world toolchain gate

Scratch module (deliberately **not** in `rtl/` or `tb/`):
`/tmp/claude-1000/-home-pgratz-pcie-matmul/d8295d42-891c-46ff-9b67-bb7ba8c3b5dc/scratchpad/hello/hello.sv`
— a parameterized two-flop shift register with active-high sync reset, matching
the repo conventions (no `initial`, no `#`, no `$display`).

| Check | Command | Result |
|-------|---------|--------|
| Lint | `verilator --lint-only -Wall hello.sv` | **PASS**, exit 0, zero warnings |
| Synth | `yosys -p "read_verilog -sv hello.sv; synth -top hello; stat"` | **PASS**, exit 0. Mapped to 16 `$_SDFF_PP0_` (= 2 stages x 8 bits), no unsupported constructs |
| Sim (Icarus) | `iverilog -g2012 -o sim_iv tb_hello.sv hello.sv && ./sim_iv` | **PASS** — self-checking tb reports `PASS errors=0` |
| Sim (Verilator) | `verilator --binary --timing --top-module tb_hello …` | **PASS** — `PASS errors=0`, `$finish at 45ns` |
| Verilator VPI headers (cocotb needs them) | `verilated_vpi.h`, `vltstd/vpi_user.h` in `/usr/share/verilator/include/` | **present** |
| **cocotb end-to-end (Icarus)** | `make SIM=icarus` in the scratch dir | **PASS** — `TESTS=1 PASS=1 FAIL=0 SKIP=0`, also PASS at `SEED=7` and `SEED=12345` |
| **cocotb end-to-end (Verilator)** | `make SIM=verilator` | **BLOCKED** — cocotb requires Verilator >= 5.036, box has 5.032 (see section 5) |

Aside worth remembering for the test-writer: `verilator -Wall` flags `BLKSEQ` on the
classic `always #5 clk = ~clk;` clock generator. That is a testbench-only concern
(cocotb drives the clock from Python, so it will not arise), but any hand-written
SV testbench needs `-Wno-BLKSEQ` or `<=`.

---

## 5. Simulator decision — **Icarus Verilog**, not Verilator

This **reverses** the `CLAUDE.md` default and the provisional recommendation in the
first draft of this report. Evidence, from an actual run:

```
$ make SIM=verilator
Makefile.verilator:29: *** cocotb requires Verilator 5.036 or later, but using 5.032.  Stop.
```

cocotb 2.1.0 enforces `VLT_MIN := 5.036` in
`cocotb_tools/makefiles/simulators/Makefile.verilator`. It is a hard `$(error)`,
not a warning. Installed Verilator is 5.032 and **`apt-cache policy verilator`
shows 5.032-1 as the only candidate** on Ubuntu 26.04 (resolute/universe). There is
no packaged upgrade path.

```
$ make SIM=icarus
** TESTS=1 PASS=1 FAIL=0 SKIP=0 **
```

**Therefore:**

- **Simulation (Phase 3 + Phase 4): Icarus Verilog 12.0 + cocotb 2.1.0.** Verified working.
- **Lint (Phase 2 gate): Verilator 5.032 `--lint-only -Wall`.** Verilator's linter is
  unaffected by the cocotb version floor and is much better than Icarus's, so keep
  using it. `tb/Makefile`'s `lint` target and `test` target use *different* tools —
  this is intentional, not an inconsistency.
- Icarus was going to be needed for Phase 4 anyway: **Verilator has no SDF support**,
  so gate-level simulation with back-annotated timing can only be done in Icarus.
  The forced choice costs less than it appears.

**Cost of this decision:** Icarus is materially slower than Verilator on large
designs. For a 16x16 INT8 systolic array with a TLP-level testbench this may make
the regression uncomfortably slow. Two mitigations, in order of preference:
1. The spec picks an **8x8** array for the first full-flow pass (already an option
   in `CLAUDE.md`), which keeps Icarus runtimes tolerable.
2. Build Verilator >= 5.036 from source, which this 32-thread machine would do in
   minutes. **Not done — requires approval:**
   ```bash
   git clone https://github.com/verilator/verilator /home/pgratz/verilator
   cd /home/pgratz/verilator && git checkout v5.038
   autoconf && ./configure --prefix=/home/pgratz/verilator/install
   make -j32 && make install
   ```
   This would install alongside, not replace, the apt Verilator. Recommend deferring
   until Phase 3 shows Icarus is actually too slow — do not pre-optimise.

## 6. Install history and remaining gaps

> **RESOLVED 2026-09-10.** The cocotb install below was approved and performed by
> the orchestrator; the predicted version trap did not bite (cocotb 2.1.0 cp314
> wheel installed cleanly and `cocotb_bus` imports fine under cocotb 2.x). Kept for
> the record. The one item in this section that is *still open* is the Phase 4
> standard-cell Verilog model gap at the end. A **new** gap discovered after
> installing is the Verilator 5.036 version floor — see section 5.

**[RESOLVED] cocotb + PCIe extension.** Because `/usr/lib/python3.14/EXTERNALLY-MANAGED`
exists, this must go in a venv:

```bash
python3 -m venv /home/pgratz/pcie-matmul/.venv
/home/pgratz/pcie-matmul/.venv/bin/pip install --upgrade pip
/home/pgratz/pcie-matmul/.venv/bin/pip install cocotb cocotbext-pcie
```

`cocotbext-pcie` pulls in `cocotbext-axi` and `cocotb-bus` automatically
(`cocotbext-pcie 0.2.16` -> `cocotbext-axi>=0.1.16` -> `cocotb-bus`), so all three
arrive from that one command.

### 6.1 Version-compatibility risk — read before installing

Python here is **3.14**, and it is the only interpreter available.

- **cocotb 2.1.0** (latest, 2026-08-30) is the **only** cocotb release that ships a
  `cp314` wheel. `requires_python >= 3.9`. This is what the command above will select.
- **cocotb 1.9.2** (the last 1.x) ships wheels only up to `cp313`. Installing it on
  3.14 means building the C extension from sdist, which may fail.
- So there is effectively no choice: it is cocotb 2.x on this machine, unless a
  3.13 interpreter is added (`sudo apt install python3.13 python3.13-venv` — but
  **apt currently has no candidate** for 3.13/3.12/3.11 on this Ubuntu 26.04 box,
  so that route needs a PPA or deadsnakes and is not a quick fix).

I inspected the `cocotbext-pcie 0.2.16` and `cocotbext-axi 0.1.28` wheels without
installing them, to see how much cocotb-1.x-only API they use:

| Legacy API | cocotbext-pcie | cocotbext-axi |
|---|---|---|
| `BinaryValue` / `cocotb.binary` | 0 files | 0 files |
| `cocotb.fork(...)` | 0 files | 0 files |
| `cocotb.decorators` | 0 files | 0 files |
| `cocotb.start_soon` (modern) | 11 files | 8 files |
| `import cocotb_bus` | 2 files | 3 files |

This is encouraging: both packages already use the modern `start_soon` API and
contain **none** of the three APIs cocotb 2.0 removed. The single residual risk is
`cocotb_bus` (`cocotb-bus 0.3.0`, which also drags in `scapy`) — imported by
`cocotbext-pcie/…/interface.py` and by cocotbext-axi's `apb.py`/`axis.py`/`stream.py`.
`cocotb-bus` was written for cocotb 1.x and may not import under 2.1.0.

**Recommended validation step the moment install is approved (before any test is
written):** run a trivial cocotb test against `hello.sv` with Verilator, *and*
separately run `python -c "import cocotbext.pcie.core; import cocotbext.axi"`. If the
`cocotb_bus` import breaks, the mitigation order is:
1. `pip install "cocotb==2.0.1"` — still no cp314 wheel, so probably not viable;
2. add a Python 3.13 interpreter and pin `cocotb==1.9.2` (known-good with
   cocotbext-pcie), which is the configuration cocotbext-pcie was released against;
3. only if both fail, revisit the `CLAUDE.md` "PCIe host model" row.

Do **not** let the test-writer start until this import check passes — the whole
PCIe testbench strategy in `CLAUDE.md` rests on `cocotbext-pcie` being importable.

**Non-blocking — Phase 4 gate-level cell models.** Neither platform dir contains
full behavioral Verilog for its standard cells; `sky130hd/` has only
`cells_adders_hd.v`, `cells_clkgate_hd.v`, `cells_latch_hd.v` (Yosys mapping
helpers), and nangate45 the equivalent three. There is no
`sky130_fd_sc_hd.v` anywhere on the machine. Gate-level simulation of
`6_final.v` will therefore need the cell library's simulation models, obtained
separately (e.g. the `skywater-pdk-libs-sky130_fd_sc_hd` repo or an open_pdks /
volare install for sky130; the Nangate Open Cell Library Verilog for nangate45).
This is not needed until Phase 4 — flagging it now so it is not a surprise at the
gate. I did not download anything.

**Non-blocking — `magic`.** Not installed (`sudo apt install magic`). Not required:
both candidate platforms use KLayout (`KLAYOUT_DRC_FILE`, `KLAYOUT_LVS_FILE`) and
KLayout 0.30.0 is present.

**Cosmetic — GPU.** `nvidia-smi` fails with a driver/library mismatch. No impact on
this project (ORFS and all simulators are CPU-only). Not worth fixing here.

---

## 7. cocotb 2.x notes for test-writer

**Read this before writing a single test.** cocotb 2.1.0 is a major-version break
from the 1.x API that most online examples and most memory are based on. Writing
1.x-style code here fails at import or, worse, silently misbehaves.

### Removed / renamed Python API

| cocotb 1.x (do NOT use) | cocotb 2.x (use this) |
|---|---|
| `cocotb.fork(coro)` | `cocotb.start_soon(coro)` — gone entirely, not deprecated |
| `from cocotb.binary import BinaryValue` | **`BinaryValue` is removed.** Use `cocotb.types.LogicArray` (and `Logic`) |
| `cocotb.decorators` | removed; `@cocotb.test()` is exposed straight off `cocotb` |
| `dut.sig.value = BinaryValue(...)` | `dut.sig.value = int` / `LogicArray` |
| `cocotb.utils.get_sim_time()` | `cocotb.simtime` / `cocotb.utils` (still present but reorganised) |
| `Clock(sig, 10, units="ns")` | **`unit=` (singular)**. `units=` is deprecated and warns |
| `TestFactory` | `@cocotb.parametrize(...)` |
| `cocotb.regression.TestFactory` | `cocotb.parametrize`, `cocotb.skipif`, `cocotb.xfail` |
| `cocotb.top` | `cocotb.tops` |

Confirmed present on `cocotb` 2.1.0's top level (`dir(cocotb)`):
`create_task, end_test, handle, is_simulation, parametrize, pass_test, simtime,
simulator, skipif, start, start_soon, task, test, tops, types, utils, xfail`.

### Value semantics (the subtle one)

- Reading `dut.sig.value` returns a `LogicArray`, **not** an int. Always wrap in
  `int(dut.sig.value)` before arithmetic or comparison against an int, or the
  comparison silently does the wrong thing. If the signal has X/Z bits, `int()`
  raises — catch that; it is a real X-propagation bug, not a nuisance.
- Writes are **deferred**: `dut.d.value = v` is scheduled, not immediate. It lands
  before the next `await` on a clock edge. Reading back `dut.d.value` on the same
  line returns the *old* value. This bit me in the hello-world test (see 7.1).

### Makefile variable renames (cocotb 2.x)

| 1.x | 2.x |
|---|---|
| `TOPLEVEL` | `COCOTB_TOPLEVEL` (1.x name still works with a deprecation warning) |
| `MODULE` | `COCOTB_TEST_MODULES` |
| `TESTCASE` | `COCOTB_TESTCASE` |
| `COVERAGE` | `COCOTB_USER_COVERAGE` |
| `RANDOM_SEED` | `COCOTB_RANDOM_SEED` |

Include path is unchanged: `include $(shell cocotb-config --makefiles)/Makefile.sim`.

**Icarus gotcha:** `EXTRA_ARGS` is passed to *both* `iverilog` and `vvp`. Putting
`-Wall` there makes `vvp` die with `invalid option -- 'W'`. Use `COMPILE_ARGS` for
compile-only flags. (Cost me one debug cycle; documented so it costs you none.)

There is also a modern Python entry point, `cocotb_tools.runner` (classes `Icarus`,
`Verilator`, `Ghdl`, `Questa`, …), if `tb/Makefile` would rather shell out to a
Python runner than use `Makefile.sim`. Either is fine; `Makefile.sim` is verified
working here.

### 7.1 A worked example of the deferred-write trap

My first hello-world test failed 49/50 with the DUT appearing one cycle "early".
Root cause was **the test, not the DUT** — logged here because the same off-by-one
will appear in the matmul reference model. Driving `d` then awaiting `RisingEdge`
means that edge captures `v_i` into stage0; sampling `q` after that edge therefore
sees `v_{i-1}` (which has passed through two edges), not `v_{i-2}`. The two-flop
latency is still 2 edges. Reference models must be aligned to the *sampling point*,
not to the nominal latency number. Fixed model:

```python
prev = 0
for _ in range(50):
    v = rnd.randrange(256)
    dut.d.value = v
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.q.value) == prev
    prev = v
```

Sampling on the falling edge (as above) sidesteps read-during-edge races entirely.
Recommend test-writer adopt that convention project-wide.

---

## 8. The venv — how every agent invokes it

```
venv: /home/pgratz/pcie-matmul/.venv        (gitignored)
python:        /home/pgratz/pcie-matmul/.venv/bin/python      -> Python 3.14.4
cocotb-config: /home/pgratz/pcie-matmul/.venv/bin/cocotb-config -> 2.1.0
```

Contents: cocotb 2.1.0, cocotbext-pcie 0.2.16, cocotbext-axi 0.1.28, cocotb-bus 0.3.0,
scapy 2.7.0, pytest 9.1.1, find-libpython 0.5.1.

The `cocotb_bus` compatibility risk flagged in the first draft **did not
materialise** — `import cocotb, cocotbext.pcie.core, cocotb_bus` exits 0 under
cocotb 2.1.0. The TLP-library plan in `CLAUDE.md` holds.

**Invocation.** `tb/Makefile` must put the venv on `PATH` so that `cocotb-config`
and the `python3` that cocotb embeds both resolve inside the venv:

```make
VENV := /home/pgratz/pcie-matmul/.venv
export PATH := $(VENV)/bin:$(PATH)
SIM ?= icarus
include $(shell cocotb-config --makefiles)/Makefile.sim
```

Do **not** merely set `PYTHONPATH` at the venv's site-packages — cocotb resolves its
own interpreter via `find_libpython` and will pick up the system 3.14 without the
venv's packages. And do **not** `source ${ORFS}/env.sh` in the same shell as a
cocotb run: ORFS prepends its own Python and library paths and can shadow the venv.
Keep the ORFS environment to the `synth`/flow targets only.

---

## 9. cocotbext-pcie 0.2.16 — the attach point (binding on spec-writer)

### There is no PIPE interface. At all.

```
$ grep -ril "pipe" .venv/lib/python3.14/site-packages/cocotbext/pcie/ --include=*.py
(no output)
```

`CLAUDE.md` states "the synthesizable design boundary is the PIPE interface" and
separately that "the spec's endpoint boundary must be one it can attach to". **These
two requirements are in direct conflict** and the second one wins, because the
library is the reference and we are not hand-writing TLP codecs. The accepted
fallback already written into `CLAUDE.md` — *"a TLP-level endpoint (TL + application
layer) with DLL modeled behaviorally"* — is therefore **mandatory, not optional**,
and spec-writer must record it as an explicit decision in `docs/spec.md` and
`docs/decisions.md`.

### What 0.2.16 actually provides

Installed tree (all verified to import):

| Import path | Exports | Boundary |
|---|---|---|
| `cocotbext.pcie.core` | `RootComplex`, `Device`, `Endpoint`, `MemoryEndpoint`, `Function`, `Switch`, plus `tlp`, `dllp`, `caps`, `msi`, `region` | Pure-Python, **no RTL signals** |
| `cocotbext.pcie.xilinx.us` | `UltraScalePcieDevice`, `UltraScalePlusPcieDevice`, + `…PcieFunction` | **RTL-facing**, AXI-Stream RQ/RC/CQ/CC |
| `cocotbext.pcie.intel.ptile` | `PTilePcieDevice`, `PTileRxBus`, `PTileTxBus`, `PTilePcieFunction` | **RTL-facing**, Intel P-Tile AXI-ST |
| `cocotbext.pcie.intel.s10` | `S10PcieDevice`, `S10RxBus`, `S10TxBus`, `S10PcieFunction` | **RTL-facing**, Stratix 10 H-Tile |

Note `pkgutil.iter_modules` lists only `core`; the `intel`/`xilinx` subpackages are
present on disk and import fine, they just are not advertised by that call. Do not
conclude from a `pkgutil` listing that they are missing.

`cocotbext.pcie.core.RootComplex` and `MemoryEndpoint` are **behavioural Python
models with no RTL ports** — `MemoryEndpoint` is something you *subclass* and hand
`handle_mem_read_tlp` / `handle_mem_write_tlp` / `handle_tlp`. It models a device;
it does not drive a DUT. It is useful as the golden reference and for the host side,
not as the DUT attachment.

Constructor signatures for test-writer:

```python
RootComplex(mem_address_space=None, io_address_space=None, *args, **kwargs)
# methods: add_endpoint, alloc_region, alloc_io_region, config_read/write[_byte|
#          _word|_dword|_qword], capability_read/write*, alloc_tag, ...
MemoryEndpoint(*args, **kwargs)
# methods: add_mem_region, add_prefetchable_mem_region, configure_bar,
#          handle_mem_read_tlp, handle_mem_write_tlp, handle_config_0_*_tlp,
#          match_bar, register_capability, ...
```

### Recommended boundary: Xilinx UltraScale+ CQ/CC (+ RQ/RC)

`UltraScalePlusPcieDevice` takes ~200 keyword args, **all defaulting to `None`** —
you connect only the buses you need. For this project the host does BAR0 register and
SRAM access, i.e. the DUT is a pure **completer**, so the minimum viable attachment is:

- `user_clk`, `user_reset`, `user_lnk_up`
- `cq_bus` — Completer reQuest: inbound MemRd/MemWr TLPs to BAR0
- `cc_bus` — Completer Completion: outbound Completions
- plus `rq_bus`/`rc_bus` **only if** the DMA stretch goal is taken (DUT as requester)
- optional: `cfg_interrupt_msi_*` for the IRQ/status requirement

Config-space tuning knobs the spec should fix now: `pcie_generation`,
`pcie_link_width`, `user_clk_frequency`, `alignment='dword'`, `max_payload_size=128`,
`pf0_msi_enable`, and the four `*_straddle` flags (**keep straddling off in v1** —
it substantially complicates the TLP framing the RTL must parse).

**Why Xilinx US+ over Intel P-Tile:** it is the most widely used interface in this
library, is exercised by the upstream `corundum` NIC, and the CQ/CC dword-aligned
AXI-Stream framing is the simplest to parse in RTL. This is a recommendation, not a
finding — spec-writer owns the call, but it should be one of these three, and it
cannot be PIPE.

**Consequence for the RTL boundary:** the DUT's top-level PCIe interface becomes an
AXI-Stream pair (CQ in, CC out) at 64/128/256 bits, not a PIPE parallel bus. The DLL
and PHY are entirely inside the behavioural model. That is *less* RTL than the PIPE
plan, and all of it still synthesises to GDS.

---

## 10. Gate assessment

| Gate item (`CLAUDE.md` Phase 0) | Status |
|---|---|
| Tool versions recorded: openroad, yosys, verilator/iverilog, python | **MET** |
| cocotb version recorded | **MET** — 2.1.0 in `/home/pgratz/pcie-matmul/.venv` |
| ORFS path + platform dir recorded | **MET** |
| `make lint` runs on a hello-world module | **MET** — `verilator --lint-only -Wall` clean, `yosys synth` clean |
| cocotb test runs end-to-end (the real gate) | **MET** — `TESTS=1 PASS=1 FAIL=0` on Icarus, reproduced on 3 seeds |

**Overall: Phase 0 gate MET.** Proceed to Phase 1 (spec-writer).

### Carried forward — items later phases must not rediscover

1. **Simulator is Icarus**, not Verilator (section 5). Update the `CLAUDE.md`
   parameters table. Verilator remains the linter.
2. **Endpoint boundary cannot be PIPE** (section 9). spec-writer must choose a
   TLP-level AXI-Stream boundary and record it in `docs/decisions.md`.
3. **Phase 4: no standard-cell Verilog models on disk.** Neither `sky130hd/` nor
   `nangate45/` ships behavioural Verilog for its cells (only the three Yosys
   mapping helpers `cells_adders*.v`, `cells_clkgate*.v`, `cells_latch*.v`), and
   there is no `sky130_fd_sc_hd.v` anywhere on this machine. Gate-level sim of
   `6_final.v` needs them fetched separately. Flagged, not fetched.
4. **Phase 4: SDF requires Icarus.** Verilator cannot back-annotate SDF at all, so
   the `test-gl` target must be Icarus regardless of item 1.
5. **Disk:** 134 G free. Several ORFS iterations will eat into that; watch it.
