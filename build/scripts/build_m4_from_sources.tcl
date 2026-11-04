# build_m4.tcl -- step A-9, the minimal capture path: codec -> I2S -> DMA -> DDR
#
# Design:
#   ps7_0           100 MHz FCLK_CLK0, M_AXI_GP0 (control), S_AXI_HP0 (DMA data)
#   axi_iic_0       configures the ADAU1761 over I2C (pins U9/T9)
#   axi_lite_ctrl_0 reused from M3; its low 4 register bits drive the LEDs
#   i2s_capture_0   i2s_serdes + 48-to-64 bit widening, one AXI-Stream master
#   axi_dma_0       S2MM only: sample stream into DDR
#
# Note: I2S runs continuously, while CTRL[0] triggers a bounded packet.
# CTRL[1] aborts the packetizer; CTRL[2] selects the explicit test source.
# codec_mclk is generated at 10 MHz from the 100 MHz FCLK.
#
# All messages are ASCII: Tcl on Chinese Windows reads scripts with the system
# code page, so non-ASCII text can be mis-decoded.

set script_dir [file dirname [file normalize [info script]]]
set root       [file normalize [file join $script_dir ".." ".."]]
set build_dir  [file join $root "build" "output" "m4"]
if {[file exists $build_dir]} {error "Use a fresh repository/output directory; M4 output already exists"}

proc stage {n text} { puts "\n===== STAGE $n: $text =====" }

# Look up a block design pin by its short name instead of hard coding the full
# path. IP pin names differ slightly between versions, so discover them and only
# fail with a clear message if the name really is absent.
proc pin_named {cell name} {
    foreach p [get_bd_pins -of_objects [get_bd_cells $cell]] {
        if {[string match -nocase "*/$name" $p]} { return $p }
    }
    return ""
}

stage 1 "project and sources"
puts "== project root : $root"
puts "== build dir    : $build_dir"

set board_repo [file normalize [file join $root build board_files]]
set_param board.repoPaths [list $board_repo]
create_project m4 $build_dir -part xc7z020clg400-1 -force
set_property board_part tul.com.tw:pynq-z2:part0:1.0 [current_project]

add_files -norecurse [list \
    [file join $root "src" "hw" "rtl" "axi_lite_ctrl.v"] \
    [file join $root "src" "hw" "rtl" "i2s" "axis.sv"] \
    [file join $root "src" "hw" "rtl" "i2s" "rising_edge.sv"] \
    [file join $root "src" "hw" "rtl" "i2s" "i2s_serdes.sv"] \
    [file join $root "src" "hw" "rtl" "i2s" "i2s_capture.sv"] \
    [file join $root "src" "hw" "rtl" "i2s" "i2s_capture_wrapper.v"] \
    [file join $root "src" "hw" "rtl" "dbg_stat.v"]]

add_files -fileset constrs_1 -norecurse [list \
    [file join $root "src" "hw" "constraints" "i2s_audio.xdc"] \
    [file join $root "src" "hw" "constraints" "m3_led.xdc"]]

stage 2 "processing_system7"
create_bd_design system

create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7:5.5 ps7_0
# Apply the board preset FIRST, then override the PCW options. The preset is a
# full configuration dump for PYNQ-Z2 and would otherwise wipe out anything set
# before it -- that is what left S_AXI_HP0 missing on the first run.
apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} [get_bd_cells ps7_0]
set_property -dict [list \
    CONFIG.PCW_USE_M_AXI_GP0 {1} \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ {100} \
] [get_bd_cells ps7_0]

stage 3 "AXI interconnect and control peripherals"
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_interconnect:2.1 axi_ic_0
 set_property -dict [list CONFIG.NUM_MI {4}] [get_bd_cells axi_ic_0]

create_bd_cell -type ip -vlnv xilinx.com:ip:axi_iic:2.1 axi_iic_0

 create_bd_cell -type module -reference axi_lite_ctrl axi_lite_ctrl_0

 create_bd_cell -type module -reference dbg_stat dbg_stat_0

connect_bd_intf_net [get_bd_intf_pins ps7_0/M_AXI_GP0] [get_bd_intf_pins axi_ic_0/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_ic_0/M00_AXI] [get_bd_intf_pins axi_iic_0/S_AXI]
 connect_bd_intf_net [get_bd_intf_pins axi_ic_0/M01_AXI] [get_bd_intf_pins axi_lite_ctrl_0/s_axi]
 connect_bd_intf_net [get_bd_intf_pins axi_ic_0/M03_AXI] [get_bd_intf_pins dbg_stat_0/s_axi]

stage 4 "AXI DMA, S2MM only, 64-bit stream"
create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma:7.1 axi_dma_0
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_sg_include_stscntrl_strm {0} \
    CONFIG.c_include_mm2s {0} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_s_axis_s2mm_tdata_width {64} \
    CONFIG.c_m_axi_s2mm_data_width {64} \
] [get_bd_cells axi_dma_0]

# Read the width back: an unknown CONFIG name is sometimes ignored silently,
# which would leave a 32-bit stream and only fail much later.
if {[catch {set dw [get_property CONFIG.c_s_axis_s2mm_tdata_width [get_bd_cells axi_dma_0]]} err]} {
    puts "WARNING: cannot read back the S2MM stream width: $err"
} else {
    puts "== DMA S2MM stream width readback = $dw   (must be 64)"
}

connect_bd_intf_net [get_bd_intf_pins axi_ic_0/M02_AXI] [get_bd_intf_pins axi_dma_0/S_AXI_LITE]

# Diagnostic: if the HP0 connection fails again, this list shows the real
# interface pin names on the PS7 so the next fix is obvious.
puts "PS7 interface pins:"
foreach p [get_bd_intf_pins -of_objects [get_bd_cells ps7_0]] {
    puts "  $p"
}

stage 4b "AXI SmartConnect for the AXI4 -> AXI3 HP0 path"
# Zynq-7000 PS ports are AXI3; the modern AXI DMA speaks AXI4. The AXI
# SmartConnect performs AXI4/AXI3 adaptation. Previous failure is not proof
# of a memory slave error; software decoding and packet framing also changed.
create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect:1.0 axi_sc_s2mm
set_property -dict [list CONFIG.NUM_SI {1} CONFIG.NUM_MI {1}] [get_bd_cells axi_sc_s2mm]
connect_bd_intf_net [get_bd_intf_pins axi_dma_0/M_AXI_S2MM] [get_bd_intf_pins axi_sc_s2mm/S00_AXI]
connect_bd_intf_net [get_bd_intf_pins axi_sc_s2mm/M00_AXI] [get_bd_intf_pins ps7_0/S_AXI_HP0]

stage 5 "i2s_capture and external I2S pins"
# Reference the plain Verilog wrapper, not the SystemVerilog module: an SV top
# in a block design breaks the out-of-context synthesis run
# (IP_Flow 19-5101 / Common 17-354). The instance keeps its old name so every
# connection below stays unchanged.
create_bd_cell -type module -reference i2s_capture_wrapper i2s_capture_0
connect_bd_net [get_bd_pins axi_lite_ctrl_0/led_o] [get_bd_pins i2s_capture_0/capture_ctrl]
create_bd_port -dir O codec_mclk
connect_bd_net [get_bd_pins i2s_capture_0/codec_mclk] [get_bd_ports codec_mclk]

# enabled is tied high for this bring-up (see header note)
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_enable
set_property -dict [list CONFIG.CONST_WIDTH {1} CONFIG.CONST_VAL {1}] [get_bd_cells const_enable]
connect_bd_net [get_bd_pins const_enable/dout] [get_bd_pins i2s_capture_0/enabled]

connect_bd_intf_net [get_bd_intf_pins i2s_capture_0/m_axis] [get_bd_intf_pins axi_dma_0/S_AXIS_S2MM]

create_bd_port -dir I bclk
create_bd_port -dir I lrclk
create_bd_port -dir I sdata_i
create_bd_port -dir O sdata_o
connect_bd_net [get_bd_ports bclk]    [get_bd_pins i2s_capture_0/bclk]
connect_bd_net [get_bd_ports lrclk]   [get_bd_pins i2s_capture_0/lrclk]
connect_bd_net [get_bd_ports sdata_i] [get_bd_pins i2s_capture_0/sdata_i]
connect_bd_net [get_bd_ports sdata_o] [get_bd_pins i2s_capture_0/sdata_o]

# codec address straps, driven high
create_bd_cell -type ip -vlnv xilinx.com:ip:xlconstant:1.1 const_addr
set_property -dict [list CONFIG.CONST_WIDTH {2} CONFIG.CONST_VAL {3}] [get_bd_cells const_addr]
create_bd_port -dir O -from 1 -to 0 codec_addr
connect_bd_net [get_bd_pins const_addr/dout] [get_bd_ports codec_addr]

# LEDs, same pins as M3
# The LEDs now carry diagnostics from the capture wrapper instead of the control
# register: led[0]=bclk seen, led[1]=lrclk seen, led[2]=live I2S source,
# led[3]=heartbeat. The register-driven LED test still exists in the M3 design.
create_bd_port -dir O -from 3 -to 0 led
 connect_bd_net [get_bd_pins i2s_capture_0/dbg_led] [get_bd_ports led]

 # debug counters into the status slave
 connect_bd_net [get_bd_pins i2s_capture_0/dbg_cnt_lrclk] [get_bd_pins dbg_stat_0/cnt_lrclk]
 connect_bd_net [get_bd_pins i2s_capture_0/dbg_cnt_beat]  [get_bd_pins dbg_stat_0/cnt_beat]
 connect_bd_net [get_bd_pins i2s_capture_0/dbg_snap]      [get_bd_pins dbg_stat_0/snapshot]
 connect_bd_net [get_bd_pins i2s_capture_0/dbg_samp]      [get_bd_pins dbg_stat_0/samp_lo]

stage 6 "I2C tristate buffers and external pins"
# axi_iic exposes split i/o/t signals; util_ds_buf in IOBUF mode turns them into
# a real bidirectional pin.
foreach n {scl sda} {
    create_bd_cell -type ip -vlnv xilinx.com:ip:util_ds_buf:2.2 iobuf_$n
    set_property -dict [list CONFIG.C_BUF_TYPE {IOBUF} CONFIG.C_SIZE {1}] [get_bd_cells iobuf_$n]
}

# Print the real pin names on both cells: if the names below are not
# IOBUF_IO / IOBUF_I / IOBUF_O / IOBUF_T, the lookups further down report it.
foreach n {scl sda} {
    puts "iobuf_$n pins:"
    foreach p [get_bd_pins -of_objects [get_bd_cells iobuf_$n]] { puts "    $p" }
}
puts "axi_iic_0 pins:"
foreach p [get_bd_pins -of_objects [get_bd_cells axi_iic_0]] { puts "    $p" }

foreach {n port} {scl audio_i2c_scl_io sda audio_i2c_sda_io} {
    # Real pin names, read from the pin list printed above (Vivado 2026.1):
    #   /iobuf_<n>/IOBUF_IO_I   data to drive onto the pad
    #   /iobuf_<n>/IOBUF_IO_O   data read back from the pad
    #   /iobuf_<n>/IOBUF_IO_T   tristate control
    #   /iobuf_<n>/IOBUF_IO_IO  the pad itself
    set pIo [pin_named iobuf_$n IOBUF_IO_IO]
    set pI  [pin_named iobuf_$n IOBUF_IO_I]
    set pO  [pin_named iobuf_$n IOBUF_IO_O]
    set pT  [pin_named iobuf_$n IOBUF_IO_T]
    if {$pIo eq "" || $pI eq "" || $pO eq "" || $pT eq ""} {
        error "iobuf_$n does not expose IOBUF_IO_IO/I/O/T -- see the pin list printed above"
    }
    create_bd_port -dir IO $port
    connect_bd_net [get_bd_ports $port] $pIo
    # The AXI IIC exposes scl_i/scl_o/scl_t and sda_i/sda_o/sda_t -- no "iic_"
    # prefix (that was wrong on the first attempt).
    connect_bd_net $pI [get_bd_pins axi_iic_0/${n}_o]
    connect_bd_net $pT [get_bd_pins axi_iic_0/${n}_t]
    connect_bd_net $pO [get_bd_pins axi_iic_0/${n}_i]
}

stage 7 "clocks and resets"
create_bd_cell -type ip -vlnv xilinx.com:ip:proc_sys_reset:5.0 rst_100m
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0]      [get_bd_pins rst_100m/slowest_sync_clk]
connect_bd_net [get_bd_pins ps7_0/FCLK_RESET0_N]  [get_bd_pins rst_100m/ext_reset_in]

# clocks: one 100 MHz source for everything, including the PS master port clock
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins ps7_0/M_AXI_GP0_ACLK]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins ps7_0/S_AXI_HP0_ACLK]
 foreach p {ACLK S00_ACLK M00_ACLK M01_ACLK M02_ACLK M03_ACLK} {
    connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_ic_0/$p]
}
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_iic_0/s_axi_aclk]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_lite_ctrl_0/s_axi_aclk]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_dma_0/s_axi_lite_aclk]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_dma_0/m_axi_s2mm_aclk]
connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins axi_sc_s2mm/aclk]
 connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins i2s_capture_0/clk]
 connect_bd_net [get_bd_pins ps7_0/FCLK_CLK0] [get_bd_pins dbg_stat_0/s_axi_aclk]

# resets: everything runs from the peripheral reset derived from FCLK_RESET0_N
set rstn [get_bd_pins rst_100m/peripheral_aresetn]
 foreach p {ARESETN S00_ARESETN M00_ARESETN M01_ARESETN M02_ARESETN M03_ARESETN} {
    connect_bd_net $rstn [get_bd_pins axi_ic_0/$p]
}
connect_bd_net $rstn [get_bd_pins axi_iic_0/s_axi_aresetn]
connect_bd_net $rstn [get_bd_pins axi_lite_ctrl_0/s_axi_aresetn]
connect_bd_net $rstn [get_bd_pins axi_dma_0/axi_resetn]
connect_bd_net $rstn [get_bd_pins axi_sc_s2mm/aresetn]
 connect_bd_net $rstn [get_bd_pins i2s_capture_0/resetn]
 connect_bd_net $rstn [get_bd_pins dbg_stat_0/s_axi_aresetn]

# the module reference has no FREQ_HZ on its clock port; set it so the
# interconnect can derive the clock ratio
foreach {pin} {axi_lite_ctrl_0/s_axi_aclk i2s_capture_0/clk} {
    if {[catch {set_property CONFIG.FREQ_HZ 100000000 [get_bd_pins $pin]} err]} {
        puts "WARNING: could not set FREQ_HZ on $pin: $err"
    }
}

stage 8 "validate, address, build"
assign_bd_address

foreach seg [get_bd_addr_segs -of_objects [get_bd_addr_spaces ps7_0/Data]] {
    set n [get_property NAME $seg]
    set o [get_property offset $seg]
    set r [get_property range $seg]
    puts "SEG  $n  offset=$o  range=$r"
    if {[string match "*axi_lite_ctrl_0*" $n]} {
        puts "M4_CTRL_BASE_ADDR=$o"
        puts "M4_CTRL_RANGE=$r"
    }
    if {[string match "*axi_iic_0*" $n]} {
        puts "M4_IIC_BASE_ADDR=$o"
    }
    if {[string match "*axi_dma_0*" $n]} {
        puts "M4_DMA_BASE_ADDR=$o"
    }
    if {[string match "*dbg_stat_0*" $n]} {
        puts "M4_DBG_BASE_ADDR=$o"
    }
}

validate_bd_design
save_bd_design

# Show what the DMA master can reach. The S2MM writes into DDR through HP0, so
# this master must have a DDR segment mapped to it. Query the master interface's
# address space: the cell-level query returns nothing because the space belongs
# to the M_AXI_S2MM interface, not the cell.
puts "DMA master address spaces (must contain HP0_DDR_LOWOCM):"
foreach sp [get_bd_addr_spaces -of_objects [get_bd_intf_pins axi_dma_0/M_AXI_S2MM]] {
    puts "  ADDRSPACE $sp"
    foreach sg [get_bd_addr_segs -of_objects $sp] {
        puts "    SEG $sg  offset=[get_property offset $sg]  range=[get_property range $sg]"
    }
}

set wrapper [make_wrapper -files [get_files system.bd] -top]
add_files -norecurse $wrapper
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1

puts "\n===== synthesising ====="
launch_runs synth_1 -jobs 8
wait_on_run synth_1
set s [get_property STATUS [get_runs synth_1]]
puts "== synth_1 status: $s"
if {![string match -nocase "*complete*" $s]} {
    error "synth_1 did not finish; see $build_dir/m4.runs/synth_1/runme.log"
}

puts "\n===== implementation and bitstream ====="
launch_runs impl_1 -to_step write_bitstream -jobs 8
wait_on_run impl_1
set s [get_property STATUS [get_runs impl_1]]
puts "== impl_1 status: $s"
if {![string match -nocase "*complete*" $s]} {
    error "impl_1 did not finish; see $build_dir/m4.runs/impl_1/runme.log"
}

open_run impl_1
report_timing_summary -file [file join $build_dir delivery_timing.rpt]
report_cdc -details -file [file join $build_dir delivery_cdc.rpt]
report_clocks -file [file join $build_dir delivery_clocks.rpt]
report_utilization -file [file join $build_dir delivery_utilization.rpt]
if {[llength [get_clocks -quiet codec_mclk_10m]] != 1} {
    error "codec_mclk_10m constraint missing; do not release this candidate"
}
foreach delay_type {max min} {
    set paths [get_timing_paths -delay_type $delay_type -max_paths 1]
    if {[llength $paths] && [get_property SLACK $paths] < 0} {
        error "Negative $delay_type timing slack; inspect delivery_timing.rpt"
    }
}
set out_dir [file join $build_dir "handoff"]
file mkdir $out_dir
file copy -force [file join $build_dir "m4.runs" "impl_1" "system_wrapper.bit"] [file join $out_dir "m4.bit"]
file copy -force [file join $build_dir "m4.gen" "sources_1" "bd" "system" "hw_handoff" "system.hwh"] [file join $out_dir "m4.hwh"]
puts "== handoff pair ready: [file join $out_dir m4.bit] + m4.hwh"

foreach pair {
    {m4_delivery.py m4_delivery.py}
    {m4_acceptance.ipynb m4_acceptance.ipynb}
    {readme_m4.md readme.md}
    {license.reed-foster.txt license.reed-foster.txt}
} {
    lassign $pair source_name target_name
    file copy -force [file join $root src ps pynq_r4 m4 $source_name] [file join $out_dir $target_name]
}
foreach name {delivery_timing.rpt delivery_clocks.rpt delivery_cdc.rpt} {
    file copy -force [file join $build_dir $name] [file join $out_dir $name]
}
file copy -force [file join $build_dir delivery_utilization.rpt] [file join $out_dir delivery_utilization.rpt]
file copy -force [file join $root sim m4 packetizer_simulation_pass.txt] [file join $out_dir packetizer_simulation_pass.txt]
set h [open [file join $out_dir build_info.txt] w]
puts $h "Vivado: [version -short]"
puts $h "Built: [clock format [clock seconds]]"
puts $h "Protocol: M4 delivery 20261018; fixed 1024 beats; CTRL-triggered"
close $h
puts "DONE: M4 capture design built"
