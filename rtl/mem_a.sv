// ---------------------------------------------------------------------------
// mem_a.sv
//
// Purpose : Storage for matrix A. N*N signed bytes, A[i][k] at byte index
//           i*N + k (BAR0 byte 0x1000 + i*N + k). Implemented as a flip-flop
//           register file, NOT an SRAM macro (DEC-010), because the systolic
//           feed schedule needs N independent byte reads per cycle.
//
// Parameters: N, DW (8 in v1), IDXW derived - do not override.
//
// Interface contract:
//   Host port  : h_dw_addr is the DWORD index inside the 4 KiB A window
//                (BAR0 offset[11:2]). h_rdata is COMBINATIONAL (app_bar0 owns the pipeline
//                register that gives the spec 9.6 t+2 read latency). h_wr is a
//                single-cycle strobe; bytes with h_be[j] = 0 are not modified.
//                Offsets >= N*N are read-as-zero / write-ignored (REQ-086).
//   Engine port: read port i returns A[i][e_idx[i]] registered, i.e. valid one
//                clock after e_idx/e_vld are applied (REQ-085). When
//                e_vld[i] = 0 the port returns 8'h00, which is what the feed
//                schedule of spec 12.4 requires outside the operand window.
//
// Latency: host read 0 cycles (combinational); host write 1 cycle; engine
//          read 1 cycle.
//
// Implements: REQ-085, REQ-086, REQ-059, REQ-060, REQ-061, REQ-111.
// ---------------------------------------------------------------------------
module mem_a #(
    parameter int N    = 8,
    parameter int DW   = 8,
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Host port (BAR0 region 0x1000-0x1FFF)
    input  logic [9:0]          h_dw_addr, // DWORD index inside the region
    input  logic                h_wr,
    input  logic [3:0]          h_be,
    input  logic [31:0]         h_wdata,
    output logic [31:0]         h_rdata,

    // Engine port: N independent byte reads per cycle
    input  logic [N*IDXW-1:0]   e_idx,
    input  logic [N-1:0]        e_vld,
    output logic [N*DW-1:0]     e_rdata
);

    localparam int NDWD    = (N*N) / 4;                       // DWORDs stored
    localparam int DWIW    = (NDWD <= 1) ? 1 : $clog2(NDWD);  // DWORD index bits
    localparam int MEMBITS = (1 << DWIW) * 32;

    logic [MEMBITS-1:0] mem;

    // ---- host access -----------------------------------------------------
    logic            h_in_range;
    logic [DWIW-1:0] h_sel;
    logic [31:0]     h_cur;
    logic [31:0]     h_new;

    assign h_in_range = (h_dw_addr < 10'(NDWD));
    assign h_sel      = h_in_range ? h_dw_addr[DWIW-1:0] : '0;
    assign h_cur      = mem[{h_sel, 5'b00000}+:32];
    assign h_rdata    = h_in_range ? h_cur : 32'h0000_0000;

    genvar gb;
    generate
        for (gb = 0; gb < 4; gb = gb + 1) begin : g_be
            assign h_new[gb*8 +: 8] = h_be[gb] ? h_wdata[gb*8 +: 8]
                                               : h_cur[gb*8 +: 8];
        end
    endgenerate

    always_ff @(posedge clk) begin
        if (rst) begin
            mem <= '0;
        end else if (h_wr && h_in_range) begin
            mem[{h_sel, 5'b00000}+:32] <= h_new;
        end
    end

    // ---- engine read ports ----------------------------------------------
    localparam int BOW = $clog2(MEMBITS);   // bit-offset width into mem

    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : g_rd
            logic [BOW-1:0] boff;
            logic [DW-1:0]  byte_sel;
            // byte index (gi*N + e_idx[gi]) -> bit offset * 8
            assign boff     = BOW'(gi*N*8) + (BOW'(e_idx[gi*IDXW +: IDXW]) << 3);
            assign byte_sel = mem[boff +: 8];

            always_ff @(posedge clk) begin
                if (rst) begin
                    e_rdata[gi*DW +: DW] <= '0;
                end else begin
                    e_rdata[gi*DW +: DW] <= e_vld[gi] ? byte_sel : {DW{1'b0}};
                end
            end
        end
    endgenerate

endmodule
