// Snapshot engine. Capture one entire frame before FFT; audio is never stalled
// by the FFT. Only one frame is in flight. M4 codec/MCLK remains independent.
module fft_frame_engine #(
    parameter COEFF_FILE = "hann_coeff_u16.mem"
) (
    input wire clk, resetn,
    input wire start_cmd, abort_cmd, clear_cmd, window_requested, audio_overflow,
    output wire [3:0] capture_ctrl,
    input wire [63:0] s_axis_audio_tdata,
    input wire [7:0] s_axis_audio_tkeep,
    input wire s_axis_audio_tvalid, s_axis_audio_tlast,
    output wire s_axis_audio_tready,
    output wire fft_resetn,
    output wire [15:0] m_axis_config_tdata,
    output wire m_axis_config_tvalid,
    input wire m_axis_config_tready,
    output wire [31:0] m_axis_fft_tdata,
    output wire m_axis_fft_tvalid, m_axis_fft_tlast,
    input wire m_axis_fft_tready,
    input wire [31:0] s_axis_fft_tdata,
    input wire [7:0] s_axis_fft_tuser,
    input wire s_axis_fft_tvalid, s_axis_fft_tlast,
    output wire s_axis_fft_tready,
    input wire [7:0] s_axis_status_tdata,
    input wire s_axis_status_tvalid,
    output wire s_axis_status_tready,
    input wire event_tlast_missing, event_tlast_unexpected, event_fft_overflow,
    output wire [63:0] m_axis_spectrum_tdata,
    output wire [7:0] m_axis_spectrum_tkeep,
    output wire m_axis_spectrum_tvalid, m_axis_spectrum_tlast,
    input wire m_axis_spectrum_tready,
    output wire [31:0] status,
    output reg [31:0] input_count, output_count, frame_sequence
);
    (* ram_style = "block" *) reg [23:0] frame_mem [0:1023];
    reg busy, capturing, sending, window_latched, capture_trigger;
    reg input_done, output_done, input_error, fft_error, missing_error;
    reg unexpected_error, start_ignored, config_done, aborted, status_seen;
    reg [2:0] reset_count;
    reg [9:0] capture_index;
    reg [10:0] issue_index;
    reg [23:0] rd_data;
    reg rd_valid, rd_last;
    wire rd_ready;
    wire accept_start = start_cmd && !abort_cmd && !clear_cmd && !busy && config_done;
    wire flush_window = accept_start || abort_cmd || (!busy && clear_cmd);
    wire [31:0] window_data;
    wire window_valid, window_last;
    wire output_fire = m_axis_spectrum_tvalid && m_axis_spectrum_tready;

    assign fft_resetn = resetn && (reset_count == 0) && !abort_cmd;
    assign m_axis_config_tdata = 16'h0557;
    assign m_axis_config_tvalid = fft_resetn && !config_done;
    assign s_axis_status_tready = 1'b1;
    assign capture_ctrl = {2'b00, (!fft_resetn || abort_cmd), capture_trigger};
    assign s_axis_audio_tready = busy && capturing && !abort_cmd;
    assign status = {22'b0,aborted,config_done,start_ignored,unexpected_error,
                     missing_error,fft_error,input_error,output_done,input_done,busy};

    fft_window_axis #(.COEFF_FILE(COEFF_FILE)) window_stage (
        .clk(clk), .resetn(fft_resetn), .flush(flush_window), .window_hann(window_latched),
        .s_axis_tdata(rd_data), .s_axis_tvalid(rd_valid && busy),
        .s_axis_tlast(rd_last), .s_axis_tready(rd_ready),
        .m_axis_tdata(window_data), .m_axis_tvalid(window_valid), .m_axis_tlast(window_last),
        .m_axis_tready(m_axis_fft_tready && busy)
    );
    assign m_axis_fft_tdata = window_data;
    assign m_axis_fft_tvalid = window_valid && busy && fft_resetn;
    assign m_axis_fft_tlast = window_last;
    wire pack_ready;
    fft_complex_pack pack_stage (
        .s_axis_tdata(s_axis_fft_tdata), .s_axis_tvalid(s_axis_fft_tvalid && busy && fft_resetn),
        .s_axis_tlast(s_axis_fft_tlast), .s_axis_tready(pack_ready),
        .m_axis_tdata(m_axis_spectrum_tdata), .m_axis_tkeep(m_axis_spectrum_tkeep),
        .m_axis_tvalid(m_axis_spectrum_tvalid), .m_axis_tlast(m_axis_spectrum_tlast),
        .m_axis_tready(m_axis_spectrum_tready)
    );
    assign s_axis_fft_tready = busy ? pack_ready : 1'b1;

    always @(posedge clk) begin
        if (!resetn) begin
            reset_count<=6; config_done<=0; busy<=0; capturing<=0; sending<=0;
            window_latched<=0; capture_trigger<=0; capture_index<=0; issue_index<=0;
            rd_data<=0; rd_valid<=0; rd_last<=0;
            input_done<=0; output_done<=0; input_error<=0; fft_error<=0;
            missing_error<=0; unexpected_error<=0; start_ignored<=0; aborted<=0;
            input_count<=0; output_count<=0; frame_sequence<=0; status_seen<=0;
        end else begin
            capture_trigger<=0;
            if (reset_count != 0) begin reset_count<=reset_count-1'b1; config_done<=0; end
            else if (m_axis_config_tvalid && m_axis_config_tready) config_done<=1;
            if (abort_cmd) begin
                reset_count<=6; config_done<=0; busy<=0; capturing<=0; sending<=0;
                rd_valid<=0; aborted<=1;
            end else if (clear_cmd && !busy) begin
                input_done<=0; output_done<=0; input_error<=0; fft_error<=0;
                missing_error<=0; unexpected_error<=0; start_ignored<=0; aborted<=0;
                input_count<=0; output_count<=0; status_seen<=0;
            end else if (!clear_cmd && start_cmd) begin
                if (accept_start) begin
                    busy<=1; capturing<=1; sending<=0; capture_trigger<=1;
                    window_latched<=window_requested; capture_index<=0; issue_index<=0; rd_valid<=0;
                    input_done<=0; output_done<=0; input_error<=0; fft_error<=0;
                    missing_error<=0; unexpected_error<=0; start_ignored<=0; aborted<=0;
                    input_count<=0; output_count<=0; frame_sequence<=frame_sequence+1'b1;
                    status_seen<=0;
                end else start_ignored<=1;
            end
            if (busy && !abort_cmd) begin
                if (audio_overflow) input_error<=1;
                if (s_axis_audio_tvalid && s_axis_audio_tready) begin
                    frame_mem[capture_index]<=s_axis_audio_tdata[55:32];
                    if (s_axis_audio_tkeep != 8'hff || s_axis_audio_tdata[63:56] != {8{s_axis_audio_tdata[55]}})
                        input_error<=1;
                    if (s_axis_audio_tlast && capture_index != 1023) unexpected_error<=1;
                    if (!s_axis_audio_tlast && capture_index == 1023) missing_error<=1;
                    if (capture_index == 1023) begin capturing<=0; sending<=1; issue_index<=0; end
                    else capture_index<=capture_index+1'b1;
                end
                // Synchronous single-port read, elastic register held under backpressure.
                if (sending && (!rd_valid || rd_ready)) begin
                    if (issue_index < 1024) begin
                        rd_data<=frame_mem[issue_index[9:0]];
                        rd_last<=(issue_index == 1023); rd_valid<=1; issue_index<=issue_index+1'b1;
                    end else begin rd_valid<=0; sending<=0; end
                end
                if (m_axis_fft_tvalid && m_axis_fft_tready) begin
                    input_count<=input_count+1'b1;
                    if (input_count == 1023) input_done<=1;
                end
                if (output_fire) begin
                    output_count<=output_count+1'b1;
                    if (output_count == 1023) output_done<=1;
                    if (s_axis_fft_tuser[0]) fft_error<=1;
                    if (m_axis_spectrum_tlast && output_count != 1023) unexpected_error<=1;
                    if (!m_axis_spectrum_tlast && output_count == 1023) missing_error<=1;
                end
                if (s_axis_status_tvalid) begin status_seen<=1; if (s_axis_status_tdata[0]) fft_error<=1; end
                if (event_tlast_missing) missing_error<=1;
                if (event_tlast_unexpected) unexpected_error<=1;
                if (event_fft_overflow) fft_error<=1;
                if (output_done && status_seen) busy<=0;
            end
        end
    end
endmodule
