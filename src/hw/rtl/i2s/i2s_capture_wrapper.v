// M4 delivery candidate: one software-triggered packet, stable AXIS output.
// CTRL[0] rising edge: capture one packet; CTRL[1]: abort/reset packetizer.
// CTRL[2]: explicit counter test source. No automatic audio/test fallback.
module i2s_capture_wrapper #(
    parameter integer PACKET_BEATS = 1024
) (
    input wire clk, resetn, enabled,
    input wire [3:0] capture_ctrl,
    input wire bclk, lrclk, sdata_i,
    output wire sdata_o,
    output reg codec_mclk,
    output wire [63:0] m_axis_tdata,
    output wire [7:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready,
    output wire [3:0] dbg_led,
    output wire [31:0] dbg_cnt_lrclk, dbg_cnt_beat, dbg_snap, dbg_samp
);
    // FCLK_CLK0 is 100 MHz. This output drives codec MCLK at 10 MHz.
    reg [2:0] mclk_div;
    always @(posedge clk) begin
        if (!resetn) begin
            mclk_div <= 0;
            codec_mclk <= 0;
        end else if (mclk_div == 4) begin
            mclk_div <= 0;
            codec_mclk <= ~codec_mclk;
        end else mclk_div <= mclk_div + 1'b1;
    end

    wire [63:0] i2s_tdata;
    wire i2s_tvalid;
    // Audio cannot be paused. Consume it continuously; samples outside a
    // requested packet are discarded. During a packet, overflow is reported.
    i2s_capture #(.BIT_DEPTH(24)) u_capture (
        .clk(clk), .resetn(resetn), .enabled(enabled),
        .bclk(bclk), .lrclk(lrclk), .sdata_i(sdata_i), .sdata_o(sdata_o),
        .m_axis_tdata(i2s_tdata), .m_axis_tvalid(i2s_tvalid),
        .m_axis_tready(1'b1)
    );

    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) reg [1:0] lr_sync;
    reg lr_d, rate_ok;
    reg [19:0] lr_idle;
    reg [31:0] lr_count, beat_count, latest_sample;
    always @(posedge clk) begin
        if (!resetn) begin
            lr_sync <= 0; lr_d <= 0; rate_ok <= 0;
            lr_idle <= 20'hfffff; lr_count <= 0;
            beat_count <= 0; latest_sample <= 0;
        end else begin
            lr_sync <= {lr_sync[0], lrclk};
            lr_d <= lr_sync[1];
            if (lr_d != lr_sync[1]) begin
                if (lr_idle >= 500 && lr_idle <= 3000) rate_ok <= 1;
                lr_idle <= 0;
                lr_count <= lr_count + 1'b1;
            end else if (lr_idle != 20'hfffff) lr_idle <= lr_idle + 1'b1;
            if (m_axis_tvalid && m_axis_tready)
                beat_count <= beat_count + 1'b1;
            if (i2s_tvalid) latest_sample <= i2s_tdata[63:32];
        end
    end
    wire live = rate_ok && (lr_idle < 100000);

    localparam integer COUNT_WIDTH = (PACKET_BEATS <= 1) ? 1 : $clog2(PACKET_BEATS);
    reg arm_d, busy, done, overflow, test_mode;
    reg [COUNT_WIDTH-1:0] beat_index;
    reg [63:0] held_data, test_next;
    reg held_valid;
    assign m_axis_tdata = held_data;
    assign m_axis_tkeep = 8'hff;
    assign m_axis_tvalid = held_valid && busy;
    assign m_axis_tlast = m_axis_tvalid && (beat_index == PACKET_BEATS-1);

    always @(posedge clk) begin
        if (!resetn) begin
            arm_d <= 0; busy <= 0; done <= 0; overflow <= 0;
            test_mode <= 0; beat_index <= 0;
            held_data <= 0; held_valid <= 0; test_next <= 0;
        end else begin
            arm_d <= capture_ctrl[0];
            if (capture_ctrl[1]) begin
                busy <= 0; done <= 0; overflow <= 0;
                beat_index <= 0; held_valid <= 0; test_next <= 0;
            end else if (capture_ctrl[0] && !arm_d && !busy) begin
                busy <= 1; done <= 0; overflow <= 0;
                test_mode <= capture_ctrl[2];
                beat_index <= 0; held_valid <= 0; test_next <= 0;
            end else if (busy) begin
                if (held_valid && m_axis_tready &&
                    beat_index == PACKET_BEATS-1) begin
                    busy <= 0; done <= 1; held_valid <= 0; beat_index <= 0;
                end else begin
                    if (held_valid && m_axis_tready)
                        beat_index <= beat_index + 1'b1;
                    if (!held_valid || m_axis_tready) begin
                        if (test_mode) begin
                            held_data <= test_next;
                            test_next <= test_next + 1'b1;
                            held_valid <= 1;
                        end else if (i2s_tvalid) begin
                            held_data <= i2s_tdata;
                            held_valid <= 1;
                        end else held_valid <= 0;
                    end else if (!test_mode && i2s_tvalid) overflow <= 1;
                end
            end
        end
    end

    // Preserve existing high status fields, use previously unused low bits.
    // [31:28]=0xA identifies this control protocol; [27]=ready [26]=valid
    // [25]=live [24:5]=LRCLK idle cycles; [3]=done [2]=test [1]=overflow [0]=busy.
    assign dbg_cnt_lrclk = lr_count;
    assign dbg_cnt_beat = beat_count;
    assign dbg_samp = latest_sample;
    assign dbg_snap = {4'ha, m_axis_tready, m_axis_tvalid, live, lr_idle,
                       1'b0, done, test_mode, overflow, busy};
    assign dbg_led = {overflow, test_mode, done, busy};
endmodule
