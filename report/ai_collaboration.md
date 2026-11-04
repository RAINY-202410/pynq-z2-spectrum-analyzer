# ROSS与大模型协作记录

开发者提出约束，AI客户端读取AMD Skills，借助Vivado MCP执行Tcl并读取真实返回，结合AMD文档与历史证据推进接口、仿真、集成和交付。ROSS属于研发辅助链路，不参与板端实时频谱计算。

## 原始记录

ai_records/figure15_original_dialogue_excerpt_20261104.md为阅读版，同名JSON保留选定条目的原始字段，original_dialogue_extraction_receipt_20261104.json记录来源和哈希。
摘录来自fpga_2聊天、2026-10-24原始会话，共9个公开条目，含用户提示词、AI回复及实际工具调用/返回。未包含内部推理或无关会话。
原始压缩会话SHA256：0cad422a4d264098ec92c396e7520a232be76b1abac33f77e3bd19896f832917。

## 自我纠错案例

尝试将PCW_M_AXI_GP0_FREQMHZ从10设为100，Vivado返回该参数只读并保留GP0_ANNOTATION_FIX_FAILED。随后读取PS配置、GP0接口及FCLK，返回10 100 100000000 100000000，确认实际接口为100MHz，保留525项PS配置和失败审计。
后续BD重建读取GP0_ANNOTATION=100、ACTUAL=100000000，17项FFT配置一致。此结果只证明BD重建和配置核对范围，不证明第二次综合或bit逐字一致。

完整工具原生日志见ai_records/ross_native_20261024.log，失败节选见gp0_readonly_failure.log。r3导出修复、CMA证据复核和11月3日交付协作节选分别保留原始来源与日期。

## 复用方法与职责

从接口宽度、线程事件循环、DMA长度、MCLK、资源所有权和交付清单等失败观察提炼两项技能，说明适用范围、用法、失效条件和已验证效果，见../skill/readme.md。
团队承担题目判断、实物接线、供电与最终结果确认；AI辅助代码、接口核对、日志分析和材料整理。归纳提示词模板是方法总结，不冒充历史逐字对话。
