# led_counter.xdc -- step A-4 pin constraints for PYNQ-Z2.
# Pins taken from the PYNQ-Z2 Master XDC:
#   sysclk  = H16  125 MHz PL oscillator (independent of the PS)
#   led[0]  = R14   led[1] = P14   led[2] = N16   led[3] = M14
#
# This design is pure PL, so the clock is an ordinary input port and needs an
# explicit create_clock (period 8.00 ns = 125 MHz). Without it Vivado would
# report "no user specified timing constraints" (Timing 38-313).

set_property -dict {PACKAGE_PIN H16 IOSTANDARD LVCMOS33} [get_ports sysclk]
create_clock -add -name sys_clk_pin -period 8.00 -waveform {0 4} [get_ports sysclk]

set_property -dict {PACKAGE_PIN R14 IOSTANDARD LVCMOS33} [get_ports {led[0]}]
set_property -dict {PACKAGE_PIN P14 IOSTANDARD LVCMOS33} [get_ports {led[1]}]
set_property -dict {PACKAGE_PIN N16 IOSTANDARD LVCMOS33} [get_ports {led[2]}]
set_property -dict {PACKAGE_PIN M14 IOSTANDARD LVCMOS33} [get_ports {led[3]}]
