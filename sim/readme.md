# 仿真与验证

## 历史结果

rtl_fft/results保留12个主例和2个ABORT恢复帧的原始捕获、日志和receipt；每个复数分量整数误差为0。
这些文件来自既有验证，本轮不重新执行。历史preparation.json对应旧目录，必须原样保存。
不能把新布局的verify_fft_chain.py直接指向sim/rtl_fft/results；旧receipt路径和部分源脚本哈希并不对应当前布局。

## 新环境复现

从仓库根目录按build/readme.md在全新项目和结果目录执行prepare、XSim与verify。
正式入口是build/scripts/run_fft_chain.tcl，复用build/scripts/sim_fft_rect.tcl显式创建BD HDL wrapper。
rtl_fft/sim_fft_chain.tcl等文件保留历史研发版本，不作为提交版入口。

## M4

测试平台sim/m4/tb_m4_delivery.v已补齐。正式入口build/scripts/sim_m4.tcl接受一个不存在的新工程目录。
历史packetizer_simulation_pass.txt作为既有结果保留，不把该文件的存在当作本次重新执行通过。

## 主机软件

build/scripts/run_host_tests.py用于在新环境复现r4/B测试。本轮不重复已有10项和72项功能测试。
包完整性与哈希检查不替代Vivado编译、综合、实现或板端验收。
