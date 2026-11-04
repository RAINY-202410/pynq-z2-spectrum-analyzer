---
name: pynq-overlay-dma-bringup
description: Bring up and debug a PYNQ Overlay with AXI DMA, AXI-Stream, I2S/codec, MMIO, and mutually exclusive hardware modes using evidence-first checks.
---

# PYNQ Overlay / DMA Bring-up

## 适用范围

适用于 PYNQ-Z1/Z2、Kria/PYNQ 或类似 Linux + FPGA overlay 工程，尤其是：

- AXI DMA S2MM/MM2S 数据宽度或地址映射错误；
- I2S、codec、MCLK 或 I2C 初始化不稳定；
- 一个网页/进程同时管理多个 Overlay；
- 实时采集和批量采集必须互斥；
- 板端结果需要与主机黄金模型对拍。

不适用于纯 RTL 仿真、只有 bitstream 而没有 `.hwh/.xclbin` 元数据的工程。

## 使用方法

1. 冻结 `bit`、`hwh`、寄存器表和数据宽度，计算 SHA256。
2. 先运行 `scripts/overlay_smoke_test.py` 做无 DMA 的静态检查。
3. 用最小输入验证 MMIO 读回：协议 ID、配置、计数器和状态。
4. 逐项确认 DMA 地址、方向、Stream 宽度、TLAST/TKEEP 和超时。
5. 保存一次原始输入和一次原始输出，不先做绘图或二次加工。
6. 用独立黄金模型逐元素对拍，记录第一个错误位置和状态位。
7. 同一进程加入模式协调器；切换前停止 DMA、释放 buffer、关闭 Overlay。
8. 冷启动至少重复三次，分别保存 boot id、Overlay 哈希和结果。

## 推荐最小证据集

- 环境：内核、PYNQ、XRT、Python、NumPy；
- 身份：`bit/hwh` SHA256、设计 revision；
- MMIO：寄存器读回和异常分支；
- DMA：实际长度、超时、状态、busy/overflow；
- 数据：输入哈希、输出哈希、黄金参考哈希、首个差异；
- 模式：进入/退出前后的 owner、进程、端口和资源状态；
- 板测：原始样本、终端输出、截图、时间和操作条件。

## 失效条件

- `.hwh/.xclbin` 与 bitstream 不匹配；
- 两个进程同时打开 XRT/ZOCL 或同一 AXI DMA；
- DMA 两端数据宽度不同却未使用宽度转换；
- 只检查 DMA done，不检查实际长度、TLAST、overflow 和协议状态；
- 把回放、模拟数据或主机测试写成板端实时结果；
- 依赖文件日期或板端 UTC 排序，而板端时钟会重置；
- 使用未校准的时域 RMS 直接代替绝对电压；
- `CmaFree` 变化被直接解释为泄漏，而未取得分配/释放覆盖。

## 已验证效果

在 PYNQ-Z2 项目中：

- M4 path 实现 codec → I2S → 64-bit packet → AXI DMA S2MM；
- 实测采样率约 47.998 kHz，块形状 `2 x 1024`；
- FFT LIVE 与 M4 被放入同一进程的状态机；
- R4 集成测试 10/10、扩展测试 72/72；
- 基础 R3 的三次冷启动均在 20 秒量级完成安全停止；不属于 R4 模式切换验收。

这些结论证明该流程适用于当前 PYNQ 3.1.1 / Zynq-7000 组合；换板卡后仍需
重新验证 PS DDR、HP 端口、时钟和 codec。

## 失败观察来源

- 旧服务仍占用 8091 端口；
- PYNQ/XRT 在硬件 owner 线程中缺少 current event loop；
- AXI-Stream 宽度与 DMA 设置不一致；
- codec MCLK 约束一度缺失；
- 只凭驱动 `freebuffer()` 调用判断 CMA 无泄漏不充分。
