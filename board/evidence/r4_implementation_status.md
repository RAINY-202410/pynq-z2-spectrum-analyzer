# R4 implementation status

日期：2026-11-02（Asia/Shanghai）

按用户要求完成前五步，跳过文件哈希核对。

## 已完成

1. 从交接 ZIP 内解出 R3 board ZIP，建立：

   `spectrum_software_v1_r4_bplus/`

2. 保留 R3 的原始目录和主入口文件名：

   `spectrum_app.py`

3. 复制 B 扩展运行目录到：

   `bplus/`

   包含 B 页面、B-X02～B-X12 报告、基线/输入副本、回放服务、RC 分析和测试。
   排除了废弃的 `reports/B-X11/signalgen_20261101/`。

4. 复制 M4 实验包到：

   `m4/`

   包含 `m4.bit`、`m4.hwh`、`m4_delivery.py`、验收 Notebook 和构建报告。

5. 修改 `spectrum_app.py`，在同一个 HTTP 服务和同一进程中加入：

   - `/bx/`
   - `/bx/replay.js`
   - `/bx/style.css`
   - `/bx/api/replay/index`
   - `/bx/api/replay/frame`
   - `/bx/api/replay/trend`
   - `/bx/api/export`
   - `/bx/api/live/status`
   - `/bx/api/extension/status`

   `/bx/api/live/status` 直接调用当前进程的 `runtime.status()`，不请求自身端口。

## 当前可验证的骨架

使用假 runtime 的本地 HTTP 烟雾测试已返回 200：

- `/`
- `/api/status`
- `/bx/`
- `/bx/replay.js`
- `/bx/api/replay/index`
- `/bx/api/live/status`
- `/bx/api/extension/status`

该测试只验证路由骨架，不包含板端硬件、FFT 或 M4 实测。

## 6～10 步完成内容

### 6. B API 前缀

- `bplus/web/index.html` 设置 `window.BX_API_BASE="/bx"`；
- `bplus/web/replay.js` 只对 `/api/...` 增加 `/bx` 前缀；
- 原有 R3 `/api/...` 路由不变；
- B 的 `/api/export` 与 R3 `/api/export` 不再冲突。

### 7. B-X08 同进程订阅

- R4 内创建一个持久 `StatusSubscriber`；
- `/bx/api/live/status` 直接读取当前进程 `runtime.status()`；
- 去重、缺口、平均和保持累计复用 B-X08；
- `/bx/api/live/summary` 返回订阅摘要；
- `/bx/api/live/export` 将同进程报告写入
  `bplus/reports/B-X08/same_process_*`。

### 8. 统一页面

根页面新增：

- 实时频谱
- B 拓展分析
- M4 / RC

B 页面通过同源 iframe 嵌入 `/bx/`。M4 页面提供模式切换、codec/fs、
计数器自检、双声道采集、B-X08 订阅状态和 B-X12 报告入口。

### 9. 统一鉴权

- R4 首页 token 继续写入 meta；
- B 首页注入同一 `X-Spectrum-Token`；
- B 导出、B-X08 导出和全部 M4 硬件命令均经过 R3 原有 POST 鉴权；
- 未携带 token 的硬件命令返回 HTTP 403。

### 10. FFT/M4 互斥模式

新增 `hardware_modes.py`：

- 进程内 `HardwareModeCoordinator` 管理 `FFT`、`M4` 和 `FAULT`；
- M4 使用独立硬件工作线程和独立 asyncio 事件循环；
- 进入 M4 前停止并关闭 FFT runtime；
- 恢复 FFT 前关闭 M4 worker 和相关 Overlay 引用；
- 模式切换期间 FFT 命令被拒绝；
- M4 自检、codec/fs 配置和双声道采集均经过同一进程；
- FFT/M4 的 Overlay 关闭前检查活动 DMA buffer 和 unsafe 状态。

## 主机验证

- B 扩展测试：`72/72` 通过；
- R4 路由、API 前缀、鉴权、用户记录、RC 响应、通用系统响应、
  错误目标频率诊断、频率响应下载和 FFT/M4 状态机测试：`10/10` 通过；
- JavaScript 语法检查通过。

以上是 HOST_VERIFIED，不代表 PYNQ 实板模式切换通过。

## 11～14 步完成内容

### 11. 版本信息

- `spectrum_recording.py` 的 `BUILD_REVISION` 更新为
  `spectrum_software_1_r4_bplus`；
- `README_SPECTRUM.md` 更新为 R4 单端口、统一页面和硬件模式说明。

### 12. Manifest

新增 `build_manifest.py` 并生成新的 `software_manifest.json`：

- build revision：`spectrum_software_1_r4_bplus`
- status：`HOST_VALIDATED_BOARD_PENDING`
- 清单文件：553
- manifest SHA256：
  `827F7446E686E9B61695533ECA96FF89C653739928A638597891954A671043AE`

没有沿用或手工修改 R3 manifest。

### 13. 主机测试

- B 扩展测试：72/72 通过
- R4 路由、鉴权、用户分析记录写读、用户分析导出、RC 响应、
  通用系统响应和 FFT/M4 状态机测试：8/8 通过
- JavaScript 语法检查通过
- R4 `spectrum_integrity.verify_software()` 通过

### 14. 板端 ZIP

生成单一压缩包：

`../spectrum_software_v1_r4_bplus_board.zip`

- 压缩大小：21.27 MB
- ZIP 条目：560
- SHA256：
  `0A83727DB5B5355D6854001EED3F64B37EC25BBD4022ED3B6D54F25262ACCC9C`
- ZIP 内逐文件哈希复核通过，校验文件 553

## 9～17 步完成内容

### 9. 我的记录完整查看

- 用户分析记录打开与演示样例相同的多帧频谱查看器；
- 支持当前谱、平均/保持、稀疏瀑布、时间轴、A/B 游标和趋势；
- 记录详情与完整查看器位于同一“我的记录”页面。

### 10. 记录质量状态

- `COMPLETE_REPLAY`
- `SINGLE_FRAME`
- `METRICS_ONLY`
- `INTERRUPTED`
- 损坏记录由 SHA256 校验拒绝加载。

### 11. 设置与来源

- `record.json` 保存窗口、场景、期望测试音、开始/停止时间、
  采样率、完整谱数量、指标数量、溢出数量、来源和 `is_demo=false`。

### 12. 算法复用

- 用户分析数据源直接复用 `ReplayService` 的游标、趋势、平均/保持
  和导出算法；
- 不重新实现第二套测量逻辑。

### 13. 分析包导出

- 用户分析记录可以导出当前谱、平均谱、保持谱、游标、趋势、
  参数、来源、事件和 manifest；
- 导出包位于用户记录目录下的 `exports/`，不写入内置演示目录。

### 14. 多频点用户频率响应

- 新增 `response_recorder.py`；
- 已拆分为 RC 低通滤波器和通用系统两种测量类型；
- RC 模式要求 R/C，并保存理论值、一阶拟合和截止频率；
- 通用系统模式不要求 R/C，只保存实测输入/输出传递比；
- RC 理论曲线、图例、理论截止频率和绘图范围改为读取每条记录的
  实际 R/C，不再固定使用 `978 Ω / 105.6 nF`；
- 通用模式仍执行正弦相量估计以取得每点幅相，但不执行一阶曲线拟合；
- 拟合失败时显示目标频率、估计频率、相对残差和失败原因；
- 在电路测量模式中逐点输入目标频率并采集；
- 每个频点保存原始左右声道块、拟合频率、C0、增益、相位、
  理论值、校准状态和质量状态；
- 最多 16 个设计频点；至少 3 点才能保存曲线。

### 15. 拟合和绘图复用

- `rc/build_bx12.py` 增加公共的复比值汇总、一阶拟合和绘图入口；
- 用户响应记录和内置响应报告共用相同拟合/绘图算法。

### 16. 响应记录查看

- “我的记录”区分 RC 低通滤波器和通用系统记录；
- RC 记录显示理论曲线、截止频率和逐点表；
- 通用系统记录只显示实测幅相曲线和 DUT 信息；
- 记录目录保存 `points.csv`、`raw/*_stereo.npy`、
  `gain_phase.png/svg`、`record.json` 和 manifest。

### 17. 数据隔离

- 内置演示数据仍位于 `bplus/reports/`；
- 用户数据位于 `../user_data/records/`；
- Board ZIP 和 software manifest 不包含用户记录；
- 用户分析导出和响应记录不会进入演示样例目录。

### 保存按钮修复

- 实时采集自然结束或点击主停止时，分析记录器会自动停止；
- 已有记录数据时，“保存到我的记录”可以直接点击；
- 保存接口会在需要时自动停止当前记录，再执行保存；
- 频率响应达到 3 个频点后，即使仍在记录中也可直接保存，
  后端会先结束响应会话；
- 避免记录器长期停留在 active 状态导致按钮永久禁用。
- “深入分析”增加实时采集相位、运行帧数、记录帧数、观察器状态和错误摘要；
- 集成测试实际触发观察器并验证运行帧数、完整谱数、指标行数同步增长；
- 只有实时采集处于 RUNNING 时才允许开始新记录。
- 修复实时帧 `payload` 不含 `elapsed_s` 时观察器抛 `KeyError` 的问题；
  时间统一取自采集记录行 `row["elapsed_s"]`；
- 回归测试使用不带 `payload.elapsed_s` 的实时帧，验证运行帧、完整谱和
  指标行均正常增长。

## 展示层调整

- 页面结构改为“当前频谱 / 深入分析 / 我的记录 / 演示样例 / 频率响应”；
- 用户界面不再显示任务编号或分工编号；
- 内部 JSON、manifest 和算法文件名仍保留原有追溯标识；
- 深入分析通过采集线程观察器记录每一帧，并将最多 32 份完整谱和
  最多 5000 条指标保存为可重放用户记录；
- 用户分析记录保存 `record.json`、`sample_index.json`、
  `metric_timeline.jsonl`、原始 words/state、渲染帧和 manifest；
- 用户记录通过独立数据源适配器复用同一套回放页面、平均/保持、
  瀑布、A/B 游标、趋势和导出逻辑；
- “我的记录”只包含用户主动保存的数据，不包含内置演示数据；
- 内置数据移到独立“演示样例”，默认空白且必须主动选择；
- 频率响应页面包含双声道采集、幅相结果演示样例和响应记录；
- 用户保存的频率响应记录支持下载逐点 CSV 和完整 JSON；
- 响应记录查看时隐藏未使用的分析 iframe，消除幅相图上方的固定空白高度；
- 用户记录保存在软件目录外的 `../user_data/records/`；
- 用户记录目录不进入 board ZIP 和 software manifest。

## 尚未完成

- 尚未进行 FFT LIVE、B-X08 BOARD_LIVE、M4 采集和恢复 FFT 的实板短测；
- `board_accepted` 仍为 false；
- R4 ZIP 不能因为主机测试通过就标记为板端验收完成。
