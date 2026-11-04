# b_plus_v1 基线记录（B-X01）

记录日期：2026-10-31（北京时间）。扩展名称：`b_plus_v1`。

## 1. 原包与来源

| 项目 | 值 |
| --- | --- |
| 配套操作包 | `D:\AMD_competition\documents\B_拓展加分操作包_20261030.zip` |
| 操作包字节数 | 8,151,396 |
| 操作包 SHA256 | `3F555DC433BDC50993BDB93B97D92415E0FE224B746DAC9B1EE30E0B79B3886E` |
| r3 完整候选 | 操作包内 `baseline/A_spectrum_software_v1_r3.zip` |
| r3 字节数 | 6,762,264 |
| r3 SHA256 | `B9079BB1AD03A610AFB2BE3D5CD8A3323B329C8F61846EB375A1C149D0907AA5` |
| r3 内部 `package_manifest.json` | 已原样复制到 `baseline_readonly/package_manifest.json` |

r3 文件哈希与操作包 `manifest.json` 一致。复制后的基线文件逐项对照 r3 内部清单和 ZIP 实际条目，未修改原 ZIP、原 manifest 或任何原始实验目录。

## 2. 板端状态

- 实际部署：`spectrum_software_1_r2`，目录 `/home/xilinx/jupyter_notebooks/spectrum_software_v1_r2`。
- r2 板端 ZIP SHA256：`D6F01E440CB184AD08E052A6A9C0789B7EA7CCFF0FA6EEA34A087E2DFDD51E1A`。
- `r3` 仅为导出等待修复候选；主机验证不等于实际 LIVE 板测。
- `board_accepted=false` 保持。
- 本轮先在 PC 上开发，不切换 Overlay、不停止 r2 服务、不重跑长测。
- 新的约 30 分钟运行仍以用户回传原件为准；B-X01 不要求重复采集。

## 3. 已有真实数据

| 数据 | 值 |
| --- | --- |
| export02 会话原件 | `inputs_readonly/spectrum_session_a79f9a7236b2_export02.zip` |
| 会话 SHA256 | `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E` |
| 运行/帧数 | 9 次运行、3542 帧 |
| 原始留样 | 28 份完整频谱留样、11 张界面图 |
| 长测 | `spectrum_569e5f254203`，Hann/tone1k，620.01506344 秒、3100 帧 |
| 双音/静音 | 矩形与 Hann 双音各 40 帧；模拟静音 40 帧 |

export02 的审计、频率表和指标表也在 `inputs_readonly/`。它们是只读输入，扩展输出不得写回这些文件或原始 run 目录。

## 4. 引用的只读代码

以下文件按原字节复制到 `baseline_readonly/`，用途仅限参考和离线解析：

| 文件 | 用途 |
| --- | --- |
| `host_tools/sw/pynq/fft_session.py` | 校验帧元数据、哈希并解析完整复数谱；不重新做 FFT |
| `host_tools/sw/pynq/fft_delivery.py` | FFT 常量、Q1.15/S=11 恢复和单边幅值；含板上类定义但导入不访问硬件 |
| `host_tools/sw/pynq/fft_contract_assets.py` | 64 位复数打包/解包和符号扩展检查 |
| `host_tools/sw/pynq/m4_delivery.py` | M4 双声道原始数据参考；B-X10/X11 才使用 |
| `host_tools/sw/pynq/spectrum_analysis.py` | 既有局部峰、三点插值和单音检查 |
| `host_tools/sw/pynq/spectrum_sources.py` | `ReplaySource` 参考；`LiveSource` 仅作只读对照 |
| `host_tools/sw/pynq/spectrum_recording.py` | 会话目录、`frames.jsonl`、`summary.json` 和导出格式参考 |
| `host_tools/sw/pynq/fft_campaign.py` | `memory_sample()` 等会话记录依赖 |
| `host_tools/sw/pynq/spectrum_app.py` | 既有页面/服务参考，不在扩展中直接运行 |
| `host_tools/sw/pynq/spectrum_web/` | 既有单游标、瀑布和范围切换前端参考 |
| `host_tools/sw/reference/audit_spectrum_session.py` | 独立证据审计器参考 |
| `host_tools/sw/pynq/replay_examples/` | 7 份真实 PL 留样（tone1k、tone2k、双音、静音） |
| `references/fft_contract.md` | FFT v1.0 接口契约，8192 字节/帧、自然序、S=11 |
| `docs/B拓展加分操作步骤_20261030.md` | 本轮 12 步实施操作单 |

完整 r3 ZIP 仍保留原处，未解压覆盖到主工程。`baseline_readonly/` 是所选子集，不宣称等于完整 r3 包；完整包中的 golden 向量、发布 ZIP 和历史报告仍可从原包取得。

## 5. 离线边界

- `plus_app.py` 只使用 Python 标准库，启动静态页面，不导入 `pynq`，不调用 `Overlay`、`allocate`、`MMIO` 或 DMA。
- 解析一份真实留样时，只读取 `*_words.npy` 和 `*_state.json`；导入 `fft_session`/`fft_delivery` 不会实例化 `FFTCapture`。
- 所有扩展输出必须经过 `export_results.resolve_report_path()`，只允许写入 `reports/`。
- `LiveSource`、M4 采集、RC 实测和 Overlay 切换不属于 B-X01；B-X08 若接实时数据，优先只读订阅既有 `/api/status`。

## 6. B-X01 验收结果

- [x] 独立目录 `extensions/b_plus_v1/` 已建立。
- [x] `baseline.md`、目录骨架和只读基线已建立。
- [x] 原操作包和 r3 ZIP 哈希未改变。
- [x] 复制文件与 r3 内部 manifest、ZIP 条目一致。
- [x] export02 会话及结果表复制后哈希一致。
- [x] 离线导入和真实留样解析不加载 PYNQ。
- [x] 输出路径守卫拒绝 `reports/` 之外的路径。

实际结果：

- `verify_baseline.py --require-source`：`ok=true`，147 项检查，0 失败；操作包、r3 归档、r3 manifest、r3 ZIP 条目和 export02 输入均匹配。
- `plus_app.py --check`：`OFFLINE_READY`，`hardware_access=false`，`pynq_imported=false`，识别 7 份真实 PL 留样。
- 单元测试：9/9 通过，覆盖真实留样解析、坏哈希拒绝、PYNQ 隔离和输出路径逃逸。
- 实际启动静态页面：HTTP 200，页面包含 `OFFLINE_ONLY`。
- 板端动作：无；`board_accepted=false` 保持。

具体记录见 `progress.md` 和 `BASELINE_MANIFEST.json`。

## 7. B-X02/B-X03 与下一步

B-X02 已完成：从 export02 选出长测 Hann 单音、矩形双音、Hann 双音和静音四个 run，建立 3220 条逐帧指标与 20 份完整频谱留样索引。结果在 `reports/B-X02/`，状态 `REPLAY_VALIDATED`。

B-X03 已完成：按原始 frame_id 顺序播放留样，支持按原时间和等间隔浏览、暂停/上一份/下一份、稀疏瀑布、缺口提示和游标锁定重置。页面与离线演示证据在 `web/` 和 `reports/B-X03/`。

B-X04 已完成：均方幅度平均谱、峰值保持、8/32 平均长度、清空和样本范围记录已接入回放页面；真实留样三曲线图在 `reports/B-X04/`。

B-X05 已完成：A/B 实际 bin 游标、测量曲线切换、Δf/ΔL、同曲线非零线性比值和局部视图读数已接入页面；双音参考读数在 `reports/B-X05/`。B-X06 起再实现趋势、事件或 RC 算法。

B-X06 已完成：逐帧局部峰趋势、目标频段缺测、连续帧/迟滞/间隔断点事件和 `events.json` 已生成；真实趋势图在 `reports/B-X06/`。B-X07 起再进行页面集成和导出。

B-X07 已完成：回放、平均/保持、双游标、趋势事件和导出集成到同一页面；真实演示分析包在 `reports/B-X07/demo_export/`，并有独立重算脚本。B-X08 起再考虑实时只读接入。

B-X08 离线部分已完成：只读 `/api/status` 适配、按 service/process/run/frame 去重、缺口记录和合成 fixture 验证在 `reports/B-X08/`。实际 BOARD_LIVE 轮询与跨域代理仍未执行。

B-X09 已完成理论/合成基准：R=1 kΩ、C=100 nF，16 个设计点实测字段留空，4 个 SYNTHETIC 双声道案例和理论图在 `reports/B-X09/`。B-X10 起再实现同步双声道拟合。

B-X10 已完成同步双声道最小二乘相量拟合：同一 `(2,1024)` 块的左右声道共用一个频率，SYNTHETIC 增益/相位和无效原因在 `reports/B-X10/`。B-X11 起再接入实际 M4 双声道直通数据。

B-X11 已完成 16 频点板端数据验证：16/16 点通过，6 kHz 使用 `val_retry_01` 替换失败的低电平 `val_03`。完整结果在 `reports/B-X11/full_20261101/`，状态 `BOARD_VALIDATED`；已记录音量 100%、PC 3.5mm 直连 LINE IN、25 C、PLL/fs 和 M4 哈希。B-X12 才接 RC 电路。

2026-11-01 补充的信号发生器信源数据在 `reports/B-X11/signal_generator_20261101/`：96 个正式块、16/16 点通过，6 kHz 补采块按要求排除；OWON XDG3122、实际 0.2 Vpp、26 C、标称 50 Ω 输出，L/R 并联且 GND 共地，状态为 `BOARD_VALIDATED`。

B-X12 真实 RC 已完成：`R=978 Ω`、`C=105.6 nF`、`25 C`，16/16 点通过。实测 R/C 理论截止 `1541.052 Hz`，一阶复数拟合截止 `1547.745 Hz`，偏差 `+0.434%`；结果在 `reports/B-X12/measured_20261101/`，状态为 `RC_MEASURED`。
