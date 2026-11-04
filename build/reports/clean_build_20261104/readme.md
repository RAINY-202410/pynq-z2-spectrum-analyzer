# 2026-11-04独立目录构建原件

使用I盘提交RAR的独立解压副本执行Vivado 2026.1正式Tcl入口。validation_receipt.json记录与最终工程一致的硬件源/Tcl文件SHA256及新输出哈希。
fft/与m4/分别保存本次综合/实现日志、资源与时序报告；compile/保存FFT链编译/展开日志。clean_build.log与stages.log为完整阶段记录。
validation_driver.tcl是本次执行记录，保留实际本机路径；通用复现入口仍为build/scripts/及build/readme.md中的命令。
未重复功能仿真或板测。冻结bit/hwh和运行ZIP保持原样；本目录报告不覆盖完整外部I/O签核。

日志扫描无ERROR。完整构建日志中20条CRITICAL WARNING均为供应商板卡预设的PSU-1～PSU-4 DDR DQS偏移提示；保留原值，不为消除提示改动DDR或PLL。FFT/M4综合、实现及仿真编译/展开日志均无ERROR或CRITICAL WARNING。详细计数见build_log_review.json。
