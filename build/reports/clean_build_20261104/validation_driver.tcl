set closeout_root D:/AMD_compitition/_pf04
set closeout_package [file join $closeout_root pynq_z2_spectrum_analyzer]
set closeout_receipt [open [file join $closeout_root stages.log] w]
proc closeout_stage {name} {
    global closeout_receipt
    puts $closeout_receipt $name
    flush $closeout_receipt
    puts "CLOSEOUT_STAGE: $name"
}
if {[catch {
    closeout_stage FFT_BUILD_STARTED
    set argv [list [file join $closeout_root fft_build]]
    set argc 1
    source [file join $closeout_package build scripts rebuild_fft.tcl]
    closeout_stage FFT_SYNTH_IMPLEMENT_BITSTREAM_PASS
    close_project

    closeout_stage FFT_COMPILE_ELABORATE_STARTED
    source [file join $closeout_package build scripts sim_fft_chain.tcl]
    fft_chain::prepare [file join $closeout_root fft_sim] [file join $closeout_root fft_inputs]
    if {[get_property TOP [get_filesets sim_1]] ne "tb_fft_chain"} {error "Wrong compile top"}
    set_property GENERATE_SCRIPTS_ONLY true [get_filesets sim_1]
    launch_simulation -simset sim_1 -mode behavioral -scripts_only
    set_property GENERATE_SCRIPTS_ONLY false [get_filesets sim_1]
    launch_simulation -simset sim_1 -mode behavioral -step compile -exec
    launch_simulation -simset sim_1 -mode behavioral -step elaborate -exec -noclean_dir
    closeout_stage FFT_COMPILE_ELABORATE_PASS_NO_FUNCTIONAL_RUN
    close_project

    closeout_stage M4_BUILD_STARTED
    set argv {}
    set argc 0
    source [file join $closeout_package build scripts build_m4_from_sources.tcl]
    closeout_stage M4_SYNTH_IMPLEMENT_BITSTREAM_PASS
    close_project
    closeout_stage CLEAN_BUILD_VALIDATION_COMPLETE
} closeout_error closeout_options]} {
    closeout_stage "FAILED: $closeout_error"
    puts stderr [dict get $closeout_options -errorinfo]
    close $closeout_receipt
    exit 1
}
close $closeout_receipt
exit 0
