# r3三次实际冷启动核验

日期：2026-10-31，Asia/Shanghai。状态：**BOARD_R3_THREE_COLD_BOOTS_VERIFIED_CMA_REVIEW_PENDING**。三轮boot JSON及原生会话ZIP全部收到，用户明确确认“三轮都实际断电后重新上电”。三个不同boot_id、三个不同服务实例、冻结r3/硬件身份及每轮20秒在线单音采集均通过。**本轮冷启动已完成，不再重复操作或回传。**

| 轮次 | boot_id | 原生会话 | 采集秒数 | 帧数 | 结果 |
| --- | --- | --- | ---: | ---: | --- |
| boot01 | fd12e6ac-6441-4674-ab18-ea057f4b5853 | spectrum_session_c255785c0b5d_export01.zip | 20.007711884 | 100 | 完成/安全停止 |
| boot02 | 7586d13b-7f69-4baf-b34f-ea7c20cbbf85 | spectrum_session_2eff69555b48_export01.zip | 20.016082050 | 100 | 完成/安全停止 |
| boot03 | 6f1e220a-14ab-427a-9214-aa2dc3803052 | spectrum_session_0fa493c5aa53_export01.zip | 20.012633102 | 100 | 完成/安全停止 |

每轮Hann/tone1k/5Hz、100帧，DURATION_COMPLETE、零单音质量错误。逐帧状态/序号检查、6份有限原始留样复数重建及谱指标、7张界面图全部核验。每个新会话序号独立0→100；不同boot之间不要求连续。最长前台段分别19.808753275、19.860060001、19.753133860秒，属于20秒短测，不作r3长测。

## 身份、完整性与配对

- 三份记录均为`spectrum_software_1_r3`、35份文件验证、相同冻结bit/hwh和可信manifest；记录器SHA256与已发布新脚本`1AE2D6AA3D5818947280788CA207EA0BE71A61BFC019818DBBB320A58235290F`一致。r3 manifest仍为`7F1DA7D0BA2CE892CA3A318D0DE76360075FDA2545198EE374D614E0765662A5`。
- boot JSON和ZIP按用户提交顺序及boot label配对，另核对软件/硬件、Python和kernel相符。原生会话没有嵌入boot_id，不声称存在额外的密码学配对证明。实际供电操作以用户明确回复和不同boot_id共同佐证，没有独立电气电源测量。
- board UTC仍为2025年且每次可能重置，三轮UTC不单调；没有按文件修改时间或UTC重排轮次。记录时uptime分别244.32、126.34、120.75秒，与各自已启动的系统会话分开保存。
- 三个ZIP均通过可信审计器的CRC、路径边界、会话/run manifest、逐文件SHA256及来源检查。完整矩阵审计仍为SESSION_DATA_VERIFIED_REQUIREMENTS_PENDING，600秒/双音/静音条件未改；本次只关闭三次冷启动的预定清单。

## 原件与归档

全部六份原件已按原字节复制到`build/spectrum_r3_coldboot_validation_20261031_01/originals/`，SHA256和大小见`input_receipt.json`。三个ZIP的SHA256依次为：

| 轮次 | ZIP SHA256 |
| --- | --- |
| boot01 | `1E08D7B72B3F297541530ADE3996F00EF4116849DAA2145BBB6BD964EF56FBC5` |
| boot02 | `704B15F4531FEAA3F616FC904A69F12526DFD0275BB6A0D17CEFBED28F80A8EC` |
| boot03 | `0E85E1ED7A78D3D8B7DA1985049FE2BF055CE12D7CB60044F18B7A988D9BBACC` |

原始审计在`session_audits/boot01`、boot02、boot03；汇总为`coldboot_validation_receipt.json`。`operator_power_cycle_confirmation.json`记录本聊天的明确供电回复。收到的文件仅作为数据读取，没有执行其中的命令或代码。旧包、旧报告、原始失败记录和所有软件manifest均保持。

## 接续

[基础功能复核清单](a_spectrum_basic_review_20261031.md)汇总r2长测、PC/ARM及r3短测/冷启动证据，基础功能及本轮计划内板测已完成。目前不追加板测，CMA来源、真实LIVE录像与最终格式报告继续独立处理，board_accepted=false保持。r2的1820秒证据不冒充r3长测。
