// led_top.v -- top level for the A-4 LED design.
// Chinese notes: see docs/a_week1_2_runbook.md
//
// Pure PL design: the 125 MHz board oscillator (sysclk, pin H16) drives the
// counter, and the four board LEDs show cnt[25:22]. No Block Design, no PS,
// no board files needed -- which is exactly the "select Parts, not Boards"
// idea from step A-1.
//
// Reset is tied high on purpose: wiring it to a slide switch invites a
// polarity mistake where the LEDs simply stay dark and the board looks dead.
`timescale 1ns / 1ps

module led_top (
    input  wire       sysclk,
    output wire [3:0] led
);

    counter #(
        .LED_TAP (22)
    ) u_counter (
        .clk   (sysclk),
        .rst_n (1'b1),
        .led   (led)
    );

endmodule
