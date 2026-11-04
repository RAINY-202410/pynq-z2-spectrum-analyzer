# Usage: vivado -mode batch -source build/scripts/rebuild_fft.tcl -tclargs <new_absolute_workdir>
set repo [file normalize [file join [file dirname [info script]] .. ..]]
source [file join $repo src hw scripts recreate_fft_delivery.tcl]
launch_runs synth_1 -jobs 2
wait_on_run synth_1
if {![string match "*Complete*" [get_property STATUS [get_runs synth_1]]]} {error "Synthesis failed"}
launch_runs impl_1 -to_step write_bitstream -jobs 2
wait_on_run impl_1
if {![string match "*Complete*" [get_property STATUS [get_runs impl_1]]]} {error "Implementation failed"}
open_run impl_1
set reports [file join $work reports]
file mkdir $reports
report_utilization -file [file join $reports utilization.rpt]
report_timing_summary -report_unconstrained -check_timing_verbose -file [file join $reports timing.rpt]
report_clocks -file [file join $reports clocks.rpt]
report_cdc -details -file [file join $reports cdc.rpt]
report_drc -file [file join $reports drc.rpt]
puts "REBUILD_COMPLETE: new outputs only; existing frozen bit/hwh were not overwritten"
