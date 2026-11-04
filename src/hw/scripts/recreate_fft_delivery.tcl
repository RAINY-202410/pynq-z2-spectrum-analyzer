# Native BD export plus source files. Run from the packaged sources directory.
# Usage: vivado -mode batch -source hw/scripts/recreate_fft_delivery.tcl -tclargs D:/new_short_path
set root [file normalize [file join [file dirname [info script]] .. ..]]
if {$argc != 1} {error "Provide one new absolute project directory"}
set work [file normalize [lindex $argv 0]]
if {[file exists $work]} {error "Project directory must not already exist: $work"}
if {[llength [get_projects -quiet]]} {error "Use a fresh Vivado project context"}
if {[version -short] ne "2026.1"} {error "Vivado 2026.1 required"}
set board_repo [file normalize [file join $root .. build board_files]]
set_param board.repoPaths [list $board_repo]
create_project fft $work -part xc7z020clg400-1
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]
set_property target_language Verilog [current_project]
foreach rel {hw/rtl/dbg_stat.v hw/rtl/i2s/axis.sv hw/rtl/i2s/rising_edge.sv hw/rtl/i2s/i2s_serdes.sv hw/rtl/i2s/i2s_capture.sv hw/rtl/i2s/i2s_capture_wrapper.v hw/rtl/fft/fft_window_axis.v hw/rtl/fft/fft_complex_pack.v hw/rtl/fft/fft_frame_engine.v hw/rtl/fft/fft_ctrl_axi.v hw/rtl/fft/fft_frame_engine_bd.v hw/rtl/fft/fft_ctrl_axi_bd.v hw/rtl/fft/hann_coeff_u16.mem} {
  add_files -norecurse [file join $root $rel]
}
foreach rel {hw/constraints/i2s_audio.xdc hw/constraints/m3_led.xdc} {add_files -fileset constrs_1 -norecurse [file join $root $rel]}
source -notrace [file join $root hw ip fft_system_bd.tcl]
set bd [get_files */system.bd]
if {[llength $bd] != 1} {error "Native BD reconstruction failed"}
validate_bd_design
save_bd_design
generate_target all $bd
add_files -norecurse [make_wrapper -files $bd -top]
set_property TOP system_wrapper [get_filesets sources_1]
update_compile_order -fileset sources_1
create_ip_run $bd
puts "FFT_RECREATED: xc7z020clg400-1; system_wrapper; inspect reports before launching synthesis"
