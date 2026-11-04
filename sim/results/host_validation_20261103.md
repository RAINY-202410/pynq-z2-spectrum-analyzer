# R4 Host Validation Summary

Date: 2026-11-03 Asia/Shanghai

The signed Board ZIP was extracted to a temporary directory and tested without
using the source mirror.

## Results

| Check | Result |
| --- | --- |
| R4 integration tests | 10/10 PASS |
| B extension tests | 72/72 PASS |
| R4 software manifest | 553 files verified |
| JavaScript syntax | PASS |
| Board ZIP internal hashes | PASS |

Manifest identity:

```text
build_revision:
spectrum_software_1_r4_bplus

manifest_sha256:
827F7446E686E9B61695533ECA96FF89C653739928A638597891954A671043AE

board_zip_sha256:
0A83727DB5B5355D6854001EED3F64B37EC25BBD4022ED3B6D54F25262ACCC9C
```

The raw command output can be regenerated with:

```bash
python build/scripts/run_host_tests.py
```

This summary is HOST_VERIFIED evidence. It is not R4 board acceptance.
