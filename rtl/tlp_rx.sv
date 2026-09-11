// ---------------------------------------------------------------------------
// tlp_rx.sv
//
// Purpose : Inbound transaction-layer engine. Frames the 32-bit DWORD stream,
//           captures and decodes the three header DWORDs (PCIe wire /
//           big-endian order, spec 7.2), classifies the TLP, and either hands
//           a decoded request to app_bar0 (memory) or pcie_cfg_space (Type 0
//           config), or rejects it. It also owns the completion descriptor and
//           completion payload source, and enforces strict in-order, one-at-a-
//           time service (DEC-007): rx_tlp_ready is held low from the moment a
//           request is dispatched until its completion has been fully
//           transferred.
//
// Parameters: none.
//
// Interface contract:
//   rx_tlp_*      : chip-boundary inbound stream. rx_tlp_ready is 0 during rst
//                   (REQ-006) and never depends combinationally on
//                   rx_tlp_valid (REQ-003).
//   app_req_*     : one decoded BAR0 request, asserted the cycle after header
//                   DW2 is accepted (REQ-021).
//   app_req_abort : asserted when a mid-payload rx_tlp_sop abandons a partly
//                   received MWr (REQ-020), so app_bar0's burst counter cannot
//                   be left stranded.
//   app_wdata_*   : MWr payload, ascending addresses, exactly Length DWORDs
//                   (REQ-022), carried verbatim in host/little-endian order.
//   app_rdata_*   : MRd data, forwarded to tlp_tx as the completion payload.
//   cfg_*         : single-cycle configuration access strobe plus the
//                   combinational read data returned by pcie_cfg_space.
//   cpl_*/pld_*   : completion descriptor and payload handed to tlp_tx.
//   ev_unsup_req  : 1-cycle pulse that sets STATUS.ERR_UNSUP_REQ.
//
// Latency: header DW0 accepted at t, DW2 at t+2 (no stalls) -> app_req_valid
//          at t+3.
//
// Implements: REQ-002 (rx_tlp_ready may be held low for an unbounded number of
//             cycles - it is low for the whole service+completion window and no
//             beat is lost), REQ-005 (idle and stall cycles may fall anywhere
//             inside a TLP; the framing FSM only advances on valid && ready),
//             REQ-008, REQ-013 ... REQ-022, REQ-028 ... REQ-032,
//             REQ-036 ... REQ-044, REQ-050, REQ-052, REQ-053, REQ-054,
//             REQ-126 (a CfgRd0/CfgWr0 whose Length is not exactly 1 fails the
//             cfg_len_ok guard, falls through to CLS_UR_ERR and so gets a UR
//             Cpl, sets STATUS.ERR_UNSUP_REQ and touches no configuration
//             register; the Device/Function test lives inside the accepted
//             branch, so the REQ-042 carve-out does not apply to it, and any
//             surplus payload is drained through eop in S_DRAIN).
// ---------------------------------------------------------------------------
module tlp_rx (
    // Clock and reset
    input  logic         clk,
    input  logic         rst,

    // Inbound TLP stream (chip boundary)
    input  logic [31:0]  rx_tlp_data,
    input  logic         rx_tlp_sop,
    input  logic         rx_tlp_eop,
    input  logic         rx_tlp_valid,
    output logic         rx_tlp_ready,

    // Decoded BAR0 request (to app_bar0)
    output logic         app_req_valid,
    input  logic         app_req_ready,
    output logic         app_req_write,
    output logic [13:0]  app_req_addr,
    output logic [5:0]   app_req_len,
    output logic [3:0]   app_req_first_be,
    output logic [3:0]   app_req_last_be,
    output logic         app_req_abort,

    // MWr payload (to app_bar0)
    output logic         app_wdata_valid,
    input  logic         app_wdata_ready,
    output logic [31:0]  app_wdata,
    output logic         app_wdata_last,

    // MRd data (from app_bar0)
    input  logic         app_rdata_valid,
    output logic         app_rdata_ready,
    input  logic [31:0]  app_rdata,

    // Configuration access (to pcie_cfg_space)
    output logic         cfg_req_valid,
    output logic         cfg_req_write,
    output logic [9:0]   cfg_req_dw_addr,
    output logic [3:0]   cfg_req_be,
    output logic [31:0]  cfg_req_wdata,
    output logic [15:0]  cfg_req_completer_id,
    input  logic [31:0]  cfg_rdata,
    input  logic [17:0]  cfg_bar0_base,
    input  logic         cfg_mem_space_en,

    // Completion descriptor (to tlp_tx)
    output logic         cpl_req_valid,
    input  logic         cpl_req_ready,
    output logic         cpl_with_data,
    output logic [5:0]   cpl_len,
    output logic [11:0]  cpl_byte_count,
    output logic [6:0]   cpl_lower_addr,
    output logic [2:0]   cpl_status,
    output logic [2:0]   cpl_tc,
    output logic [2:0]   cpl_attr,
    output logic [15:0]  cpl_req_id,
    output logic [7:0]   cpl_tag,

    // Completion payload (to tlp_tx)
    output logic         pld_valid,
    input  logic         pld_ready,
    output logic [31:0]  pld_data,
    input  logic         cpl_done,

    // Error event (to reg_file via app_bar0)
    output logic         ev_unsup_req
);

    // ---- TLP classification ---------------------------------------------
    localparam logic [2:0] CLS_MWR       = 3'd0;  // accepted MWr to BAR0
    localparam logic [2:0] CLS_MRD       = 3'd1;  // accepted MRd from BAR0
    localparam logic [2:0] CLS_CFGRD     = 3'd2;  // accepted CfgRd0
    localparam logic [2:0] CLS_CFGWR     = 3'd3;  // accepted CfgWr0
    localparam logic [2:0] CLS_UR_ERR    = 3'd4;  // UR Cpl + ERR_UNSUP_REQ
    localparam logic [2:0] CLS_UR_NOERR  = 3'd5;  // UR Cpl, no error bit
    localparam logic [2:0] CLS_DROP_ERR  = 3'd6;  // discard + ERR_UNSUP_REQ
    localparam logic [2:0] CLS_DROP      = 3'd7;  // discard silently

    typedef enum logic [3:0] {
        S_H0      = 4'd0,   // awaiting header DW0 (sop)
        S_H1      = 4'd1,   // awaiting header DW1
        S_H2      = 4'd2,   // awaiting header DW2
        S_MEMREQ  = 4'd3,   // presenting the request to app_bar0
        S_WDATA   = 4'd4,   // forwarding MWr payload
        S_CFGW    = 4'd5,   // awaiting the CfgWr0 payload DWORD
        S_CFGACC  = 4'd6,   // one-cycle configuration read / write
        S_CPL     = 4'd7,   // presenting the completion descriptor
        S_CPLWAIT = 4'd8,   // waiting for the completion to be transmitted
        S_DRAIN   = 4'd9    // consuming a rejected TLP up to eop
    } state_e;

    state_e      state;
    // Header bits the design deliberately ignores: DW0 T9[23], T8[19], LN[17],
    // TH[16] and AT[11:10] are "ignored on receive" per spec 7.2.1; DW2 PH[1:0]
    // is ignored per spec 7.2.2 and DW2 Address[15:14] lies above the 16 KiB
    // BAR0 window and is consumed only by the combinational BAR compare on
    // rx_tlp_data at decode time.
    // verilator lint_off UNUSEDSIGNAL
    logic [31:0] dw0_r;
    logic [31:0] dw2_r;
    // verilator lint_on UNUSEDSIGNAL
    logic [31:0] dw1_r;
    logic [2:0]  cls_r;
    logic [5:0]  len_r;
    logic [5:0]  wbeat;
    logic [31:0] cfg_wdata_r;
    logic [31:0] cfg_data_r;
    logic        cfg_pld_v;

    logic        beat;          // an inbound beat transfers this cycle
    logic        beat_hdr;      // ... and it is not a re-synchronising sop
    logic        restart;       // ... and it IS a re-synchronising sop

    assign rx_tlp_ready = !rst && ((state == S_H0)  || (state == S_H1) ||
                                   (state == S_H2)  || (state == S_CFGW) ||
                                   (state == S_DRAIN) ||
                                   ((state == S_WDATA) && app_wdata_ready));

    assign beat     = rx_tlp_valid && rx_tlp_ready;
    assign restart  = beat && rx_tlp_sop && (state != S_H0);
    assign beat_hdr = beat && !rx_tlp_sop;

    // ---- combinational decode of the header being completed in S_H2 ------
    logic [2:0]  fmt;
    logic [4:0]  ttype;
    logic        td_bit;
    logic        ep_bit;
    logic [9:0]  len_raw;
    logic [5:0]  len6;
    logic        len_ok;
    logic        cfg_len_ok;
    logic        is_cpl;
    logic        is_msg;
    logic        is_mem;
    logic        is_io;
    logic        is_cfg0;
    logic        fmt_3dw;
    logic        fmt_wr;
    logic        posted;
    logic        addr_match;
    logic        range_ok;
    logic        bar_hit;
    logic        devfn_ok;
    logic [12:0] end_dw;
    logic [2:0]  cls_c;

    assign fmt     = dw0_r[31:29];
    assign ttype   = dw0_r[28:24];
    assign td_bit  = dw0_r[15];
    assign ep_bit  = dw0_r[14];
    assign len_raw = dw0_r[9:0];
    assign len6    = len_raw[5:0];
    assign len_ok  = (len_raw != 10'd0) && (len_raw <= 10'd32);
    // Spec 7.2.3 fixes Length at 1 for CfgRd0/CfgWr0. Anything else is an
    // unsupported request, so surplus payload DWORDs can never be left in the
    // stream to be mistaken for a header.
    assign cfg_len_ok = (len_raw == 10'd1);

    assign is_cpl  = (ttype == 5'b01010);
    assign is_msg  = (ttype[4:3] == 2'b10);
    assign is_mem  = (ttype == 5'b00000);
    assign is_io   = (ttype == 5'b00010);
    assign is_cfg0 = (ttype == 5'b00100);
    assign fmt_3dw = (fmt == 3'b000) || (fmt == 3'b010);
    assign fmt_wr  = fmt[1];              // Fmt[1] = 1 -> request carries data
    assign posted  = is_msg || ((is_mem || is_io) && fmt_wr);

    assign addr_match = (rx_tlp_data[31:14] == cfg_bar0_base);
    assign end_dw     = {1'b0, rx_tlp_data[13:2]} + {7'b0, len6};
    assign range_ok   = (end_dw <= 13'd4096);
    assign bar_hit    = cfg_mem_space_en && addr_match && range_ok;
    assign devfn_ok   = (rx_tlp_data[23:16] == 8'h00);

    always_comb begin
        if (is_cpl) begin
            // A Completion never generates a Completion (REQ-037, REQ-043).
            cls_c = CLS_DROP;
        end else if (td_bit || ep_bit) begin
            cls_c = posted ? CLS_DROP_ERR : CLS_UR_ERR;
        end else if (is_cfg0 && fmt_3dw && cfg_len_ok) begin
            if (!devfn_ok)      cls_c = CLS_UR_NOERR;   // bus scan, not an error
            else if (fmt_wr)    cls_c = CLS_CFGWR;
            else                cls_c = CLS_CFGRD;
        end else if (is_mem && fmt_3dw) begin
            if (!len_ok || !bar_hit) cls_c = fmt_wr ? CLS_DROP_ERR : CLS_UR_ERR;
            else                     cls_c = fmt_wr ? CLS_MWR : CLS_MRD;
        end else begin
            cls_c = posted ? CLS_DROP_ERR : CLS_UR_ERR;
        end
    end

    assign ev_unsup_req = (state == S_H2) && beat_hdr &&
                          ((cls_c == CLS_UR_ERR) || (cls_c == CLS_DROP_ERR));

    // ---- completion field generation (from the registered header) --------
    logic [3:0] fbe;
    logic [3:0] lbe;
    logic [3:0] lbe_eff;
    logic [1:0] fbo;
    logic [1:0] lbo;
    logic       is_ur;

    assign fbe     = dw1_r[3:0];
    assign lbe     = dw1_r[7:4];
    assign lbe_eff = (len_r > 6'd1) ? lbe : fbe;
    assign fbo     = fbe[0] ? 2'd0 : fbe[1] ? 2'd1 : fbe[2] ? 2'd2 : 2'd3;
    assign lbo     = (lbe_eff == 4'b0001)                  ? 2'd3 :
                     ((lbe_eff & 4'b1110) == 4'b0010)      ? 2'd2 :
                     ((lbe_eff & 4'b1100) == 4'b0100)      ? 2'd1 : 2'd0;
    assign is_ur   = (cls_r == CLS_UR_ERR) || (cls_r == CLS_UR_NOERR);

    assign cpl_with_data  = (cls_r == CLS_MRD) || (cls_r == CLS_CFGRD);
    assign cpl_len        = (cls_r == CLS_MRD)   ? len_r :
                            (cls_r == CLS_CFGRD) ? 6'd1  : 6'd0;
    assign cpl_byte_count = (cls_r == CLS_MRD)
                            ? ({4'b0000, len_r, 2'b00} - {10'b0, fbo} -
                               {10'b0, lbo})
                            : 12'd4;
    assign cpl_lower_addr = (cls_r == CLS_MRD) ? {dw2_r[6:2], fbo} : 7'd0;
    assign cpl_status     = is_ur ? 3'b001 : 3'b000;
    assign cpl_tc         = dw0_r[22:20];
    assign cpl_attr       = {dw0_r[18], dw0_r[13:12]};
    assign cpl_req_id     = dw1_r[31:16];
    assign cpl_tag        = dw1_r[15:8];
    assign cpl_req_valid  = (state == S_CPL);

    // ---- request / payload interfaces ------------------------------------
    assign app_req_valid    = (state == S_MEMREQ);
    assign app_req_write    = (cls_r == CLS_MWR);
    assign app_req_addr     = {dw2_r[13:2], 2'b00};
    assign app_req_len      = len_r;
    assign app_req_first_be = fbe;
    assign app_req_last_be  = (len_r > 6'd1) ? lbe : 4'b0000;
    assign app_req_abort    = (state == S_WDATA) && restart;

    assign app_wdata_valid  = (state == S_WDATA) && rx_tlp_valid && !rx_tlp_sop;
    assign app_wdata        = rx_tlp_data;
    assign app_wdata_last   = (wbeat == (len_r - 6'd1)) || rx_tlp_eop;

    assign cfg_req_valid        = (state == S_CFGACC);
    assign cfg_req_write        = (cls_r == CLS_CFGWR);
    assign cfg_req_dw_addr      = dw2_r[11:2];
    assign cfg_req_be           = fbe;
    assign cfg_req_wdata        = cfg_wdata_r;
    assign cfg_req_completer_id = dw2_r[31:16];

    // Completion payload source: cfg read data (1 DWORD) or app_bar0 read data.
    logic pld_src_cfg;
    assign pld_src_cfg     = (cls_r == CLS_CFGRD);
    assign pld_valid       = pld_src_cfg ? cfg_pld_v  : app_rdata_valid;
    assign pld_data        = pld_src_cfg ? cfg_data_r : app_rdata;
    assign app_rdata_ready = !pld_src_cfg && pld_ready;

    // ---- next state after the header ------------------------------------
    state_e after_hdr;
    always_comb begin
        case (cls_c)
            CLS_MWR, CLS_MRD: after_hdr = S_MEMREQ;
            CLS_CFGRD:        after_hdr = S_CFGACC;
            CLS_CFGWR:        after_hdr = S_CFGW;
            CLS_UR_ERR,
            CLS_UR_NOERR:     begin
                if (rx_tlp_eop) after_hdr = S_CPL;
                else            after_hdr = S_DRAIN;
            end
            default: begin
                if (rx_tlp_eop) after_hdr = S_H0;
                else            after_hdr = S_DRAIN;
            end
        endcase
    end

    // ---- state machine ---------------------------------------------------
    always_ff @(posedge clk) begin
        if (rst) begin
            state       <= S_H0;
            dw0_r       <= 32'h0000_0000;
            dw1_r       <= 32'h0000_0000;
            dw2_r       <= 32'h0000_0000;
            cls_r       <= CLS_DROP;
            len_r       <= 6'd1;
            wbeat       <= 6'd0;
            cfg_wdata_r <= 32'h0000_0000;
            cfg_data_r  <= 32'h0000_0000;
            cfg_pld_v   <= 1'b0;
        end else begin
            // Completion payload handshake for the configuration-read source.
            if (state == S_CFGACC) begin
                cfg_pld_v  <= (cls_r == CLS_CFGRD);
                cfg_data_r <= cfg_rdata;
            end else if (pld_src_cfg && pld_valid && pld_ready) begin
                cfg_pld_v  <= 1'b0;
            end

            if (restart) begin
                // REQ-020: mid-packet sop abandons the partial TLP.
                dw0_r <= rx_tlp_data;
                state <= S_H1;
            end else begin
                case (state)
                    S_H0: begin
                        if (beat && rx_tlp_sop) begin
                            dw0_r <= rx_tlp_data;
                            state <= S_H1;
                        end
                    end

                    S_H1: begin
                        if (beat_hdr) begin
                            dw1_r <= rx_tlp_data;
                            if (rx_tlp_eop) state <= S_H0;   // malformed 2 DW
                            else            state <= S_H2;
                        end
                    end

                    S_H2: begin
                        if (beat_hdr) begin
                            dw2_r <= rx_tlp_data;
                            cls_r <= cls_c;
                            len_r <= len6;
                            wbeat <= 6'd0;
                            state <= after_hdr;
                        end
                    end

                    S_MEMREQ: begin
                        if (app_req_ready) begin
                            if (cls_r == CLS_MWR) state <= S_WDATA;
                            else                  state <= S_CPL;
                        end
                    end

                    S_WDATA: begin
                        if (beat_hdr) begin
                            wbeat <= wbeat + 6'd1;
                            if (app_wdata_last) begin
                                state <= S_H0;   // posted: no completion
                            end
                        end
                    end

                    S_CFGW: begin
                        if (beat_hdr) begin
                            cfg_wdata_r <= rx_tlp_data;
                            state       <= S_CFGACC;
                        end
                    end

                    S_CFGACC: begin
                        state <= S_CPL;
                    end

                    S_CPL: begin
                        if (cpl_req_ready) begin
                            state <= S_CPLWAIT;
                        end
                    end

                    S_CPLWAIT: begin
                        if (cpl_done) begin
                            state <= S_H0;
                        end
                    end

                    S_DRAIN: begin
                        if (beat_hdr && rx_tlp_eop) begin
                            if (is_ur) state <= S_CPL;
                            else       state <= S_H0;
                        end
                    end

                    default: begin
                        state <= S_H0;
                    end
                endcase
            end
        end
    end

endmodule
