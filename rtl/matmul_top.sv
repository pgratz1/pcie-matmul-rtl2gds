// ---------------------------------------------------------------------------
// matmul_top.sv
//
// Purpose : Top level of the PCIe-attached matrix multiplier. Contains nothing
//           but the instantiation and wiring of pcie_tl, app_bar0 and
//           matmul_engine (REQ-011).
//
//           The chip boundary is a raw-TLP, 32-bit synchronous valid/ready
//           DWORD stream carrying complete, DLL-stripped TLPs (DEC-003,
//           spec 5). Header DWORDs are big-endian (PCIe wire order), payload
//           DWORDs are little-endian (host order) - spec 5.3.
//
// Parameters:
//   N    - systolic array dimension; power of two, 2..32. 8 in v1 (DEC-004).
//   DW   - operand width in bits; 8 in v1.
//   ACCW - accumulator width in bits; 32 in v1.
//   IDXW - derived from N; do not override.
//
// Interface contract: spec 6.1. This port list is binding; the testbench shim
//   is built against it. Single clock, active-high SYNCHRONOUS reset, no clock
//   domain crossing anywhere in the design (REQ-107, REQ-108).
//
// Latency:
//   Register write accepted at t -> observable at t+1.
//   BAR0 read request accepted at t -> first read DWORD at t+2.
//   CTRL.START accepted at t -> STATUS.DONE reads 1 at t + 4N + 2.
//
// Implements: REQ-010, REQ-011, REQ-012, REQ-107, REQ-113.
//
// Whole-tree properties asserted at this level because no single submodule owns
// them:
//   REQ-109 - every flop in the tree uses the same synchronous reset, so holding
//             rst for >= 2 clk cycles reaches the spec 13.4 reset state.
//   REQ-110 - no `initial` block, no `#` delay and no `$display` appears
//             anywhere under rtl/; all reset values come from `rst`.
// System-level behaviours that emerge from the wiring below rather than from any
// one module, and are verified end to end at the chip boundary:
//   REQ-116 - the spec 15 operating sequence completes with no UR and no error
//             bit set.
//   REQ-117 - back-to-back operations: mm_ctrl asserts clr_acc in PRIME on every
//             START, so no accumulator residue survives into the next operation.
//   REQ-118 - an all-zero A and B still runs the full 4N+2 sequence and sets DONE.
//   REQ-119 - A/B loaded by maximal MWr bursts or by single-DWORD writes are
//             identical: app_bar0 decodes every DWORD of a burst from its own
//             address and applies Byte Enables per beat.
//   REQ-120 - C read by maximal MRd bursts or by single-DWORD reads is identical
//             for the same reason on the read path.
//   REQ-122 - D_WR = 1 for every BAR0 write: the write strobe into reg_file /
//             mem_a / mem_b / mem_c is combinational from the accepted payload
//             beat, so storage always commits on the edge that ends that beat,
//             independently of region, burst position, Byte Enables and N.
// ---------------------------------------------------------------------------
module matmul_top #(
    parameter int N    = 8,     // systolic array dimension; power of two, 2..32
    parameter int DW   = 8,     // operand width in bits; 8 in v1
    parameter int ACCW = 32,    // accumulator width in bits; 32 in v1
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)   // derived, do not override
) (
    // Clock and reset
    input  logic        clk,
    input  logic        rst,            // active-high, SYNCHRONOUS

    // Inbound TLP stream (host -> device)
    input  logic [31:0] rx_tlp_data,
    input  logic        rx_tlp_sop,
    input  logic        rx_tlp_eop,
    input  logic        rx_tlp_valid,
    output logic        rx_tlp_ready,

    // Outbound TLP stream (device -> host)
    output logic [31:0] tx_tlp_data,
    output logic        tx_tlp_sop,
    output logic        tx_tlp_eop,
    output logic        tx_tlp_valid,
    input  logic        tx_tlp_ready,

    // Sideband
    output logic        irq             // level-sensitive, active high
);

    // pcie_tl <-> app_bar0
    logic         app_req_valid;
    logic         app_req_ready;
    logic         app_req_write;
    logic [13:0]  app_req_addr;
    logic [5:0]   app_req_len;
    logic [3:0]   app_req_first_be;
    logic [3:0]   app_req_last_be;
    logic         app_req_abort;
    logic         app_wdata_valid;
    logic         app_wdata_ready;
    logic [31:0]  app_wdata;
    logic         app_wdata_last;
    logic         app_rdata_valid;
    logic         app_rdata_ready;
    logic [31:0]  app_rdata;
    logic         ev_unsup_req;

    // app_bar0 <-> matmul_engine
    logic               eng_start;
    logic               eng_soft_reset;
    logic               eng_busy;
    logic               eng_done_set;
    logic [31:0]        eng_cycles;
    logic [N*IDXW-1:0]  eng_ka_idx;
    logic [N-1:0]       eng_ka_vld;
    logic [N*DW-1:0]    eng_a_rd;
    logic [N*IDXW-1:0]  eng_kb_idx;
    logic [N-1:0]       eng_kb_vld;
    logic [N*DW-1:0]    eng_b_rd;
    logic               eng_c_wr_en;
    logic [IDXW-1:0]    eng_c_row;
    logic [N*ACCW-1:0]  eng_c_data;

    pcie_tl u_pcie_tl (
        .clk              (clk),
        .rst              (rst),
        .rx_tlp_data      (rx_tlp_data),
        .rx_tlp_sop       (rx_tlp_sop),
        .rx_tlp_eop       (rx_tlp_eop),
        .rx_tlp_valid     (rx_tlp_valid),
        .rx_tlp_ready     (rx_tlp_ready),
        .tx_tlp_data      (tx_tlp_data),
        .tx_tlp_sop       (tx_tlp_sop),
        .tx_tlp_eop       (tx_tlp_eop),
        .tx_tlp_valid     (tx_tlp_valid),
        .tx_tlp_ready     (tx_tlp_ready),
        .app_req_valid    (app_req_valid),
        .app_req_ready    (app_req_ready),
        .app_req_write    (app_req_write),
        .app_req_addr     (app_req_addr),
        .app_req_len      (app_req_len),
        .app_req_first_be (app_req_first_be),
        .app_req_last_be  (app_req_last_be),
        .app_req_abort    (app_req_abort),
        .app_wdata_valid  (app_wdata_valid),
        .app_wdata_ready  (app_wdata_ready),
        .app_wdata        (app_wdata),
        .app_wdata_last   (app_wdata_last),
        .app_rdata_valid  (app_rdata_valid),
        .app_rdata_ready  (app_rdata_ready),
        .app_rdata        (app_rdata),
        .ev_unsup_req     (ev_unsup_req)
    );

    app_bar0 #(
        .N    (N),
        .DW   (DW),
        .ACCW (ACCW),
        .IDXW (IDXW)
    ) u_app_bar0 (
        .clk            (clk),
        .rst            (rst),
        .req_valid      (app_req_valid),
        .req_ready      (app_req_ready),
        .req_write      (app_req_write),
        .req_addr       (app_req_addr),
        .req_len        (app_req_len),
        .req_first_be   (app_req_first_be),
        .req_last_be    (app_req_last_be),
        .req_abort      (app_req_abort),
        .wdata_valid    (app_wdata_valid),
        .wdata_ready    (app_wdata_ready),
        .wdata          (app_wdata),
        .wdata_last     (app_wdata_last),
        .rdata_valid    (app_rdata_valid),
        .rdata_ready    (app_rdata_ready),
        .rdata          (app_rdata),
        .ev_unsup_req   (ev_unsup_req),
        .eng_start      (eng_start),
        .eng_soft_reset (eng_soft_reset),
        .eng_busy       (eng_busy),
        .eng_done_set   (eng_done_set),
        .eng_cycles     (eng_cycles),
        .eng_ka_idx     (eng_ka_idx),
        .eng_ka_vld     (eng_ka_vld),
        .eng_a_rd       (eng_a_rd),
        .eng_kb_idx     (eng_kb_idx),
        .eng_kb_vld     (eng_kb_vld),
        .eng_b_rd       (eng_b_rd),
        .eng_c_wr_en    (eng_c_wr_en),
        .eng_c_row      (eng_c_row),
        .eng_c_data     (eng_c_data),
        .irq            (irq)
    );

    matmul_engine #(
        .N    (N),
        .DW   (DW),
        .ACCW (ACCW),
        .IDXW (IDXW)
    ) u_engine (
        .clk         (clk),
        .rst         (rst),
        .start       (eng_start),
        .soft_reset  (eng_soft_reset),
        .busy        (eng_busy),
        .done_set    (eng_done_set),
        .cycle_count (eng_cycles),
        .ka_idx      (eng_ka_idx),
        .ka_vld      (eng_ka_vld),
        .a_rd        (eng_a_rd),
        .kb_idx      (eng_kb_idx),
        .kb_vld      (eng_kb_vld),
        .b_rd        (eng_b_rd),
        .c_wr_en     (eng_c_wr_en),
        .c_wr_row    (eng_c_row),
        .c_wr_data   (eng_c_data)
    );

endmodule
