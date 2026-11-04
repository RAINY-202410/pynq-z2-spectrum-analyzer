// Frozen v1.0 preprocessing: signed24 >> 8; unsigned Hann /32768; floor product.
module fft_window_axis #(
    parameter COEFF_FILE = "hann_coeff_u16.mem"
) (
    input wire clk, resetn, flush, window_hann,
    input wire [23:0] s_axis_tdata,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    output reg [31:0] m_axis_tdata,
    output reg m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready
);
    reg [15:0] hann [0:1023];
    reg [9:0] index;
    wire signed [15:0] q15 = s_axis_tdata[23:8];
    wire signed [16:0] coefficient = {1'b0, hann[index]};
    wire signed [32:0] product = q15 * coefficient;
    wire signed [15:0] result = window_hann ? (product >>> 15) : q15;
    initial $readmemh(COEFF_FILE, hann);
    assign s_axis_tready = resetn && !flush && (!m_axis_tvalid || m_axis_tready);
    always @(posedge clk) begin
        if (!resetn || flush) begin
            index <= 0; m_axis_tvalid <= 0; m_axis_tlast <= 0; m_axis_tdata <= 0;
        end else if (s_axis_tready) begin
            m_axis_tvalid <= s_axis_tvalid;
            if (s_axis_tvalid) begin
                m_axis_tdata <= {16'h0000, result};
                m_axis_tlast <= s_axis_tlast;
                index <= index + 1'b1;
            end
        end
    end
endmodule
