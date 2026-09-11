// ---------------------------------------------------------------------------
// mem_c.sv
//
// Purpose : Storage for matrix C. N*N signed 32-bit words, C[i][j] at word
//           index i*N + j (BAR0 DWORD 0x3000 + 4*(i*N + j)). Flip-flop
//           register file, not an SRAM macro (DEC-010). Kept separate from the
//           PE accumulators (DEC-012) so the host read path never reaches into
//           the array.
//
// Parameters: N, ACCW (32 in v1), IDXW derived - do not override.
//
// Interface contract:
//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB C window.
//                h_rdata is COMBINATIONAL. h_wr is a single-cycle strobe with
//                byte enables. Indices >= N*N are RAZ/WI (REQ-091).
//   Drain port : d_wr_en writes one COMPLETE ROW of C per cycle: word indices
//                d_row*N + j for j = 0..N-1, taken from d_data lane j
//                (REQ-089). The drain port has priority over the host port;
//                host writes to C are discarded while BUSY anyway (REQ-062).
//
// Latency: host read 0 cycles (combinational); writes take effect 1 cycle
//          after the strobe.
//
// Implements: REQ-089, REQ-090, REQ-091, REQ-092.
// ---------------------------------------------------------------------------
module mem_c #(
    parameter int N    = 8,
    parameter int ACCW = 32,
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Host port (BAR0 region 0x3000-0x3FFF)
    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
    input  logic                h_wr,
    input  logic [3:0]          h_be,
    input  logic [31:0]         h_wdata,
    output logic [31:0]         h_rdata,

    // Drain port from matmul_engine: one row of C per cycle
    input  logic                d_wr_en,
    input  logic [IDXW-1:0]     d_row,
    input  logic [N*ACCW-1:0]   d_data
);

    localparam int NW      = N * N;                     // 32-bit words stored
    localparam int WIW     = (NW <= 1) ? 1 : $clog2(NW);
    localparam int MEMBITS = (1 << WIW) * ACCW;
    localparam int BOW     = $clog2(MEMBITS);

    logic [MEMBITS-1:0] mem;

    // ---- host access -----------------------------------------------------
    logic            h_in_range;
    logic [WIW-1:0]  h_sel;
    logic [BOW-1:0]  h_boff;
    logic [31:0]     h_cur;
    logic [31:0]     h_new;

    // 11-bit compare: NW reaches 1024 at N = 32, which does not fit in the
    // 10-bit DWORD index type.
    assign h_in_range = ({1'b0, h_dw_addr} < 11'(NW));
    assign h_sel      = h_in_range ? h_dw_addr[WIW-1:0] : '0;
    assign h_boff     = BOW'(h_sel) * BOW'(ACCW);
    assign h_cur      = mem[h_boff +: 32];
    assign h_rdata    = h_in_range ? h_cur : 32'h0000_0000;

    genvar gb;
    generate
        for (gb = 0; gb < 4; gb = gb + 1) begin : g_be
            assign h_new[gb*8 +: 8] = h_be[gb] ? h_wdata[gb*8 +: 8]
                                               : h_cur[gb*8 +: 8];
        end
    endgenerate

    // ---- drain row write -------------------------------------------------
    // Rows of N words in mem. This is an EXACT tiling -- NROW fills of N*ACCW
    // bits cover MEMBITS with no gap and no overlap -- only because N is a power
    // of two (spec section 14 requires that, so NW = N*N and 1<<WIW are the same
    // number). A non-power-of-two N would leave the tail of mem unreset, and
    // neither lint nor a reset test would catch it.
    localparam int NROW = (1 << WIW) / N;

    integer         ri;
    logic [BOW-1:0] d_boff;
    assign d_boff = BOW'(d_row) * BOW'(N * ACCW);

    always_ff @(posedge clk) begin
        if (rst) begin
            // Reset one row of N words at a time. A single MEMBITS-wide '0 fill
            // is 32768 bits at N = 32, which trips Verilator's WIDTHCONCAT
            // "more than 8k bit replication" heuristic; each row fill is
            // N*ACCW bits. The loop bound is static, so this unrolls to the
            // same flop reset (REQ-092) with no extra logic.
            for (ri = 0; ri < NROW; ri = ri + 1) begin
                mem[ri[BOW-1:0] * BOW'(N * ACCW) +: N*ACCW] <= '0;
            end
        end else if (d_wr_en) begin
            mem[d_boff +: N*ACCW] <= d_data;
        end else if (h_wr && h_in_range) begin
            mem[h_boff +: 32] <= h_new;
        end
    end

endmodule
