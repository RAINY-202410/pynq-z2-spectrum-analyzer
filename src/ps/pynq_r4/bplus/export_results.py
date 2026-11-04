"""扩展结果输出路径约束。

扩展输出只能落在 b_plus_v1/reports/ 内。该约束在 B-X01 建立，后续导出模块复用。
"""

from pathlib import Path

EXTENSION_ROOT = Path(__file__).resolve().parent
REPORTS_ROOT = (EXTENSION_ROOT / "reports").resolve()


def reports_root() -> Path:
    """Return the only allowed output root."""
    return REPORTS_ROOT


def resolve_report_path(name: str) -> Path:
    """Resolve a relative output name under reports/.

    Rejects absolute paths, drive-qualified paths, traversal components and
    names that resolve outside reports/.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError("report path must be a non-empty string")
    if "\x00" in name:
        raise ValueError("report path contains NUL")
    candidate = Path(name)
    if candidate.is_absolute() or candidate.drive:
        raise ValueError("report path must be relative to reports/")
    if any(part == ".." for part in candidate.parts):
        raise ValueError("report path must not contain '..'")
    target = (REPORTS_ROOT / candidate).resolve()
    try:
        target.relative_to(REPORTS_ROOT)
    except ValueError as exc:
        raise ValueError("report path escapes reports/") from exc
    return target


def prepare_report_dir(name: str) -> Path:
    """Create a report subdirectory after the path guard passes."""
    target = resolve_report_path(name)
    target.mkdir(parents=True, exist_ok=True)
    return target
