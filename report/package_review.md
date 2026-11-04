# 工程与材料对应

本包采用src、sim、build、board、data、skill、report结构，外层路径为英文小写。供应商资产、历史日志与不可变运行ZIP保持原有身份和内部路径。
正式交付图文报告为design_report.docx，配套文字版由同一Word正文生成。原始开发提示词、AI回复与工具纠错条目已经纳入ai_records/，不再沿用早期未取得原始对话时的缺项说明。
最小部署使用根目录运行ZIP及packeditor.ipynb，配套视频说明操作，环境前提为PYNQ 3.1.1；入口提供全部五个功能界面。
正式构建使用build/scripts。src/hw/scripts中旧实验脚本作为历史源码保留，其中旧sim路径不作为当前构建入口。
静态完整性校验、独立构建、功能回归、板端验收和发布状态分别记录，见final_recheck.md、required_validation.md、verification_report.md及known_gaps.md。
