# ---------------------------------------------------------------------------
# Gate-level simulation of results/sky130hd/pcie_matmul/base/6_final.v
#
#   make -C tb/gl test-gl                 SDF back-annotated, smoke test
#   make -C tb/gl test-gl TEST=test_regs  another module from the RTL suite
#   make -C tb/gl test-gl SDF=            no back-annotation (unit delay)
#   make -C tb/gl models                  regenerate tb/gl/models_sdf
#
# This is deliberately a SEPARATE Makefile from tb/Makefile.  It shares the
# cocotb tests and models (tb/tests, tb/models) but nothing else: the RTL
# suite's 72/72 must not be perturbed by anything here, and a GL run must
# never be mistaken for an RTL run in a log.
#
# The netlist is N=8 (the flow synthesized N=8); `N` is not overridable here,
# unlike tb/Makefile.  Tests read N from CONFIG[7:0] so they adapt by
# themselves.
# ---------------------------------------------------------------------------
GL_DIR   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
TB_DIR   := $(abspath $(GL_DIR)/..)
TOP_DIR  := $(abspath $(TB_DIR)/..)
VENV     := $(TOP_DIR)/.venv

export PATH := $(VENV)/bin:$(PATH)
export PYTHONPATH := $(TB_DIR)/tests:$(TB_DIR):$(PYTHONPATH)

RESULTS  := $(TOP_DIR)/results/sky130hd/pcie_matmul/base
NETLIST  ?= $(RESULTS)/6_final.v
SDF      ?= $(RESULTS)/6_final.sdf
MODELS   := $(GL_DIR)/models_sdf

SIM             := icarus
TOPLEVEL_LANG   := verilog
COCOTB_TOPLEVEL := gl_top
TEST            ?= test_smoke
SEED            ?=

COCOTB_TEST_MODULES := $(TEST)
export COCOTB_TEST_MODULES COCOTB_TOPLEVEL
ifneq ($(SEED),)
export SEED
endif

VERILOG_SOURCES := $(GL_DIR)/gl_top.v $(MODELS)/sky130_fd_sc_hd.v $(NETLIST)

# iverilog resolves `include against -I and CWD, never against the including
# file, and the upstream cells include siblings by bare name plus the UDPs by
# ../../models/... -- so every cells/<n>/ dir goes on -I and both forms resolve.
GL_INCLUDES := -I$(MODELS) $(addprefix -I,$(wildcard $(MODELS)/cells/*)) \
               $(addprefix -I,$(wildcard $(MODELS)/models/*))

# -gspecify is REQUIRED.  Without it Icarus drops every specify block and
# prints "Omitting $sdf_annotate() since specify blocks are being omitted."
# -- the run then silently has no back-annotation at all.
# -DFUNCTIONAL is REQUIRED.  The default `behavioral` sky130 models clock from
# D_delayed/CLK_delayed, which only $setuphold drives; Icarus implements no
# timing checks, so those nets stay undriven and every flop output is X.
COMPILE_ARGS += -gspecify -DFUNCTIONAL -DUNIT_DELAY= $(GL_INCLUDES)

ifneq ($(strip $(SDF)),)
PLUSARGS += +sdf=$(SDF)
endif

SIM_BUILD := $(GL_DIR)/sim_build
COCOTB_RESULTS_FILE := $(SIM_BUILD)/results.xml

.PHONY: test-gl models gl-guard clean

models:
	@$(VENV)/bin/python $(GL_DIR)/build_sdf_models.py

gl-guard:
	@test -f $(NETLIST) || { echo "no netlist at $(NETLIST)"; exit 1; }
	@test -d $(MODELS)  || { echo "no models; run: make -C tb/gl models"; exit 1; }
	@if [ -n "$(strip $(SDF))" ]; then test -f $(SDF) || \
	    { echo "no SDF at $(SDF); pass SDF= to run unannotated"; exit 1; }; fi
	@echo "gl: netlist=$(notdir $(NETLIST)) sdf=$(if $(strip $(SDF)),$(notdir $(SDF)),<none>) modules=$(COCOTB_TEST_MODULES)"

include $(shell cocotb-config --makefiles)/Makefile.sim

test-gl: gl-guard
	@$(MAKE) -f $(firstword $(MAKEFILE_LIST)) sim

clean::
	@rm -rf $(SIM_BUILD)
