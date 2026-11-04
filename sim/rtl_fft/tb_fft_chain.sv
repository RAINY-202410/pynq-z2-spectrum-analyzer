`timescale 1ns/1ps
module tb_fft_chain;
  reg clk=0; always #5 clk=~clk;
  reg resetn=0;
  reg [4:0] awaddr=0, araddr=0;
  reg [31:0] wdata=0;
  reg [3:0] wstrb=15;
  reg awvalid=0,wvalid=0,arvalid=0,bready=1,rready=0;
  wire awready,wready,arready,bvalid,rvalid;
  wire [1:0] bresp,rresp;
  wire [31:0] rdata;
  wire start_cmd,abort_cmd,clear_cmd,window_requested;
  wire [31:0] status,input_count,output_count,frame_seq;
  wire [3:0] capture_ctrl;
  reg [63:0] audio_data=0;
  reg [7:0] audio_keep=255;
  reg audio_valid=0,audio_last=0,audio_overflow=0;
  reg suppress_audio_last=0,inject_fft_overflow=0;
  wire audio_ready,core_resetn;
  wire [15:0] cfg_data; wire cfg_valid,cfg_ready;
  wire [31:0] fft_in,fft_out;
  wire in_valid,in_ready,in_last,out_valid,out_ready,out_last;
  wire [7:0] out_user,stat_data;
  wire stat_valid,stat_ready,frame_event,missing_event,unexpected_event,overflow_event;
  wire in_halt,out_halt,status_halt;
  wire [63:0] spectrum;
  wire [7:0] spectrum_keep;
  wire spectrum_valid,spectrum_last;
  reg spectrum_ready=1,stalls=0;
  reg [23:0] samples[0:1023];
  string result_dir,current_case;
  integer cycles=0,configs=0,cap_count,in_count,out_count,status_count;
  integer raw_fd,in_fd,out_fd,win_fd,state_fd,marker_fd;
  integer stall_cycles=0,probe_count=0;
  bit collecting=0,previous_stall=0,previous_in_stall=0;
  reg [63:0] held_spectrum;
  reg held_last;
  reg [31:0] held_fft_in;
  reg held_fft_last;
  reg [31:0] value,old_sequence;

  fft_ctrl_axi control (
    .s_axi_aclk(clk),.s_axi_aresetn(resetn),.s_axi_awaddr(awaddr),.s_axi_awprot(3'b0),
    .s_axi_awvalid(awvalid),.s_axi_awready(awready),.s_axi_wdata(wdata),.s_axi_wstrb(wstrb),
    .s_axi_wvalid(wvalid),.s_axi_wready(wready),.s_axi_bvalid(bvalid),.s_axi_bready(bready),.s_axi_bresp(bresp),
    .s_axi_araddr(araddr),.s_axi_arprot(3'b0),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
    .s_axi_rdata(rdata),.s_axi_rvalid(rvalid),.s_axi_rready(rready),.s_axi_rresp(rresp),
    .start_cmd(start_cmd),.abort_cmd(abort_cmd),.clear_cmd(clear_cmd),.window_requested(window_requested),
    .status(status),.input_count(input_count),.output_count(output_count),.frame_sequence(frame_seq)
  );
  fft_frame_engine engine (
    .clk(clk),.resetn(resetn),.start_cmd(start_cmd),.abort_cmd(abort_cmd),.clear_cmd(clear_cmd),
    .window_requested(window_requested),.audio_overflow(audio_overflow),.capture_ctrl(capture_ctrl),
    .s_axis_audio_tdata(audio_data),.s_axis_audio_tkeep(audio_keep),.s_axis_audio_tvalid(audio_valid),
    .s_axis_audio_tlast(audio_last),.s_axis_audio_tready(audio_ready),.fft_resetn(core_resetn),
    .m_axis_config_tdata(cfg_data),.m_axis_config_tvalid(cfg_valid),.m_axis_config_tready(cfg_ready),
    .m_axis_fft_tdata(fft_in),.m_axis_fft_tvalid(in_valid),.m_axis_fft_tlast(in_last),.m_axis_fft_tready(in_ready),
    .s_axis_fft_tdata(fft_out),.s_axis_fft_tuser(out_user),.s_axis_fft_tvalid(out_valid),
    .s_axis_fft_tlast(out_last),.s_axis_fft_tready(out_ready),
    .s_axis_status_tdata(stat_data),.s_axis_status_tvalid(stat_valid),.s_axis_status_tready(stat_ready),
    .event_tlast_missing(missing_event),.event_tlast_unexpected(unexpected_event),.event_fft_overflow(overflow_event|inject_fft_overflow),
    .m_axis_spectrum_tdata(spectrum),.m_axis_spectrum_tkeep(spectrum_keep),
    .m_axis_spectrum_tvalid(spectrum_valid),.m_axis_spectrum_tlast(spectrum_last),.m_axis_spectrum_tready(spectrum_ready),
    .status(status),.input_count(input_count),.output_count(output_count),.frame_sequence(frame_seq)
  );
  contract_probe_wrapper fft (
    .aclk_0(clk),.aresetn_0(core_resetn),
    .S_AXIS_CONFIG_0_tdata(cfg_data),.S_AXIS_CONFIG_0_tvalid(cfg_valid),.S_AXIS_CONFIG_0_tready(cfg_ready),
    .S_AXIS_DATA_0_tdata(fft_in),.S_AXIS_DATA_0_tvalid(in_valid),.S_AXIS_DATA_0_tlast(in_last),.S_AXIS_DATA_0_tready(in_ready),
    .M_AXIS_DATA_0_tdata(fft_out),.M_AXIS_DATA_0_tvalid(out_valid),.M_AXIS_DATA_0_tlast(out_last),
    .M_AXIS_DATA_0_tready(out_ready),.M_AXIS_DATA_0_tuser(out_user),
    .M_AXIS_STATUS_0_tdata(stat_data),.M_AXIS_STATUS_0_tvalid(stat_valid),.M_AXIS_STATUS_0_tready(stat_ready),
    .event_frame_started_0(frame_event),.event_tlast_missing_0(missing_event),
    .event_tlast_unexpected_0(unexpected_event),.event_fft_overflow_0(overflow_event),
    .event_data_in_channel_halt_0(in_halt),.event_data_out_channel_halt_0(out_halt),.event_status_channel_halt_0(status_halt)
  );

  // Independent boundary check of the RTL converter, with expected values hand specified.
  reg probe_reset=0,probe_flush=0,probe_valid=0,probe_last=0;
  reg [23:0] probe_data=0;
  wire probe_ready,probe_out_valid,probe_out_last;
  wire [31:0] probe_out;
  reg signed [15:0] expected_boundary[0:10];
  reg [23:0] boundary[0:10];
  fft_window_axis boundary_dut(.clk(clk),.resetn(probe_reset),.flush(probe_flush),.window_hann(1'b0),
    .s_axis_tdata(probe_data),.s_axis_tvalid(probe_valid),.s_axis_tlast(probe_last),.s_axis_tready(probe_ready),
    .m_axis_tdata(probe_out),.m_axis_tvalid(probe_out_valid),.m_axis_tlast(probe_out_last),.m_axis_tready(1'b1));

  always @(negedge clk) if (stalls) spectrum_ready = (cycles%13 < 8);
  always @(posedge clk) begin
    cycles=cycles+1;
    if (resetn && cfg_valid && cfg_ready) begin
      if (cfg_data !== 16'h0557) $fatal(1,"Config word");
      configs=configs+1;
    end
    if (probe_out_valid) begin
      if (probe_count>=11 || $signed(probe_out[15:0]) !== expected_boundary[probe_count] || probe_out[31:16] !== 0)
        $fatal(1,"signed24 boundary mismatch index=%0d",probe_count);
      probe_count=probe_count+1;
    end
    if (core_resetn && !abort_cmd) begin
      if(out_valid&&out_ready&&!status[0]) $fatal(1,"FFT output outside active frame");
      if (previous_stall && (!spectrum_valid || spectrum!==held_spectrum || spectrum_last!==held_last || spectrum_keep!==8'hff))
        $fatal(1,"Spectrum changed under backpressure");
      if (previous_in_stall && (!in_valid || fft_in!==held_fft_in || in_last!==held_fft_last))
        $fatal(1,"Window output changed under backpressure");
      previous_stall=spectrum_valid&&!spectrum_ready;
      previous_in_stall=in_valid&&!in_ready;
      held_spectrum=spectrum;held_last=spectrum_last;held_fft_in=fft_in;held_fft_last=in_last;
    end else begin previous_stall=0;previous_in_stall=0; end
    if (collecting) begin
      if (audio_valid&&audio_ready) begin $fdisplay(raw_fd,"%06x",audio_data[55:32]);cap_count=cap_count+1; end
      if (in_valid&&in_ready) begin
        $fdisplay(win_fd,"%08x",fft_in);
        if (in_last !== (in_count==1023)) $fatal(1,"Input TLAST");
        in_count=in_count+1;
      end
      if (stat_valid&&stat_ready) begin
        status_count=status_count+1;
        if (stat_data[0]) $fatal(1,"FFT status overflow");
      end
      if (spectrum_valid&&!spectrum_ready) stall_cycles=stall_cycles+1;
      if (spectrum_valid&&spectrum_ready) begin
        if ($isunknown({spectrum,spectrum_last,spectrum_keep}) || spectrum_keep!==255 || spectrum_last!==(out_count==1023))
          $fatal(1,"Packed data/TLAST/TKEEP");
        $fdisplay(out_fd,"%016x",spectrum);
        out_count=out_count+1;
        if (out_count>1024) $fatal(1,"Extra spectrum beat");
      end
    end
  end

  task automatic write_axi(input [4:0] address,input [31:0] data,input [3:0] strobes,input integer order);
    begin
      @(negedge clk);awaddr=address;wdata=data;wstrb=strobes;
      if(order==3)bready=0;
      if(order==0) begin
        awvalid=1;do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;
        repeat(3) @(negedge clk);wvalid=1;do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;
      end else if(order==1) begin
        wvalid=1;do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;
        repeat(3) @(negedge clk);awvalid=1;do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;
      end else begin
        awvalid=1;wvalid=1;do @(posedge clk);while(!(awready&&wready));@(negedge clk);awvalid=0;wvalid=0;
      end
      wait(bvalid);if(bresp!==0)$fatal(1,"AXI write response");
      if(order==3)begin
        repeat(3)begin @(negedge clk);if(!bvalid||bresp!==0)$fatal(1,"AXI write hold");end
        bready=1;
      end
      @(posedge clk);@(negedge clk);
    end
  endtask
  task automatic read_axi(input [4:0] address,output [31:0] data);
    begin
      @(negedge clk);araddr=address;arvalid=1;
      do @(posedge clk);while(!arready);@(negedge clk);arvalid=0;
      wait(rvalid);data=rdata;
      repeat(2) begin @(negedge clk);if(!rvalid||rdata!==data||rresp!==0)$fatal(1,"AXI read hold");end
      rready=1;@(posedge clk);@(negedge clk);rready=0;
    end
  endtask
  task automatic send_samples(input integer count,input bit exercise);
    integer n;
    begin
      for(n=0;n<count;n=n+1) begin
        @(negedge clk);audio_data={{8{samples[n][23]}},samples[n],32'h00012345};
        audio_valid=1;audio_last=(n==1023)&&!suppress_audio_last;
        do @(posedge clk);while(!audio_ready);
        @(negedge clk);audio_valid=0;audio_last=0;
        if(n%7==0) repeat(2) @(negedge clk);
        if(exercise&&n==100) write_axi(0,1,15,0); // Busy START is ignored.
        if(exercise&&n==200) write_axi(4,!window_requested,15,1); // Latched window must hold.
        if(exercise&&n==300) write_axi(0,4,15,2); // Busy CLEAR is ignored.
      end
    end
  endtask
  task automatic wait_config;
    integer guard;
    begin
      guard=0;while(!status[8])begin @(negedge clk);guard=guard+1;if(guard>1000)$fatal(1,"Config timeout");end
    end
  endtask
  task automatic wait_done;
    integer guard;
    begin
      guard=0;while(status[0])begin @(negedge clk);guard=guard+1;if(guard>100000)$fatal(1,"Frame timeout");end
      repeat(32) @(negedge clk);
    end
  endtask
  task automatic run_case(input string name,input bit hann_mode,input bit exercise);
    string folder;
    begin
      current_case=name;folder={result_dir,"/",name};
      $readmemh({folder,"/input_s24.hex"},samples);
      raw_fd=$fopen({folder,"/actual_s24.hex"},"w");
      win_fd=$fopen({folder,"/actual_fft_input32.hex"},"w");
      out_fd=$fopen({folder,"/actual_spectrum64.hex"},"w");
      if(!raw_fd||!win_fd||!out_fd)$fatal(1,"Capture paths");
      cap_count=0;in_count=0;out_count=0;status_count=0;stall_cycles=0;
      // Previous busy-window write must supply this frame without another WINDOW write.
      if(name!="bin16p35_rect")write_axi(4,hann_mode,15,0);
      else if(window_requested!==hann_mode)$fatal(1,"Busy WINDOW write not retained");
      write_axi(0,4,15,1);
      old_sequence=frame_seq;
      collecting=1;write_axi(0,1,15,2);
      if(!status[0]||frame_seq!=old_sequence+1)$fatal(1,"START not accepted");
      send_samples(1024,exercise);wait_done();collecting=0;
      if(cap_count!=1024||in_count!=1024||out_count!=1024||status_count!=1||input_count!=1024||output_count!=1024||
         (status&32'h7e)!==32'h6||!status[8]||status[9]) $fatal(1,"Frame/count/state: %s status=%x",name,status);
      if(exercise && !status[7])$fatal(1,"Busy START not recorded");
      read_axi(20,value);if(value!=1024)$fatal(1,"INPUT_COUNT register");
      read_axi(24,value);if(value!=1024)$fatal(1,"OUTPUT_COUNT register");
      $fclose(raw_fd);$fclose(win_fd);$fclose(out_fd);
      state_fd=$fopen({folder,"/state.json"},"w");
      $fdisplay(state_fd,"{\"case\":\"%s\",\"source\":\"XSIM_RTL_FRAME_ENGINE\",\"status\":%0d,",name,status);
      $fdisplay(state_fd,"\"captured\":%0d,\"fft_inputs\":%0d,\"outputs\":%0d,\"status_beats\":%0d,",cap_count,in_count,out_count,status_count);
      $fdisplay(state_fd,"\"input_count\":%0d,\"output_count\":%0d,\"frame_seq\":%0d,\"stall_cycles\":%0d}",input_count,output_count,frame_seq,stall_cycles);
      $fclose(state_fd);
      $display("CHAIN_CASE_CAPTURE_PASS: %s",name);
    end
  endtask

  task automatic fault_latch_tests;
    begin
      $readmemh({result_dir,"/zero_rect/input_s24.hex"},samples);
      write_axi(0,1,15,2);send_samples(32,0);
      @(negedge clk);audio_overflow=1;repeat(2)@(negedge clk);audio_overflow=0;
      if(!status[3])$fatal(1,"Input overflow not latched");
      write_axi(0,2,15,2);wait_config();if(!status[3]||!status[9])$fatal(1,"ABORT diagnostic preservation");
      write_axi(0,4,15,2);if(status[9:0]!==10'h100)$fatal(1,"CLEAR sticky faults");
      write_axi(0,1,15,2);
      @(negedge clk);audio_data=0;audio_valid=1;audio_last=1;
      do @(posedge clk);while(!audio_ready);@(negedge clk);audio_valid=0;audio_last=0;
      if(!status[6])$fatal(1,"Unexpected input TLAST not latched");
      write_axi(0,2,15,2);wait_config();write_axi(0,4,15,2);
      write_axi(0,1,15,2);suppress_audio_last=1;send_samples(1024,0);suppress_audio_last=0;wait_done();
      if(!status[5]||status[0])$fatal(1,"Missing input TLAST not latched");
      write_axi(0,4,15,2);
      write_axi(0,1,15,2);send_samples(32,0);
      @(negedge clk);inject_fft_overflow=1;repeat(2)@(negedge clk);inject_fft_overflow=0;
      if(!status[4])$fatal(1,"FFT event detector not latched");
      write_axi(0,2,15,2);wait_config();write_axi(0,4,15,2);
      $display("FAULT_LATCH_PASS: input overflow, early/missing TLAST, injected FFT event, sticky/CLEAR/ABORT");
    end
  endtask
  task automatic abort_test(input bit during_output);
    integer n,old_configs;
    begin
      $readmemh({result_dir,"/bin16_rect/input_s24.hex"},samples);
      write_axi(0,4,15,2);write_axi(0,1,15,2);
      if(during_output)begin stalls=0;spectrum_ready=0;send_samples(1024,0);wait(spectrum_valid);repeat(8)@(negedge clk);end
      else send_samples(32,0);
      old_sequence=frame_seq;old_configs=configs;
      write_axi(0,3,15,2); // ABORT has priority over START.
      if(status[0]||!status[9]||frame_seq!=old_sequence)$fatal(1,"ABORT semantics");
      if(core_resetn)$fatal(1,"ABORT reset not asserted");
      repeat(4)begin @(negedge clk);if(core_resetn)$fatal(1,"Reset pulse too short");end
      wait_config();if(configs!=old_configs+1)$fatal(1,"Automatic reconfiguration");
      spectrum_ready=1;stalls=1;
      write_axi(0,4,15,1);if(status[9]||input_count||output_count||frame_seq!=old_sequence)$fatal(1,"CLEAR semantics");
      $display("ABORT_RECOVERY_PASS: during_output=%0d",during_output);
    end
  endtask

  integer n;
  initial begin
    if(!$value$plusargs("RESULT_DIR=%s",result_dir))$fatal(1,"RESULT_DIR");
    boundary[0]=24'h800000;boundary[1]=24'h8000ff;boundary[2]=-257;boundary[3]=-256;boundary[4]=-255;
    boundary[5]=-1;boundary[6]=0;boundary[7]=1;boundary[8]=255;boundary[9]=256;boundary[10]=24'h7fffff;
    expected_boundary[0]=-32768;expected_boundary[1]=-32768;expected_boundary[2]=-2;expected_boundary[3]=-1;
    expected_boundary[4]=-1;expected_boundary[5]=-1;expected_boundary[6]=0;expected_boundary[7]=0;
    expected_boundary[8]=0;expected_boundary[9]=1;expected_boundary[10]=32767;
    repeat(8)@(negedge clk);resetn=1;
    write_axi(0,1,15,2);wait_config();if(!status[7]||frame_seq!=0)$fatal(1,"START before config");
    read_axi(12,value);if(value!=1024)$fatal(1,"LENGTH");
    write_axi(16,0,15,3);read_axi(16,value);if(value!==32'h46465401)$fatal(1,"VERSION read only");
    write_axi(4,1,2,1);read_axi(4,value);if(value!=0)$fatal(1,"WSTRB WINDOW");
    write_axi(0,1,0,2);if(frame_seq!=0)$fatal(1,"WSTRB COMMAND");
    write_axi(0,5,15,2);if(frame_seq!=0||status[7])$fatal(1,"CLEAR priority");
    probe_reset=1;
    for(n=0;n<11;n=n+1)begin
      @(negedge clk);probe_data=boundary[n];probe_valid=1;probe_last=(n==10);
      do @(posedge clk);while(!probe_ready);
    end
    @(negedge clk);probe_valid=0;repeat(3)@(negedge clk);
    if(probe_count!=11)$fatal(1,"Boundary test count");
    $display("SIGNED24_BOUNDARIES_PASS: 11");
    stalls=1;
    run_case("zero_rect",0,0);run_case("zero_hann",1,0);
    run_case("dc_rect",0,0);run_case("dc_hann",1,0);
    run_case("impulse_rect",0,0);run_case("impulse_hann",1,0);
    run_case("bin16_rect",0,1);run_case("bin16_hann",1,1);
    run_case("bin16p35_rect",0,0);run_case("bin16p35_hann",1,0);
    run_case("bin16_bin70_rect",0,0);run_case("bin16_bin70_hann",1,0);
    abort_test(0);run_case("bin16_rect_recovery",0,0);
    abort_test(1);run_case("impulse_hann_recovery",1,0);
    fault_latch_tests();
    marker_fd=$fopen({result_dir,"/CHAIN_CAPTURE_PASS.txt"},"w");
    $fdisplay(marker_fd,"CHAIN_CAPTURE_PASS: 12 main + 2 recovery; numeric verification pending");$fclose(marker_fd);
    $display("CHAIN_CAPTURE_PASS: 14 actual frames; numeric verification pending");$finish;
  end
  initial begin #50000000;$fatal(1,"GLOBAL_WATCHDOG 50ms");end
endmodule
