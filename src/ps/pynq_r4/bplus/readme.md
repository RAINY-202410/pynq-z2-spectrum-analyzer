# b_plus_v1 频谱分析拓展工作区

本目录是 `B拓展加分操作步骤_20261030.md` 中 **B-X01（工作区）** 至 **B-X12（实测 RC）** 的交付物。

## 当前状态

- 扩展名称：`b_plus_v1`
- 当前状态：B-X01/B-X09/B-X10 `HOST_VALIDATED`；B-X11 的 PC 和信号发生器直通数据均为 `BOARD_VALIDATED`；B-X12 真实 RC 为 `RC_MEASURED`；B-X02～B-X07 `REPLAY_VALIDATED`；B-X08 离线 `OFFLINE_VERIFIED`。
- 执行环境：PC 离线；不加载 Overlay，不分配 PYNQ CMA，不访问 DMA。
- 板端实际版本：`spectrum_software_1_r2`，保持不动。
- `r3`：仅为已归档候选，未在板上部署，不能登记为 LIVE 实测。
- 可复用数据：r3 包内 7 份真实 PL 留样，以及 export02 会话原件（只读副本）。
- B-X02 索引：4 个 run、3220 条逐帧指标、20 份完整频谱留样。
- B-X03 回放：按 frame_id 顺序播放、原始时间/等间隔两种模式、稀疏瀑布和缺口提示。
- B-X04 特征：均方幅度平均谱、峰值保持、8/32 平均长度、清空和样本范围记录。
- B-X05 游标：A/B 实际 bin、Δf/ΔL、同曲线非零线性比值、5/12/24 kHz 视图。
- B-X06 趋势：保存局部峰趋势、目标频段缺测、按原时间事件和离群断点。
- B-X07 集成：统一工作台、趋势/事件、页面导出和独立重算。
- B-X08 离线：`/api/status` 只读适配、去重、缺口和合成状态验证；未访问板端。
- B-X09 RC 基准：R=1 kΩ、C=100 nF 的理论响应、16 个设计点和 4 个 SYNTHETIC 双声道案例。
- B-X10 拟合：同一同步 `(2,1024)` 块的共同频率最小二乘相量拟合和无效原因。
- B-X11：PC 数据使用 6 kHz 补采块；信号发生器补充数据 16 频点通过，按用户要求完全排除补采块。
- B-X12：978 Ω + 105.6 nF 真实 RC，16/16 点通过，一阶拟合截止约 1547.7 Hz。

## 快速检查

在本目录执行：

```powershell
python verify_baseline.py --require-source
python session_reader.py
python spectrum_features.py
python timeline_features.py
python live_subscription.py --fixture reports\B-X08\status_fixture.jsonl --out reports\B-X08
python rc\rc_model.py
python rc\phasor_fit.py
python rc\channel_calibration.py --m4-dir <M4 validation dir>
python -m rc.build_bx12 --dataset-dir <B-X12 M4 dir>
python plus_app.py --check
python -m unittest discover -s tests -v
```

B-X02 结果写入 `reports/B-X02/`：

- `sample_index.json`：run 摘要、20 条频谱留样索引和来源哈希。
- `metric_timeline.jsonl`：3220 条逐帧指标。
- `data_inventory.md`：数据清单和边界说明。
- `index_manifest.json`：三个输出文件的 SHA256。

B-X03 离线演示证据在 `reports/B-X03/`，包括初始页面、暂停状态、完整回放截图、执行后 DOM 和演示说明。

B-X04 参考算法、真实留样三曲线图和页面截图在 `reports/B-X04/`。平均谱只对单边线性幅度做均方平均；峰值保持覆盖本轮已观测帧。名称固定为“均方幅度平均谱”，不称为功率谱、PSD 或时域 RMS。

B-X05 双音游标参考和页面证据在 `reports/B-X05/`。A/B 都吸附真实 FFT bin；缩放只改变视图，不改变 bin、频率或读数。零幅度时幅比显示“不适用”，不会用 -240 dBFS 绘图下限计算。

B-X06 趋势与事件在 `reports/B-X06/`。趋势只使用已保存的最多三个局部峰；目标频段没有保存峰时记为缺测。`events.json` 中的合成验证明确标为 SYNTHETIC，不是板端故障。

B-X07 集成页面、分析包和演示在 `reports/B-X07/`。真实演示包为 `reports/B-X07/demo_export/`，可用 `recompute_export.py` 从同一 B-X02 索引重算；导出包有独立 manifest，不宣称旧审计器完整验收扩展格式。

B-X08 离线只读订阅在 `reports/B-X08/`。`live_subscription.py` 只读取 `/api/status`，按 `(service_address, process_id, run_id, frame_id)` 去重；实际状态缺少 `latest.frame_id` 时使用 `status.frames` 回退。当前验证是 OFFLINE_FIXTURE，BOARD_LIVE 尚未执行。

B-X09 RC 理论基准在 `reports/B-X09/`。16 个设计点的实测列保持空白；SYNTHETIC 案例独立标记，理论截止约 1591.5494 Hz，fc 处约 -3.0103 dB、-45°。

B-X10 同步双声道拟合在 `reports/B-X10/`。左声道为参考、右声道为输出，两个通道使用同一个拟合频率；零/弱参考、削顶候选和拟合差会保留无效原因。结果仍为 SYNTHETIC，不是 M4 板端实测。

B-X11 已完成 16 频点板端数据验证：PC 直通数据在 `reports/B-X11/full_20261101/`，每点 3 个校准块和 3 个有效独立验证块，6 kHz 使用 `val_retry_01`，状态为 `BOARD_VALIDATED`。新的 OWON XDG3122 信号发生器直通数据在 `reports/B-X11/signal_generator_20261101/`，16/16 点通过；6 kHz 的三个正式验证块均有效，`val_retry_01` 按用户要求完全排除。信源条件为实际 `0.2 Vpp`、`26 C`、标称 `50 Ω` 输出阻抗，3.5 mm 转接后的 L/R 并联到发生器输出、GND 共地；状态为 `BOARD_VALIDATED`。`board_accepted` 仍为 false。`reports/B-X11/audio_sources/` 有 16 个 48 kHz PCM WAV 播放源。

B-X12 已完成真实 RC 板端测量，数据在 `reports/B-X12/measured_20261101/`。实际元件为 `R=978 Ω`、`C=105.6 nF`、`25 C`；左声道为输入参考，右声道串入 R 并用 C 接 GND。16/16 点通过 B-X10 同步相量拟合和 B-X11 信号发生器通道校准。实测 R/C 理论截止约 `1541.05 Hz`，一阶复数拟合截止约 `1547.74 Hz`，偏差 `+0.434%`。该结果登记为 `RC_MEASURED`。

启动集成分析工作台：

```powershell
python plus_app.py
```

然后打开 `http://127.0.0.1:8765/`。这是 B-X07 集成页面；`?demo=bx07&range=5000` 会加载双音、A/B 游标和目标频段趋势，`?demo=bx07&range=5000&export=1` 还会通过页面导出可重算分析包。

## 目录说明

| 路径 | 用途 |
| --- | --- |
| `baseline.md` | B-X01 基线说明、来源、哈希和边界 |
| `BASELINE_MANIFEST.json` | 只读基线与输入副本的逐文件 SHA256 |
| `verify_baseline.py` | 校验原包未变、副本哈希一致、无未登记文件 |
| `baseline_readonly/` | 从 r3 候选和操作包提取的只读解析、参考代码与文档 |
| `inputs_readonly/` | export02 会话、审计和结果表的只读副本 |
| `plus_app.py` | B-X07 集成离线服务；回放、趋势和导出，不导入 PYNQ |
| `session_reader.py` | B-X02 实现：校验会话/run/成员哈希，复用 `fft_session.load_frame` 建立索引 |
| `spectrum_features.py` | B-X04 均方幅度平均、保持累计、样本范围和三曲线图 |
| `cursor_features.py` | B-X05 双游标实际 bin、读数和差值参考计算 |
| `timeline_features.py` | B-X06 局部峰趋势、缺测、迟滞事件和 `events.json` |
| `recompute_export.py` | B-X07 分析包独立重算和哈希校验 |
| `live_subscription.py` | B-X08 离线 `/api/status` 只读订阅、去重和缺口 |
| `rc/rc_model.py` | B-X09 RC 理论、测点结构和 SYNTHETIC 双声道数据生成 |
| `rc/phasor_fit.py` | B-X10 同步双声道最小二乘相量拟合 |
| `rc/channel_calibration.py` | B-X11 双通道直通校准试点和重复性 |
| `rc/build_full_bx11.py` | B-X11 16 频点完整数据集汇总和报告 |
| `rc/build_bx12.py` | B-X12 真实 RC 校准、拟合、截止频率和报告生成 |
| `export_results.py` | 扩展结果路径约束，只允许写入 `reports/` |
| `web/` | B-X07 集成页面：回放、曲线、游标、趋势和导出 |
| `tests/` | 基线、离线隔离、索引、特征、游标、趋势、导出和重算测试 |
| `reports/B-X02/` | B-X02 索引、逐帧指标、数据清单和输出哈希 |
| `reports/B-X03/` | B-X03 页面截图、DOM 证据和离线演示说明 |
| `reports/B-X04/` | 真实留样三曲线图、B-X04 页面截图和计算说明 |
| `reports/B-X05/` | 双音 A/B 游标截图、参考读数和 DOM 证据 |
| `reports/B-X06/` | 真实趋势图、`events.json`、合成序列验证和事件说明 |
| `reports/B-X07/` | 集成页面、演示视频、分析包和重算证据 |
| `reports/B-X08/` | 合成状态 fixture、只读订阅报告和验证记录 |
| `reports/B-X09/` | RC 理论图、设计点表、SYNTHETIC 数据和 manifest |
| `reports/B-X10/` | SYNTHETIC 拟合结果、残差/质量原因和证据清单 |
| `reports/B-X11/` | 16 频点原始数据、完整校准报告、重复性图和 1 kHz pilot |
| `reports/B-X12/` | 978 Ω + 105.6 nF 真实 RC、逐点幅相结果和截止频率 |
| `matlab/` | B-X11 16 频点 WAV 生成脚本（MATLAB 主脚本和 fallback） |
| `rc/` | B-X09～B-X12 的离线算法与实验预留目录 |

## 边界

`baseline_readonly/` 中的文件按原字节复制，不在其中修改代码。所有新增实现放在本目录的扩展模块中。原始操作包、r3 包、export02 会话和板端 r2 服务均不因 B-X01 改变。

`spectrum_sources.py` 和 `fft_delivery.py` 中包含 `LiveSource`/`FFTCapture` 类的参考定义，但导入这些文件不会加载 PYNQ；扩展入口 `plus_app.py` 也不会导入它们。B-X02 只读会话 ZIP，复用已保存的 PL 复数结果，不做 CPU FFT。实时只读订阅属于 B-X08，必须等 r2 数据保全完成后再做。

B-X12 已完成真实 RC 实测并登记为 `RC_MEASURED`；信号发生器条件下的 B-X11 数据和物理源条件也已完整记录。`board_accepted` 仍由整个作品发布验收决定。B-X08 实时部分仍需在 r2 数据保全后安排；离线部分已经可以使用 B-X02 索引、B-X04 线性幅度、B-X05 游标、B-X06 事件、B-X07 分析包和 B-X08 状态 fixture。长测的 3100 条指标不等于 3100 份频谱；只有 `saved_sample_frame_ids` 中的 14 个 frame 有完整频谱。

点击页面上的 A/B 按钮可切换活动游标；`?demo=bx05&range=5000` 会加载双音留样并把 A/B 放到 1 kHz/3 kHz 最近的实际 bin。
