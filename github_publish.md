# GitHub公开发布

本包已有readme.md、license.md、third_party_notices.md、.gitignore与.gitattributes。
使用GitHub Desktop新建空仓库时，README、License及Git ignore模板均不额外生成，复制本包全部内容至仓库根目录后提交并发布为Public。
保留build/scripts、正式报告与bit/hwh；.gitattributes用于保持manifest所覆盖文件的原始字节，.git和缓存不参与总清单。
发布前运行python build/scripts/verify_package.py；将最终RAR、运行ZIP与Notebook作为同一版本Release附件，建议标签v1.0.0。
公开后将实际仓库与固定Release地址填写到竞赛提交说明中；新增或修改包内文件后需最后重建manifest，并重新生成对应RAR和哈希。
本包的MIT授权不代替第三方许可证，也不表示GitHub仓库或竞赛后台已经发布。
