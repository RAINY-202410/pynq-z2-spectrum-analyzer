# 独立解压副本构建验证（2026-11-04）

本机使用Vivado 2026.1，将提交RAR独立解压至新英文短路径，不打开原开发工程，不借用旧项目生成目录。
与最终交付一致的RTL/XDC、IP/BD及正式Tcl入口已按SHA256核对，来源清单见build/reports/clean_build_20261104/validation_receipt.json。

| 项目 | 实际结果 |
|---|---|
| FFT板定义、原生BD与wrapper生成 | 通过 |
| FFT综合、实现与bitstream生成 | 通过 |
| FFT链仿真编译与展开 | 通过，生成tb_fft_chain_behav快照 |
| M4综合、实现与bit/hwh生成 | 通过 |

原始批处理日志、分阶段报告与编译/展开日志保存在build/reports/clean_build_20261104/。
新生成硬件文件只用于验证构建，不替换board/overlays及运行ZIP中的冻结资产；新输出SHA256单独登记。
本次没有执行功能仿真的时间推进或重新运行12主例/2恢复帧矩阵，没有新增板测，没有重装或升级r3/r4。
独立目录构建通过不等于全新操作系统验证、bit逐字一致、完整r4板端交互验收或外部I/O完整签核。
