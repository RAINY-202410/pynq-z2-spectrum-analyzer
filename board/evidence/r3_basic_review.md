# 基础功能复核与交付清单

日期：2026-10-31，Asia/Shanghai。状态：**BASIC_FUNCTIONAL_REGRESSION_VERIFIED_CMA_REVIEW_PENDING**。

实采→PL窗/FFT→PS幅值/峰值→浏览器频谱/瀑布→停止恢复→导出的基础功能已经完成，本轮计划内板测也已完成。当前板端为r3。**不再要求重复30分钟、ARM或三次冷启动。** 本页是基础功能复核与已知问题交付记录；CMA分配来源未关闭，board_accepted=false，不作为全部项目最终验收。

## 已验证的功能与证据

| 工作 | 版本/平台 | 已有结果 | 核验入口 |
| --- | --- | --- | --- |
| 冻结数值与硬件 | FFT v1.0 | 历史12主例+2恢复例、官方模型对拍及bit/hwh身份保持；本轮未重建硬件 | HANDOFF既有硬件/数值归档 |
| 单音、双音两窗、静音、停止恢复 | r2 LIVE | 原矩阵保持；救援14次18537帧中的失败诊断原件保留 | [r2核验](a_spectrum_rescue_validation_20261031.md) |
| 30分钟采集/前台显示 | r2 LIVE | 1820.013秒、9100帧；连续前台1819.799秒，零隐藏回执；随后20.032秒/100帧恢复通过 | [r2长测](a_spectrum_rescue_validation_20261031.md) |
| 同输入CPU基准 | PC/ARM | 各12类；ARM 240批计时复算及CSV/JSON/输入哈希一致；ARM均值351.87～372.83 µs | [ARM核验](a_spectrum_arm_validation_20261031.md) |
| r3部署/单音/停止恢复/原生导出 | r3 LIVE | 4次321帧全部安全停止；其中两次20秒tone1k各100帧通过 | [r3短复验](a_spectrum_r3_validation_20261031.md) |
| 三次实际冷启动 | r3 LIVE | 三个不同boot_id和实例；每次20秒/100帧单音及安全停止通过，用户确认实际断电上电 | [冷启动核验](a_spectrum_r3_coldboot_validation_20261031.md) |

版本范围保持明确：r2进行了长测与完整功能矩阵，r3进行了导出修复短复验和三次冷启动；没有将这些记录包装成r3同一版本完整30分钟矩阵。各原生短会话的通用完整矩阵审计字段保持false，本轮没有修改审计器、放宽门槛或删掉早期失败来收尾。

## 当前软件与归档

- 当前板端包：`release/spectrum_software_v1_r3/spectrum_software_v1_r3_board.zip`，SHA256 `A7D05615F13D0573711CA353899C7A5C4278B65ED4696F735838C0BF63F92780`。包内含冻结bit/hwh及完整软件子目录；已部署，无需再安装。
- 独立r3 boot记录器保留在Jupyter根目录，避免修改软件manifest。工具本身7项HOST检查通过，本轮三份实际记录的工具SHA256吻合。
- 基础复核包：`release/spectrum_basic_review_20261031/A_spectrum_basic_review_20261031.zip`。包含r3原安装ZIP、r2救援原件/资源日志、ARM原件、r3短测原件、六份冷启动原件、审计receipt、报告与已知问题，以及逐文件哈希清单。它是本地复核交付，未对外提交、未虚构签收。
- 综合receipt：`build/spectrum_r3_coldboot_validation_20261031_01/basic_review_receipt.json`；各阶段原始receipt和旧ZIP不覆盖。收到的代码/文本仅按证据读取，不执行。

## 尚未关闭的项目

1. **CMA分配来源**：r2长测RSS73453568字节恒定，FD17→15，但全局CmaFree净减12201984字节；独立资源日志也有下降。已取得资源证据，未定位分配来源，不能据此宣布无泄漏或已证实泄漏。当前不为此盲目重跑长测，先审阅现有计数和软件分配生命周期，必要时只补能区分原因的观测。
2. **最终材料**：真实LIVE录像和最终剪辑尚未取得；10/30的8页DOCX/PDF仍是当日候选稿。新增Markdown结果页已覆盖新实测，后续格式报告需要据本轮结论更新，不能把旧PDF冒称已回填最终版。
3. **未测指标/扩展**：绝对电压标定、THD/SNR、纯PL及同步端到端延迟、完整外部I/O时序仍按既有边界记录；DDS/RC及独立PS GUI属于此前保留的后续条件项。CPU FFT微基准不作为PL加速比，snapshot并非无间隙连续音频。

当前基础板测证据已齐，不再需要用户补交本批文件或重复测试。下一阶段是CMA问题和材料收尾，全部项目最终验收仍保持独立状态。
