// ---------------------------------------------------------------------------
// reg_file.sv
//
// Purpose : BAR0 control/status register block, offsets 0x0000-0x0FFF.
//           Implements ID, VERSION, CONFIG, CTRL, STATUS, IRQ_ENABLE,
//           IRQ_STATUS, PERF_CYCLES, SCRATCH, OP_COUNT exactly as
//           docs/register-map.md v1.0.0 defines them. Everything else in the
//           4 KiB window is RAZ/WI.
//
// Parameters: N, DW, ACCW - reported through CONFIG (REQ-067, REQ-114).
//
// Interface contract:
//   h_dw_addr : DWORD index inside the register window (BAR0 offset[11:2]).
//   h_rd_data : COMBINATIONAL read of the addressed register.
//   h_wr      : single-cycle write strobe; h_be selects bytes.
//   ev_unsup_req / ev_write_busy : single-cycle event pulses from tlp_rx and
//               app_bar0 that set the corresponding W1C STATUS bits. A set
//               always beats a simultaneous W1C clear (REQ-077).
//   eng_busy / eng_done_set / eng_cycles : from matmul_engine. eng_done_set is
//               a 1-cycle pulse on the last DRAIN cycle so that STATUS.DONE
//               reads 1 exactly 4N+2 cycles after CTRL.START was accepted.
//   start / soft_reset : 1-cycle strobes to matmul_engine, produced
//               combinationally from the CTRL write so that the engine leaves
//               IDLE on the same clock edge that accepts the write.
//   irq       : registered, level sensitive; 1 iff STATUS & IRQ_ENABLE != 0.
//
// Latency: register write visible on the next cycle; read is combinational.
//          irq follows IRQ_STATUS with one cycle of latency (REQ-081 allows 2).
//
// Implements: REQ-012, REQ-064, REQ-065 ... REQ-084, REQ-101 ... REQ-104,
//             REQ-111, REQ-114.
// ---------------------------------------------------------------------------
module reg_file #(
    parameter int N    = 8,
    parameter int DW   = 8,
    parameter int ACCW = 32
) (
    // Clock and reset
    input  logic         clk,
    input  logic         rst,

    // Host DWORD port (BAR0 region 0x0000-0x0FFF)
    input  logic [9:0]   h_dw_addr,
    input  logic         h_wr,
    input  logic [3:0]   h_be,
    input  logic [31:0]  h_wdata,
    output logic [31:0]  h_rdata,

    // Error event pulses
    input  logic         ev_unsup_req,
    input  logic         ev_write_busy,

    // matmul_engine status
    input  logic         eng_busy,
    input  logic         eng_done_set,
    input  logic [31:0]  eng_cycles,

    // matmul_engine control
    output logic         start,
    output logic         soft_reset,

    // Sideband
    output logic         irq
);

    // Register DWORD indices (BAR0 offset >> 2)
    localparam logic [9:0] A_ID          = 10'h000;
    localparam logic [9:0] A_VERSION     = 10'h001;
    localparam logic [9:0] A_CONFIG      = 10'h002;
    localparam logic [9:0] A_CTRL        = 10'h003;
    localparam logic [9:0] A_STATUS      = 10'h004;
    localparam logic [9:0] A_IRQ_ENABLE  = 10'h005;
    localparam logic [9:0] A_IRQ_STATUS  = 10'h006;
    localparam logic [9:0] A_PERF_CYCLES = 10'h007;
    localparam logic [9:0] A_SCRATCH     = 10'h008;
    localparam logic [9:0] A_OP_COUNT    = 10'h009;

    // ---- state ----------------------------------------------------------
    logic        st_done;
    logic        st_err_start_busy;
    logic        st_err_write_busy;
    logic        st_err_unsup_req;
    logic [4:1]  irq_en;
    logic [31:0] perf_cycles;
    logic [31:0] scratch;
    logic [31:0] op_count;

    logic [31:0] status_val;
    logic [31:0] irq_en_val;
    logic [31:0] irq_status_val;

    assign status_val = {27'b0, st_err_unsup_req, st_err_write_busy,
                         st_err_start_busy, st_done, eng_busy};
    assign irq_en_val = {27'b0, irq_en, 1'b0};
    assign irq_status_val = status_val & irq_en_val;

    // ---- write decode ----------------------------------------------------
    logic wr_ctrl;
    logic wr_status;
    logic wr_irq_en;
    logic wr_scratch;
    logic ctrl_b0;

    assign wr_ctrl    = h_wr && (h_dw_addr == A_CTRL);
    assign wr_status  = h_wr && (h_dw_addr == A_STATUS);
    assign wr_irq_en  = h_wr && (h_dw_addr == A_IRQ_ENABLE);
    assign wr_scratch = h_wr && (h_dw_addr == A_SCRATCH);
    assign ctrl_b0    = wr_ctrl && h_be[0];

    // CTRL.SOFT_RESET (bit 1) takes precedence over CTRL.START (bit 0).
    assign soft_reset = ctrl_b0 && h_wdata[1];
    assign start      = ctrl_b0 && h_wdata[0] && !h_wdata[1] && !eng_busy;

    logic start_while_busy;
    assign start_while_busy = ctrl_b0 && h_wdata[0] && !h_wdata[1] && eng_busy;

    // STATUS is W1C and every implemented bit lives in byte 0.
    logic       clr_en;
    logic [4:1] clr_bits;
    assign clr_en   = wr_status && h_be[0];
    assign clr_bits = h_wdata[4:1];

    // ---- registers -------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            st_done           <= 1'b0;
            st_err_start_busy <= 1'b0;
            st_err_write_busy <= 1'b0;
            st_err_unsup_req  <= 1'b0;
            irq_en            <= '0;
            perf_cycles       <= 32'h0000_0000;
            scratch           <= 32'h0000_0000;
            op_count          <= 32'h0000_0000;
            irq               <= 1'b0;
        end else begin
            // ---- STATUS.DONE (W1C, set wins) ----
            if (soft_reset)            st_done <= 1'b0;
            else if (eng_done_set)     st_done <= 1'b1;
            else if (start)            st_done <= 1'b0;   // REQ-069
            else if (clr_en && clr_bits[1]) st_done <= 1'b0;

            // ---- STATUS.ERR_START_BUSY (W1C, set wins) ----
            if (soft_reset)            st_err_start_busy <= 1'b0;
            else if (start_while_busy) st_err_start_busy <= 1'b1;
            else if (clr_en && clr_bits[2]) st_err_start_busy <= 1'b0;

            // ---- STATUS.ERR_WRITE_BUSY (W1C, set wins) ----
            if (soft_reset)            st_err_write_busy <= 1'b0;
            else if (ev_write_busy)    st_err_write_busy <= 1'b1;
            else if (clr_en && clr_bits[3]) st_err_write_busy <= 1'b0;

            // ---- STATUS.ERR_UNSUP_REQ (W1C, set wins) ----
            if (soft_reset)            st_err_unsup_req <= 1'b0;
            else if (ev_unsup_req)     st_err_unsup_req <= 1'b1;
            else if (clr_en && clr_bits[4]) st_err_unsup_req <= 1'b0;

            // ---- IRQ_ENABLE (RW, bits 4:1 only, byte 0) ----
            if (wr_irq_en && h_be[0]) begin
                irq_en <= h_wdata[4:1];
            end

            // ---- PERF_CYCLES (RO, latched on completion) ----
            if (soft_reset)            perf_cycles <= 32'h0000_0000;
            else if (eng_done_set)     perf_cycles <= eng_cycles;

            // ---- OP_COUNT (RO, not cleared by SOFT_RESET) ----
            if (eng_done_set)          op_count <= op_count + 32'd1;

            // ---- SCRATCH (RW, byte granular, unaffected by SOFT_RESET) ----
            if (wr_scratch) begin
                if (h_be[0]) scratch[7:0]   <= h_wdata[7:0];
                if (h_be[1]) scratch[15:8]  <= h_wdata[15:8];
                if (h_be[2]) scratch[23:16] <= h_wdata[23:16];
                if (h_be[3]) scratch[31:24] <= h_wdata[31:24];
            end

            // ---- irq ----
            irq <= |irq_status_val;
        end
    end

    // ---- read mux (combinational) ---------------------------------------
    always_comb begin
        case (h_dw_addr)
            A_ID:          h_rdata = 32'h4D41_5431;                      // "MAT1"
            A_VERSION:     h_rdata = 32'h0001_0000;
            A_CONFIG:      h_rdata = {8'h00, 8'(ACCW), 8'(DW), 8'(N)};
            A_CTRL:        h_rdata = 32'h0000_0000;                      // WO
            A_STATUS:      h_rdata = status_val;
            A_IRQ_ENABLE:  h_rdata = irq_en_val;
            A_IRQ_STATUS:  h_rdata = irq_status_val;
            A_PERF_CYCLES: h_rdata = perf_cycles;
            A_SCRATCH:     h_rdata = scratch;
            A_OP_COUNT:    h_rdata = op_count;
            default:       h_rdata = 32'h0000_0000;                      // RAZ/WI
        endcase
    end

endmodule
