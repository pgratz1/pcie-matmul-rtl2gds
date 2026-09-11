// ---------------------------------------------------------------------------
// pcie_tl.sv
//
// Purpose : PCIe Transaction Layer container. Instantiates tlp_rx, tlp_tx and
//           pcie_cfg_space and wires them to each other, to the chip-boundary
//           TLP streams and to app_bar0. Contains no logic of its own.
//
//           Serialization model (DEC-007): inbound TLPs are serviced in strict
//           arrival order, one at a time, with at most one Completion in
//           flight. tlp_rx holds rx_tlp_ready low from dispatch of a request
//           until its Completion has been fully transferred, which is what
//           makes an outbound arbiter unnecessary and what guarantees no
//           deadlock when tx_tlp_ready is held low (REQ-015).
//
//           There is NO data link layer in this design: no sequence numbers,
//           no LCRC, no ACK/NAK, no credit accounting, and zero DLLPs cross
//           this boundary (spec 4.4). There is also no clock domain crossing:
//           both streams are synchronous to clk (REQ-107).
//
// Parameters: none.
//
// Latency: see tlp_rx and tlp_tx headers.
//
// Implements: REQ-013, REQ-014, REQ-015 (by construction of its children).
// ---------------------------------------------------------------------------
module pcie_tl (
    // Clock and reset
    input  logic         clk,
    input  logic         rst,

    // Inbound TLP stream (chip boundary)
    input  logic [31:0]  rx_tlp_data,
    input  logic         rx_tlp_sop,
    input  logic         rx_tlp_eop,
    input  logic         rx_tlp_valid,
    output logic         rx_tlp_ready,

    // Outbound TLP stream (chip boundary)
    output logic [31:0]  tx_tlp_data,
    output logic         tx_tlp_sop,
    output logic         tx_tlp_eop,
    output logic         tx_tlp_valid,
    input  logic         tx_tlp_ready,

    // Decoded BAR0 request (to app_bar0)
    output logic         app_req_valid,
    input  logic         app_req_ready,
    output logic         app_req_write,
    output logic [13:0]  app_req_addr,
    output logic [5:0]   app_req_len,
    output logic [3:0]   app_req_first_be,
    output logic [3:0]   app_req_last_be,
    output logic         app_req_abort,

    // Write payload (to app_bar0)
    output logic         app_wdata_valid,
    input  logic         app_wdata_ready,
    output logic [31:0]  app_wdata,
    output logic         app_wdata_last,

    // Read data (from app_bar0)
    input  logic         app_rdata_valid,
    output logic         app_rdata_ready,
    input  logic [31:0]  app_rdata,

    // Error event (to reg_file via app_bar0)
    output logic         ev_unsup_req
);

    // tlp_rx <-> pcie_cfg_space
    logic        cfg_req_valid;
    logic        cfg_req_write;
    logic [9:0]  cfg_req_dw_addr;
    logic [3:0]  cfg_req_be;
    logic [31:0] cfg_req_wdata;
    logic [15:0] cfg_req_completer_id;
    logic [31:0] cfg_rdata;
    logic [17:0] cfg_bar0_base;
    logic        cfg_mem_space_en;
    logic [15:0] cfg_completer_id;

    // tlp_rx <-> tlp_tx
    logic        cpl_req_valid;
    logic        cpl_req_ready;
    logic        cpl_with_data;
    logic [5:0]  cpl_len;
    logic [11:0] cpl_byte_count;
    logic [6:0]  cpl_lower_addr;
    logic [2:0]  cpl_status;
    logic [2:0]  cpl_tc;
    logic [2:0]  cpl_attr;
    logic [15:0] cpl_req_id;
    logic [7:0]  cpl_tag;
    logic        pld_valid;
    logic        pld_ready;
    logic [31:0] pld_data;
    logic        cpl_done;

    tlp_rx u_tlp_rx (
        .clk                  (clk),
        .rst                  (rst),
        .rx_tlp_data          (rx_tlp_data),
        .rx_tlp_sop           (rx_tlp_sop),
        .rx_tlp_eop           (rx_tlp_eop),
        .rx_tlp_valid         (rx_tlp_valid),
        .rx_tlp_ready         (rx_tlp_ready),
        .app_req_valid        (app_req_valid),
        .app_req_ready        (app_req_ready),
        .app_req_write        (app_req_write),
        .app_req_addr         (app_req_addr),
        .app_req_len          (app_req_len),
        .app_req_first_be     (app_req_first_be),
        .app_req_last_be      (app_req_last_be),
        .app_req_abort        (app_req_abort),
        .app_wdata_valid      (app_wdata_valid),
        .app_wdata_ready      (app_wdata_ready),
        .app_wdata            (app_wdata),
        .app_wdata_last       (app_wdata_last),
        .app_rdata_valid      (app_rdata_valid),
        .app_rdata_ready      (app_rdata_ready),
        .app_rdata            (app_rdata),
        .cfg_req_valid        (cfg_req_valid),
        .cfg_req_write        (cfg_req_write),
        .cfg_req_dw_addr      (cfg_req_dw_addr),
        .cfg_req_be           (cfg_req_be),
        .cfg_req_wdata        (cfg_req_wdata),
        .cfg_req_completer_id (cfg_req_completer_id),
        .cfg_rdata            (cfg_rdata),
        .cfg_bar0_base        (cfg_bar0_base),
        .cfg_mem_space_en     (cfg_mem_space_en),
        .cpl_req_valid        (cpl_req_valid),
        .cpl_req_ready        (cpl_req_ready),
        .cpl_with_data        (cpl_with_data),
        .cpl_len              (cpl_len),
        .cpl_byte_count       (cpl_byte_count),
        .cpl_lower_addr       (cpl_lower_addr),
        .cpl_status           (cpl_status),
        .cpl_tc               (cpl_tc),
        .cpl_attr             (cpl_attr),
        .cpl_req_id           (cpl_req_id),
        .cpl_tag              (cpl_tag),
        .pld_valid            (pld_valid),
        .pld_ready            (pld_ready),
        .pld_data             (pld_data),
        .cpl_done             (cpl_done),
        .ev_unsup_req         (ev_unsup_req)
    );

    pcie_cfg_space u_cfg (
        .clk              (clk),
        .rst              (rst),
        .req_valid        (cfg_req_valid),
        .req_write        (cfg_req_write),
        .req_dw_addr      (cfg_req_dw_addr),
        .req_be           (cfg_req_be),
        .req_wdata        (cfg_req_wdata),
        .req_completer_id (cfg_req_completer_id),
        .rdata            (cfg_rdata),
        .bar0_base        (cfg_bar0_base),
        .mem_space_en     (cfg_mem_space_en),
        .completer_id     (cfg_completer_id)
    );

    tlp_tx u_tlp_tx (
        .clk              (clk),
        .rst              (rst),
        .cpl_req_valid    (cpl_req_valid),
        .cpl_req_ready    (cpl_req_ready),
        .cpl_with_data    (cpl_with_data),
        .cpl_len          (cpl_len),
        .cpl_byte_count   (cpl_byte_count),
        .cpl_lower_addr   (cpl_lower_addr),
        .cpl_status       (cpl_status),
        .cpl_tc           (cpl_tc),
        .cpl_attr         (cpl_attr),
        .cpl_req_id       (cpl_req_id),
        .cpl_tag          (cpl_tag),
        .cpl_completer_id (cfg_completer_id),
        .pld_valid        (pld_valid),
        .pld_ready        (pld_ready),
        .pld_data         (pld_data),
        .cpl_done         (cpl_done),
        .tx_tlp_data      (tx_tlp_data),
        .tx_tlp_sop       (tx_tlp_sop),
        .tx_tlp_eop       (tx_tlp_eop),
        .tx_tlp_valid     (tx_tlp_valid),
        .tx_tlp_ready     (tx_tlp_ready)
    );

endmodule
