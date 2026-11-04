# build_m3.tcl -- steps A-5 / A-6, produces the M3 handoff
#
# PS7 + AXI Interconnect + custom AXI-Lite slave (axi_lite_ctrl, 4 registers).
# The low 4 bits of reg0 drive the board LEDs, so a register write is visible
# without any extra instrumentation.
# All messages are ASCII on purpose: Tcl reads scripts with the system code page
# on Chinese Windows, so non-ASCII text in a .tcl file can be mis-decoded.
# Chinese notes live in docs/interface.md and docs/a_week1_2_runbook.md.
#
# Fix log (2026-10-03), after the first real run failed at validate_bd_design:
#   1. connected ps7_0/M_AXI_GP0_ACLK to FCLK_CLK0. Without it validate_bd_design
#      aborts with [BD 41-758] "clock pins are not connected to a valid clock
#      source". The PS7 master port has its own clock input; enabling
#      PCW_USE_M_AXI_GP0 creates it but does not connect it.
#   2. moved assign_bd_address in front of validate_bd_design. Validating first
#      produced [BD 41-1356] "slave segment is not assigned into address space".
#   3. set CONFIG.FREQ_HZ on the custom IP clock pin to clear
#      [IP_Flow 19-11770] "clock interface has no FREQ_HZ parameter".
#   4. added hw/constraints/m3_led.xdc. Without pin constraints the led[3:0] port
#      landed on arbitrary pins, so the register-to-LED demo could not work.
#
# Outputs:
#   build/m3/m3.runs/impl_1/system_wrapper.bit    bitstream
#   build/m3/m3.gen/.../hw_handoff/system.hwh     handoff file used by PYNQ ip_dict
#   build/m3/pynq/m3.bit + m3.hwh                 matched pair, copy to the board

set script_dir [file dirname [file normalize [info script]]]
set root       [file normalize [file join $script_dir ".." ".."]]
set build_dir  [file join $root "build" "m3"]

puts "== project root : $root"
puts "== build dir    : $build_dir"

create_project m3 $build_dir -part xc7z020clg400-1 -force
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]

add_files -norecurse [list [file join $root "hw" "rtl" "axi_lite_ctrl.v"]]
add_files -fileset constrs_1 -norecurse [list [file join $root "hw" "constraints" "m3_led.xdc"]]

create_bd_design system

create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7_0
set_property -dict [list CONFIG.PCW_USE_M_AXI_GP0 {1} CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100}] [get_bd_cells ps7_0]
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} [get_bd_cells ps7_0]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_interconnect_0
set_property -dict [list CONFIG.NUM_MI {1}] [get_bd_cells axi_interconnect_0]

create_bd_cell -type module -reference axi_lite_ctrl axi_lite_ctrl_0

# A module reference has no FREQ_HZ on its inferred clock interface; set it so
# the interconnect can derive the clock ratio.
if {[catch {set_property CONFIG.FREQ_HZ 100000000 [get_bd_pins axi_lite_ctrl_0/s_axi_aclk]} err]} {
    puts "WARNING: could not set FREQ_HZ on axi_lite_ctrl_0/s_axi_aclk: $err"
}

# ---- AXI wiring: PS GP0 -> interconnect -> slave ----
connect_bd_intf_net [get_bd_intf_pins ps7_0/M_AXI_GP0] [get_bd_intf_pins axi_interconnect_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_interconnect_0/M00_AXI] [get_bd_intf_pins axi_lite_ctrl_0/s_axi]

# ---- clocks and resets ----
# FCLK_CLK0 is the single 100 MHz source for everything, including the PS7
# master port clock input (fix 1).
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins ps7_0/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_interconnect_0/ACLK]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_interconnect_0/S00_ACLK]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_interconnect_0/M00_ACLK]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_lite_ctrl_0/s_axi_aclk]

connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins axi_interconnect_0/ARESETN]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins axi_interconnect_0/S00_ARESETN]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins axi_interconnect_0/M00_ARESETN]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N] [get_bd_pins axi_lite_ctrl_0/s_axi_aresetn]

# ---- register low bits drive the board LEDs ----
create_bd_port -dir O -from 3 -to 0 led
connect_bd_net [get_bd_pins axi_lite_ctrl_0/led_o] [get_bd_ports led]

# ---- assign addresses first, then validate (fix 2) ----
assign_bd_address

foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps7_0/Data]] {
    set seg_name [get_property NAME $seg]
    set seg_off  [get_property offset $seg]
    set seg_rng  [get_property range $seg]
    puts "SEG  $seg_name  offset=$seg_off  range=$seg_rng"
    if {[string match "*axi_lite_ctrl_0*" $seg_name]} {
        puts "M3_IP_BASE_ADDR=$seg_off"
        puts "M3_IP_RANGE=$seg_rng"
    }
}

validate_bd_design
save_bd_design

set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "== running synthesis"
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set synth_status [get_property STATUS [get_runs synth_1]]
puts "== synth_1 status: $synth_status"
if {![string match -nocase "*complete*" $synth_status]} {
    error "synth_1 did not finish; see $build_dir/m3.runs/synth_1/runme.log"
}

puts "== running implementation and bitstream"
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set impl_status [get_property STATUS [get_runs impl_1]]
puts "== impl_1 status: $impl_status"
if {![string match -nocase "*complete*" $impl_status]} {
    error "impl_1 did not finish; see $build_dir/m3.runs/impl_1/runme.log"
}

# ---- prepare a matched bit + hwh pair for the M3 handoff ----
set bit_src [file join $build_dir "m3.runs" "impl_1" "system_wrapper.bit"]
set hwh_src [file join $build_dir "m3.gen" "sources_1" "bd" "system" "hw_handoff" "system.hwh"]
set out_dir [file join $build_dir "pynq"]
file mkdir $out_dir
if {[file exists $bit_src]} {
    file copy -force $bit_src [file join $out_dir "m3.bit"]
} else {
    puts "WARNING: $bit_src not found, listing what was produced:"
    foreach f [glob -nocomplain -directory [file join $build_dir "m3.runs" "impl_1"] "*.bit"] {
        file copy -force $f [file join $out_dir "m3.bit"]
        puts "== handoff bitstream: $f"
    }
}
if {[file exists $hwh_src]} {
    file copy -force $hwh_src [file join $out_dir "m3.hwh"]
    puts "== handoff pair ready: [file join $out_dir m3.bit] + m3.hwh"
} else {
    puts "WARNING: $hwh_src not found, export hardware manually"
}

if {[catch {write_hw_platform -fixed -include_bit -force [file join $build_dir "m3.xsa"]} err]} {
    puts "WARNING: XSA export failed, the bitstream itself is fine. Reason: $err"
}

puts "DONE: M3 design built, ready for the register test"
