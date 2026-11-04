# B-X11 信号发生器信源 16 频点直通校准

日期：2026-11-01（Asia/Shanghai）。状态：`BOARD_VALIDATED`。

## 数据范围

原始数据位于：

```text
../audio_test_20261101/b_x11_m4_only_20261101/
```

- 信源：信号发生器，正弦波由数据拟合确认；
- 16 个设计频点；
- 每点 3 个校准块和 3 个验证块；
- 共使用 96 个 `(2,1024)` int32 双声道块；
- 按用户要求排除 `b11_f6000_val_retry_01.npy`；
- 6 kHz 只使用 `val_01`、`val_02`、`val_03`。

`source_dataset_manifest.json` 登记原始目录内全部 101 个文件及其 SHA256；
补采块明确标为 `excluded_retry`，没有删除。

## 结果

- 16/16 频点通过；
- 每点 3 个校准块和 3 个有效独立验证块；
- 没有正式验证块被质量规则判为无效；
- `C0` 增益：`0.043404～0.044280 dB`；
- `C0` 相位：`-0.019371～+0.012997°`；
- 校正后验证均值：增益 `-0.000185～+0.000214 dB`，
  相位 `-0.001843～+0.001232°`；
- 验证重复性标准差最大值：增益 `0.000163 dB`，相位 `0.001357°`。

6 kHz 单点：

- `C0 = 0.043651 dB / -0.015487°`；
- 验证均值 `-0.000061 dB / +0.001232°`；
- 三个正式验证块全部有效；
- 补采块未参与拟合、校准或验证。

与 PC 直通信源数据集相比，本次 `C0` 增益低约 `0.0693～0.0699 dB`，
但相位差异约在 `0.0014°` 内。这组差异说明必须保留“信源和线路条件”标签，
不能把两次会话的 `C0` 不加说明地混用。

## 条件

本次会话条件完整：

- 信源：OWON XDG3122 信号发生器；
- 波形：正弦波，实际幅度 `0.2 Vpp`；
- 输出阻抗：XDG3122 标称 `50 Ω`，本次没有使用其它阻抗设置；
- 音量：不适用；
- 温度：`26 C`；
- 接口：PYNQ LINE IN 使用 3.5 mm 三节立体公转接为 L、R、GND；
- 直通拓扑：信号发生器输出端同时连接 L 和 R，信号发生器地连接 GND；
- 当前为 B-X11 直通校准，L/R 之间没有 RC，也没有测试电路；
- `fs=47998.77998801426 Hz`；
- codec 配置来自 M4 候选；
- `m4.bit` 和 `m4.hwh` 哈希与当前候选一致。

因此本会话登记为条件完整的 `BOARD_VALIDATED`，16/16 点通过。该状态只说明
B-X11 直通校准在当前信号源和线路条件下有效，不代表 B-X12 的 RC 已经测量。

进入 B-X12 时必须改变拓扑：L 继续直接作为 `input_reference`，R 改为经过
`R=1 kΩ` 后再接 `rc_output`，并从 `rc_output` 用 `C=100 nF` 接 GND；
不能再把发生器输出直接并接到 L、R 两端。

## 文件

- `channel_calibration.json`：16 点校准、验证、条件和排除记录；
- `fit_results.json`：96 个入选原始块的同步双声道拟合结果；
- `calibration_summary.csv`：频点级 `C0` 和独立验证汇总；
- `calibration_repeatability.png` / `.svg`：校准及验证重复性；
- `source_dataset_manifest.json`：原始数据集逐文件哈希和补采排除状态；
- `manifest.json`：本目录派生文件哈希。

## 重建

```powershell
python -m rc.build_full_bx11 `
  --dataset-dir reports\B-X11\audio_test_20261101\b_x11_m4_only_20261101 `
  --out reports\B-X11\signal_generator_20261101 `
  --ignore-retry `
  --condition source_profile=SIGNAL_GENERATOR `
  --condition generator_model=OWON_XDG3122 `
  --condition volume=NOT_APPLICABLE_SIGNAL_GENERATOR `
  --condition input_route=GENERATOR_OUTPUT_PARALLEL_TO_LINE_IN_L_AND_R_GROUND_TO_GND `
  --condition temperature=26_C `
  --condition generator_waveform=SINE `
  --condition generator_amplitude_vpp=0.2_VPP_ACTUAL `
  --condition generator_output_impedance=50_OHM_NOMINAL_MODEL_SPEC
```

本任务只处理已保存的 `.npy` 数据，没有加载 Overlay、M4 或 DMA。
