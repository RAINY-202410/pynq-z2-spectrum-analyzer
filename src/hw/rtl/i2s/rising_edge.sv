// Derived from Reed Foster's rising_edge.sv (MIT, Copyright 2020 Reed Foster).
// At least two metastability stages precede edge detection. The additional
// PRE_FF_COUNT delay preserves the relative BCLK/LRCLK detector offset.
module rising_edge #(parameter int PRE_FF_COUNT = 1) (
    input wire clk,
    input wire in,
    output wire rising_edge,
    output wire falling_edge
);
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *)
    logic [PRE_FF_COUNT+1:0] shift_reg = '0;
    always @(posedge clk)
        shift_reg <= {shift_reg[PRE_FF_COUNT:0], in};
    assign rising_edge = !shift_reg[PRE_FF_COUNT+1] & shift_reg[PRE_FF_COUNT];
    assign falling_edge = shift_reg[PRE_FF_COUNT+1] & !shift_reg[PRE_FF_COUNT];
endmodule
