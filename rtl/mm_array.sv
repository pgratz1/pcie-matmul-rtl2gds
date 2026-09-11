// ---------------------------------------------------------------------------
// mm_array.sv
//
// Purpose : N x N mesh of mm_pe. A and the valid bit flow west -> east,
//           B flows north -> south, accumulators shift north -> south during
//           the drain phase only.
//
// Parameters:
//   N     - array dimension (power of two, 2..32)
//   DW    - operand width in bits
//   ACCW  - accumulator width in bits
//
// Interface contract (spec 12.4):
//   Let t = 0 be the first COMPUTE cycle.
//     a_west[i] at cycle t = A[i][t-i], v_west[i] = (0 <= t-i < N),
//     a_west[i] driven to 0 when v_west[i] = 0.
//     b_north[j] at cycle t = B[t-j][j], driven to 0 when t-j is out of range.
//   With that skew PE(i,j) sees operand index k = t-i-j on both inputs and its
//   v_in (which travelled j hops east) is exactly (0 <= t-i-j < N), so a single
//   valid bit propagating east is sufficient.
//
//   drain   : during drain cycle m, acc_south[j] carries acc(N-1-m, j).
//   clr_acc : clears every accumulator.
//
// Latency: compute phase is exactly 3N-2 cycles (t = 0 .. 3N-3); drain phase
//          is exactly N cycles.
//
// Implements: REQ-096, REQ-097, REQ-098, REQ-099, REQ-100.
// ---------------------------------------------------------------------------
module mm_array #(
    parameter int N    = 8,
    parameter int DW   = 8,
    parameter int ACCW = 32
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Control (broadcast to every PE)
    input  logic                clr_acc,
    input  logic                drain,

    // West edge: one operand byte + valid per row
    input  logic [N*DW-1:0]     a_west_flat,
    input  logic [N-1:0]        v_west,

    // North edge: one operand byte per column
    input  logic [N*DW-1:0]     b_north_flat,

    // South edge: bottom-row accumulator bus (drain)
    output logic [N*ACCW-1:0]   acc_south_flat
);

    // Per-PE registered outputs, flattened as index (i*N + j).
    // The east column's a_out/v_out and the south row's b_out leave the mesh and
    // have no consumer by construction of the dataflow (spec 12.4): A and the
    // valid bit exit to the east, B exits to the south, and only the south
    // accumulator bus is read. Suppressed at the declarations rather than sunk
    // in a reduction-OR, which would synthesise a dead cone of N*N*(2*DW+1)
    // bits (4608 at N = 8, 73728 at N = 32).
    // verilator lint_off UNUSEDSIGNAL
    logic [N*N*DW-1:0]   a_o;
    logic [N*N*DW-1:0]   b_o;
    logic [N*N-1:0]      v_o;
    // verilator lint_on UNUSEDSIGNAL
    logic [N*N*ACCW-1:0] acc_o;

    genvar gi, gj;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : g_row
            for (gj = 0; gj < N; gj = gj + 1) begin : g_col

                logic [DW-1:0]   pe_a_in;
                logic [DW-1:0]   pe_b_in;
                logic            pe_v_in;
                logic [ACCW-1:0] pe_acc_in;

                if (gj == 0) begin : g_a_edge
                    assign pe_a_in = a_west_flat[gi*DW +: DW];
                    assign pe_v_in = v_west[gi];
                end else begin : g_a_chain
                    assign pe_a_in = a_o[(gi*N + gj - 1)*DW +: DW];
                    assign pe_v_in = v_o[gi*N + gj - 1];
                end

                if (gi == 0) begin : g_b_edge
                    assign pe_b_in   = b_north_flat[gj*DW +: DW];
                    assign pe_acc_in = '0;
                end else begin : g_b_chain
                    assign pe_b_in   = b_o[((gi-1)*N + gj)*DW +: DW];
                    assign pe_acc_in = acc_o[((gi-1)*N + gj)*ACCW +: ACCW];
                end

                mm_pe #(
                    .DW   (DW),
                    .ACCW (ACCW)
                ) u_pe (
                    .clk     (clk),
                    .rst     (rst),
                    .clr_acc (clr_acc),
                    .drain   (drain),
                    .a_in    (pe_a_in),
                    .b_in    (pe_b_in),
                    .v_in    (pe_v_in),
                    .acc_in  (pe_acc_in),
                    .a_out   (a_o[(gi*N + gj)*DW +: DW]),
                    .b_out   (b_o[(gi*N + gj)*DW +: DW]),
                    .v_out   (v_o[gi*N + gj]),
                    .acc_out (acc_o[(gi*N + gj)*ACCW +: ACCW])
                );
            end
        end

        for (gj = 0; gj < N; gj = gj + 1) begin : g_south
            assign acc_south_flat[gj*ACCW +: ACCW] =
                       acc_o[((N-1)*N + gj)*ACCW +: ACCW];
        end
    endgenerate

endmodule
