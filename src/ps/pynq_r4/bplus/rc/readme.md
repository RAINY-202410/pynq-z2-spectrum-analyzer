# RC 拓展目录

B-X09 已实现一阶 RC 理论基准、16 个设计频点和 SYNTHETIC 双声道夹具；B-X10 已实现同步双声道相量拟合。

## 生成基准

```powershell
python rc\rc_model.py
python rc\phasor_fit.py
python rc\channel_calibration.py --m4-dir <M4 validation dir>
```

输出在 `reports/B-X09/`：

- `theory.png` / `theory.svg`：理论幅频/相频；
- `rc_points.json` / `rc_points.csv`：16 个设计点，实测列保持空白；
- `synthetic_points.csv`：单独的 SYNTHETIC 点表；
- `synthetic/*.npz`：双声道 1024 点合成数据，含 int32 原始量化和 float 参考；
- `manifest.json`：输出 SHA256。

B-X10 的 `phasor_fit.py` 读取 B-X09 的 SYNTHETIC NPZ，并生成
`reports/B-X10/fit_results.json` 与 `fit_results.csv`。拟合使用同一个左/右声道
频率，不从未同步的单声道 FFT 相位相减。

B-X11 的根目录 `channel_calibration.json` 保留历史 1 kHz pilot；完整 16 频点板端
直通校准和独立验证结果在 `reports/B-X11/full_20261101/`，状态为 `BOARD_VALIDATED`。
现场条件为 PC 音量 100%、PC 3.5 mm 立体声直连 PYNQ LINE IN、WAV L/R 同源和 25 C。

B-X12 的信号发生器会话使用 OWON XDG3122、实际 `0.2 Vpp`、`26 C`，L/R 直通校准
位于 `reports/B-X11/signal_generator_20261101/`。真实 RC 数据使用
`R=978 Ω`、`C=105.6 nF`，16/16 点通过，结果登记为 `RC_MEASURED`，报告在
`reports/B-X12/measured_20261101/`。

## 边界

- B-X09 的理论设计表仍保留原样；B-X12 的实测结果写入独立报告，不回填历史理论文件。
- SYNTHETIC 点只用于算法验证，不是 RC 实测。
- 理论截止约 1591.5494 Hz；该频率处幅值约 -3.0103 dB、相位 -45°。
- 如果使用 SciPy `freqs` 交叉核对，传入角频率 `w=2*pi*f`；板端实现可只依赖 NumPy。
- B-X11 直通数据不能当作 RC 实测；B-X12 结果通过 `H_cal=H_raw/C0` 得到。
