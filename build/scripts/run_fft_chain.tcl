# Usage: vivado -mode batch -source build/scripts/run_fft_chain.tcl -tclargs <new_project> <prepared_results>
set repo [file normalize [file join [file dirname [info script]] .. ..]]
if {$argc != 2} {error "Provide new project directory and prepared result directory"}
source [file join $repo build scripts sim_fft_chain.tcl]
set work [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
fft_chain::prepare $work $out
fft_chain::run $work $out
