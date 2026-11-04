# b_plus_v1 进度记录

## B-X01：建立独立扩展工作区

步骤编号：B-X01

实际完成的操作：

- 建立 `extensions/b_plus_v1/`，把新增实现限制在该目录内。
- 从操作包和 r3 完整候选提取解析、参考、审计、前端样例和真实 PL 留样，按原字节放入 `baseline_readonly/`。
- 复制 export02 会话、审计和结果表到 `inputs_readonly/`，原件不变。
- 建立 `BASELINE_MANIFEST.json`，记录操作包、r3、export02、44 个基线文件和 5 个输入文件哈希。
- 建立纯标准库离线入口 `plus_app.py`、静态状态页、B-X02/B-X04/B-X06 预留桩和 `reports/` 输出守卫。

这一步实现了什么：

形成一个不依赖板卡、可单独开发与回退的离线工作区；后续步骤可以基于真实留样开始实现，而不会改动 r2 服务、Overlay 或原始证据。

新增/修改文件：

- `README.md`、`baseline.md`、`BASELINE_MANIFEST.json`、`progress.md`
- `verify_baseline.py`、`plus_app.py`、`export_results.py`
- `session_reader.py`、`spectrum_features.py`、`timeline_features.py`
- `web/`、`tests/`、`reports/`、`rc/`
- `baseline_readonly/`、`inputs_readonly/`

使用的输入及来源：

- `documents/B_拓展加分操作包_20261030.zip`，SHA256 `3F555DC433BDC50993BDB93B97D92415E0FE224B746DAC9B1EE30E0B79B3886E`
- 操作包内 `baseline/A_spectrum_software_v1_r3.zip`，SHA256 `B9079BB1AD03A610AFB2BE3D5CD8A3323B329C8F61846EB375A1C149D0907AA5`
- export02 会话，SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`

验证方法和实际结果：

- `python verify_baseline.py --require-source`
  - `ok=true`，147 项检查，0 失败。
  - 操作包、r3 归档、r3 manifest、r3 ZIP 条目和 export02 输入均逐项匹配。
- `python plus_app.py --check`
  - `status=OFFLINE_READY`，`hardware_access=false`，`pynq_imported=false`。
  - 识别到 7 份真实 PL 留样。
- `python -m unittest discover -s tests -v`
  - 9 个测试全部通过。
  - 覆盖真实留样解析、坏哈希拒绝、PYNQ 未导入、输出路径逃逸拒绝。
- 实际启动 `plus_app.py` 并访问 `http://127.0.0.1:8765/`
  - HTTP 200，页面标题为 `b_plus_v1 · B-X01 离线基线`，页面包含 `OFFLINE_ONLY`。
- 板端动作：无。未加载 Overlay、未分配 CMA、未访问 DMA、未切换 r2 服务。

状态：HOST_VALIDATED

尚未完成与所需配合：

- B-X01 完成时 B-X02 尚未开始；B-X02 现已由下一节完成。
- 多帧回放、平均/保持谱、双游标、趋势/事件和 RC 算法均未在 B-X01 实现。
- r3 仍未部署；实际 LIVE 验证和板端签收保持待定。
- 无需用户为 B-X01 上板；B-X02 起的离线开发也继续使用已有 export02，不要求重跑 30 分钟。

## B-X02：建立真实数据读取与时间索引

步骤编号：B-X02

实际完成的操作：

- 从 export02 会话中选择四个代表性 run：长测 Hann 单音、矩形双音、Hann 双音和模拟静音。
- 校验会话 ZIP、session manifest、4 个 run ZIP、每个 run 的 export manifest，以及全部已列文件的 SHA256。
- 按 `summary.json` 的 `saved_samples` 建立 `frame_id → stem`，再从 `frames.jsonl` 取原始 `elapsed_s`、硬件 sequence 和逐帧 metrics。
- 复用冻结的 `fft_session.load_frame` 解析 20 份完整频谱；逐份核对解析出的复数 FFT 与归档 `_fft.npy` 完全一致，没有重新做 FFT。
- 输出 `reports/B-X02/sample_index.json`、`metric_timeline.jsonl`、`data_inventory.md` 和 `index_manifest.json`。

这一步实现了什么：

把已有 export02 证据统一成两个可复用数据集合：20 份真实完整频谱留样和 3220 条逐帧指标时间线。后续回放、平均谱、双游标和趋势分析可以直接读取，不需要重新采集或重新 FFT。

新增/修改文件：

- `session_reader.py`
- `reports/B-X02/sample_index.json`
- `reports/B-X02/metric_timeline.jsonl`
- `reports/B-X02/data_inventory.md`
- `reports/B-X02/index_manifest.json`
- `tests/test_session_reader.py`

使用的输入及来源：

- `inputs_readonly/spectrum_session_a79f9a7236b2_export02.zip`
- SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`
- 原始上下文 `BOARD_LIVE`，原始采集模式 `LIVE`，实例 `instrument_a79f9a7236b2`

验证方法和实际结果：

- 选中 4 个 run，`frames.jsonl` 行数与各 summary 一致：3100 + 40 + 40 + 40 = 3220 条。
- 完整频谱留样：长测 14 份，双音各 2 份，静音 2 份，共 20 份。
- 20 份留样全部通过 `fft_session.load_frame`；20/20 的解析复数结果与归档 `_fft.npy` 一致。
- 4 个 run 的硬件 sequence 均连续；索引 warnings 为 0。
- `python -m unittest discover -s tests -v`：17/17 通过。
- 板端动作：无；未加载 Overlay、未访问 DMA、未切换 r2 服务。

状态：REPLAY_VALIDATED（仅 B-X02 索引/解析，不代表 B-X03 回放 UI）

尚未完成与所需配合：

- 长测的 3100 条指标只有 14 条对应完整频谱，不能把其余区间画成完整频谱。
- 四个 run 分开保存，未做跨 run、跨窗或不同频率网格的统计合并。
- B-X03 多帧回放尚未实现；B-X04～B-X12 仍按原操作单推进。
- 无需用户为 B-X02 上板；B-X03 的离线演示可继续使用当前索引。

## B-X03：按时间顺序的多帧回放

步骤编号：B-X03

实际完成的操作：

- 在 `plus_app.py` 增加只读回放 API：`/api/replay/index` 返回 run、留样顺序和缺口段；`/api/replay/frame` 按需加载指定 frame。
- 页面增加 run、播放方式、速度、上一份、播放/暂停、下一份控件。
- 支持“按原时间播放”和“等间隔浏览留样（非原始时间轴）”，速度只缩放播放节奏，不修改原始 `elapsed_s` 标签。
- 频谱按真实留样 frame_id 顺序显示；缺口面板显示中间缺少的指标行数，不插造中间曲线。
- 瀑布纵轴明确标为“留样序号 / 原始时间”，并且只绘制真实留样行。
- 换 run 时清空瀑布、统计和游标锁定；暂停清除定时器并使在途加载失效；播放结束停在最后一份，不自动循环。
- 生成无头 Edge 实际渲染截图和 DOM，作为离线演示证据。

这一步实现了什么：

把 B-X02 的静态索引变成可复盘实验过程的播放器，能够展示单音、双音和静音留样之间的原始时间变化，并明确区分完整频谱留样和仅有指标的区间。

新增/修改文件：

- `plus_app.py`：B-X03 回放服务与 API
- `web/index.html`、`web/style.css`、`web/replay.js`
- `tests/test_replay_service.py`
- `reports/B-X03/player_initial.png`
- `reports/B-X03/player_demo_complete.png`
- `reports/B-X03/player_paused.png`
- `reports/B-X03/player_dom.html`、`reports/B-X03/player_demo_dom.html`、`reports/B-X03/player_paused_dom.html`
- `reports/B-X03/offline_demo.md`

使用的输入及来源：

- B-X02 的 `reports/B-X02/sample_index.json`
- export02 会话 SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`
- 4 个选中 run，共 20 份完整频谱留样

验证方法和实际结果：

- `python -m unittest discover -s tests -v`：23/23 通过。
- `python plus_app.py --check`：`OFFLINE_READY`，`hardware_access=false`，`pynq_imported=false`。
- 实际启动 `plus_app.py`：页面 HTTP 200；索引 API 返回 4 个 run、3220 条指标、20 份频谱；frame 1 API 返回 513 点 REPLAY 频谱；缺失 frame 返回 404。
- Edge 无头渲染初始页面：14 行留样列表、REPLAY 标签、time-axis 缺口标注可见。
- `?demo=1` 完整演示：14 行瀑布、等间隔非原始时间标签、末尾“播放结束 · 未自动循环”可见。
- 暂停/上一份/下一份的状态机在页面代码中清定时器、失效在途请求，并保持当前 frame 不变。
- 板端动作：无；未加载 Overlay、未访问 DMA、未切换 r2 服务。

状态：REPLAY_VALIDATED（B-X03 页面与 API 已用真实归档数据验证；不代表板端 UI 验收）

尚未完成与所需配合：

- B-X04 平均/保持谱、B-X05 双游标、B-X06 趋势/事件和 RC 系列尚未实现。
- 播放器目前只加载 B-X02 的四个代表性 run，不宣称覆盖完整 9-run 会话。
- 没有把截图或 DOM 当作新的板端采集证据；`board_accepted` 仍为 false。

## B-X04：均方幅度平均谱与峰值保持

步骤编号：B-X04

实际完成的操作：

- 实现 `spectrum_features.py` 的线性均方幅度平均、元素最大值保持、dBFS 绘图转换和 8/32 平均长度。
- 页面增加三条可独立显示/隐藏的曲线、平均长度选择、清空平均/保持按钮。
- 页面记录平均曲线的有效样本数与起止 frame/elapsed_s，记录保持曲线的累计样本数与起止时间。
- 同一 frame_id 重复加载不增加累计样本；换 run/切换窗/显式清空会重置特征状态。
- 使用真实 export02 `long_hann_tone1k` 的 14 份留样生成 M=8 与 M=32 的三曲线对比图。

这一步实现了什么：

可以在真实留样上观察当前谱、均方幅度平均谱和峰值保持，区分平均时间窗与从重置以来的最大值；没有把稀疏帧伪装成连续音频，也没有跨 run 合并统计。

新增/修改文件：

- `spectrum_features.py`
- `tests/test_spectrum_features.py`
- `web/index.html`、`web/style.css`、`web/replay.js`
- `reports/B-X04/three_curves.png`、`three_curves.svg`
- `reports/B-X04/player_features_initial.png`
- `reports/B-X04/player_features_demo_m8.png`
- `reports/B-X04/player_features_demo_m32.png`
- `reports/B-X04/README.md`

使用的输入及来源：

- B-X02 的 `reports/B-X02/sample_index.json` 和真实 `long_hann_tone1k` 留样
- export02 会话 SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`

验证方法和实际结果：

- `python spectrum_features.py`：生成 M=8 平均 8 份、保持 14 份；M=32 实际平均 14 份、保持 14 份的三曲线图。
- 页面无头 Edge 实际渲染：M=8 显示平均 8/8、保持 14；M=32 显示平均 14/32、保持 14；状态为“累计中”。
- `python -m unittest discover -s tests -v`：33/33 通过。
- 逐项测试覆盖小数组手工结果、零幅度、重复 frame、窗口/reset、平均长度切换、32 份内存上限和保持累计。
- 板端动作：无；未加载 Overlay、未访问 DMA、未切换 r2 服务。

状态：REPLAY_VALIDATED（B-X04 算法、真实留样图和页面已离线验证；不代表板端验收）

尚未完成与所需配合：

- B-X05 双游标、B-X06 趋势/事件和 RC 系列尚未实现。
- 峰值保持只代表已采到的留样；不能捕获帧间未采样瞬态。
- 页面当前使用 B-X02 的四个代表性 run；不把页面演示当作新的板端采集。

## B-X05：双游标和差值读数

步骤编号：B-X05

实际完成的操作：

- 新增 A/B 两个独立游标，点击频谱移动当前活动游标；游标位置为实际 FFT bin。
- 增加测量曲线选择：当前谱、均方幅度平均谱、峰值保持；切换后 A/B 读数、Δ 和比值同步更新。
- 显示每个游标的 bin、实际频率、线性幅度和 dBFS。
- 计算 `Δf = f_B - f_A`、`ΔL = L_B - L_A`，并在同一曲线且两个线性幅度非零时给出 `A_B/A_A` 及其 dB 表示。
- 增加双音 A/B 示例按钮；`?demo=bx05` 选择 `dual_hann` 的 1 kHz/3 kHz 最近实际 bin。
- 保留 5/12/24 kHz 局部视图，并明确缩放不提高 FFT 分辨率。

这一步实现了什么：

可以直接在双音留样上量化两个实际频点的频率差、电平和线性幅比，同时明确测量对象是当前谱、平均谱还是保持谱。

新增/修改文件：

- `cursor_features.py`
- `tests/test_cursor_features.py`
- `web/index.html`、`web/style.css`、`web/replay.js`
- `reports/B-X05/cursor_reference.json`
- `reports/B-X05/player_dual_cursors_zoom5k.png`
- `reports/B-X05/player_dual_cursors_average.png`
- `reports/B-X05/player_dual_cursors_zoom24k.png`
- `reports/B-X05/player_dual_cursors_dom.html` 等 DOM 证据

使用的输入及来源：

- B-X02 的 `spectrum_38749b56cab6`（dual_hann）frame 1、真实 1024 点留样
- export02 会话 SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`

验证方法和实际结果：

- 实际 A/B：bin 21 / 64，984.3456597535279 Hz / 2999.9105821059898 Hz。
- 线性幅度 0.14419390360589673 / 0.07728916282466285，dBFS -16.821062016504825 / -22.237627936742932。
- Δf 2015.564922352462 Hz，ΔL -5.4165659202381065 dB，线性幅比 0.5360085335917222。
- 5 kHz 和 24 kHz 视图的 DOM 读数一致：A 线性 0.144194、B 线性 0.0772892、比值 0.53601，说明缩放没有改变 bin 网格。
- 零幅度比值不适用、不同曲线不产生比值、非法 bin 拒绝均有测试。
- `python -m unittest discover -s tests -v`：37/37 通过。
- 板端动作：无；未加载 Overlay、未访问 DMA、未切换 r2 服务。

状态：REPLAY_VALIDATED（B-X05 双音游标和页面已离线验证；不代表板端验收）

尚未完成与所需配合：

- B-X05 完成时 B-X06 尚未实现；B-X06 见下一节。
- 游标读数来自保存的线性幅度；幅值未做物理电压标定。
- 局部视图没有增加 FFT 分辨率，不能把缩放后的频轴当作新增谱线。

## B-X06：信号趋势和阈值事件

步骤编号：B-X06

实际完成的操作：

- 从 B-X02 的 `metric_timeline.jsonl` 读取全部 3220 条逐帧指标，支持最大局部峰和目标频段内保存峰两种选择。
- 每个趋势点保留离散 bin 频率、辅助插值估计频率、线性幅度、dBFS、原质量状态和弱信号/邻峰提示。
- 目标频段没有保存峰时记录缺测，不从标量日志重建频谱。
- 实现幅值低于阈值、频率超出范围、目标频段缺测三类事件；使用连续帧、迟滞和 `max_gap_s=2.0 s` 断点。
- 输出真实 REPLAY 趋势图和 `events.json`；合成验证序列单独标记 `SYNTHETIC_TEST`、`board_fault=false`。

这一步实现了什么：

将逐帧指标变成了可复核的实验趋势，并能在保持“缺测就是缺测”的前提下标记连续阈值事件。事件只表示观测条件，不自动控制硬件，也不直接命名断线或削顶。

新增/修改文件：

- `timeline_features.py`
- `tests/test_timeline_features.py`
- `reports/B-X06/events.json`
- `reports/B-X06/trend_long_hann.png` / `.svg`
- `reports/B-X06/trend_dual_hann_target1k.png` / `.svg`
- `reports/B-X06/trend_silence_target1k.png` / `.svg`
- `reports/B-X06/README.md`

使用的输入及来源：

- B-X02 的 `reports/B-X02/metric_timeline.jsonl`
- export02 会话 SHA256 `3E7FFF49310213C024F073566E5420B5F69727BD9E9C225698B90D7272EBD62E`

验证方法和实际结果：

- 长测 max_peak：3100 点全部有保存峰，0 缺测、0 事件；离散峰约 984.3 Hz，辅助估计约 1000.7 Hz。
- 静音 target 1000 ± 50 Hz：40 点全部缺测，形成 frame 1–40 的连续缺测事件；没有伪造该频段 dBFS。
- 双音 target 1000 ± 100 Hz：40 点全部有保存峰，0 缺测、0 事件。
- 合成序列验证 4 个事件：幅值越阈恢复、频率越界恢复、缺测恢复、10 秒间隔后的独立未闭合幅值事件；长间隔没有合并。
- `python -m unittest discover -s tests -v`：41/41 通过。
- 板端动作：无；未加载 Overlay、未访问 DMA、未切换 r2 服务。

状态：REPLAY_VALIDATED（B-X06 趋势与事件已用真实 REPLAY 指标和合成序列验证；不代表板端故障验收）

尚未完成与所需配合：

- B-X06 完成时 B-X07 页面集成/导出尚未完成；B-X07 见下一节。
- 事件只基于最多三个保存峰和逐帧指标；没有完整频谱的区间不能做谱重建。
- 合成事件不是板端故障记录；`board_accepted=false` 保持。

## B-X07：集成工作台与可重算导出

步骤编号：B-X07

实际完成的操作：

- 页面集成回放、当前/平均/保持曲线、A/B 游标、趋势/事件和导出按钮。
- 首屏保留原始来源 BOARD_LIVE、当前 REPLAY、run、原始 elapsed_s、window、fs、N 和稀疏留样提示。
- 增加 `/api/replay/trend`，使用 `timeline_features.py` 的保存峰/缺测/迟滞规则生成页面趋势。
- 增加 `/api/export`，页面提交观察帧、当前帧、平均长度、游标曲线/bin 和趋势参数；服务端从归档重算后写包。
- 导出包包含 `analysis_summary.json`、平均/保持/当前/所选曲线数组、频率轴、游标读数、源索引、趋势、事件、参数、manifest 和独立重算脚本。
- 生成真实演示包 `reports/B-X07/demo_export/`，并用 `recompute_export.py` 验证 `ok=true`。
- 生成集成页面截图、页面实际导出截图和由实际截图/真实趋势图组成的 12 秒 `demo.mp4`。

这一步实现了什么：

形成可演示、可截图、可复核且能由另一台电脑重算的完整扩展工作台；导出结果不写回原始 run 目录，也不冒充旧会话审计格式。

新增/修改文件：

- `plus_app.py`：B-X07 页面服务、趋势 API 和导出 POST
- `web/index.html`、`web/style.css`、`web/replay.js`
- `recompute_export.py`
- `tests/test_export_package.py`
- `reports/B-X07/README.md`
- `reports/B-X07/integrated_workbench.png`、`integrated_export.png`
- `reports/B-X07/demo.mp4`
- `reports/B-X07/demo_export/`

使用的输入及来源：

- B-X02 export02 索引与 20 份真实频谱留样
- B-X02 的 3220 条逐帧指标
- 真实双音 run `spectrum_38749b56cab6`

验证方法和实际结果：

- 页面无头 Edge 实际渲染：`?demo=bx07&range=5000` 显示 A/B bin 21/64、趋势面板和导出按钮。
- 页面实际触发 `/api/export`：HTTP 200，生成包含 14 个文件的分析包；页面显示导出路径与平均/保持/事件摘要。
- 演示包重算：观察 frame 1/40，当前 frame 40，平均 2 份、保持 2 份、趋势 40 点、事件 0；`ok=true`，无失败项。
- 趋势 API 返回 40 点，页面显示 source BOARD_LIVE → REPLAY、稀疏留样和原时间轴。
- `python -m unittest discover -s tests -v`：44/44 通过。
- B-X01 基线复核 147 项检查、0 失败。
- 板端动作：无；未加载 Overlay、未访问 DMA。

状态：REPLAY_VALIDATED（B-X07 集成、页面导出和独立重算已离线验证；不代表板端验收）

尚未完成与所需配合：

- B-X08 实时只读接入尚未完成；当前仅为归档 REPLAY。
- 导出包有自己的 manifest；旧会话审计器不能被称为已完整验收扩展格式。
- `demo.mp4` 是实际页面截图/真实趋势图的离线短片，不是实板屏幕录像。
- 幅值未物理标定；`board_accepted=false` 保持。

## B-X08：离线只读订阅部分

步骤编号：B-X08（离线部分）

实际完成的操作：

- 实现 `live_subscription.py`，只读取既有 `/api/status`，不初始化 LiveSource，也不调用 start/stop/render。
- 使用 `(service_address, process_id, run_id, frame_id)` 去重；重复轮询同一最新帧只计一次。
- 当前状态没有 `latest.frame_id` 时使用 `status.frames` 回退；不假设 instance_id 或新字段。
- 记录 frame/sequence 缺口、latest=None 跳过、run/process 切换和特征重置。
- 把接受的最新帧送入 `SpectrumAccumulator`，保留逐帧 metrics 供趋势计算。
- 生成合成 `status_fixture.jsonl`、`subscription_report.json` 和离线验证记录。

这一步实现了什么：

在不接触板卡的前提下，验证了后续实时增强所需的只读订阅、去重、缺口语义和特征接入。实际 BOARD_LIVE 顺序轮询和跨域代理仍未执行。

新增/修改文件：

- `live_subscription.py`
- `tests/test_live_subscription.py`
- `reports/B-X08/status_fixture.jsonl`
- `reports/B-X08/subscription_report.json`
- `reports/B-X08/README.md`
- `reports/B-X08/verification.md`

使用的输入及来源：

- 现有 r3 `/api/status` 字段形状：process_id、run_id、frames、elapsed_s、latest、metrics
- 合成状态序列；不包含板端原始数据

验证方法和实际结果：

- 合成 fixture 接受 4 帧、重复 1 次、跳过 1 次、记录 frame 2→5 缺口 2 帧。
- run A/process 4101 到 run B/process 4102 后，特征/history 重置；最终 run B 特征平均/保持各 1 份。
- `live_subscription.py` 只使用 GET `/api/status`；未执行任何控制 POST。
- 全套测试 `48/48` 通过；B-X01 基线 `147` 项检查、0 失败。
- 未访问实际 `192.168.2.99:8091`，因此 B-X08 BOARD_LIVE 仍是 `NOT_EXECUTED`。

状态：OFFLINE_VERIFIED（离线订阅/去重/缺口）；BOARD_LIVE_PENDING

尚未完成与所需配合：

- 实际板端状态短测需在 r2 数据保全和服务安排后由用户配合；不重复 30 分钟长测。
- 跨域只读代理尚未实现；后续不得开放基线控制接口。
- 不把轮询次数当作采集帧数，不把缺口两侧当作连续触发。

## B-X09：RC 理论基准与 SYNTHETIC 数据

步骤编号：B-X09

实际完成的操作：

- 建立 R=1 kΩ、C=100 nF 的一阶 RC 低通理论模型。
- 计算理论截止 `1591.5494309189535 Hz`，并验证 fc 处约 `-3.010299956639812 dB`、`-45°`。
- 建立 16 个设计频点和 `rc_points` 数据结构，实测频率、帧号、原始文件、通道校准、传递比、增益/相位和实际 R/C 字段保持空白。
- 生成 4 个 SYNTHETIC 双声道案例，包含已知增益/相位、公共频偏、不同直流偏置和弱参考案例。
- 生成独立合成点表、NPZ 原始/浮点数据、理论/合成点分别图例的幅相图。

这一步实现了什么：

为后续 B-X10 双声道拟合提供可复现的理论参照、空白实测模板和带已知真值的测试输入；没有把理论或合成点冒充实测 RC。

新增/修改文件：

- `rc/rc_model.py`、`rc/__init__.py`、`rc/README.md`
- `tests/test_rc_model.py`
- `reports/B-X09/rc_points.json`、`rc_points.csv`
- `reports/B-X09/synthetic_points.csv`
- `reports/B-X09/synthetic/*.npz`
- `reports/B-X09/theory.png`、`theory.svg`
- `reports/B-X09/README.md`、`manifest.json`

使用的输入及来源：

- 项目 RC 实验设计：R=1 kΩ、C=100 nF
- 合成数据；无板端原始 RC 测量

验证方法和实际结果：

- 16 个设计点全部 `NOT_MEASURED`，实测 gain/phase 列为空；所有点 `source=DESIGN_ONLY`。
- 4 个合成案例 `source=SYNTHETIC`；NPZ 为 `(2,1024)` int32/float 双声道，含真实频偏和 `truth_gain_db/truth_phase_deg`。
- 理论图将设计点与 SYNTHETIC 真值点使用不同图例。
- `python -m unittest discover -s tests -v`：53/53 通过。
- 未执行板端 RC 接线或采集；`board_accepted=false`。

状态：HOST_VALIDATED（仅理论/合成基准；实测 RC 待 B-X11/B-X12）

尚未完成与所需配合：

- B-X10 尚未实现同步双声道拟合和复数传递比。
- 实际 R/C、通道直通校准、接线和板测需要用户后续配合。
- SYNTHETIC 点不是 RC 实测结果，不能填入实测列。

## B-X10：同步双声道相量拟合

步骤编号：B-X10

实际完成的操作：

- 实现 `rc/phasor_fit.py`，读取同一份 `(2,1024)` M4 同步块；左声道为参考、右声道为输出。
- 对两路使用同一个拟合频率，列余弦、正弦和直流项，使用 `numpy.linalg.lstsq(..., rcond=None)`。
- 在标称频率附近执行一维残差搜索，并输出最终频率、残差、参考/输出幅度、矩阵 rank/condition 和数据范围。
- 按 `Cx=ax-j*bx`、`Cy=ay-j*by`、`H_raw=Cy/Cx` 计算增益和相位。
- 明确标记弱参考、参考为零、削顶候选、秩不足、条件数过高和拟合差/同步未验证。
- 对 B-X09 NPZ 和额外 SYNTHETIC 案例生成拟合报告；没有使用 PL FFT 单声道相位相减。

这一步实现了什么：

提供了可用于后续 B-X11/B-X12 的同步双声道传递比算法和质量筛选，并用已知增益/相位的合成块验证系数、频率和相位。

新增/修改文件：

- `rc/phasor_fit.py`
- `tests/test_phasor_fit.py`
- `reports/B-X10/fit_results.json`
- `reports/B-X10/fit_results.csv`
- `reports/B-X10/README.md`
- `reports/B-X10/manifest.json`
- `rc/README.md`

使用的输入及来源：

- B-X09 `reports/B-X09/synthetic/*.npz` 和合成真值
- `README_M4.md` 的双声道格式说明
- 额外 SYNTHETIC 验证案例；无板端 M4 数据

验证方法和实际结果：

- B-X09 三个有效合成案例拟合为约 0 dB/0°、-6.0206 dB/-45°、-20 dB/-80°；弱参考被标记 `REFERENCE_WEAK`。
- B-X10 额外验证 0.5 增益的 0°/-45°/-90°、初始相位、公共频偏和直流偏置；有效案例残差远低于阈值，系数误差测试门槛 `1e-6`。
- 削顶候选被标记无效；错误 shape、超出 signed24 和非同步/拟合差路径有测试。
- `python -m unittest discover -s tests -v`：59/59 通过。
- 未加载 M4/Overlay、未访问 DMA、未执行板端实测。

状态：HOST_VALIDATED（SYNTHETIC 双声道算法验证；不代表 RC 板端验收）

尚未完成与所需配合：

- B-X11 需要实际 M4 双声道直通校准数据。
- B-X12 需要元件、接线和用户板测。
- 当前只有 SYNTHETIC 结果，不能把拟合增益/相位写成真实 RC 测量。

## B-X11：双通道直通校准试点

步骤编号：B-X11

实际完成的操作：

- 使用现有 `M4_for_B/validation` 中 10 个真实 1 kHz 双声道块；`cap_01..05` 作校准，`cap_06..10` 作独立验证。
- 用 `phasor_fit.py` 从同一同步块计算每块原始传递比，计算 `C0(f)=mean(Cy/Cx)`。
- 对验证块计算 `H_cal=H_raw/C0`，记录校正后均值、标准差和离差。
- 生成 16 个 B-X09 设计频点状态；只有 1000 Hz 是 `PILOT_M4_1KHZ`，其余为 `NOT_MEASURED`，不插值。
- 复制原始 1 kHz 双声道块到 `reports/B-X11/raw_pilot/`，生成重复性图、`channel_calibration.json` 和 manifest。
- 生成 16 个 B-X11 播放 WAV（48 kHz、16-bit、12 秒、左右复制）和源清单，供后续完整频点采集使用。

这一步实现了什么：

验证了直通校准的状态机、独立校准/验证分离、复数传递比校正和重复性报告；现有真实数据只支持 1 kHz 试点，不能替代完整 B-X11 板测。

使用的输入及来源：

- 既有 `b_20261018_1025/M4_for_B/validation/cap_01..10.npy`
- M4 原始格式 `(2,1024)` int32、signed24，fs `47998.2293823345 Hz`
- `overlay_hashes.json` 中的 m4.bit/hwh 哈希

验证方法和实际结果：

- 1 kHz `C0` 约 `0.064254 dB / -0.007763°`。
- 独立验证校正后均值约 `-0.000213 dB / 0.000365°`，试点阈值 0.5 dB/2° 内通过。
- 校准/验证各 5 块，无重叠；原始块和 manifest 哈希通过。
- 16 个设计点中 1 个试点、15 个未测；没有用 1 kHz 结果填充其它频点。
- 16 个 WAV 已核验双声道、48 kHz、16-bit、576000 帧、左右样本完全一致、峰值不超过 3277。
- `python -m unittest discover -s tests -v`：66/66 通过。
- 未执行新的板端 M4/Overlay/DMA 操作。

状态：BOARD_VALIDATED

2026-11-01 后续：收到完整 16 频点 × 3 cal + 3 val 数据，16/16 点通过；
6 kHz 的 `val_03` 保留为失败记录，使用 `val_retry_01` 作为第三验证块。
完整结果在 `reports/B-X11/full_20261101/`。已记录 PC 音量 100%、PC 3.5mm 立体声
直连 LINE IN、WAV L=R、25 C、PLL `0271023c2103`、`fs=47998.77998801426 Hz`
和 M4 哈希；状态更新为 `BOARD_VALIDATED`，`board_accepted` 仍为 false。

2026-11-01 又收到信号发生器信源的 16 频点直通数据。使用 96 个正式块，16/16
点通过；6 kHz 的三个正式验证块均有效，按用户要求完全排除
`b11_f6000_val_retry_01.npy`。结果在
`reports/B-X11/signal_generator_20261101/`，`C0` 增益
`0.043404～0.044280 dB`、相位 `-0.019371～+0.012997°`。该组状态为
`BOARD_VALIDATED`。信源为 OWON XDG3122，实际 `0.2 Vpp`、`26 C`、
标称 `50 Ω`；3.5 mm 转接后的 L/R 并联到发生器输出，GND 共地。

2026-11-01 收到 B-X12 完整 16 频点真实 RC 数据。实际元件为
`R=978 Ω`、`C=105.6 nF`，温度 `25 C`；左声道直接作为参考，右声道串入
978 Ω 并使用 105.6 nF 接 GND。96 个同步双声道块全部通过质量筛选，
16/16 点通过。实测 R/C 理论截止为 `1541.052 Hz`，一阶复数拟合截止为
`1547.745 Hz`，偏差 `+6.692 Hz (+0.434%)`。B-X12 状态登记为
`RC_MEASURED`，结果在 `reports/B-X12/measured_20261101/`。

尚未完成与所需配合：

- PC 数据的 16 频点、独立验证和现场条件已记录，不需要重跑；
- 信号发生器数据的质量检查和物理源条件均已完成；
- 线路是直接立体声线，不是物理单路分线器；报告中已明确记录这一拓扑。
- B-X12 数据现已实测完成；`board_accepted` 仍需整个作品最终发布验收。
