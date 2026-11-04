# 板端部署与运行

software提供完整r4运行ZIP，overlays提供冻结FFT/M4资产，scripts提供工程脚本部署、状态、启动与停止入口。

## 三步快速启动

环境前提：PYNQ-Z2已刷写PYNQ 3.1.1镜像，并可访问板端Jupyter。
本入口包含当前频谱、深入分析、我的记录、演示样例、频率响应测量全部五个界面，配有启动操作视频。

1. 将工程包根目录的spectrum_software_v1_r4_bplus_board.zip和packeditor.ipynb上传至Jupyter文件页根目录（/home/xilinx/jupyter_notebooks）。
2. 在Jupyter中打开并运行packeditor.ipynb，按配套视频使用其中提供的终端启动命令。
3. 打开频谱分析仪：http://192.168.2.99:8091/ 。

192.168.2.99对应演示环境；板卡网络地址发生变化时，使用实际板卡IP和8091端口。

Notebook末尾的终端命令按配套视频复制到Jupyter终端使用。Notebook及根目录ZIP与工程内版本对应。
用户记录位于/home/xilinx/jupyter_notebooks/user_data/records，处于软件目录之外。

## 已有服务与工程脚本

已有r4服务时先查询原服务状态、build_revision并复用；需要替换时先安全停止并保存用户记录，避免多个进程争用Overlay/DMA。
工程脚本部署适用于上传完整工程后，在工程根目录执行：

```bash
bash board/scripts/deploy_r4.sh board/software/spectrum_software_v1_r4_bplus_board.zip
bash board/scripts/start_r4.sh
```

脚本拒绝覆盖已有运行目录。仅上传根目录两个快速启动文件时，使用配套Notebook和视频流程。
普通频谱使用LINE IN左声道；频率响应左路接输入参考、右路接被测系统输出并共地。FFT/M4互斥，安全停止失败时不继续切换硬件。

## 证据范围

r2长测、r3短复验/三次冷启动与独立RC实测具有历史记录。r4实际界面和用户记录已收入设计报告，完整交互证据范围按report/verification_report.md说明。
板端ZIP及冻结资产未因文档整理而改变，HOST_VALIDATED_BOARD_PENDING、board_accepted=false与CMA有限结论保留。
