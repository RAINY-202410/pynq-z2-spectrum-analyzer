namespace eval fft_chain {
  variable root [file normalize [file join [file dirname [info script]] .. ..]]
}
proc fft_chain::prepare {work output} {
  variable root
  uplevel #0 [list source -notrace [file join $root build scripts sim_fft_rect.tcl]]
  ::fft_rect::prepare $work $output
  foreach name {fft_window_axis.v fft_complex_pack.v fft_frame_engine.v fft_ctrl_axi.v hann_coeff_u16.mem} {
    add_files -norecurse [file join $root src hw rtl fft $name]
  }
  add_files -fileset sim_1 -norecurse [file join $root sim rtl_fft tb_fft_chain.sv]
  set_property TOP tb_fft_chain [get_filesets sim_1]
  set_property TOP_LIB xil_defaultlib [get_filesets sim_1]
  set_property SOURCE_SET sources_1 [get_filesets sim_1]
  update_compile_order -fileset sources_1
  update_compile_order -fileset sim_1
  puts "CHAIN_PREPARED: [get_property PART [current_project]] top=tb_fft_chain"
}
proc fft_chain::run {work output} {
  if {![llength [get_projects -quiet]]} {open_project [file join $work fft_rect.xpr]}
  if {[get_property TOP [get_filesets sim_1]] ne "tb_fft_chain"} {error "Wrong simulation top"}
  if {[file exists [file join $output zero_rect actual_spectrum64.hex]]} {error "Use a fresh result directory for rerun"}
  set_property -dict [list xsim.simulate.xsim.more_options "-testplusarg RESULT_DIR=$output"] [get_filesets sim_1]
  set_property xsim.simulate.wdb [file join $output interface.wdb] [get_filesets sim_1]
  set_property GENERATE_SCRIPTS_ONLY false [get_filesets sim_1]
  set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
  launch_simulation -simset sim_1 -mode behavioral
  log_wave [get_objects /tb_fft_chain/*]
  ::run 50ms
  if {![file exists [file join $output CHAIN_CAPTURE_PASS.txt]]} {error "No chain capture PASS"}
  close_sim
  puts "CHAIN_CAPTURE_COMPLETE: numeric verification required"
}
