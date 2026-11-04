# 构建与实现

工具为 Vivado 2026.1，器件 xc7z020clg400-1，需安装 PYNQ-Z2 board files 和相应 IP 许可。
从包根执行，使用新英文短路径输出。2026-11-04已完成独立解压副本构建验证，日志见reports/clean_build_20261104/。
所有输出目录必须新建且使用较短的英文绝对路径，不能覆盖已冻结报告或运行目录。

## FFT 系统

```bash
vivado -mode batch -source build/scripts/rebuild_fft.tcl -tclargs D:/fft_rebuild_new
```

脚本使用 `src/hw/ip/fft_system_bd.tcl` 原生 BD 导出重建；原 RTL、约束和 IP 配置全部在包内。
2026-10-24 已有独立 BD 重建及连线/17项参数比对，原始 receipt 在 `reports/fft/rebuild_comparison.json`。
2026-10-24的历史BD核对未重复综合；2026-11-04另在本机独立解压副本完成正式入口的综合、实现与bitstream生成，两个日期的证据分开保留。
新实现输出不保证与旧 bitstream 字节相同，不自动替换 board/overlays 中的冻结资产。

## FFT 链仿真

```bash
python src/reference/fft_chain/verify_fft_chain.py prepare --out D:/fft_results_new
vivado -mode batch -source build/scripts/run_fft_chain.tcl -tclargs D:/fft_sim_new D:/fft_results_new
python src/reference/fft_chain/verify_fft_chain.py verify --out D:/fft_results_new
```

参考模型向量为既有官方定点 C 模型输出；重新运行官方模型还需自行从 Vivado 安装目录取得对应模型库。
历史 results/preparation.json 的路径/源哈希对应历史布局，只作为原始证据保留；不要用新布局覆盖该收据。

## M4

`build/scripts/build_m4_from_sources.tcl` 为适配本目录的 M4 构建入口。
`build/scripts/sim_m4.tcl -tclargs <new_directory>` 为补齐测试平台后的仿真入口。
`src/hw/scripts/` 中其余旧构建脚本为历史研发代码，可能依赖旧布局和保护检查，不能替代上述提交入口。

## 报告

`reports/fft/` 已补回同版路由后资源、时序、时钟、CDC、DRC和重建记录。
FFT LUT=5631、FF=8533、BRAM36等效=5.5、DSP=13；100 MHz；WNS=+0.585733 ns。
`reports/timing/` 为既有 M4 时序报告。外部 I/O delay 仍未完整签核。

`src/reference/fft_chain/package_fft_chain.py`是历史归档脚本，依赖旧研发目录，不是提交版复现入口。正式流程只使用上文的verify_fft_chain与build/scripts入口。

## r02复核修订

仿真wrapper使用显式make_wrapper；2026-11-04独立编译/展开已通过并生成tb_fft_chain_behav快照，未重复数值矩阵。
build/board_files已纳入原环境的PYNQ-Z2供应商板定义，FFT/M4构建入口自动设置会话级board.repoPaths。
build/reports/fft/synthesis_utilization.rpt和synthesis_run.log为同一冻结FFT实现工程的既有综合报告/日志；utilization.rpt为routed结果，不混用阶段。
report/verification_report.md与sim/readme.md已去掉直接将新校验器指向历史旧路径receipt的错误命令。
独立构建结果及验证范围见../report/required_validation.md和reports/clean_build_20261104/validation_receipt.json；冻结运行资产未替换。
