"""端到端 pipeline：转换 → 清洗规则链 → (干净 Markdown, 清洗报告)。"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from . import cleaners
from .converters import convert_to_markdown

EMPTY_EXTRACTION_WARNING = (
    "正文过短，疑似提取失败（如扫描版 PDF、图片型 PDF 或 CJK 子集字体问题），"
    "建议改用带 OCR / 版式理解的工具（如 Docling）重试。"
)


def process(input_path: str | Path, disabled: List[str] | Tuple[str, ...] = ()) -> Tuple[str, Dict]:
    """运行完整 pipeline。

    :param input_path: 输入文档路径（任意 markitdown 支持的格式，或 .md/.txt 透传）
    :param disabled: 要关闭的规则名列表，见 cleaners.RULE_NAMES
    :return: (clean_md, report)，report 记录每条规则触发情况与统计
    """
    disabled = set(disabled)
    unknown = disabled - set(cleaners.RULE_NAMES)
    if unknown:
        raise ValueError(
            f"未知规则: {sorted(unknown)}，可用规则: {cleaners.RULE_NAMES}"
        )

    raw_md = convert_to_markdown(input_path)
    text = raw_md
    rule_reports: Dict[str, Dict] = {}
    for name, fn in cleaners.RULES:
        if name in disabled:
            rule_reports[name] = {"enabled": False, "lines_removed": 0, "lines_changed": 0}
            continue
        text, stats = fn(text)
        entry: Dict = {
            "enabled": True,
            "lines_removed": int(stats.get("lines_removed", 0)),
            "lines_changed": int(stats.get("lines_changed", 0)),
        }
        if "needs_ocr" in stats:
            entry["needs_ocr"] = bool(stats["needs_ocr"])
        rule_reports[name] = entry

    needs_ocr = bool(
        rule_reports.get("detect_empty_extraction", {}).get("needs_ocr", False)
    )
    warnings = [EMPTY_EXTRACTION_WARNING] if needs_ocr else []

    report = {
        "source": str(input_path),
        "chars_before": len(raw_md),
        "chars_after": len(text),
        "lines_before": raw_md.count("\n") + (1 if raw_md else 0),
        "lines_after": text.count("\n") + (1 if text else 0),
        "rules": rule_reports,
        "needs_ocr": needs_ocr,
        "warnings": warnings,
    }
    return text, report
