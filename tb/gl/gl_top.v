// ---------------------------------------------------------------------------
// gl_top.v -- gate-level simulation wrapper for results/.../6_final.v
//
// Purpose: give the post-route netlist a top level that can call
//          $sdf_annotate.  The netlist cannot host the call itself (it is a
//          flow output and must not be edited), and cocotb needs a single
//          elaborated root.
//
// The port list is identical to matmul_top's (spec 6.1), so every existing
// cocotb test binds to it unchanged -- tb/ only ever touches top-level ports,
// never internal hierarchy, which is what makes running the RTL suite against
// the netlist possible at all.
//
// SDF: annotated onto the matmul_top instance, because the SDF's (INSTANCE ...)
//      paths are relative to matmul_top.  The file is selected at RUN time with
//      +sdf=<path>, not at compile time, so one 262 MB .vvp serves both the
//      back-annotated and the un-annotated run and the two are otherwise
//      bit-identical builds -- which is what makes comparing them meaningful.
//      Requires iverilog -gspecify; without it Icarus silently omits every
//      specify block and prints
//        "Omitting $sdf_annotate() since specify blocks are being omitted."
//      and the run degrades to zero delay with no other symptom.
//
// NOT synthesizable, NOT part of rtl/.  `initial` is deliberate and legal here.
// ---------------------------------------------------------------------------
`timescale 1ns / 1ps

module gl_top (
    input  wire        clk,
    input  wire        rst,

    input  wire [31:0] rx_tlp_data,
    input  wire        rx_tlp_sop,
    input  wire        rx_tlp_eop,
    input  wire        rx_tlp_valid,
    output wire        rx_tlp_ready,

    output wire [31:0] tx_tlp_data,
    output wire        tx_tlp_sop,
    output wire        tx_tlp_eop,
    output wire        tx_tlp_valid,
    input  wire        tx_tlp_ready,

    output wire        irq
);

    matmul_top dut (
        .clk          (clk),
        .rst          (rst),
        .rx_tlp_data  (rx_tlp_data),
        .rx_tlp_sop   (rx_tlp_sop),
        .rx_tlp_eop   (rx_tlp_eop),
        .rx_tlp_valid (rx_tlp_valid),
        .rx_tlp_ready (rx_tlp_ready),
        .tx_tlp_data  (tx_tlp_data),
        .tx_tlp_sop   (tx_tlp_sop),
        .tx_tlp_eop   (tx_tlp_eop),
        .tx_tlp_valid (tx_tlp_valid),
        .tx_tlp_ready (tx_tlp_ready),
        .irq          (irq)
    );

    reg [8*512:1] sdf_path;

    initial begin
        if ($value$plusargs("sdf=%s", sdf_path)) begin
            $display("[gl] $sdf_annotate(\"%0s\") -> gl_top.dut", sdf_path);
            $sdf_annotate(sdf_path, dut);
            $display("[gl] SDF annotation complete");
        end else begin
            $display("[gl] no +sdf= given: no back-annotation (compiled UNIT_DELAY only)");
        end
    end

endmodule
