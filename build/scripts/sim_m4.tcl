# Usage: vivado -mode batch -source build/scripts/sim_m4.tcl -tclargs <new_absolute_workdir>
set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {$argc != 1} {error "Provide a new absolute project directory"}
set work [file normalize [lindex $argv 0]]
if {[file exists $work]} {error "Use a fresh directory"}
create_project m4_packet_test $work -part xc7z020clg400-1
add_files -norecurse [file join $repo src hw rtl i2s i2s_capture_wrapper.v]
add_files -fileset sim_1 -norecurse [file join $repo sim m4 tb_m4_delivery.v]
set_property top tb_m4_delivery [get_filesets sim_1]
set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
launch_simulation -simset sim_1 -mode behavioral
run all
set pass [file join $work m4_packet_test.sim sim_1 behav xsim m4_packet_test.pass]
if {![file exists $pass]} {error "No packetizer PASS marker"}
close_sim
