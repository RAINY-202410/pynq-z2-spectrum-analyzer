# External I2S is oversampled in the 100 MHz PL domain, not used as FF clocks.
# Only asynchronous input-to-first-stage paths are excluded. Synchronizer
# stages and all packetizer/DMA paths remain timed in the PL clock domain.
set_property -dict {PACKAGE_PIN R18 IOSTANDARD LVCMOS33} [get_ports bclk]
set_property -dict {PACKAGE_PIN T17 IOSTANDARD LVCMOS33} [get_ports lrclk]
set_property -dict {PACKAGE_PIN F17 IOSTANDARD LVCMOS33} [get_ports sdata_i]
set_property -dict {PACKAGE_PIN G18 IOSTANDARD LVCMOS33} [get_ports sdata_o]
set_false_path -from [get_ports {bclk lrclk sdata_i}]

set_property -dict {PACKAGE_PIN U5 IOSTANDARD LVCMOS33} [get_ports codec_mclk]
# XDC files cannot contain Tcl conditional control flow.
# Query the divider register clock pin directly; post-build checks require
# exactly one generated clock with a 100 ns period.
create_generated_clock -name codec_mclk_10m \
    -source [get_pins -hier -filter {NAME =~ *codec_mclk_reg/C}] \
    -divide_by 10 [get_ports codec_mclk]

set_property -dict {PACKAGE_PIN U9 IOSTANDARD LVCMOS33 PULLUP true} [get_ports audio_i2c_scl_io]
set_property -dict {PACKAGE_PIN T9 IOSTANDARD LVCMOS33 PULLUP true} [get_ports audio_i2c_sda_io]
set_property -dict {PACKAGE_PIN M17 IOSTANDARD LVCMOS33} [get_ports {codec_addr[0]}]
set_property -dict {PACKAGE_PIN M18 IOSTANDARD LVCMOS33} [get_ports {codec_addr[1]}]
