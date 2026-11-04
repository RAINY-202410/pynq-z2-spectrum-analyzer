# 综合与实现报告

目标 PYNQ-Z2，xc7z020clg400-1，Vivado 2026.1，PL 100 MHz。
`build/reports/fft/utilization.rpt` 已补回原始 routed 报告：LUT 5631/53200（10.58%）、FF 8533/106400（8.02%）、BRAM36 等效 5.5/140（3.93%）、DSP 13/220（5.91%）。
FFT WNS +0.585733 ns、TNS 0、WHS +0.019605 ns、THS 0，范围为受约束内部路径。
M4 既有 routed 时序 WNS +3.021 ns、WHS +0.044 ns。外部 I/O delay 尚未完整签核。
这些指标与冻结硬件的历史实现对应，冻结bit/hwh保持原样；2026-11-04独立构建结果另行保存。
正式FFT构建入口是build/scripts/rebuild_fft.tcl；2026-11-04已在独立解压副本完成FFT/M4构建，但不声称bit-exact rebuild。

已另补同版FFT原始综合阶段报告synthesis_utilization.rpt及日志synthesis_run.log。对应原工程impl_1比特流SHA与冻结fft.bit一致；不是本次新综合。

## 2026-11-04独立构建

FFT与M4均完成综合、实现和硬件文件生成；原始日志及新报告位于../build/reports/clean_build_20261104/。
FFT时序：{"wns_ns": 0.586, "tns_ns": 0.0, "whs_ns": 0.02, "ths_ns": 0.0}；M4时序：{"wns_ns": 3.021, "tns_ns": 0.0, "whs_ns": 0.044, "ths_ns": 0.0}。
该验证不覆盖完整外部I/O签核或新板端验收，新产物没有替换冻结运行资产。
