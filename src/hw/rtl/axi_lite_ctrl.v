// axi_lite_ctrl.v -- minimal AXI4-Lite slave for steps A-5 / M3.
// Chinese notes: see docs/interface.md and docs/a_week1_2_runbook.md
//
// Register map, matching the frozen M1 contract:
//   reg0 (0x00) CTRL    : bit0 start, bit1 reset; low 4 bits also drive led_o
//   reg1 (0x04) WINDOW  : window select
//   reg2 (0x08) STATUS  : placeholder, becomes read-only in phase 3
//   reg3 (0x0C) LENGTH  : reset value 1024, useful as an "IP alive" probe
//
// Built as a module reference inside the Block Design instead of the
// Create-and-Package-IP wizard, so the whole flow stays scriptable.
`timescale 1ns / 1ps

module axi_lite_ctrl #(
    parameter integer C_S_AXI_DATA_WIDTH = 32,
    parameter integer C_S_AXI_ADDR_WIDTH = 5
) (
    input  wire                            s_axi_aclk,
    input  wire                            s_axi_aresetn,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0]   s_axi_awaddr,
    input  wire [2:0]                      s_axi_awprot,
    input  wire                            s_axi_awvalid,
    output reg                             s_axi_awready,

    input  wire [C_S_AXI_DATA_WIDTH-1:0]   s_axi_wdata,
    input  wire [C_S_AXI_DATA_WIDTH/8-1:0] s_axi_wstrb,
    input  wire                            s_axi_wvalid,
    output reg                             s_axi_wready,

    output reg  [1:0]                      s_axi_bresp,
    output reg                             s_axi_bvalid,
    input  wire                            s_axi_bready,

    input  wire [C_S_AXI_ADDR_WIDTH-1:0]   s_axi_araddr,
    input  wire [2:0]                      s_axi_arprot,
    input  wire                            s_axi_arvalid,
    output reg                             s_axi_arready,

    output reg  [C_S_AXI_DATA_WIDTH-1:0]   s_axi_rdata,
    output reg  [1:0]                      s_axi_rresp,
    output reg                             s_axi_rvalid,
    input  wire                            s_axi_rready,

    output wire [3:0]                      led_o
);

    // Two bits of address select one of the four registers;
    // address bits [1:0] are the byte offset inside a 32-bit word.
    localparam integer ADDR_LSB          = (C_S_AXI_DATA_WIDTH / 32) + 1;
    localparam integer OPT_MEM_ADDR_BITS = 1;

    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg0;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg1;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg2;
    reg [C_S_AXI_DATA_WIDTH-1:0] slv_reg3;

    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_awaddr_q;
    reg [C_S_AXI_ADDR_WIDTH-1:0] axi_araddr_q;
    reg                          aw_en;

    integer byte_idx;

    assign led_o = slv_reg0[3:0];

    // ---- write address channel ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_awready <= 1'b0;
            aw_en         <= 1'b1;
            axi_awaddr_q  <= {C_S_AXI_ADDR_WIDTH{1'b0}};
        end else begin
            if (s_axi_awready && s_axi_awvalid)
                axi_awaddr_q <= s_axi_awaddr;

            if (~s_axi_awready && s_axi_awvalid && s_axi_wvalid && aw_en) begin
                s_axi_awready <= 1'b1;
                aw_en         <= 1'b0;
            end else if (s_axi_bready && s_axi_bvalid) begin
                aw_en         <= 1'b1;
                s_axi_awready <= 1'b0;
            end else begin
                s_axi_awready <= 1'b0;
            end
        end
    end

    // ---- write data channel ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_wready <= 1'b0;
        end else begin
            if (~s_axi_wready && s_axi_wvalid && s_axi_awvalid && aw_en)
                s_axi_wready <= 1'b1;
            else
                s_axi_wready <= 1'b0;
        end
    end

    // ---- register write: byte enables from WSTRB, untouched bytes keep value ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            slv_reg0 <= 32'h0000_0000;
            slv_reg1 <= 32'h0000_0000;
            slv_reg2 <= 32'h0000_0000;
            slv_reg3 <= 32'h0000_0400;   // 1024
        end else begin
            if (s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid) begin
                case (axi_awaddr_q[ADDR_LSB + OPT_MEM_ADDR_BITS : ADDR_LSB])
                    2'b00: for (byte_idx = 0; byte_idx < 4; byte_idx = byte_idx + 1)
                               if (s_axi_wstrb[byte_idx])
                                   slv_reg0[byte_idx*8 +: 8] <= s_axi_wdata[byte_idx*8 +: 8];
                    2'b01: for (byte_idx = 0; byte_idx < 4; byte_idx = byte_idx + 1)
                               if (s_axi_wstrb[byte_idx])
                                   slv_reg1[byte_idx*8 +: 8] <= s_axi_wdata[byte_idx*8 +: 8];
                    2'b10: for (byte_idx = 0; byte_idx < 4; byte_idx = byte_idx + 1)
                               if (s_axi_wstrb[byte_idx])
                                   slv_reg2[byte_idx*8 +: 8] <= s_axi_wdata[byte_idx*8 +: 8];
                    2'b11: for (byte_idx = 0; byte_idx < 4; byte_idx = byte_idx + 1)
                               if (s_axi_wstrb[byte_idx])
                                   slv_reg3[byte_idx*8 +: 8] <= s_axi_wdata[byte_idx*8 +: 8];
                    default: ;
                endcase
            end
        end
    end

    // ---- write response: only after both AW and W handshakes completed ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_bvalid <= 1'b0;
            s_axi_bresp  <= 2'b00;
        end else begin
            if (s_axi_awready && s_axi_awvalid && s_axi_wready && s_axi_wvalid) begin
                s_axi_bvalid <= 1'b1;
                s_axi_bresp  <= 2'b00;       // OKAY
            end else if (s_axi_bready && s_axi_bvalid) begin
                s_axi_bvalid <= 1'b0;
            end
        end
    end

    // ---- read address channel ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_arready <= 1'b0;
            axi_araddr_q  <= {C_S_AXI_ADDR_WIDTH{1'b0}};
        end else begin
            if (~s_axi_arready && s_axi_arvalid && ~s_axi_rvalid) begin
                s_axi_arready <= 1'b1;
                axi_araddr_q  <= s_axi_araddr;
            end else begin
                s_axi_arready <= 1'b0;
            end
        end
    end

    // ---- read data channel ----
    always @(posedge s_axi_aclk) begin
        if (!s_axi_aresetn) begin
            s_axi_rvalid <= 1'b0;
            s_axi_rresp  <= 2'b00;
            s_axi_rdata  <= 32'h0000_0000;
        end else begin
            if (~s_axi_rvalid && s_axi_arready && s_axi_arvalid) begin
                s_axi_rvalid <= 1'b1;
                s_axi_rresp  <= 2'b00;       // OKAY
            end else if (s_axi_rvalid && s_axi_rready) begin
                s_axi_rvalid <= 1'b0;
            end

            case (axi_araddr_q[ADDR_LSB + OPT_MEM_ADDR_BITS : ADDR_LSB])
                2'b00:   s_axi_rdata <= slv_reg0;
                2'b01:   s_axi_rdata <= slv_reg1;
                2'b10:   s_axi_rdata <= slv_reg2;
                2'b11:   s_axi_rdata <= slv_reg3;
                default: s_axi_rdata <= 32'h0000_0000;
            endcase
        end
    end

    // AWPROT / ARPROT are unused in this design; consume them to avoid warnings
    wire unused_prot;
    assign unused_prot = &{1'b0, s_axi_awprot, s_axi_arprot, 1'b0};

endmodule
