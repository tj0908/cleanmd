"""pipeline 与 converters 的单测。"""

import pytest

from cleanmd import cleaners
from cleanmd.converters import convert_to_markdown
from cleanmd.pipeline import process


def test_process_cleans_dirty_markdown(tmp_path):
    src = tmp_path / "doc.md"
    src.write_text(
        "CONFIDENTIAL - XX Tech\n\n1. Background\n\n" + "正文  有双空格。" * 8 + "\n",
        encoding="utf-8",
    )
    md, report = process(src)
    assert "CONFIDENTIAL" not in md
    assert "# 1. Background" in md
    assert "正文 有双空格。" in md
    assert report["rules"]["strip_headers_footers"]["lines_removed"] == 1
    assert report["rules"]["restore_headings"]["lines_changed"] == 1
    assert report["needs_ocr"] is False
    assert report["lines_before"] > report["lines_after"]


def test_process_clean_file_stays_unchanged(tmp_path):
    # 干净文件（xlsx/csv 风格）跑完 pipeline 应基本原样
    clean = (
        "## 销售数据\n"
        "| 日期 | 产品 | 数量 |\n"
        "| --- | --- | --- |\n"
        "| 2026-10-01 | 音箱 | 120 |\n"
    )
    src = tmp_path / "clean.md"
    src.write_text(clean, encoding="utf-8")
    md, report = process(src)
    assert md == clean
    total_removed = sum(r["lines_removed"] for r in report["rules"].values())
    total_changed = sum(r["lines_changed"] for r in report["rules"].values())
    assert total_removed == 0 and total_changed == 0


def test_process_disable_rule(tmp_path):
    src = tmp_path / "ad.md"
    src.write_text("🔥 双十一大促，点击领取优惠券\n\n正文。\n", encoding="utf-8")
    md, report = process(src, disabled=["filter_html_noise"])
    assert "大促" in md  # 规则被关闭，广告行保留
    assert report["rules"]["filter_html_noise"]["enabled"] is False


def test_process_unknown_rule_raises(tmp_path):
    src = tmp_path / "a.md"
    src.write_text("hello\n", encoding="utf-8")
    with pytest.raises(ValueError, match="未知规则"):
        process(src, disabled=["不存在的规则"])


def test_process_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process(tmp_path / "nope.pdf")


def test_process_empty_file_flags_ocr(tmp_path):
    src = tmp_path / "empty.md"
    src.write_text("   \n", encoding="utf-8")
    _, report = process(src)
    assert report["needs_ocr"] is True
    assert report["warnings"], "应给出明确警告"


def test_convert_passthrough_md(tmp_path):
    src = tmp_path / "a.md"
    src.write_text("# 标题\n", encoding="utf-8")
    assert convert_to_markdown(src) == "# 标题\n"


def test_convert_missing_file():
    with pytest.raises(FileNotFoundError):
        convert_to_markdown("/tmp/一定不存在的文件.pdf")


def test_all_rules_pluggable():
    # 每条注册的规则都可被单独关闭
    assert set(cleaners.RULE_NAMES) == {
        "strip_headers_footers", "filter_html_noise", "fix_tables",
        "restore_headings", "normalize_whitespace", "detect_empty_extraction",
    }
