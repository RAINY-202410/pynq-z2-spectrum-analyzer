# Source once, then call fft_rect::prepare, fft_rect::compile, or fft_rect::run.
namespace eval fft_rect {
  variable root [file normalize [file join [file dirname [info script]] .. ..]]
}

proc fft_rect::write_text {path data} {
  set stream [open $path w]
  puts $stream $data
  close $stream
}

proc fft_rect::prepare {work output} {
  variable root
  set work [file normalize $work]
  set output [file normalize $output]
  if {[file exists $work]} {error "Use a new short project directory: $work"}
  if {![file exists [file join $output preparation.json]]} {error "Run verify_fft_rect.py prepare first"}
  if {[llength [get_projects -quiet]]} {error "A project is already open; preserve it and use a separate session"}
  if {[version -short] ne "2026.1"} {error "Frozen tool version is Vivado 2026.1"}
  create_project fft_rect $work -part xc7z020clg400-1
  set_property target_language Verilog [current_project]
  set_property target_simulator XSim [current_project]
  uplevel #0 [list source -notrace [file join $root hw ip fft_contract_v02_bd.tcl]]
  set cell [get_bd_cells /fft_0]
  set stream [open [file join $output expected_config.tcldict] r]
  set expected [read $stream]
  close $stream
  set rows "property\trequested\tactual\n"
  dict for {key value} $expected {
    set actual [get_property $key $cell]
    if {$value in {true false}} {
      if {[expr {!!$value}] != [expr {!!$actual}]} {error "Frozen config mismatch: $key=$actual"}
    } elseif {$actual ne $value} {error "Frozen config mismatch: $key=$actual expected=$value"}
    append rows "$key\t$value\t$actual\n"
  }
  write_text [file join $output ip_readback.tsv] $rows
  if {[dict size $expected] != 17} {error "Expected 17 frozen properties"}
  if {[get_property PART [current_project]] ne "xc7z020clg400-1"} {error "Part mismatch"}
  set bd [get_files */contract_probe.bd]
  generate_target all $bd
  finish_prepare $work $output
}

proc fft_rect::finish_prepare {work output} {
  variable root
  if {[get_property PART [current_project]] ne "xc7z020clg400-1"} {error "Part mismatch"}
  set wrapper [file join $work fft_rect.gen sources_1 bd contract_probe hdl contract_probe_wrapper.v]
  if {![file exists $wrapper]} {error "Generated BD wrapper missing: $wrapper"}
  if {[lsearch -exact [get_files -of_objects [get_filesets sources_1]] $wrapper] < 0} {
    add_files -norecurse $wrapper
  }
  set_property top contract_probe_wrapper [get_filesets sources_1]
  set tb [file join $root sim tb_fft_rect.sv]
  if {[lsearch -exact [get_files -of_objects [get_filesets sim_1]] $tb] < 0} {
    add_files -fileset sim_1 -norecurse $tb
  }
  set_property top tb_fft_rect [get_filesets sim_1]
  set_property SOURCE_SET sources_1 [get_filesets sim_1]
  set_property TOP_LIB xil_defaultlib [get_filesets sim_1]
  set_property xsim.simulate.runtime 0ns [get_filesets sim_1]
  set_property -dict [list xsim.simulate.xsim.more_options "-testplusarg RESULT_DIR=$output"] [get_filesets sim_1]
  set_property xsim.simulate.wdb [file join $output interface.wdb] [get_filesets sim_1]
  update_compile_order -fileset sources_1
  update_compile_order -fileset sim_1
  write_text [file join $output environment.tcldict] [dict create vivado [version -short] part [get_property PART [current_project]] project [file join $work fft_rect.xpr] simulator [get_property target_simulator [current_project]] top [get_property TOP [get_filesets sim_1]] mode behavioral]
  write_text [file join $output preparation_done.txt] "PROJECT_PREPARED: frozen export replayed once; 17 properties read back; simulation NOT RUN"
  puts "PROJECT_PREPARED: $work/fft_rect.xpr ; top=tb_fft_rect ; static_parameters=17"
}

proc fft_rect::open_checked {work output} {
  set project [file normalize [file join $work fft_rect.xpr]]
  if {![llength [get_projects -quiet]]} {open_project $project}
  if {[file normalize [get_property DIRECTORY [current_project]]] ne [file normalize $work]} {error "Wrong project open"}
  if {[get_property TOP [get_filesets sim_1]] ne "tb_fft_rect"} {error "Wrong simulation top"}
  if {![file exists [file join $output preparation_done.txt]]} {error "Missing preparation receipt"}
}

proc fft_rect::compile {work output} {
  open_checked $work $output
  update_compile_order -fileset sim_1
  set order [get_files -compile_order sources -used_in simulation -of_objects [get_filesets sim_1]]
  if {[llength $order] < 3} {error "Simulation compile order is missing managed BD/IP sources"}
  write_text [file join $output compile_order.txt] [join $order \n]
  # Regenerate scripts after source/library changes; step-only calls may reuse old scripts.
  launch_simulation -simset sim_1 -mode behavioral -scripts_only
  set_property GENERATE_SCRIPTS_ONLY false [get_filesets sim_1]
  launch_simulation -simset sim_1 -mode behavioral -step compile -exec
  launch_simulation -simset sim_1 -mode behavioral -step elaborate -exec -noclean_dir
  write_text [file join $output compile_elaborate_done.txt] "COMPILE_ELABORATE_RETURNED: inspect xvlog/xvhdl/elaborate logs and snapshot; functional simulation NOT RUN"
  puts "COMPILE_ELABORATE_RETURNED: functional simulation NOT RUN"
}

proc fft_rect::run {work output} {
  open_checked $work $output
  foreach case {zero_rect dc_rect impulse_rect bin16_rect} {
    if {[llength [glob -nocomplain [file join $output $case actual_*]]] || [file exists [file join $output $case frame_status.json]]} {
      error "Capture already exists; preserve it and prepare a new run directory"
    }
  }
  if {![file exists [file join $output compile_elaborate_done.txt]]} {error "Compile/elaborate first"}
  set_property GENERATE_SCRIPTS_ONLY false [get_filesets sim_1]
  launch_simulation -simset sim_1 -mode behavioral
  log_wave [get_objects /tb_fft_rect/*]
  ::run 5ms
  if {![file exists [file join $output TB_CAPTURE_PASS.txt]]} {error "No TB capture PASS: inspect simulation logs"}
  close_sim
  puts "TB_CAPTURE_COMPLETE: verify_fft_rect.py verify is required for numerical acceptance"
}
