// ---------------------------------------------------------------------------
// pcie_cfg_space.sv
//
// Purpose : Minimal Type 0 PCI configuration space for Function 0. Services
//           CfgRd0/CfgWr0 DWORD accesses, supplies the BAR0 base and Memory
//           Space Enable used for BAR0 address decoding, and captures the
//           device's own Bus/Device/Function number from the Completer ID of
//           every accepted configuration request.
//
// Parameters: none.
//
// Interface contract:
//   req_valid  : single-cycle strobe, asserted by tlp_rx for one accepted
//                Type 0 configuration request (Device = 0, Function = 0).
//   req_write  : 1 = CfgWr0, 0 = CfgRd0.
//   req_dw_addr: configuration DWORD index, i.e. Cfg Addr[11:2] from header
//                DW2 (spec 7.2.3).
//   req_be     : First DW Byte Enables. Only byte-enabled bytes are written
//                (REQ-046). Reads ignore byte enables (REQ-033).
//   req_wdata  : the payload DWORD of a CfgWr0, already in host order.
//   req_completer_id : header DW2[31:16] of the request; captured on every
//                accepted request (REQ-052).
//   rdata      : COMBINATIONAL read of req_dw_addr; tlp_rx registers it on
//                the same edge that it strobes req_valid.
//
// Latency: read 0 cycles (combinational); write visible 1 cycle after the
//          strobe.
//
// Implements: REQ-045 ... REQ-054, REQ-112, REQ-115, REQ-121.
// ---------------------------------------------------------------------------
module pcie_cfg_space (
    // Clock and reset
    input  logic         clk,
    input  logic         rst,

    // Configuration request port (from tlp_rx)
    input  logic         req_valid,
    input  logic         req_write,
    input  logic [9:0]   req_dw_addr,
    input  logic [3:0]   req_be,
    input  logic [31:0]  req_wdata,
    input  logic [15:0]  req_completer_id,
    output logic [31:0]  rdata,

    // Decode outputs
    output logic [17:0]  bar0_base,       // BAR0 Address[31:14]
    output logic         mem_space_en,    // Command.MSE
    output logic [15:0]  completer_id     // captured Bus/Device/Function
);

    // Configuration DWORD indices
    localparam logic [9:0] C_ID       = 10'h000;  // 0x00 Vendor/Device ID
    localparam logic [9:0] C_CMDSTS   = 10'h001;  // 0x04 Command/Status
    localparam logic [9:0] C_CLASS    = 10'h002;  // 0x08 Class/Revision
    localparam logic [9:0] C_MISC     = 10'h003;  // 0x0C Cache line/hdr type
    localparam logic [9:0] C_BAR0     = 10'h004;  // 0x10 BAR0
    localparam logic [9:0] C_SUBSYS   = 10'h00B;  // 0x2C Subsystem IDs
    localparam logic [9:0] C_INTR     = 10'h00F;  // 0x3C Interrupt Line/Pin

    logic [2:0]  cmd;         // {BME, MSE, IOSE}
    logic [17:0] bar0_hi;     // BAR0[31:14]
    logic [7:0]  cache_line;
    logic [7:0]  int_line;
    logic [15:0] cid;

    assign bar0_base    = bar0_hi;
    assign mem_space_en = cmd[1];
    assign completer_id = cid;

    always_ff @(posedge clk) begin
        if (rst) begin
            cmd        <= 3'b000;
            bar0_hi    <= 18'h0_0000;
            cache_line <= 8'h00;
            int_line   <= 8'h00;
            cid        <= 16'h0000;
        end else if (req_valid) begin
            cid <= req_completer_id;
            if (req_write) begin
                case (req_dw_addr)
                    C_CMDSTS: begin
                        // Command[2:0] RW, [15:3] RO 0, Status[31:16] RO 0.
                        if (req_be[0]) cmd <= req_wdata[2:0];
                    end
                    C_MISC: begin
                        // Cache Line Size RW; Latency Timer/Header Type/BIST RO.
                        if (req_be[0]) cache_line <= req_wdata[7:0];
                    end
                    C_BAR0: begin
                        // BAR0[31:14] RW, BAR0[13:0] RO 0.
                        if (req_be[1]) bar0_hi[1:0]   <= req_wdata[15:14];
                        if (req_be[2]) bar0_hi[9:2]   <= req_wdata[23:16];
                        if (req_be[3]) bar0_hi[17:10] <= req_wdata[31:24];
                    end
                    C_INTR: begin
                        // Interrupt Line RW; Interrupt Pin/Min Gnt/Max Lat RO.
                        if (req_be[0]) int_line <= req_wdata[7:0];
                    end
                    default: begin
                        // RO or unimplemented: accepted, changes no state.
                    end
                endcase
            end
        end
    end

    // req_wdata[13:8] land on Command[15:8] and BAR0[13:8], both RO 0, so they
    // are deliberately dropped. Explicit sink so the linter sees that.
    logic unused_wdata;
    assign unused_wdata = |req_wdata[13:8];

    always_comb begin
        case (req_dw_addr)
            C_ID:     rdata = 32'h8000_1234;               // Device 0x8000, Vendor 0x1234
            C_CMDSTS: rdata = {16'h0000, 13'b0, cmd};      // Status = 0, no cap list
            C_CLASS:  rdata = 32'h1200_0001;               // Class 0x120000, Rev 0x01
            C_MISC:   rdata = {8'h00, 8'h00, 8'h00, cache_line};
            C_BAR0:   rdata = {bar0_hi, 14'h0000};
            C_SUBSYS: rdata = 32'h0001_1234;               // SSID 0x0001, SSVID 0x1234
            C_INTR:   rdata = {8'h00, 8'h00, 8'h00, int_line};
            default:  rdata = 32'h0000_0000;               // BAR1-5, cap ptr, 0x40-0xFFF
        endcase
    end

endmodule
