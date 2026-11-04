`timescale 1ns/1ps
// Native FFT capture only. Numerical acceptance is performed by verify_fft_rect.py.
module tb_fft_rect;
  localparam integer N = 1024;
  reg clk = 0;
  always #5 clk = ~clk;
  reg rstn = 0, cfg_valid = 0, in_valid = 0, in_last = 0;
  reg [15:0] cfg_data = 16'h0557;
  reg [31:0] in_data = 0;
  wire cfg_ready, in_ready, out_valid, out_last, status_valid;
  wire [31:0] out_data;
  wire [7:0] out_user, status_data;
  wire frame_started, tlast_missing, tlast_unexpected, fft_overflow;
  wire in_halt, out_halt, status_halt;
  reg [15:0] samples [0:N-1];
  string result_dir, case_name;
  integer cycle = 0, case_begin = 0, cfg_cycle, first_input_cycle;
  integer config_count, input_count, output_count, status_count;
  integer input_last_count, output_last_count, input_last_index, output_last_index;
  integer frame_events, missing_events, unexpected_events, overflow_events;
  integer in_halt_events, out_halt_events, status_halt_events, raw_status;
  integer raw_fd, csv_fd, input_fd, json_fd, marker_fd, probe_fd;
  bit active = 0, overflow_seen;

  // Instantiate the managed BD wrapper so Vivado includes its IP dependencies.
  contract_probe_wrapper dut (
    .aclk_0(clk), .aresetn_0(rstn),
    .S_AXIS_CONFIG_0_tdata(cfg_data), .S_AXIS_CONFIG_0_tvalid(cfg_valid),
    .S_AXIS_CONFIG_0_tready(cfg_ready),
    .S_AXIS_DATA_0_tdata(in_data), .S_AXIS_DATA_0_tvalid(in_valid),
    .S_AXIS_DATA_0_tready(in_ready), .S_AXIS_DATA_0_tlast(in_last),
    .M_AXIS_DATA_0_tdata(out_data), .M_AXIS_DATA_0_tuser(out_user),
    .M_AXIS_DATA_0_tvalid(out_valid), .M_AXIS_DATA_0_tready(1'b1),
    .M_AXIS_DATA_0_tlast(out_last),
    .M_AXIS_STATUS_0_tdata(status_data), .M_AXIS_STATUS_0_tvalid(status_valid),
    .M_AXIS_STATUS_0_tready(1'b1), .event_frame_started_0(frame_started),
    .event_tlast_missing_0(tlast_missing), .event_tlast_unexpected_0(tlast_unexpected),
    .event_fft_overflow_0(fft_overflow), .event_data_in_channel_halt_0(in_halt),
    .event_data_out_channel_halt_0(out_halt), .event_status_channel_halt_0(status_halt)
  );

  // Driver changes on falling edges; monitor samples stable payload at rising edges.
  always @(posedge clk) begin
    cycle = cycle + 1;
    if (active && rstn) begin
      if (cycle - case_begin > 100000)
        $fatal(1, "WATCHDOG case=%s in=%0d out=%0d status=%0d", case_name, input_count, output_count, status_count);
      if (cfg_valid && cfg_ready) begin
        if (cfg_data !== 16'h0557) $fatal(1, "Wrong config");
        config_count = config_count + 1;
        cfg_cycle = cycle;
      end
      if (in_valid && in_ready) begin
        if (config_count != 1 || cycle <= cfg_cycle) $fatal(1, "Input before config");
        if ($isunknown({in_data, in_last})) $fatal(1, "Unknown input");
        if (input_count == 0) first_input_cycle = cycle;
        $fdisplay(input_fd, "%08x", in_data);
        if (in_last) begin
          input_last_count = input_last_count + 1;
          input_last_index = input_count;
        end
        if (in_last !== (input_count == N-1)) $fatal(1, "Input TLAST position");
        input_count = input_count + 1;
        if (input_count > N) $fatal(1, "Extra input");
      end
      if (out_valid) begin
        if ($isunknown({out_data, out_last, out_user})) $fatal(1, "Unknown output");
        if (output_count >= N) $fatal(1, "Extra output");
        $fdisplay(raw_fd, "%08x", out_data);
        $fdisplay(csv_fd, "%0d,%0d,%0d,%0d,%0d,%0d", output_count,
                  $signed(out_data[15:0]), $signed(out_data[31:16]), out_last, out_user, cycle);
        if (out_last) begin
          output_last_count = output_last_count + 1;
          output_last_index = output_count;
        end
        if (out_last !== (output_count == N-1)) $fatal(1, "Output TLAST position");
        overflow_seen = overflow_seen | out_user[0];
        output_count = output_count + 1;
      end
      if (status_valid) begin
        if ($isunknown(status_data)) $fatal(1, "Unknown status");
        status_count = status_count + 1;
        raw_status = status_data;
        overflow_seen = overflow_seen | status_data[0];
      end
      frame_events = frame_events + frame_started;
      missing_events = missing_events + tlast_missing;
      unexpected_events = unexpected_events + tlast_unexpected;
      overflow_events = overflow_events + fft_overflow;
      overflow_seen = overflow_seen | fft_overflow;
      in_halt_events = in_halt_events + in_halt;
      out_halt_events = out_halt_events + out_halt;
      status_halt_events = status_halt_events + status_halt;
    end
  end

  task automatic run_case(input string name);
    integer n;
    string folder;
    begin
      @(negedge clk);
      active = 0; rstn = 0; cfg_valid = 0; in_valid = 0; in_last = 0;
      case_name = name;
      folder = {result_dir, "/", name};
      probe_fd = $fopen({folder, "/input_q15.hex"}, "r");
      if (!probe_fd) $fatal(1, "Missing staged input: %s", folder);
      $fclose(probe_fd);
      $readmemh({folder, "/input_q15.hex"}, samples);
      raw_fd = $fopen({folder, "/actual_fft32.hex"}, "w");
      csv_fd = $fopen({folder, "/actual_components.csv"}, "w");
      input_fd = $fopen({folder, "/actual_input32.hex"}, "w");
      if (!raw_fd || !csv_fd || !input_fd) $fatal(1, "Cannot open capture files");
      $fdisplay(csv_fd, "index,real_i16,imag_i16,tlast,tuser,cycle");
      config_count=0; input_count=0; output_count=0; status_count=0;
      input_last_count=0; output_last_count=0; input_last_index=-1; output_last_index=-1;
      frame_events=0; missing_events=0; unexpected_events=0; overflow_events=0;
      in_halt_events=0; out_halt_events=0; status_halt_events=0;
      raw_status=0; overflow_seen=0; cfg_cycle=-1; first_input_cycle=-1;
      repeat (6) @(negedge clk);
      case_begin = cycle; active = 1; rstn = 1;
      repeat (4) @(negedge clk);
      cfg_data = 16'h0557; cfg_valid = 1;
      do @(posedge clk); while (cfg_ready !== 1'b1);
      @(negedge clk); cfg_valid = 0;
      for (n=0; n<N; n=n+1) begin
        @(negedge clk);
        in_data = {16'h0000, samples[n]};
        in_last = (n == N-1); in_valid = 1;
        do @(posedge clk); while (in_ready !== 1'b1);
      end
      @(negedge clk); in_valid = 0; in_last = 0;
      wait (output_count == N && status_count >= 1);
      repeat (32) @(negedge clk);
      if (config_count != 1 || input_count != N || output_count != N || status_count != 1 ||
          input_last_count != 1 || output_last_count != 1 || overflow_seen ||
          missing_events != 0 || unexpected_events != 0)
        $fatal(1, "Frame check failed: %s", name);
      $fclose(raw_fd); $fclose(csv_fd); $fclose(input_fd);
      json_fd = $fopen({folder, "/frame_status.json"}, "w");
      if (!json_fd) $fatal(1, "Cannot open status record");
      $fdisplay(json_fd, "{");
      $fdisplay(json_fd, "\"source\":\"XSIM_NATIVE_FFT_CAPTURE\",\"case\":\"%s\",", name);
      $fdisplay(json_fd, "\"config_word\":\"0x0557\",\"config_handshake_count\":%0d,", config_count);
      $fdisplay(json_fd, "\"config_accept_cycle\":%0d,\"first_input_cycle\":%0d,", cfg_cycle, first_input_cycle);
      $fdisplay(json_fd, "\"input_count\":%0d,\"output_count\":%0d,", input_count, output_count);
      $fdisplay(json_fd, "\"input_tlast_count\":%0d,\"output_tlast_count\":%0d,", input_last_count, output_last_count);
      $fdisplay(json_fd, "\"input_tlast_index\":%0d,\"output_tlast_index\":%0d,", input_last_index, output_last_index);
      $fdisplay(json_fd, "\"status_handshake_count\":%0d,\"raw_status\":%0d,", status_count, raw_status);
      $fdisplay(json_fd, "\"overflow\":%0d,\"frame_started_events\":%0d,", overflow_seen, frame_events);
      $fdisplay(json_fd, "\"tlast_missing_events\":%0d,\"tlast_unexpected_events\":%0d,", missing_events, unexpected_events);
      $fdisplay(json_fd, "\"fft_overflow_events\":%0d,\"input_halt_cycles\":%0d,", overflow_events, in_halt_events);
      $fdisplay(json_fd, "\"output_halt_cycles\":%0d,\"status_halt_cycles\":%0d,", out_halt_events, status_halt_events);
      $fdisplay(json_fd, "\"begin_cycle\":%0d,\"end_cycle\":%0d,\"timeout\":false}", case_begin, cycle);
      $fclose(json_fd);
      active = 0;
      $display("CASE_CAPTURE_PASS: %s input=%0d output=%0d", name, input_count, output_count);
    end
  endtask

  initial begin
    if (!$value$plusargs("RESULT_DIR=%s", result_dir)) $fatal(1, "Missing +RESULT_DIR");
    run_case("zero_rect"); run_case("dc_rect");
    run_case("impulse_rect"); run_case("bin16_rect");
    marker_fd = $fopen({result_dir, "/TB_CAPTURE_PASS.txt"}, "w");
    if (!marker_fd) $fatal(1, "Cannot write capture marker");
    $fdisplay(marker_fd, "TB_CAPTURE_PASS: 4 frames, 4096 output points; numerical check pending");
    $fclose(marker_fd);
    $display("TB_CAPTURE_PASS: 4 frames; numerical check pending");
    $finish;
  end
  initial begin
    #5000000;
    $fatal(1, "GLOBAL_WATCHDOG: 5ms");
  end
endmodule
