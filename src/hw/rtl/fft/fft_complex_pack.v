// Native {imag16,real16} -> {sign_extended_imag32,sign_extended_real32}.
module fft_complex_pack (
    input wire [31:0] s_axis_tdata,
    input wire s_axis_tvalid, s_axis_tlast,
    output wire s_axis_tready,
    output wire [63:0] m_axis_tdata,
    output wire [7:0] m_axis_tkeep,
    output wire m_axis_tvalid, m_axis_tlast,
    input wire m_axis_tready
);
    assign m_axis_tdata = {{16{s_axis_tdata[31]}},s_axis_tdata[31:16],
                          {16{s_axis_tdata[15]}},s_axis_tdata[15:0]};
    assign m_axis_tkeep = 8'hff;
    assign m_axis_tvalid = s_axis_tvalid;
    assign m_axis_tlast = s_axis_tlast;
    assign s_axis_tready = m_axis_tready;
endmodule
