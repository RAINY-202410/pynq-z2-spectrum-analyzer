# 源码说明

## 实现方式

本项目采用 RTL + Vivado IP Integrator，没有使用 HLS。因此不创建空的
`hls/` 目录，也不虚构 HLS 源文件。

## 目录

- `hw/rtl/`：I2S 接收、分帧、Hann 窗、FFT 控制、复数打包和调试寄存器；
- `hw/constraints/`：PYNQ-Z2 音频、MCLK 和 LED 约束；
- `hw/ip/`：Xilinx `xfft 9.1` 配置和参考 BD 配置脚本；
- `hw/scripts/`：历史研发脚本及正式入口引用的BD重建过程；当前构建使用`../build/scripts/`，部分旧实验脚本保留旧布局路径；
- `ps/pynq_r4/`：R4 应用、B 扩展、RC 测量和测试源码的全小写镜像；
- `reference/`：FFT 黄金模型及 R3 会话审计工具。

## 运行时代码的权威副本

R4 运行时包含大量带原始大小写的报告目录和哈希 manifest。为了保持
manifest 可验证性，完整运行源码放在：

`board/software/spectrum_software_v1_r4_bplus_board.zip`

`ps/pynq_r4/` 只保留源码、网页和测试的可读镜像；数据和签名报告以 ZIP
及 `data/` 为准。

## 数据通路

```text
PC / signal generator
        |
        v
PYNQ-Z2 LINE IN -> ADAU1761 -> I2S -> 1024-sample frame
                                      |
                                      v
                              PL Hann/rect window
                                      |
                                      v
                           xfft 9.1 1024-point FFT
                                      |
                                      v
                         64-bit complex AXI-Stream
                                      |
                                      v
                         DMA S2MM -> PS parse/display
```

频率响应模式复用 M4 双声道采集：左声道为 `input_reference`，右声道为
`rc_output`，PS 使用同一频率的正弦相量拟合计算幅相。
