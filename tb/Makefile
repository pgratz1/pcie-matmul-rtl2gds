# ---------------------------------------------------------------------------
# Testbench entry point for the PCIe-attached matrix multiplier.
#
#   make lint               verilator --lint-only -Wall over rtl/ + structural
#                           checks (tb/tools/check_rtl_rules.py)
#   make test               run every cocotb test module
#   make test TEST=test_smoke
#                           run one module (or TEST=test_smoke::test_name)
#   make waves              same as `make test` but dump an FST/VCD
#   make elab-sweep         elaborate matmul_top for N in {2,4,8,16,32}
#                           (REQ-113)
#   make clean
#
#   SIM=icarus (default) | verilator
#   SEED=<n>    seeds every random choice in the testbench (default 1)
#   N=<n>       elaboration parameter override
#
# Simulator note (DEC-001): cocotb 2.1.0 hard-errors on Verilator < 5.036 and
# this machine has 5.032, so the *simulator* is Icarus and Verilator is used
# only as the linter.  `make lint` and `make test` deliberately use different
# tools; that is not an inconsistency.
# ---------------------------------------------------------------------------

TB_DIR   := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
TOP_DIR  := $(abspath $(TB_DIR)/..)
RTL_DIR  := $(TOP_DIR)/rtl
FILELIST := $(RTL_DIR)/filelist.f
VENV     := $(TOP_DIR)/.venv

export PATH := $(VENV)/bin:$(PATH)
export PYTHONPATH := $(TB_DIR)/tests:$(TB_DIR):$(PYTHONPATH)

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
COCOTB_TOPLEVEL := matmul_top
N ?= 8
SEED ?=

# --- source list ------------------------------------------------------------
# rtl/filelist.f is the authority (CLAUDE.md); fall back to a glob so the
# harness still works the moment the first .sv appears.
ifneq ($(wildcard $(FILELIST)),)
VERILOG_SOURCES := $(shell sed -e 's:#.*::' -e 's://.*::' $(FILELIST) \
    | grep -v '^[[:space:]]*[-+]' | grep -v '^[[:space:]]*$$' \
    | sed -e 's:^[[:space:]]*::' -e 's:[[:space:]]*$$::' \
    | sed -e 's:^rtl/:$(TOP_DIR)/rtl/:' \
    | sed -e 's:^\([^/]\):$(RTL_DIR)/\1:')
else
VERILOG_SOURCES := $(sort $(wildcard $(RTL_DIR)/*.sv) $(wildcard $(RTL_DIR)/*.v))
endif

# --- test selection ---------------------------------------------------------
ALL_TEST_MODULES := test_smoke test_regs test_tlp test_cfg test_matmul \
                    test_stress

ifeq ($(TEST),)
COCOTB_TEST_MODULES := $(shell echo $(ALL_TEST_MODULES) | tr ' ' ',')
else
ifneq ($(findstring ::,$(TEST)),)
COCOTB_TEST_MODULES := $(word 1,$(subst ::, ,$(TEST)))
COCOTB_TESTCASE := $(word 2,$(subst ::, ,$(TEST)))
else
COCOTB_TEST_MODULES := $(TEST)
endif
endif

export COCOTB_TEST_MODULES
export COCOTB_TOPLEVEL
ifneq ($(COCOTB_TESTCASE),)
export COCOTB_TESTCASE
endif
ifneq ($(SEED),)
export SEED
endif

# Icarus trap (phase0-env.md 7): EXTRA_ARGS is passed to vvp as well as to
# iverilog, so compile-only flags must go in COMPILE_ARGS.
ifeq ($(SIM),icarus)
COMPILE_ARGS += -P$(COCOTB_TOPLEVEL).N=$(N)
endif
ifeq ($(SIM),verilator)
EXTRA_ARGS += --trace-fst
COMPILE_ARGS += -Wall -GN=$(N)
endif

.PHONY: usage test sim-guard lint lint-verilator lint-rules waves clean \
        elab-sweep list-tests sources

usage:
	@echo "targets: lint | test [TEST=<module>] | waves | elab-sweep | clean"
	@echo "vars:    SIM=$(SIM)  N=$(N)  SEED=$(or $(SEED),1 (default))"
	@echo "sources: $(words $(VERILOG_SOURCES)) file(s)"

sources:
	@for f in $(VERILOG_SOURCES); do echo $$f; done

list-tests:
	@for t in $(ALL_TEST_MODULES); do echo $$t; done

# ---------------------------------------------------------------------------
# Lint
# ---------------------------------------------------------------------------
lint: lint-verilator lint-rules

lint-verilator:
	@if [ -z "$(strip $(VERILOG_SOURCES))" ]; then \
	    echo "lint: no RTL under $(RTL_DIR) yet -- nothing to lint."; \
	else \
	    echo "verilator --lint-only -Wall --top-module $(COCOTB_TOPLEVEL)"; \
	    verilator --lint-only -Wall --top-module $(COCOTB_TOPLEVEL) \
	        -GN=$(N) $(VERILOG_SOURCES); \
	fi

lint-rules:
	@$(VENV)/bin/python $(TB_DIR)/tools/check_rtl_rules.py

# ---------------------------------------------------------------------------
# Elaboration sweep -- REQ-113: matmul_top elaborates for every legal N
# ---------------------------------------------------------------------------
elab-sweep:
	@if [ -z "$(strip $(VERILOG_SOURCES))" ]; then \
	    echo "elab-sweep: no RTL yet -- skipping."; exit 0; \
	fi; \
	rc=0; \
	for n in 2 4 8 16 32; do \
	    echo "--- elaborating $(COCOTB_TOPLEVEL) with N=$$n (REQ-113)"; \
	    iverilog -g2012 -o /dev/null -s $(COCOTB_TOPLEVEL) \
	        -P$(COCOTB_TOPLEVEL).N=$$n $(VERILOG_SOURCES) || rc=1; \
	done; \
	if [ $$rc -ne 0 ]; then \
	    echo "REQ-113 FAILED: matmul_top does not elaborate for every legal N"; \
	fi; \
	exit $$rc

# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------
sim-guard:
	@if [ -z "$(strip $(VERILOG_SOURCES))" ]; then \
	    echo "ERROR: no RTL sources found."; \
	    echo "       expected $(FILELIST) or $(RTL_DIR)/*.sv"; \
	    echo "       (the testbench is complete; it is waiting on rtl-designer)"; \
	    exit 1; \
	fi
	@echo "tb: SIM=$(SIM) N=$(N) MODULES=$(COCOTB_TEST_MODULES)"

ifneq ($(strip $(VERILOG_SOURCES)),)
include $(shell cocotb-config --makefiles)/Makefile.sim

test: sim-guard
	@$(MAKE) -f $(firstword $(MAKEFILE_LIST)) sim
else
test: sim-guard
endif

waves:
	@$(MAKE) -f $(firstword $(MAKEFILE_LIST)) WAVES=1 test
	@echo "wave file: $(TB_DIR)/sim_build/$(COCOTB_TOPLEVEL).fst"

clean::
	@rm -rf $(TB_DIR)/sim_build $(TB_DIR)/results.xml \
	        $(TB_DIR)/__pycache__ $(TB_DIR)/tests/__pycache__ \
	        $(TB_DIR)/models/__pycache__

.DEFAULT_GOAL := usage
