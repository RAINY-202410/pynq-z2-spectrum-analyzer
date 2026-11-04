# Repair the missing output-clock constraint in the completed routed design.
# No RTL changes and no synthesis/place/route rerun. Execute with Vivado batch.
set script_dir [file dirname [file normalize [info script]]]
set root [file normalize [file join $script_dir .. ..]]
set build_dir [file join $root build m4_delivery_20261018]
set checkpoint [file join $build_dir m4.runs impl_1 system_wrapper_routed.dcp]
set hwh [file join $build_dir m4.gen sources_1 bd system hw_handoff system.hwh]
foreach f [list $checkpoint $hwh] {
    if {![file exists $f]} {error "Completed build output missing: $f"}
}
# Reject reuse if hardware sources changed after routing.
foreach rel {hw/rtl/axi_lite_ctrl.v hw/rtl/dbg_stat.v hw/rtl/i2s/axis.sv hw/rtl/i2s/rising_edge.sv hw/rtl/i2s/i2s_serdes.sv hw/rtl/i2s/i2s_capture.sv hw/rtl/i2s/i2s_capture_wrapper.v hw/constraints/m3_led.xdc hw/scripts/build_m4_delivery.tcl} {
    if {[file mtime [file join $root $rel]] > [file mtime $checkpoint]} {
        error "Source is newer than routed checkpoint; run full build instead: $rel"
    }
}
set report_dir [file join $build_dir mclk_constraint_recovery]
file mkdir $report_dir
open_checkpoint $checkpoint
puts "MCLK divider candidates: [get_cells -hier -filter {NAME =~ *codec_mclk_reg}]"
set divider_clock [get_pins -hier -quiet -filter {NAME =~ *codec_mclk_reg/C}]
if {[llength $divider_clock] != 1} {
    error "Expected exactly one codec_mclk_reg/C clock pin; found: $divider_clock"
}
# The old checkpoint has no MCLK clock. Allow a repeat of this repair.
set existing_mclk [get_clocks -quiet codec_mclk_10m]
if {[llength $existing_mclk]} {delete_clocks $existing_mclk}
read_xdc [file join $root hw constraints i2s_audio.xdc]
set mclk [get_clocks -quiet codec_mclk_10m]
if {[llength $mclk] != 1 || abs([get_property PERIOD $mclk] - 100.0) > 0.001} {
    error "codec_mclk_10m is missing or its period is not 100 ns"
}
puts "MCLK_CLOCK_PASS: [get_property NAME $mclk] period=[get_property PERIOD $mclk] ns"
report_timing_summary -file [file join $report_dir delivery_timing.rpt]
report_cdc -details -file [file join $report_dir delivery_cdc.rpt]
report_clocks -file [file join $report_dir delivery_clocks.rpt]
if {[llength [get_clocks -quiet codec_mclk_10m]] != 1} {
    error "codec_mclk_10m constraint missing; do not release this candidate"
}
foreach delay_type {max min} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $paths] && [get_property SLACK $paths] < 0} {
        error "Negative $delay_type timing slack; inspect delivery_timing.rpt"
    }
}
set out_dir [file join $build_dir "pynq"]
file mkdir $out_dir
write_checkpoint -force [file join $report_dir system_wrapper_mclk_fixed.dcp]
write_bitstream -force [file join $out_dir m4.bit]
file copy -force [file join $build_dir "m4.gen" "sources_1" "bd" "system" "hw_handoff" "system.hwh"] [file join $out_dir "m4.hwh"]
puts "== handoff pair ready: [file join $out_dir m4.bit] + m4.hwh"

foreach name {m4_delivery.py M4_acceptance.ipynb README_M4.md LICENSE.reed-foster.txt} {
    file copy -force [file join $root sw pynq $name] [file join $out_dir $name]
}
foreach name {delivery_timing.rpt delivery_clocks.rpt delivery_cdc.rpt} {
    file copy -force [file join $report_dir $name] [file join $out_dir $name]
}
file copy -force [file join $root build m4_delivery_packetizer_pass.txt] [file join $out_dir packetizer_simulation_pass.txt]
set h [open [file join $out_dir BUILD_INFO.txt] w]
puts $h "Vivado: [version -short]"
puts $h "Built: [clock format [clock seconds]]"
puts $h "Flow: existing routed checkpoint; MCLK constraint repaired and timing rechecked"
puts $h "Checkpoint: $checkpoint"
puts $h "Protocol: M4 delivery 20261018; fixed 1024 beats; CTRL-triggered"
close $h
puts "DONE: M4 MCLK constraint recovery complete"
puts "UPLOAD_DIR=$out_dir"
