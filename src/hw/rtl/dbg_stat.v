// dbg_stat.v -- minimal read-only AXI4-Lite slave exposing debug counters.
//
// Four 32-bit read-only registers:
//   0x00  cnt_lrclk   number of lrclk edges seen
//   0x04  cnt_beat    number of AXI-Stream handshakes completed
//   0x08  snapshot    {i2s_tready, i2s_tvalid, i2s_live, lrclk_idle[19:0]}
//   0x0C  version     fixed 0x00000003 (identifies this bitstream build)
//
// The read channel is modelled on axi_lite_ctrl.v, which was verified on the
// board in the M3 milestone. The write channel only exists so the AXI
// interconnect is happy; writes are accepted and discarded.
//
// Reading two snapshots in a row and comparing counters tells the PS exactly
// what is happening in real time, instead of the sticky on/off that the LEDs
// provide.

module dbg_stat #(
    parameter integer C_S_AXI_DATA_WIDTH = 32,
    parameter integer C_S_AXI_ADDR_WIDTH = 5
) (
    input  wire                          s_axi_aclk,
    input  wire                          s_axi_aresetn,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_awaddr,
    input  wire                          s_axi_awvalid,
    output wire                          s_axi_awready,
    input  wire [C_S_AXI_DATA_WIDTH-1:0] s_axi_wdata,
    input  wire [C_S_AXI_DATA_WIDTH/8-1:0] s_axi_wstrb,
    input  wire                          s_axi_wvalid,
    output wire                          s_axi_wready,
    output wire [1:0]                    s_axi_bresp,
    output wire                          s_axi_bvalid,
    input  wire                          s_axi_bready,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0] s_axi_araddr,
    input  wire                          s_axi_arvalid,
    output wire                          s_axi_arready,
    output wire [C_S_AXI_DATA_WIDTH-1:0] s_axi_rdata,
    output wire [1:0]                    s_axi_rresp,
    output wire                          s_axi_rvalid,
    input  wire                          s_axi_rready,

    input  wire [31:0]                   cnt_lrclk,
    input  wire [31:0]                   cnt_beat,
    input  wire [31:0]                   snapshot,
    input  wire [31:0]                   samp_lo
);

    localparam integer ADDR_LSB          = (C_S_AXI_DATA_WIDTH / 32) + 1;   // 2
    localparam integer OPT_MEM_ADDR_BITS = 1;
    localparam [31:0] VERSION            = 32'h0000_0003;

    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr_q;
    reg                          axi_arready;
    reg                          axi_awready;
    reg                          axi_wready;
    reg                          axi_bvalid;
    reg                          axi_rvalid;
    reg [C_S_AXI_DATA_WIDTH-1:0] axi_rdata;

    // ---- write channel: accept and discard, always respond OKAY ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            axi_awready <= 1'b0;
            axi_wready  <= 1'b0;
            axi_bvalid  <= 1'b0;
        end else begin
            if (~axi_awready && s_axi_awvalid && ~axi_bvalid)
                axi_awready <= 1'b1;
            else
                axi_awready <= 1'b0;

            if (~axi_wready && s_axi_wvalid && ~axi_bvalid)
                axi_wready <= 1'b1;
            else
                axi_wready <= 1'b0;

            if (axi_awready && s_axi_awvalid && axi_wready && s_axi_wvalid && ~axi_bvalid)
                axi_bvalid <= 1'b1;
            else if (s_axi_bready && axi_bvalid)
                axi_bvalid <= 1'b0;
        end
    end

    // ---- read channel ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            axi_arready  <= 1'b0;
            axi_araddr_q <= {C_S_AXI_ADDR_WIDTH{1'b0}};
        end else begin
            if (~axi_arready && s_axi_arvalid && ~axi_rvalid) begin
                axi_arready  <= 1'b1;
                axi_araddr_q <= s_axi_araddr;
            end else begin
                axi_arready <= 1'b0;
            end
        end
    end

    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            axi_rvalid <= 1'b0;
            axi_rdata  <= 32'd0;
        end else begin
            if (~axi_rvalid && axi_arready && s_axi_arvalid)
                axi_rvalid <= 1'b1;
            else if (axi_rvalid && s_axi_rready)
                axi_rvalid <= 1'b0;

            case (axi_araddr_q[ADDR_LSB + OPT_MEM_ADDR_BITS + 1 : ADDR_LSB])
                3'b000:  axi_rdata <= cnt_lrclk;
                3'b001:  axi_rdata <= cnt_beat;
                3'b010:  axi_rdata <= snapshot;
                3'b011:  axi_rdata <= VERSION;
                3'b100:  axi_rdata <= samp_lo;
                default: axi_rdata <= 32'd0;
            endcase
        end
    end

    assign s_axi_awready = axi_awready;
    assign s_axi_wready  = axi_wready;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_bvalid  = axi_bvalid;
    assign s_axi_arready = axi_arready;
    assign s_axi_rresp   = 2'b00;
    assign s_axi_rvalid  = axi_rvalid;
    assign s_axi_rdata   = axi_rdata;

endmodule
