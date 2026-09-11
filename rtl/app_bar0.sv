// ---------------------------------------------------------------------------
// app_bar0.sv
//
// Purpose : BAR0 application layer. Decodes the 14-bit BAR0 byte offset into
//           one of four 4 KiB regions, sequences 1..32 DWORD bursts, applies
//           byte enables on writes, and returns read data. Instantiates
//           reg_file, mem_a, mem_b and mem_c.
//
//   BAR0 offset[13:12] -> 00 reg_file, 01 mem_a, 10 mem_b, 11 mem_c.
//   Every DWORD of a burst is decoded independently from its own address
//   (REQ-057); anything that is not an implemented location is RAZ/WI with SC
//   status (REQ-055).
//
// Parameters: N, DW, ACCW; IDXW derived - do not override.
//
// Interface contract:
//   req_*    : one decoded BAR0 request from tlp_rx. req_ready is high only
//              in IDLE and never depends on req_valid (REQ-003).
//   req_abort: 1-cycle strobe from tlp_rx when an inbound TLP is abandoned
//              mid-payload (REQ-020). Returns this block to IDLE so a truncated
//              write burst can never deadlock the request path.
//   wdata_*  : write payload, req_len beats, ascending addresses.
//   rdata_*  : read payload, req_len beats, ascending addresses.
//   eng_*    : engine-side ports of mem_a / mem_b / mem_c and the reg_file
//              control/status handshake, brought out for matmul_top to wire to
//              matmul_engine.
//
// Latency (spec 9.6):
//   Read  : request accepted at cycle t -> first rdata beat at cycle t+2, then
//           one DWORD per cycle when not stalled.
//   Write : payload DWORD accepted at cycle t -> storage updated at cycle t+1.
//
// Implements: REQ-055 ... REQ-064, and hosts REQ-065 ... REQ-092.
// ---------------------------------------------------------------------------
module app_bar0 #(
    parameter int N    = 8,
    parameter int DW   = 8,
    parameter int ACCW = 32,
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Decoded BAR0 request (from tlp_rx)
    input  logic                req_valid,
    output logic                req_ready,
    input  logic                req_write,
    input  logic [13:0]         req_addr,
    input  logic [5:0]          req_len,
    input  logic [3:0]          req_first_be,
    input  logic [3:0]          req_last_be,
    input  logic                req_abort,

    // Write payload stream (from tlp_rx)
    input  logic                wdata_valid,
    output logic                wdata_ready,
    input  logic [31:0]         wdata,
    input  logic                wdata_last,

    // Read data stream (to tlp_tx via tlp_rx)
    output logic                rdata_valid,
    input  logic                rdata_ready,
    output logic [31:0]         rdata,
    output logic                rdata_last,

    // Error event from the transaction layer
    input  logic                ev_unsup_req,

    // matmul_engine control / status
    output logic                eng_start,
    output logic                eng_soft_reset,
    input  logic                eng_busy,
    input  logic                eng_done_set,
    input  logic [31:0]         eng_cycles,

    // matmul_engine operand ports
    input  logic [N*IDXW-1:0]   eng_ka_idx,
    input  logic [N-1:0]        eng_ka_vld,
    output logic [N*DW-1:0]     eng_a_rd,
    input  logic [N*IDXW-1:0]   eng_kb_idx,
    input  logic [N-1:0]        eng_kb_vld,
    output logic [N*DW-1:0]     eng_b_rd,
    input  logic                eng_c_wr_en,
    input  logic [IDXW-1:0]     eng_c_row,
    input  logic [N*ACCW-1:0]   eng_c_data,

    // Sideband
    output logic                irq
);

    typedef enum logic [1:0] {
        S_IDLE = 2'd0,
        S_WR   = 2'd1,
        S_RD   = 2'd2
    } state_e;

    state_e      state;
    logic [13:0] cur_addr;
    logic [5:0]  beat_cnt;
    logic [5:0]  len_r;
    logic [3:0]  fbe_r;
    logic [3:0]  lbe_r;

    logic [31:0] rd_data_r;
    logic        rd_v;
    logic        rd_last_r;

    logic [1:0]  region;
    logic [9:0]  dw_index;

    assign region   = cur_addr[13:12];
    assign dw_index = cur_addr[11:2];

    assign req_ready   = (state == S_IDLE);
    assign wdata_ready = (state == S_WR);
    assign rdata_valid = rd_v;
    assign rdata       = rd_data_r;
    assign rdata_last  = rd_last_r;

    // ---- byte enables for the current burst beat -------------------------
    logic       last_beat;
    logic [3:0] m_first;
    logic [3:0] m_last;
    logic [3:0] be_now;

    assign last_beat = (beat_cnt == (len_r - 6'd1));
    assign m_first   = (beat_cnt == 6'd0) ? fbe_r : 4'b1111;
    assign m_last    = last_beat ? ((len_r == 6'd1) ? fbe_r : lbe_r) : 4'b1111;
    assign be_now    = m_first & m_last;

    // ---- write strobes ---------------------------------------------------
    logic wr_beat;
    logic reg_wr;
    logic a_wr;
    logic b_wr;
    logic c_wr;
    logic ev_write_busy;

    assign wr_beat       = (state == S_WR) && wdata_valid;
    assign reg_wr        = wr_beat && (region == 2'b00);
    assign a_wr          = wr_beat && (region == 2'b01) && !eng_busy;
    assign b_wr          = wr_beat && (region == 2'b10) && !eng_busy;
    assign c_wr          = wr_beat && (region == 2'b11) && !eng_busy;
    assign ev_write_busy = wr_beat && (region != 2'b00) && eng_busy;

    // ---- read data mux ---------------------------------------------------
    logic [31:0] reg_rdata;
    logic [31:0] a_rdata;
    logic [31:0] b_rdata;
    logic [31:0] c_rdata;
    logic [31:0] rd_mux;

    always_comb begin
        case (region)
            2'b00:   rd_mux = reg_rdata;
            2'b01:   rd_mux = a_rdata;
            2'b10:   rd_mux = b_rdata;
            default: rd_mux = c_rdata;
        endcase
    end

    // ---- read pipeline control ------------------------------------------
    logic s1_adv;
    logic rd_issue;

    assign s1_adv   = !rd_v || rdata_ready;
    assign rd_issue = (state == S_RD) && (beat_cnt < len_r) && s1_adv;

    // ---- burst sequencer -------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            state     <= S_IDLE;
            cur_addr  <= 14'h0000;
            beat_cnt  <= 6'd0;
            len_r     <= 6'd1;
            fbe_r     <= 4'b0000;
            lbe_r     <= 4'b0000;
            rd_data_r <= 32'h0000_0000;
            rd_v      <= 1'b0;
            rd_last_r <= 1'b0;
        end else if (req_abort) begin
            state     <= S_IDLE;
            rd_v      <= 1'b0;
            rd_last_r <= 1'b0;
        end else begin
            case (state)
                S_IDLE: begin
                    if (req_valid) begin
                        cur_addr <= req_addr;
                        len_r    <= req_len;
                        fbe_r    <= req_first_be;
                        lbe_r    <= req_last_be;
                        beat_cnt <= 6'd0;
                        if (req_write) state <= S_WR;
                        else           state <= S_RD;
                    end
                end

                S_WR: begin
                    if (wdata_valid) begin
                        cur_addr <= cur_addr + 14'd4;
                        beat_cnt <= beat_cnt + 6'd1;
                        if (last_beat || wdata_last) begin
                            state <= S_IDLE;
                        end
                    end
                end

                S_RD: begin
                    if (rd_issue) begin
                        rd_data_r <= rd_mux;
                        rd_v      <= 1'b1;
                        rd_last_r <= last_beat;
                        cur_addr  <= cur_addr + 14'd4;
                        beat_cnt  <= beat_cnt + 6'd1;
                    end else if (s1_adv) begin
                        rd_v <= 1'b0;
                    end
                    if (rd_v && rd_last_r && rdata_ready) begin
                        state <= S_IDLE;
                    end
                end

                default: begin
                    state <= S_IDLE;
                end
            endcase
        end
    end

    // ---- sub-blocks ------------------------------------------------------
    reg_file #(
        .N    (N),
        .DW   (DW),
        .ACCW (ACCW)
    ) u_reg_file (
        .clk           (clk),
        .rst           (rst),
        .h_dw_addr     (dw_index),
        .h_wr          (reg_wr),
        .h_be          (be_now),
        .h_wdata       (wdata),
        .h_rdata       (reg_rdata),
        .ev_unsup_req  (ev_unsup_req),
        .ev_write_busy (ev_write_busy),
        .eng_busy      (eng_busy),
        .eng_done_set  (eng_done_set),
        .eng_cycles    (eng_cycles),
        .start         (eng_start),
        .soft_reset    (eng_soft_reset),
        .irq           (irq)
    );

    mem_a #(
        .N    (N),
        .DW   (DW),
        .IDXW (IDXW)
    ) u_mem_a (
        .clk       (clk),
        .rst       (rst),
        .h_dw_addr (dw_index),
        .h_wr      (a_wr),
        .h_be      (be_now),
        .h_wdata   (wdata),
        .h_rdata   (a_rdata),
        .e_idx     (eng_ka_idx),
        .e_vld     (eng_ka_vld),
        .e_rdata   (eng_a_rd)
    );

    mem_b #(
        .N    (N),
        .DW   (DW),
        .IDXW (IDXW)
    ) u_mem_b (
        .clk       (clk),
        .rst       (rst),
        .h_dw_addr (dw_index),
        .h_wr      (b_wr),
        .h_be      (be_now),
        .h_wdata   (wdata),
        .h_rdata   (b_rdata),
        .e_idx     (eng_kb_idx),
        .e_vld     (eng_kb_vld),
        .e_rdata   (eng_b_rd)
    );

    mem_c #(
        .N    (N),
        .ACCW (ACCW),
        .IDXW (IDXW)
    ) u_mem_c (
        .clk       (clk),
        .rst       (rst),
        .h_dw_addr (dw_index),
        .h_wr      (c_wr),
        .h_be      (be_now),
        .h_wdata   (wdata),
        .h_rdata   (c_rdata),
        .d_wr_en   (eng_c_wr_en),
        .d_row     (eng_c_row),
        .d_data    (eng_c_data)
    );

endmodule
