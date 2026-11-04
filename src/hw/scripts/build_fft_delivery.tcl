# Reuse the validated M4 PS/I2S/DMA BD in a new project; never edit the M4 BD.
namespace eval fft_hw {variable root [file normalize [file join [file dirname [info script]] .. ..]]}
proc fft_hw::write_text {path data} {set f [open $path w];puts $f $data;close $f}
proc fft_hw::wire {a b} {
  if {[llength $a] != 1 || [llength $b] != 1} {error "Expected two scalar pins: $a / $b"}
  set an [get_bd_nets -quiet -of_objects $a]
  set bn [get_bd_nets -quiet -of_objects $b]
  if {$an ne "" && $an eq $bn} {return}
  connect_bd_net $a $b
}
proc fft_hw::intf {a b} {
  if {[llength $a] != 1 || [llength $b] != 1} {error "Expected two interfaces: $a / $b"}
  set an [get_bd_intf_nets -quiet -of_objects $a]
  set bn [get_bd_intf_nets -quiet -of_objects $b]
  if {$an ne "" && $an eq $bn} {return}
  connect_bd_intf_net $a $b
}
proc fft_hw::prepare {work output} {
  variable root
  if {[file exists $work]} {error "New project directory required: $work"}
  if {![file exists [file join $output inputs.json]]} {error "Run prepare_fft_hardware.py first"}
  if {[version -short] ne "2026.1"} {error "Vivado 2026.1 required"}
  if {[llength [get_projects -quiet]]} {error "Close the current project first"}
  create_project fft $work -part xc7z020clg400-1
  set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
  set_property target_language Verilog [current_project]
  foreach rel {hw/rtl/axi_lite_ctrl.v hw/rtl/dbg_stat.v hw/rtl/i2s/axis.sv hw/rtl/i2s/rising_edge.sv hw/rtl/i2s/i2s_serdes.sv hw/rtl/i2s/i2s_capture.sv hw/rtl/i2s/i2s_capture_wrapper.v hw/rtl/fft/fft_window_axis.v hw/rtl/fft/fft_complex_pack.v hw/rtl/fft/fft_frame_engine.v hw/rtl/fft/fft_ctrl_axi.v hw/rtl/fft/fft_frame_engine_bd.v hw/rtl/fft/fft_ctrl_axi_bd.v hw/rtl/fft/hann_coeff_u16.mem} {
    add_files -norecurse [file join $root $rel]
  }
  foreach rel {hw/constraints/i2s_audio.xdc hw/constraints/m3_led.xdc} {add_files -fileset constrs_1 -norecurse [file join $root $rel]}
  import_files -norecurse [file join $root build m4_delivery_20261018 m4.srcs sources_1 bd system system.bd]
  set bd [get_files */system.bd]
  if {[llength $bd] != 1 || [string first [file normalize $work] [file normalize $bd]] != 0} {error "BD must be a private copy in new project"}
  open_bd_design $bd
  # Preserve the original PS parameters. PCW_M_AXI_GP0_FREQMHZ is a read-only
  # legacy annotation (10); the connected interface and FCLK both report 100 MHz.
  # The failed annotation-write probe is retained separately, never replayed.
  # Replace the legacy register slave in its existing interconnect slot.
  delete_bd_objs [get_bd_cells axi_lite_ctrl_0]
  create_bd_cell -type module -reference fft_ctrl_axi_bd fft_ctrl_0
  create_bd_cell -type module -reference fft_frame_engine_bd fft_engine_0
  set f [open [file join $output expected_config.tcldict] r];set expected [read $f];close $f
  set receipt [ipcfg::capture [file join $output fft_create.tcldict] [list ipcfg::create_cell_cfg xilinx.com:ip:xfft:9.1 fft_0 $expected] {SUCCESS:created+configured}]
  if {[dict get $receipt status] ne "OK"} {error "FFT creation failed: $receipt"}
  # A native slice fans out the existing capture overflow bit without changing I2S RTL.
  set receipt [ipcfg::capture [file join $output overflow_slice_create.tcldict] [list ipcfg::create_cell_cfg xilinx.com:ip:xlslice:1.0 capture_overflow_slice [dict create CONFIG.DIN_WIDTH 32 CONFIG.DIN_FROM 1 CONFIG.DIN_TO 1 CONFIG.DOUT_WIDTH 1]] {SUCCESS:created+configured}]
  if {[dict get $receipt status] ne "OK"} {error "Overflow slice failed: $receipt"}
  set rows ""
  foreach cell {fft_ctrl_0 fft_engine_0} {
    append rows "$cell INTERFACES: [get_bd_intf_pins -of_objects [get_bd_cells $cell]]\n"
    append rows "$cell PINS: [get_bd_pins -of_objects [get_bd_cells $cell]]\n"
  }
  write_text [file join $output module_interfaces.txt] $rows
  save_bd_design
  puts "FFT_HW_COMPONENTS_CREATED: private BD copy, part=[get_property PART [current_project]]"
}
proc fft_hw::connect_and_validate {work output} {
  variable root
  # Preserve the PS DDR and DMA path; replace only the stream between capture and DMA.
  set audio_net [get_bd_intf_nets -of_objects [get_bd_intf_pins i2s_capture_0/m_axis]]
  if {$audio_net ne "" && [get_bd_intf_nets -quiet -of_objects [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]] eq $audio_net} {delete_bd_objs $audio_net}
  intf [get_bd_intf_pins i2s_capture_0/m_axis] [get_bd_intf_pins fft_engine_0/s_axis_audio]
  intf [get_bd_intf_pins fft_engine_0/m_axis_spectrum] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]
  intf [get_bd_intf_pins axi_ic_0/M01_AXI] [get_bd_intf_pins fft_ctrl_0/s_axi]
  foreach {engine core} {m_axis_config S_AXIS_CONFIG m_axis_fft S_AXIS_DATA s_axis_fft M_AXIS_DATA s_axis_status M_AXIS_STATUS} {
    intf [get_bd_intf_pins fft_engine_0/$engine] [get_bd_intf_pins fft_0/$core]
  }
  foreach name {start_cmd abort_cmd clear_cmd window_requested} {
    wire [get_bd_pins fft_ctrl_0/$name] [get_bd_pins fft_engine_0/$name]
  }
  foreach name {status input_count output_count frame_sequence} {
    wire [get_bd_pins fft_engine_0/$name] [get_bd_pins fft_ctrl_0/$name]
  }
  wire [get_bd_pins fft_engine_0/capture_ctrl] [get_bd_pins i2s_capture_0/capture_ctrl]
  wire [get_bd_pins i2s_capture_0/dbg_snap] [get_bd_pins capture_overflow_slice/Din]
  wire [get_bd_pins capture_overflow_slice/Dout] [get_bd_pins fft_engine_0/audio_overflow]
  wire [get_bd_pins fft_engine_0/fft_resetn] [get_bd_pins fft_0/aresetn]
  foreach name {event_tlast_missing event_tlast_unexpected event_fft_overflow} {
    wire [get_bd_pins fft_0/$name] [get_bd_pins fft_engine_0/$name]
  }
  foreach pin {fft_ctrl_0/s_axi_aclk fft_engine_0/clk fft_0/aclk} {wire [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins $pin]}
  foreach pin {fft_ctrl_0/s_axi_aresetn fft_engine_0/resetn} {wire [get_bd_pins rst_100m/peripheral_aresetn] [get_bd_pins $pin]}
  # Clock/reset associations are supplied by identity wrappers, not read-only pin writes.
  # Module-reference replacement can leave empty scalar nets in the private BD.
  foreach net [get_bd_nets] {
    if {![llength [get_bd_pins -quiet -of_objects $net]] && ![llength [get_bd_ports -quiet -of_objects $net]]} {delete_bd_objs $net}
  }
  assign_bd_address
  validate_bd_design
  save_bd_design
  foreach pin {ps7_0/M_AXI_GP0 fft_ctrl_0/s_axi} {
    if {[get_property CONFIG.FREQ_HZ [get_bd_intf_pins $pin]] != 100000000} {error "Interface is not 100 MHz: $pin"}
  }
  write_text [file join $output clock_annotation_note.txt] "FCLK_CLK0 and GP0/FFT AXI interfaces: 100000000 Hz. Original read-only PS parameter PCW_M_AXI_GP0_FREQMHZ=[get_property CONFIG.PCW_M_AXI_GP0_FREQMHZ [get_bd_cells ps7_0]] MHz retained. Direct annotation write was unapplied:integration-derived; original failed probe/ledger retained. No PS physical clocks/DDR/PLL change."
  set f [open [file join $output expected_config.tcldict] r];set expected [read $f];close $f
  set rows "property\texpected\tactual\n"
  dict for {key value} $expected {
    set actual [get_property $key [get_bd_cells fft_0]]
    if {$value in {true false}} {
      if {[expr {!!$value}] != [expr {!!$actual}]} {error "FFT readback mismatch: $key"}
    } elseif {$actual ne $value} {error "FFT readback mismatch: $key"}
    append rows "$key\t$value\t$actual\n"
  }
  write_text [file join $output fft_readback.tsv] $rows
  if {[get_property CONFIG.c_include_mm2s [get_bd_cells axi_dma_0]] != 0 || [get_property CONFIG.c_s_axis_s2mm_tdata_width [get_bd_cells axi_dma_0]] != 64} {error "DMA mode/width mismatch"}
  set addresses ""
  foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps7_0/Data]] {append addresses "[get_property NAME $seg]\t[get_property OFFSET $seg]\t[get_property RANGE $seg]\n"}
  write_text [file join $output address_map.tsv] $addresses
  set bd [get_files */system.bd]
  generate_target all $bd
  set wrapper [make_wrapper -files $bd -top]
  if {![llength [get_files -quiet $wrapper]]} {add_files -norecurse $wrapper}
  set_property TOP system_wrapper [get_filesets sources_1]
  update_compile_order -fileset sources_1
  write_bd_tcl -force [file join $output fft_system_bd.tcl]
  puts "FFT_HW_BD_VALIDATED: part=[get_property PART [current_project]]; top=system_wrapper; DMA=S2MM64"
}
proc fft_hw::reports {output} {
  report_timing_summary -report_unconstrained -check_timing_verbose -file [file join $output timing.rpt]
  report_clocks -file [file join $output clocks.rpt]
  report_cdc -details -file [file join $output cdc.rpt]
  report_utilization -file [file join $output utilization.rpt]
  check_timing -verbose -file [file join $output check_timing.rpt]
  report_methodology -file [file join $output methodology.rpt]
  report_methodology -json [file join $output methodology.json]
  report_drc -file [file join $output drc.rpt]
  write_xdc -force -exclude_physical [file join $output implemented_constraints.xdc]
  set rows "part\t[get_property PART [current_project]]\n"
  foreach key {WNS TNS WHS THS} {append rows "$key\t[get_property STATS.$key [get_runs impl_1]]\n"}
  append rows "run_status\t[get_property STATUS [get_runs impl_1]]\n"
  set mclk [get_clocks codec_mclk_10m]
  if {[llength $mclk] != 1 || [get_property PERIOD $mclk] != 100} {error "Codec generated clock is missing/not 10MHz"}
  append rows "codec_mclk_period_ns\t[get_property PERIOD $mclk]\n"
  write_text [file join $output implementation_metrics.tsv] $rows
}
