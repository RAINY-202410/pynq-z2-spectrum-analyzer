# M4交付候选版：PS控制的1024拍音频快照

本文件在硬件构建/上板前属于接口说明，不代表已经验收。只有Notebook测试通过并由用户确认输入变化后，生成的 `M4_for_B.zip` 才是板上验收交付包。

## 使用方式

将同版 `m4.bit`、`m4.hwh`、`m4_delivery.py`、`M4_acceptance.ipynb`、本README和 `LICENSE.reed-foster.txt` 放在同一目录。在Jupyter中打开Notebook，从上到下逐格执行。一次测试会话只加载一次Overlay，不同时运行旧Notebook或DMA脚本。

## 固定数据格式

- PL时钟：FCLK_CLK0目标100MHz；新增U5引脚codec_mclk输出，按10分频得到10MHz。
- codec：ADAU1761，I2C七位地址0x3B。0x76是写地址字节，不是另一个七位地址。
- PLL：六字节配置从0x4002写入并回读，按10MHz输入配置目标48kHz；用LRCLK边沿计数实测近似fs并记录。
- 采集：仅S2MM、简单模式。每次触发1024拍，8192字节；TKEEP固定0xFF，TLAST仅在第1024拍有效。
- 每拍uint64，高32位为左声道、低32位为右声道；每路24位有符号样本扩展到32位。
- 音频npy形状(2,1024)，dtype=int32；归一化除以2**23。
- 这是时域音频，不能把左右声道解释为FFT实部/虚部。
- 这是软件触发的快照采集，包与包之间存在空隙，不承诺跨包连续音频。包内发生输出背压导致丢样时，overflow置位，验收失败。

## 控制寄存器（此版本语义）

从本次hwh的ip_dict读取实际地址，预期如下：

| IP | 预期基地址 |
|---|---|
| axi_lite_ctrl_0 | 0x40000000 |
| dbg_stat_0 | 0x40001000 |
| axi_dma_0 | 0x40400000 |
| axi_iic_0 | 0x41600000 |

axi_lite_ctrl_0偏移0x00：bit0上升沿触发一包；bit1=1中止并清分帧状态；bit2选择显式计数器测试源。软件先置abort、复位DMA并等待停止，再清控制、武装DMA，最后写bit0。真实音频写0x1，自检写0x5。bit2在ARM时锁存，一包中不切换数据源。

0x04、0x08、0x0C仍是旧寄存器占位；LENGTH占位寄存器不能动态改变本版固定1024拍。LED在本版用于busy/done/test/overflow诊断，不能再使用M3的寄存器点灯验收口径。

dbg_stat_0：

| 偏移 | 含义 |
|---|---|
| 0x00 | LRCLK双边沿累计计数，fs≈增量/(2×测量秒数) |
| 0x04 | 对DMA的有效AXIS握手累计计数 |
| 0x08 | 状态，见下 |
| 0x0C | 原dbg_stat版本寄存器（保留0x3） |
| 0x10 | 最近左声道样本，DMA未武装时也会更新 |

0x08状态：[31:28]=0xA（本版协议标识），bit27=DMA TREADY、bit26=输出TVALID、bit25=I2S时钟活跃、[24:5]=LRCLK空闲周期数、bit3=done、bit2=test、bit1=overflow、bit0=busy。

## 验收内容

1. 自检必须精确接收uint64的0～1023，不能只用“非零、有变化”判断。
2. codec PLL锁定、关键输入路由回读正确，fs测量在48kHz±1%内。±1%为本次流程建议门限，不是板卡精度规格。
3. 真实音频无DMA错误、无overflow，每次1024拍/8192字节；连续10次在同一Overlay会话中通过。
4. 播放已知测试音，改变音量后查看波形与RMS确实变化。Notebook中的软件FFT仅作诊断，不代表PL FFT已经实现。
5. 硬件构建须通过配套packetizer仿真和原I2S仿真；检查最终timing、clocks、CDC报告，不用正WNS替代CDC审查。

## 来源

I2S串并转换与codec配置派生自reed-foster/pynq-audio，MIT许可，原声明见LICENSE.reed-foster.txt。此次增加软件触发分帧、显式测试源、AXIS保持寄存器、溢出诊断、同步级、MCLK和Notebook验收。

[AMD AXI DMA简单模式](https://docs.amd.com/r/en-US/pg021_axi_dma/Direct-Register-Mode-Simple-DMA)

[PYNQ连续内存和缓存同步](https://pynq.readthedocs.io/en/latest/pynq_libraries/allocate.html)

[ADAU1761数据手册：PLL从0x4002开始](https://www.analog.com/media/en/technical-documentation/data-sheets/ADAU1761.pdf)
