// ---------------------------------------------------------------------------
// mm_ctrl.sv
//
// Purpose : Sequencer for one C = A x B operation. Owns the operand-address
//           generator for mem_a / mem_b, the array phase controls, the drain
//           write sequence into mem_c, the busy/done handshake and the
//           performance cycle counter.
//
// Parameters:
//   N     - array dimension (power of two, 2..32)
//
// Interface contract:
//   start        - 1-cycle strobe from reg_file (already gated on !busy).
//   soft_reset   - 1-cycle strobe from reg_file; returns the FSM to IDLE and
//                  clears the accumulators and the cycle counter.
//   busy         - 1 from the cycle after start is accepted through the cycle
//                  on which done_set is observed (REQ-074, REQ-103).
//   done_set     - 1 for exactly one cycle, on the final DRAIN cycle, so that
//                  reg_file's STATUS.DONE register reads 1 during the FINISH
//                  cycle, i.e. exactly 4N+2 cycles after start (REQ-101).
//   cycle_count  - value to latch into PERF_CYCLES on done_set; equals 4N+2.
//   ka_idx/ka_vld, kb_idx/kb_vld - operand indices issued one cycle ahead of
//                  the compute cycle that consumes them (mem_* read latency
//                  is 1 cycle, REQ-085/REQ-087).
//   v_west       - registered copy of ka_vld, aligned with the mem_a data.
//   c_wr_en/c_wr_row - drain write strobe and destination row of mem_c.
//
// State sequence and duration (spec 12.5):
//   IDLE -> PRIME(1) -> FETCH(1) -> COMPUTE(3N-2) -> TURN(1) -> DRAIN(N)
//        -> FINISH(1) -> IDLE.  Total 4N+2 cycles.
//
// NOTE ON SPEC INTERPRETATION: spec 12.5 puts "issue the first mem_a/mem_b read
//   indices" in PRIME. Issuing there would make the first operand pair arrive
//   at the array edge one cycle before COMPUTE t=0 and be accumulated twice.
//   The first indices are therefore issued in FETCH, which is the cycle whose
//   stated job is "absorb the 1-cycle mem read latency; first operands arrive
//   at the array edge". Externally visible behaviour (4N+2 cycles, value of C)
//   is unchanged.
//
// Latency: 4N+2 cycles from start to done_set + 1.
//
// Implements: REQ-069, REQ-071, REQ-074, REQ-082, REQ-095, REQ-096, REQ-098,
//             REQ-099, REQ-101, REQ-102, REQ-103, REQ-104.
// ---------------------------------------------------------------------------
module mm_ctrl #(
    parameter int N    = 8,
    parameter int IDXW = (N <= 2) ? 1 : $clog2(N)
) (
    // Clock and reset
    input  logic                clk,
    input  logic                rst,

    // Control from reg_file
    input  logic                start,
    input  logic                soft_reset,

    // Status to reg_file
    output logic                busy,
    output logic                done_set,
    output logic [31:0]         cycle_count,

    // Operand address generation (to mem_a / mem_b)
    output logic [N*IDXW-1:0]   ka_idx,
    output logic [N-1:0]        ka_vld,
    output logic [N*IDXW-1:0]   kb_idx,
    output logic [N-1:0]        kb_vld,

    // Array control
    output logic                clr_acc,
    output logic                drain,
    output logic [N-1:0]        v_west,

    // mem_c drain write
    output logic                c_wr_en,
    output logic [IDXW-1:0]     c_wr_row
);

    // Counter widths -------------------------------------------------------
    localparam int FTW  = $clog2(3*N + 2) + 1;   // operand-index time counter
    localparam int CMPW = $clog2(3*N + 1) + 1;   // compute-phase counter
    localparam int CYCW = $clog2(4*N + 4) + 1;   // performance counter

    typedef enum logic [2:0] {
        ST_IDLE    = 3'd0,
        ST_PRIME   = 3'd1,
        ST_FETCH   = 3'd2,
        ST_COMPUTE = 3'd3,
        ST_TURN    = 3'd4,
        ST_DRAIN   = 3'd5,
        ST_FINISH  = 3'd6
    } state_e;

    state_e             state;
    logic [FTW-1:0]     feed_t;
    logic [CMPW-1:0]    cmp_cnt;
    logic [IDXW-1:0]    drn_cnt;
    logic [CYCW-1:0]    cyc_cnt;

    logic               feed_active;
    logic               cmp_last;
    logic               drn_last;

    assign feed_active = (state == ST_FETCH) || (state == ST_COMPUTE);
    assign cmp_last    = (cmp_cnt == CMPW'(3*N - 3));
    assign drn_last    = (drn_cnt == IDXW'(N - 1));

    // ---------------------------------------------------------------------
    // State machine
    // ---------------------------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            state   <= ST_IDLE;
            cmp_cnt <= '0;
            drn_cnt <= '0;
            feed_t  <= '0;
            cyc_cnt <= '0;
        end else if (soft_reset) begin
            state   <= ST_IDLE;
            cmp_cnt <= '0;
            drn_cnt <= '0;
            feed_t  <= '0;
            cyc_cnt <= '0;
        end else begin
            // Operand index time base.
            if (state == ST_PRIME) begin
                feed_t <= '0;
            end else if (feed_active) begin
                feed_t <= feed_t + FTW'(1);
            end

            // Elapsed-cycle counter: during cycle t_start+k, cyc_cnt == k.
            if (state == ST_IDLE) begin
                cyc_cnt <= start ? CYCW'(1) : '0;
            end else begin
                cyc_cnt <= cyc_cnt + CYCW'(1);
            end

            case (state)
                ST_IDLE: begin
                    cmp_cnt <= '0;
                    drn_cnt <= '0;
                    if (start) begin
                        state <= ST_PRIME;
                    end
                end
                ST_PRIME: begin
                    state <= ST_FETCH;
                end
                ST_FETCH: begin
                    state   <= ST_COMPUTE;
                    cmp_cnt <= '0;
                end
                ST_COMPUTE: begin
                    if (cmp_last) begin
                        state <= ST_TURN;
                    end else begin
                        cmp_cnt <= cmp_cnt + CMPW'(1);
                    end
                end
                ST_TURN: begin
                    state   <= ST_DRAIN;
                    drn_cnt <= '0;
                end
                ST_DRAIN: begin
                    if (drn_last) begin
                        state <= ST_FINISH;
                    end else begin
                        drn_cnt <= drn_cnt + IDXW'(1);
                    end
                end
                ST_FINISH: begin
                    state <= ST_IDLE;
                end
                default: begin
                    state <= ST_IDLE;
                end
            endcase
        end
    end

    // ---------------------------------------------------------------------
    // Operand index generation.  Row i needs A[i][feed_t - i]; column j needs
    // B[feed_t - j][j].  Out of range -> invalid, and mem_* drives 8'h00.
    // ---------------------------------------------------------------------
    genvar gi;
    generate
        for (gi = 0; gi < N; gi = gi + 1) begin : g_feed
            logic [FTW-1:0] diff;
            // diff wraps to a value > 3N-2 when feed_t < gi (FTW is sized so
            // that 2**FTW >= 6N+4), so "diff < N" alone is the window test.
            assign diff       = feed_t - FTW'(gi);
            assign ka_vld[gi] = feed_active && (diff < FTW'(N));
            assign kb_vld[gi] = ka_vld[gi];
            assign ka_idx[gi*IDXW +: IDXW] = diff[IDXW-1:0];
            assign kb_idx[gi*IDXW +: IDXW] = diff[IDXW-1:0];
        end
    endgenerate

    // v_west is the valid vector delayed by one cycle so that it lines up with
    // the registered mem_a read data.
    always_ff @(posedge clk) begin
        if (rst) begin
            v_west <= '0;
        end else if (soft_reset) begin
            v_west <= '0;
        end else begin
            v_west <= ka_vld;
        end
    end

    // ---------------------------------------------------------------------
    // Array and mem_c controls
    // ---------------------------------------------------------------------
    assign clr_acc     = (state == ST_PRIME) || soft_reset;
    assign drain       = (state == ST_DRAIN);
    assign c_wr_en     = (state == ST_DRAIN);
    assign c_wr_row    = IDXW'(N - 1) - drn_cnt;

    assign busy        = (state != ST_IDLE);
    assign done_set    = (state == ST_DRAIN) && drn_last;
    assign cycle_count = 32'(cyc_cnt + CYCW'(1));

endmodule
