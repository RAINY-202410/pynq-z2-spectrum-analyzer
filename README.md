# PYNQ-Z2 实时音频频谱分析与频率响应测量系统

2026年全国大学生嵌入式芯片与系统设计竞赛AMD自主选题赛道初级组作品。
目标平台为PYNQ-Z2（xc7z020clg400-1），采用RTL与Vivado IP Integrator实现。
PL承担I2S接收、1024点分帧、矩形/Hann加窗、流水FFT、AXI-Stream帧控制和DMA搬运；PS承担硬件结果解析、幅值恢复、峰值分析、记录及浏览器交互。
频率响应使用独立M4同步双声道时域采集，FFT与M4由同一进程互斥管理。

## 五个功能界面

| 界面 | 功能 |
|---|---|
| 当前频谱 | 实时频谱、瀑布、窗选择、主峰/局部峰、状态与会话导出 |
| 深入分析 | 截取当前采集过程、命名保存并进一步分析 |
| 我的记录 | 回看用户保存的频谱分析及RC/通用系统响应结果 |
| 演示样例 | 查看开发过程中保存的历史信号与分析结果，明确区分新采集与回放 |
| 频率响应测量 | RC低通滤波器与通用系统两类幅频/相频测量 |

## 三步快速启动

环境前提：PYNQ-Z2已刷写PYNQ 3.1.1镜像，并可访问板端Jupyter。
本入口包含当前频谱、深入分析、我的记录、演示样例、频率响应测量全部五个界面，配有启动操作视频。

1. 将工程包根目录的spectrum_software_v1_r4_bplus_board.zip和packeditor.ipynb上传至Jupyter文件页根目录（/home/xilinx/jupyter_notebooks）。
2. 在Jupyter中打开并运行packeditor.ipynb，按配套视频使用其中提供的终端启动命令。
3. 打开频谱分析仪：http://192.168.2.99:8091/ 。

192.168.2.99对应演示环境；板卡网络地址发生变化时，使用实际板卡IP和8091端口。

## 工程目录

| 路径 | 内容 |
|---|---|
| src/ | RTL、XDC、IP/BD配置、PS软件阅读镜像和参考模型 |
| sim/ | 历史仿真向量、测试平台、协议和数值结果 |
| build/ | 正式构建脚本、供应商板定义、综合/实现报告 |
| board/ | 冻结FFT/M4 bit/hwh、运行ZIP、部署脚本和证据范围说明 |
| data/ | 原始实测块、参考、拟合、CPU基准与版本化板测数据 |
| skill/ | PYNQ调试与FPGA交付审计两项可复用技能 |
| report/ | 已补实际界面的设计报告、验证说明及原始AI协作记录 |
| packeditor.ipynb | 配套视频使用的最小部署Notebook及终端命令参考 |

根目录运行ZIP与board/software中的ZIP字节完全相同，SHA256为0a83727db5b5355d6854001eed3f64b37ec25bbd4022ed3b6d54f25262accc9c。
保留两处入口便于快速部署与工程归档。src/ps/pynq_r4仅为全小写阅读镜像；实际部署使用原运行ZIP，保留其manifest与运行路径。
供应商IP、冻结运行ZIP和历史记录保留原有内部命名及校验身份；外层目录采用英文小写。

## 硬件构建与验证

Vivado 2026.1，器件xc7z020clg400-1；随包提供PYNQ-Z2板定义。
正式构建步骤见[build/readme.md](build/readme.md)，当前构建验证状态见[report/required_validation.md](report/required_validation.md)。
主机依赖Python与NumPy，JavaScript语法检查另需Node.js。

只检查交付完整性：

```bash
python build/scripts/verify_package.py
python board/scripts/check_assets.py
python skill/fpga_delivery_audit/scripts/audit_submission.py .
```

如需自行运行软件功能矩阵，入口为python build/scripts/run_host_tests.py；历史结果已在sim/results/保存，功能回归与文件校验分别解释。
修改交付文件后，可运行python build/scripts/generate_manifest.py更新总清单，再执行上述完整性检查。
根目录.gitattributes禁止Git自动转换换行，保持跨平台克隆后的字节哈希一致；.git及本地缓存不计入交付清单。

## 既有结果与证据范围

- FFT：12主例及2恢复帧，1024复数点逐整数比较一致。
- FFT冻结实现：LUT 5631、FF 8533、BRAM36等效5.5、DSP 13；PL 100 MHz，内部受约束路径WNS +0.585733 ns。
- r2长测1820.013秒、9100帧；r3短复验与3次冷启动保留独立证据。
- 历史RC低通：978Ω、105.6nF、25℃，16点96块，拟合截止1547.7446Hz，相对理论偏差+0.4343%。
- r4既有主机记录：10项集成、72项扩展；技术报告包含五个界面和实际用户保存结果。

运行ZIP元数据HOST_VALIDATED_BOARD_PENDING、board_accepted=false及CMA有限结论原样保留。
界面截图不扩展为全部r4交互验收；历史RC低通与另一组RC高通用户记录分别标注。绝对电压、端到端延迟与同口径PL加速比不作为已完成指标。

## 报告与ROSS协作

正式图文报告：[report/design_report.docx](report/design_report.docx)；同步文字版：[report/design_report.md](report/design_report.md)。
2026-10-24选定原始提示词、AI回复及Vivado MCP调用/返回见report/ai_records/figure15_original_dialogue_excerpt_20261104.md和同名JSON，提取来源回执同目录保存。
上述记录呈现只读GP0参数失败、实际100MHz接口核对与后续BD重建；BD重建不解释为第二次综合或bit逐字一致。

## 开源许可

团队原创代码采用[MIT](license.md)许可；第三方来源及授权范围见[third_party_notices.md](third_party_notices.md)。
GitHub Desktop发布方法见[github_publish.md](github_publish.md)。完整RAR和快速启动文件适合作为同一版本的Release附件提供。
