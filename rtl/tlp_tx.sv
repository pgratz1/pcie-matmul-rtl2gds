// ---------------------------------------------------------------------------
// tlp_tx.sv
//
// Purpose : Build and transmit Cpl / CplD TLPs on the outbound 32-bit DWORD
//           stream. Emits the three header DWORDs in PCIe wire (big-endian)
//           order per spec 7.2.4, then cpl_len payload DWORDs taken verbatim
//           from the payload port (which is already in host/little-endian
//           order, spec 5.3).
//
// Parameters: none.
//
// Interface contract:
//   cpl_req_valid/ready : one completion descriptor. cpl_req_ready is high
//                         only in IDLE and never depends on cpl_req_valid.
//   cpl_with_data       : 1 = CplD (Fmt 010), 0 = Cpl (Fmt 000).
//   cpl_len             : payload DWORD count, 1..32 (ignored when
//                         cpl_with_data = 0; the Length field is then 0).
//   pld_*               : payload DWORD stream, exactly cpl_len beats.
//   cpl_done            : 1-cycle pulse on the transfer of the eop beat; used
//                         by tlp_rx to enforce one completion in flight
//                         (REQ-014).
//   tx_tlp_*            : chip-boundary stream. valid/sop/eop are forced to 0
//                         while rst is asserted (REQ-006). Once asserted,
//                         valid/data/sop/eop are held until the beat transfers
//                         (REQ-001): the header DWORDs come from registers and
//                         the payload source (app_bar0) holds its own outputs.
//
// Latency: cpl_req accepted at cycle t -> header DW0 presented at cycle t+1,
//          then one DWORD per cycle when tx_tlp_ready is high.
//
// Implements: REQ-006, REQ-007, REQ-023 ... REQ-027, REQ-031, REQ-033 ...
//             REQ-035, REQ-009.
// ---------------------------------------------------------------------------
module tlp_tx (
    // Clock and reset
    input  logic         clk,
    input  logic         rst,

    // Completion descriptor (from tlp_rx)
    input  logic         cpl_req_valid,
    output logic         cpl_req_ready,
    input  logic         cpl_with_data,
    input  logic [5:0]   cpl_len,
    input  logic [11:0]  cpl_byte_count,
    input  logic [6:0]   cpl_lower_addr,
    input  logic [2:0]   cpl_status,
    input  logic [2:0]   cpl_tc,
    input  logic [2:0]   cpl_attr,
    input  logic [15:0]  cpl_req_id,
    input  logic [7:0]   cpl_tag,
    input  logic [15:0]  cpl_completer_id,

    // Completion payload stream (from tlp_rx)
    input  logic         pld_valid,
    output logic         pld_ready,
    input  logic [31:0]  pld_data,

    // Completion retired
    output logic         cpl_done,

    // Outbound TLP stream (chip boundary)
    output logic [31:0]  tx_tlp_data,
    output logic         tx_tlp_sop,
    output logic         tx_tlp_eop,
    output logic         tx_tlp_valid,
    input  logic         tx_tlp_ready
);

    typedef enum logic [2:0] {
        T_IDLE = 3'd0,
        T_DW0  = 3'd1,
        T_DW1  = 3'd2,
        T_DW2  = 3'd3,
        T_PLD  = 3'd4
    } state_e;

    state_e      state;

    logic        wd_r;
    logic [5:0]  len_r;
    logic [11:0] bc_r;
    logic [6:0]  la_r;
    logic [2:0]  st_r;
    logic [2:0]  tc_r;
    logic [2:0]  attr_r;
    logic [15:0] rid_r;
    logic [7:0]  tag_r;
    logic [15:0] cid_r;
    logic [5:0]  pld_cnt;

    logic [31:0] hdr_dw0;
    logic [31:0] hdr_dw1;
    logic [31:0] hdr_dw2;
    logic [9:0]  len_field;
    logic        pld_last;
    logic        beat_go;

    // DW0: Fmt[31:29] Type[28:24] T9[23] TC[22:20] T8[19] Attr2[18] LN[17]
    //      TH[16] TD[15] EP[14] Attr[13:12] AT[11:10] Length[9:0]
    assign len_field = wd_r ? {4'b0000, len_r} : 10'd0;
    assign hdr_dw0   = {wd_r ? 3'b010 : 3'b000,  // Fmt
                        5'b01010,                // Type = Completion
                        1'b0,                    // T9
                        tc_r,                    // TC
                        1'b0,                    // T8
                        attr_r[2],               // Attr[2] (IDO)
                        1'b0,                    // LN
                        1'b0,                    // TH
                        1'b0,                    // TD
                        1'b0,                    // EP
                        attr_r[1:0],             // Attr[1:0] (RO, NS)
                        2'b00,                   // AT
                        len_field};              // Length
    // DW1: Completer ID[31:16] Status[15:13] BCM[12] Byte Count[11:0]
    assign hdr_dw1   = {cid_r, st_r, 1'b0, bc_r};
    // DW2: Requester ID[31:16] Tag[15:8] R[7] Lower Address[6:0]
    assign hdr_dw2   = {rid_r, tag_r, 1'b0, la_r};

    assign pld_last      = (pld_cnt == (len_r - 6'd1));
    assign cpl_req_ready = (state == T_IDLE);
    assign beat_go       = tx_tlp_valid && tx_tlp_ready;

    // Stream outputs. Gated with !rst so REQ-006 holds on the very first
    // reset cycle as well as after the state register has settled.
    always_comb begin
        tx_tlp_data  = 32'h0000_0000;
        tx_tlp_sop   = 1'b0;
        tx_tlp_eop   = 1'b0;
        tx_tlp_valid = 1'b0;
        case (state)
            T_DW0: begin
                tx_tlp_data  = hdr_dw0;
                tx_tlp_sop   = 1'b1;
                tx_tlp_valid = 1'b1;
            end
            T_DW1: begin
                tx_tlp_data  = hdr_dw1;
                tx_tlp_valid = 1'b1;
            end
            T_DW2: begin
                tx_tlp_data  = hdr_dw2;
                tx_tlp_eop   = !wd_r;
                tx_tlp_valid = 1'b1;
            end
            T_PLD: begin
                tx_tlp_data  = pld_data;
                tx_tlp_eop   = pld_last;
                tx_tlp_valid = pld_valid;
            end
            default: begin
                tx_tlp_data  = 32'h0000_0000;
            end
        endcase
        if (rst) begin
            tx_tlp_sop   = 1'b0;
            tx_tlp_eop   = 1'b0;
            tx_tlp_valid = 1'b0;
        end
    end

    assign pld_ready = (state == T_PLD) && tx_tlp_ready;
    assign cpl_done  = beat_go && tx_tlp_eop;

    always_ff @(posedge clk) begin
        if (rst) begin
            state   <= T_IDLE;
            wd_r    <= 1'b0;
            len_r   <= 6'd1;
            bc_r    <= 12'd0;
            la_r    <= 7'd0;
            st_r    <= 3'b000;
            tc_r    <= 3'b000;
            attr_r  <= 3'b000;
            rid_r   <= 16'h0000;
            tag_r   <= 8'h00;
            cid_r   <= 16'h0000;
            pld_cnt <= 6'd0;
        end else begin
            case (state)
                T_IDLE: begin
                    if (cpl_req_valid) begin
                        wd_r    <= cpl_with_data;
                        len_r   <= cpl_len;
                        bc_r    <= cpl_byte_count;
                        la_r    <= cpl_lower_addr;
                        st_r    <= cpl_status;
                        tc_r    <= cpl_tc;
                        attr_r  <= cpl_attr;
                        rid_r   <= cpl_req_id;
                        tag_r   <= cpl_tag;
                        cid_r   <= cpl_completer_id;
                        pld_cnt <= 6'd0;
                        state   <= T_DW0;
                    end
                end
                T_DW0: if (beat_go) state <= T_DW1;
                T_DW1: if (beat_go) state <= T_DW2;
                T_DW2: if (beat_go) begin
                    if (wd_r) state <= T_PLD;
                    else      state <= T_IDLE;
                end
                T_PLD: begin
                    if (beat_go) begin
                        pld_cnt <= pld_cnt + 6'd1;
                        if (pld_last) begin
                            state <= T_IDLE;
                        end
                    end
                end
                default: state <= T_IDLE;
            endcase
        end
    end

endmodule
