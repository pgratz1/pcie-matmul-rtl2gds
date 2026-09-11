// Timescale for the post-synthesis replay: the Yosys netlist and simcells.v
// carry none, and cocotb needs a precision finer than 1s to express its
// microsecond test timeouts.
`timescale 1ns / 1ps
