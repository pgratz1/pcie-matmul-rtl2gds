// ---------------------------------------------------------------------------
// matmul_engine.sv
//
// Purpose : Container for mm_ctrl and mm_array. Presents the start/soft_reset
//           inputs and busy/done/cycle_count status to reg_file, the operand
//           read indices to mem_a / mem_b, and the drain write bus to mem_c.
//           Contains no logic of its own beyond instantiation and wiring.
//
// Parameters: N, DW, ACCW (see spec section 14). IDXW is derived; do not
//             override it.
//
// Interface contract:
//   start / soft_reset are 1-cycle strobes from reg_file.
//   a_rd / b_rd arrive one cycle after ka_idx / kb_idx are issued.
//   c_wr_en/c_wr_row/c_wr_data write one complete row of C per cycle.
//
// Latency: 4N+2 cycles from start to the cycle on which STATUS.DONE reads 1.
//
// Implements: spec section 12.1.
// ---------------------------------------------------------------------------
module matmul_engine #(
    parameter int N    = 8,
    parameter int DW   = 8,
    parameter int ACCW = 32,
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Control / status (reg_file)
    input  logic                start,
    input  logic                soft_reset,
    output logic                busy,
    output logic                done_set,
    output logic [31:0]         cycle_count,

    // mem_a engine read port
    output logic [N*IDXW-1:0]   ka_idx,
    output logic [N-1:0]        ka_vld,
    input  logic [N*DW-1:0]     a_rd,

    // mem_b engine read port
    output logic [N*IDXW-1:0]   kb_idx,
    output logic [N-1:0]        kb_vld,
    input  logic [N*DW-1:0]     b_rd,

    // mem_c drain write port
    output logic                c_wr_en,
    output logic [IDXW-1:0]     c_wr_row,
    output logic [N*ACCW-1:0]   c_wr_data
);

    logic             clr_acc;
    logic             drain;
    logic [N-1:0]     v_west;

    mm_ctrl #(
        .N    (N),
        .IDXW (IDXW)
    ) u_ctrl (
        .clk         (clk),
        .rst         (rst),
        .start       (start),
        .soft_reset  (soft_reset),
        .busy        (busy),
        .done_set    (done_set),
        .cycle_count (cycle_count),
        .ka_idx      (ka_idx),
        .ka_vld      (ka_vld),
        .kb_idx      (kb_idx),
        .kb_vld      (kb_vld),
        .clr_acc     (clr_acc),
        .drain       (drain),
        .v_west      (v_west),
        .c_wr_en     (c_wr_en),
        .c_wr_row    (c_wr_row)
    );

    mm_array #(
        .N    (N),
        .DW   (DW),
        .ACCW (ACCW)
    ) u_array (
        .clk            (clk),
        .rst            (rst),
        .clr_acc        (clr_acc),
        .drain          (drain),
        .a_west_flat    (a_rd),
        .v_west         (v_west),
        .b_north_flat   (b_rd),
        .acc_south_flat (c_wr_data)
    );

endmodule
