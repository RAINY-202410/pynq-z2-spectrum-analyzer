# m3_led.xdc -- pin constraints for the M3 Block Design (PS + AXI + axi_lite_ctrl).
#
# The M3 design takes its clock from the PS (FCLK_CLK0 = 100 MHz), so unlike the
# pure-PL LED design there is no create_clock here: the PS7 IP generates its own
# clock constraints. Only the four LED outputs need pin locations.
#
# Pins taken from the PYNQ-Z2 Master XDC (hw/constraints/pynq_z2_master.xdc):
#   led[0] = R14   led[1] = P14   led[2] = N16   led[3] = M14

set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
