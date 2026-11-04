// counter.v -- Step A-2: first design proving the sim -> synth -> board chain.
// Chinese notes: see docs/a_week1_2_runbook.md
//
// Only difference from the plain version: the LED tap index is a parameter.
// On the board LED_TAP=22 toggles every 2^22 clocks (about 42 ms at 100 MHz),
// which the eye can follow. In simulation that would need 4.2 million clocks
// and the waveform would look flat, so the testbench overrides it with a small
// value. Same RTL, two time scales.
`timescale 1ns / 1ps

module counter #(
    parameter integer LED_TAP = 22
) (
    input  wire       clk,
    input  wire       rst_n,
    output reg  [3:0] led
);

    reg [25:0] cnt;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) cnt <= 26'd0;
        else        cnt <= cnt + 1'b1;
    end

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) led <= 4'b0000;
        else        led <= cnt[LED_TAP +: 4];
    end

endmodule
