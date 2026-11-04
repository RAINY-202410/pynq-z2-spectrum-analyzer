# ARM同输入CPU基准核验与r3下一步

> 同日后续：r3原生会话短复验已通过，新冷启动脚本7项HOST检查通过。当前转入[r3三次实际冷启动](r3三次冷启动_20261031.md)，见[r3核验](a_spectrum_r3_validation_20261031.md)，不再重跑ARM或切换r3。

日期：2026-10-31，Asia/Shanghai。用户回传的CSV/JSON现已归档并通过数据核验，状态为 **USER_BOARD_PS_CPU_BENCHMARK_DATA_VERIFIED**。r2的1820秒长测、连续前台及20秒恢复保持通过，详见[长测核验](a_spectrum_rescue_validation_20261031.md)。**不重复ARM基准或30分钟。**

## 核验结果

- 12类（6类输入×矩形/Hann），每类预热20次、20批×500次；共240批、120000次计时FFT和240次预热。
- 每类冻结reference.npz的SHA256均与可信manifest及PC结果一致。CSV和JSON逐字段一致；每类20个原始批均值均有限且为正，均值/中位/P95/最小/最大均从原始数据复算吻合。
- 板端工具报告12类最终FFT输出与浮点参考一致；本机另用冻结输入做12类FFT参考复核通过。此次未收到ARM完整输出数组，不将本机复核冒称为重新执行板端FFT。
- 环境为用户板端输出的Linux armv7l、Python3.10.4、NumPy1.21.5；PC为Windows AMD64、Python3.12.14、NumPy2.3.5。时钟均为单调计时。
- ARM各类mean为351.8725028～372.8343343 µs，PC为8.98501～9.27658 µs。计时范围是已量化/加窗的冻结输入z之NumPy1024点FFT，含Python调用和NumPy输出分配，不含ADC/DMA/绘图。P95是20个批均值的百分位，不是单次调用P95。
- 不将CPU环境差异或capture总调用时间用于宣称PL加速比；纯PL延迟、同步端到端延迟仍未测。原JSON的physical_hardware_execution_verified=false保持原样，按用户回传与记录环境登记BOARD_PS结果，不捏造独立物理执行认证。

| 输入 | ARM mean µs | ARM P95批均值 µs | PC mean µs |
| --- | ---: | ---: | ---: |
| zero_rect | 351.872503 | 352.842134 | 9.242770 |
| zero_hann | 357.023139 | 357.310429 | 9.175970 |
| dc_rect | 357.580358 | 382.116958 | 9.158590 |
| dc_hann | 354.208061 | 355.701039 | 9.119200 |
| impulse_rect | 371.718699 | 372.086888 | 8.988000 |
| impulse_hann | 372.834334 | 394.479397 | 8.985480 |
| bin16_rect | 356.442851 | 358.406575 | 9.053830 |
| bin16_hann | 354.436403 | 355.392367 | 9.100510 |
| bin16p35_rect | 355.057668 | 356.607211 | 9.263400 |
| bin16p35_hann | 356.843070 | 381.572110 | 9.202250 |
| bin16_bin70_rect | 356.389981 | 357.540652 | 9.276580 |
| bin16_bin70_hann | 355.041182 | 359.423928 | 8.985010 |

## 原件与审计

| 原件 | 字节数 | SHA256 |
| --- | ---: | --- |
| cpu_fft_arm_20261031.json | 15730 | `130BEF9A4CDB98C266141B5F225961947C96B216FAAF97C00710555CF7C40CF9` |
| cpu_fft_arm_20261031.csv | 3105 | `BACD9B30F55E0EE30EBEA02B26C2D513A825EA722CECFCE44E6981CE4DCEC51C` |

审计目录`build/cpu_fft_arm_validation_20261031_01/`包含原件、input_receipt、ARM核验receipt、PC/ARM逐类对照表及combined_validation_receipt。旧r2原始receipt和ZIP不覆盖。证据补包为`release/spectrum_validation_20261031/A_spectrum_arm_validation_20261031.zip`，它引用此前的救援证据包，不冒充新的整会话原件或板端安装包。收到的文件仅作为数据解析。

## 当前下一步

按[r3两次20秒短复验](r3短复验_20261031.md)操作：上传现成r3板端包→新目录完整解压→旧服务安全停止/端口释放→r3新实例→两次20秒Hann/tone1k/5Hz→保存界面图→整会话导出，回传ZIP及启动/错误原文。只在STOPPED或PORT_FREE后启动，不重跑30分钟，不再运行ARM。

现成r3 ZIP已再次核验CRC、可信manifest、35份文件哈希及Notebook源，未重新构建或重跑既有34项HOST测试，尚无r3实板结果。r2长测证据不冒充r3板测。

后续仍有CMA分配来源、三次物理冷启动、真实LIVE录像及最终报告/验收。旧冷启动身份脚本硬性固定r2 manifest，必须先准备并验证适配r3的工具，再让用户执行三次冷启动；当前不直接套旧操作单。`board_accepted=false`保持。旧8页DOCX/PDF继续作为当日候选稿，两份Markdown附页补充新证据，未宣称已生成最终报告。
