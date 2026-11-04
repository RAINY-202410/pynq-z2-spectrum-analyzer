# r3导出等待修复候选

> 同日最新：r3已经实板短复验并导出成功，见[r3核验](a_spectrum_r3_validation_20261031.md)。当前执行[r3三次实际冷启动](r3三次冷启动_20261031.md)，使用新独立r3身份记录脚本。下文保留修复候选生成时说明；r3长测尚未执行，不冒称r2长测为r3证据。

> 2026-10-31接续：r2本轮救援原件已取回并核验，1820秒前台长测及同服务20秒恢复通过，见[最新实测附页](a_spectrum_rescue_validation_20261031.md)。当前先补ARM基准，之后再统一安排下述r3安全切换及短复验；r3仍未部署，不将r2长测登记为r3板测。

日期2026-10-30。用户已确认导出时提示`Worker command still pending; do not start another acquisition`。这表示HTTP调用等待后台命令超过15秒；超时不会取消已排队/正在执行的操作。ZIP是否最终完成仍需检查文件与CRC，不能仅凭提示断言数据损坏或已打包成功。

## 当前r2先取回数据

先保留现有服务和原始结果，不再次点导出、开始采集、重启或升级。等待当前任务结束，按[现有导出恢复步骤](spectrum_export_recovery_20261030.md)运行独立检查工具；有CRC通过的整会话ZIP直接从Jupyter下载，没有完整ZIP再用原始证据备份。不要为导出重跑长测。

## 修复内容

构建`spectrum_software_1_r3`仅为HTTP的单次导出和整会话导出单独设置300秒等待上限，其他采集/停止/绘制/截图命令仍为15秒。命令只入队一次；压缩、CRC和原始文件哈希规则不变。

采集工作线程、asyncio loop、驱动、数据解析、数值算法、浏览器绘图和bit/hwh保持与r2相同。构建号及部署说明相应更新。主机审计器接受受信任receipt中的v1/r2/r3，未绕过文件完整性校验。

300秒是有限的导出等待预算，不保证任何磁盘/文件系统问题都能被等待解决；已保存原始数据的保全入口继续独立提供。达到期限时仍按既有提示保留服务并检查后台结果。

## 验证与范围

主机34项检查通过，包含两种导出等待预算、其他控制预算不变，以及既有安全停止/恢复/数值/证据保护。Windows沙箱限制本机回环socket会阻塞asyncio，已依据线程栈确认，并在允许本机回环的环境重跑通过；测试无板卡访问。

新包另做完整性、Python3.6语法、受保护M4/RTL/契约检查、干净目录导入/7类真实PL留样REPLAY、导出与审计。它们不代表r3已经做过实际LIVE板测或长跑。

## 后续部署顺序

**先下载并核验当前r2结果，再安排r3。不要现在替换运行文件或手改manifest。** r2长测和恢复原件保留，不因导出等待问题自动作废。

确认数据保全后，完整上传`spectrum_software_v1_r3_board.zip`至`/home/xilinx/jupyter_notebooks/`，解压新目录，按以下顺序安全切换：

```bash
cd /home/xilinx/jupyter_notebooks
python3 -m zipfile -e spectrum_software_v1_r3_board.zip .
cd spectrum_software_v1_r3
python3 spectrum_service.py stop --port 8091
python3 spectrum_app.py --mode live --bind 0.0.0.0 --port 8091
```

只有stop报告STOPPED或PORT_FREE后才执行最后一行。需要实际配合时再统一安排同版20秒单音/停止恢复/导出复验与发布冷启动；不因等待设置变化立即重复全部30分钟矩阵。CMA、连续前台、ARM基准和发布验收结论继续由实际证据决定。
