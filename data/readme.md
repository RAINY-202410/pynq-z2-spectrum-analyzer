# 测试数据与参考结果

- `golden_fft/`：FFT 黄金 manifest 与逐例比较摘要；
- `b11_signal_generator/`：OWON XDG3122 直通校准，16 频点；
- `b12_rc_measured/`：R=978 Ω、C=105.6 nF 的 RC 实测；
- `performance/`：PYNQ ARM 与主机 CPU FFT 基准；
- `board_runs/`：长测、短复验、三次冷启动和项目状态摘要。

原始 `.npy` 块数量较大，完整测试条件、逐块哈希和报告在对应 JSON 中给出。
比赛提交时不修改原始状态码，也不把回放数据标成新的板端采集。

为满足全仓库小写文件命名，镜像中的 `readme.md` 由原报告的 `README.md`
规范化而来。原 manifest 中的内容和哈希没有改写。B-X11 和 B-X12 均另带
`original_reports.zip`，需要按原 manifest 做严格复算时应解压该原件。
