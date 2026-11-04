# 同步双声道原始数据

b11为直通信号发生器原始数据，b12为RC原始数据。按 data/b11_signal_generator 和 data/b12_rc_measured 中 source_dataset_manifest.json 核对，原件字节与源清单SHA256一致。
每组正式分析96块；自检和元数据不计作测量频点。B11保留排除的6kHz retry原件，源清单明确排除，不能用它替换正式验证。
本轮只补原件和核对哈希，没有重新采集或拟合。
