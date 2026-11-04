---
name: fpga-delivery-audit
description: Audit an FPGA competition or Vivado handoff package for naming, required artifacts, manifest coverage, source/bit consistency, and evidence labels.
---

# FPGA Delivery Audit

## 适用范围

适用于 Vivado RTL/IPI/HLS、PYNQ 软件和竞赛提交包。可用于避免：

- 源码改了但 manifest 没重建；
- manifest 新了但板端 ZIP 仍是旧版；
- `.bit` 与 `.hwh` 混用不同版本；
- 主机测试、板端冒烟和最终验收状态混写；
- 中文、空格或大小写混乱导致 Linux/Windows 复现差异。

## 使用方法

```bash
python scripts/audit_submission.py <project_root>
```

脚本检查：

- 必需目录与文件；
- 文件名是否符合 `[a-z0-9_.-]+`；
- manifest 的文件覆盖和 SHA256；
- bit/hwh/软件包是否为非空文件；
- 是否存在应显式标注的 board acceptance 字段。

更完整的项目可以扩展 `required_paths` 和业务字段检查。

## 失效条件

- manifest 生成器把自身或临时文件纳入递归哈希；
- 交付 ZIP 内保留绝对路径；
- 报告和 bitstream 不具有版本对应关系；
- 用户没有提供原始综合/实现报告却要求填写资源数字；
- 修改了已签名报告后再用旧 manifest 验证。

## 已验证效果

在本项目中发现并修正：

- R4 源码修改后 manifest 哈希失效；
- 旧板端 ZIP 在原位压缩时未被更新；
- 临时 `__pycache__` 不应进入 manifest；
- 可见目录名需要从小写规则统一；
- R4 主机测试与最终板端验收必须分开记录。

## 失败观察来源

- 旧 ZIP 时间戳与源码不一致；
- UI 修复后 manifest 测试报 changed files；
- 收件中的资源观察不能替代 `report_utilization`；
- 板端 UTC 日期异常，证明文件日期不能作为运行顺序依据。
