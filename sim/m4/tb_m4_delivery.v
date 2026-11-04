`timescale 1ns/1ps
// Unit test: the I2S block is stubbed; existing I2S tests cover serial decoding.
module i2s_capture #(parameter BIT_DEPTH=24) (
    input wire clk, resetn, enabled, bclk, lrclk, sdata_i,
    output wire sdata_o, output wire [63:0] m_axis_tdata,
    output wire m_axis_tvalid, input wire m_axis_tready
);
    reg [31:0] sample;
    always @(posedge clk) begin
        if (!resetn) sample <= 0;
        else if (bclk && enabled && m_axis_tready) sample <= sample + 1;
    end
    assign sdata_o=0;
    assign m_axis_tvalid=bclk && enabled;
    assign m_axis_tdata={sample,sample};
endmodule

module tb_m4_delivery;
    reg clk=0, resetn=0, ready=0, bclk=0;
    reg [3:0] ctrl=0;
    wire [63:0] data;
    wire valid,last,mclk;
    wire [31:0] snap,beats;
    integer count=0, packets=0, cycle=0, file_handle;
    reg previous_stall=0, previous_last=0;
    reg [63:0] previous_data;
    reg check_counter=1;
    i2s_capture_wrapper dut (
        .clk(clk),.resetn(resetn),.enabled(1'b1),.capture_ctrl(ctrl),
        .bclk(bclk),.lrclk(1'b0),.sdata_i(1'b0),.sdata_o(),.codec_mclk(mclk),
        .m_axis_tdata(data),.m_axis_tvalid(valid),.m_axis_tlast(last),
        .m_axis_tready(ready),.dbg_led(),.dbg_cnt_lrclk(),
        .dbg_cnt_beat(beats),.dbg_snap(snap),.dbg_samp()
    );
    always #5 clk=~clk;
    always @(posedge clk) begin
        if (resetn && !ctrl[1]) begin
            if (previous_stall && (!valid || data!==previous_data || last!==previous_last))
                $fatal(1,"AXIS payload changed under backpressure");
            if (valid && ready && check_counter) begin
                if (data !== count) $fatal(1,"Counter data mismatch at %0d",count);
                if (last !== (count==1023)) $fatal(1,"TLAST not on beat 1024");
                if(last) begin count=0; packets=packets+1; end
                else count=count+1;
            end
            previous_stall=valid && !ready;
            previous_data=data; previous_last=last;
        end else previous_stall=0;
    end
    task arm_test;
        begin
            @(negedge clk); ctrl=4;
            repeat(3) @(negedge clk);
            ctrl=5;
        end
    endtask
    initial begin
        repeat(5) @(negedge clk); resetn=1; ready=1;
        repeat(8) @(negedge clk);
        if(valid || beats!=0) $fatal(1,"Data escaped before ARM");
        arm_test;
        // Exercise arbitrary stalls, including a long stall on the final beat.
        while(packets<1) begin
            @(negedge clk); cycle=cycle+1;
            ready=(cycle%5 != 0);
            if(last && count==1023) begin
                ready=0;
                repeat(12) @(negedge clk);
                ready=1;
            end
        end
        repeat(12) @(negedge clk);
        if(valid || beats!=1024 || !snap[3]) $fatal(1,"Packet did not stop");
        arm_test; ready=1;
        wait(packets==2);
        repeat(8) @(negedge clk);
        if(beats!=2048) $fatal(1,"Re-arm length mismatch");
        // Abort a partial packet, then confirm the next packet starts at zero.
        arm_test;
        wait(count==17);
        @(negedge clk); ctrl=2; count=0;
        repeat(4) @(negedge clk);
        if(valid || snap[0]) $fatal(1,"Abort did not clear packet state");
        arm_test; wait(packets==3);
        // Real-mode source is stalled by receiver: overflow must be visible.
        @(negedge clk); ctrl=2; ready=0; check_counter=0;
        repeat(4) @(negedge clk); ctrl=0;
        repeat(4) @(negedge clk); ctrl=1; bclk=1;
        repeat(10) @(negedge clk);
        if(!snap[1]) $fatal(1,"Dropped live sample was not reported");
        file_handle=$fopen("m4_packet_test.pass","w");
        $fdisplay(file_handle,"TEST_PASS"); $fclose(file_handle);
        $display("TEST_PASS: 1024-beat TLAST, stall stability, one-shot, re-arm, abort, overflow");
        $finish;
    end
    initial begin #1000000; $fatal(1,"Testbench watchdog expired"); end
endmodule
