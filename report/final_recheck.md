# 交付整理核验

本版以原625文件工程与用户新增的最小部署入口为基础，保留RTL/XDC、IP/BD源、原始实验数据、运行ZIP及冻结FFT/M4 bit/hwh。
同步已补图的24页Word和对应文字，加入2026-10-24原始协作摘录与来源回执，更新五界面/三步部署说明，并按团队决定采用MIT许可。
总manifest在全部文件整理后生成；RAR通过真实解压逐文件核对后交付。校验工具排除.git及本地缓存，正式构建脚本、日志、报告与硬件资产仍在清单中。

| 指南项目 | 对应材料 |
|---|---|
| 3.3.5.1 完整工程与源码 | src/、原生BD、RTL/XDC及PS源码阅读镜像 |
| 仿真或验证结果 | sim/、report/verification_report.md及版本化板端原件 |
| 综合实现及性能 | build/reports/及report/implementation_report.md |
| 上板工程、实测/参考 | board/及data/；保留实际版本与验证范围 |
| 可复现构建脚本 | build/scripts/、build/board_files/及build/readme.md |
| 3.3.5.2 技能包 | skill/两项技能的适用范围、方法、失效条件和效果 |
| 3.3.5.3 设计与协作 | report/design_report.docx与ai_records/真实提示词/回复/工具返回 |
| 开源授权 | 根目录license.md及third_party_notices.md |

独立硬件构建的实际状态见required_validation.md。该状态与功能回归、板端验收、GitHub发布和竞赛后台提交分别记录。
