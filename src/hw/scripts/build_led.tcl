# build_led.tcl -- steps A-1 / A-4
#
# Pure PL design: board oscillator (H16, 125 MHz) -> counter -> four LEDs.
# No Block Design, no PS7, no board files, no AXI automation. All messages are
# ASCII on purpose: Tcl reads scripts with the system code page on Chinese
# Windows, so non-ASCII text in a .tcl file can be mis-decoded.
# Chinese notes live in docs/a_week1_2_runbook.md.
#
# Usage (from the project root, or run hw/scripts/build_led.bat):
#   D:/AMDDesignTools/2026.1/Vivado/bin/vivado.bat -mode batch -source hw/scripts/build_led.tcl

set script_dir [file dirname [file normalize [info script]]]
set root       [file normalize [file join $script_dir ".." ".."]]
set build_dir  [file join $root "build" "led_blink"]

puts "== project root : $root"
puts "== build dir    : $build_dir"

create_project led_blink $build_dir -part xc7z020clg400-1 -force

add_files -norecurse [list \
    [file join $root "hw" "rtl" "counter.v"] \
    [file join $root "hw" "rtl" "led_top.v"]]
add_files -fileset constrs_1 -norecurse [list [file join $root "hw" "constraints" "led_counter.xdc"]]
add_files -fileset sim_1 -norecurse [list [file join $root "sim" "tb_counter.v"]]

set_property top led_top [get_filesets sources_1]
set_property top tb_counter [get_filesets sim_1]
set_property -name {xsim.simulate.runtime} -value {all} -objects [get_filesets sim_1]
update_compile_order -fileset sources_1

puts "== running synthesis"
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "== synth_1 status: $synth_status"
if {![string match -nocase "*complete*" $synth_status]} {
    error "synth_1 did not finish; see $build_dir/led_blink.runs/synth_1/runme.log"
}

puts "== running implementation and bitstream"
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "== impl_1 status: $impl_status"
if {![string match -nocase "*complete*" $impl_status]} {
    error "impl_1 did not finish; see $build_dir/led_blink.runs/impl_1/runme.log"
}

set impl_dir [file join $build_dir "led_blink.runs" "impl_1"]
set bit [file join $impl_dir "led_top.bit"]
if {[file exists $bit]} {
    puts "== bitstream: $bit"
} else {
    puts "WARNING: expected bitstream not found, listing what was produced:"
    foreach f [glob -nocomplain -directory $impl_dir "*.bit"] {
        puts "== bitstream: $f"
    }
}

puts "DONE: LED design built"
