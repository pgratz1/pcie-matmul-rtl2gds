// ---------------------------------------------------------------------------
// mm_pe.sv
//
// Purpose : Output-stationary systolic processing element. Owns the 32-bit
//           accumulator for exactly one element of C. Forwards the 8-bit A
//           operand east and the 8-bit B operand south, both with exactly one
//           cycle of latency, together with a 1-bit valid that travels east.
//
// Parameters:
//   DW    - operand width in bits (8 in v1)
//   ACCW  - accumulator width in bits (32 in v1)
//
// Interface contract:
//   clr_acc : synchronous accumulator clear, highest priority after rst.
//   drain   : when 1 the accumulator loads acc_in (north neighbour's acc),
//             and no multiply-accumulate happens (REQ-100).
//   a_in/b_in/v_in : operands and valid for THIS cycle. The MAC uses the
//             *inputs*, not the registered copies, so PE(i,j) accumulates
//             operand index k = t-i-j (see mm_array header).
//   a_out/b_out/v_out : registered copies of a_in/b_in/v_in.
//   acc_out : current accumulator value (registered).
//
// Latency: 1 cycle. This is a single pipeline stage and is FIXED by DEC-009 /
//          spec 12.3 because the 4N+2 cycle count (REQ-101/102) depends on it.
//
// Implements: REQ-093, REQ-094, REQ-095, REQ-100, REQ-105, REQ-106, REQ-108.
// ---------------------------------------------------------------------------
module mm_pe #(
    parameter int DW   = 8,
    parameter int ACCW = 32
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,       // active-high, synchronous

    // Control
    input  logic                clr_acc,   // clear accumulator this cycle
    input  logic                drain,     // shift phase: acc <= acc_in

    // Operand inputs
    input  logic [DW-1:0]       a_in,      // from west
    input  logic [DW-1:0]       b_in,      // from north
    input  logic                v_in,      // from west
    input  logic [ACCW-1:0]     acc_in,    // from north (drain chain)

    // Operand outputs
    output logic [DW-1:0]       a_out,     // to east
    output logic [DW-1:0]       b_out,     // to south
    output logic                v_out,     // to east
    output logic [ACCW-1:0]     acc_out    // to south / to drain bus
);

    logic [DW-1:0]           a_reg;
    logic [DW-1:0]           b_reg;
    logic                    v_reg;
    logic [ACCW-1:0]         acc_reg;

    logic signed [2*DW-1:0]  prod;
    logic        [ACCW-1:0]  prod_ext;

    assign prod     = $signed(a_in) * $signed(b_in);
    assign prod_ext = {{(ACCW-2*DW){prod[2*DW-1]}}, prod};

    always_ff @(posedge clk) begin
        if (rst) begin
            a_reg   <= '0;
            b_reg   <= '0;
            v_reg   <= 1'b0;
            acc_reg <= '0;
        end else begin
            a_reg <= a_in;
            b_reg <= b_in;
            v_reg <= v_in;
            if (clr_acc) begin
                acc_reg <= '0;
            end else if (drain) begin
                acc_reg <= acc_in;
            end else if (v_in) begin
                acc_reg <= acc_reg + prod_ext;
            end
        end
    end

    assign a_out   = a_reg;
    assign b_out   = b_reg;
    assign v_out   = v_reg;
    assign acc_out = acc_reg;

endmodule
