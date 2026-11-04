// FFT v1.0 AXI-Lite registers. AW and W may arrive independently; one reply in flight.
module fft_ctrl_axi (
    input wire s_axi_aclk, s_axi_aresetn,
    input wire [4:0] s_axi_awaddr,
    input wire [2:0] s_axi_awprot,
    input wire s_axi_awvalid,
    output wire s_axi_awready,
    input wire [31:0] s_axi_wdata,
    input wire [3:0] s_axi_wstrb,
    input wire s_axi_wvalid,
    output wire s_axi_wready,
    output reg s_axi_bvalid,
    input wire s_axi_bready,
    output wire [1:0] s_axi_bresp,
    input wire [4:0] s_axi_araddr,
    input wire [2:0] s_axi_arprot,
    input wire s_axi_arvalid,
    output wire s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output reg s_axi_rvalid,
    input wire s_axi_rready,
    output wire [1:0] s_axi_rresp,
    output reg start_cmd, abort_cmd, clear_cmd, window_requested,
    input wire [31:0] status, input_count, output_count, frame_sequence
);
    reg aw_held, w_held;
    reg [4:0] address;
    reg [31:0] data;
    reg [3:0] strobes;
    assign s_axi_awready = !aw_held && !s_axi_bvalid;
    assign s_axi_wready = !w_held && !s_axi_bvalid;
    assign s_axi_arready = !s_axi_rvalid;
    assign s_axi_bresp=2'b00;
    assign s_axi_rresp=2'b00;
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            aw_held<=0; w_held<=0; address<=0; data<=0; strobes<=0;
            s_axi_bvalid<=0; s_axi_rvalid<=0; s_axi_rdata<=0;
            start_cmd<=0; abort_cmd<=0; clear_cmd<=0; window_requested<=0;
        end else begin
            start_cmd<=0; abort_cmd<=0; clear_cmd<=0;
            if (s_axi_awready && s_axi_awvalid) begin address<=s_axi_awaddr; aw_held<=1; end
            if (s_axi_wready && s_axi_wvalid) begin data<=s_axi_wdata; strobes<=s_axi_wstrb; w_held<=1; end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid<=0;
            if (aw_held && w_held && !s_axi_bvalid) begin
                aw_held<=0; w_held<=0; s_axi_bvalid<=1;
                if (address[4:2]==0 && strobes[0]) begin
                    if (data[1]) abort_cmd<=1;
                    else if (data[2]) clear_cmd<=1;
                    else if (data[0]) start_cmd<=1;
                end
                if (address[4:2]==1 && strobes[0]) window_requested<=data[0];
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid<=0;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid<=1;
                case (s_axi_araddr[4:2])
                    0: s_axi_rdata<=0;
                    1: s_axi_rdata<={31'b0,window_requested};
                    2: s_axi_rdata<=status;
                    3: s_axi_rdata<=1024;
                    4: s_axi_rdata<=32'h46465401;
                    5: s_axi_rdata<=input_count;
                    6: s_axi_rdata<=output_count;
                    7: s_axi_rdata<=frame_sequence;
                endcase
            end
        end
    end
endmodule
