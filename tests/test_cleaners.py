"""每条清洗规则的单测。"""

from cleanmd.cleaners import (
    RULE_NAMES,
    detect_empty_extraction,
    filter_html_noise,
    fix_tables,
    normalize_whitespace,
    restore_headings,
    strip_headers_footers,
)


def test_rule_registry_complete():
    assert RULE_NAMES == [
        "strip_headers_footers",
        "filter_html_noise",
        "fix_tables",
        "restore_headings",
        "normalize_whitespace",
        "detect_empty_extraction",
    ]


# ---- strip_headers_footers ----

def test_strip_headers_footers_removes_junk():
    text = (
        "CONFIDENTIAL - XX Tech Co., Ltd.\n"
        "\n"
        "正文第一段。\n"
        "Page 1 of 12 - Revised 2024\n"
        "© 2026 技术博客 · 京ICP备123456号\n"
        "正文第二段。\n"
    )
    out, stats = strip_headers_footers(text)
    assert stats["lines_removed"] == 3
    assert "CONFIDENTIAL" not in out
    assert "Page 1 of 12" not in out
    assert "京ICP备" not in out
    assert "正文第一段。" in out and "正文第二段。" in out


def test_strip_headers_footers_keeps_long_lines():
    # 长正文即使含有"机密"字样也不删（长度保护）
    text = "这份很长很长的正文段落里不小心提到了机密两个字，但它显然不是水印行而是正常句子内容，千万不要被删掉啊。"
    assert len(text) > 40
    out, stats = strip_headers_footers(text)
    assert stats["lines_removed"] == 0
    assert out == text


def test_strip_cn_page_number():
    out, stats = strip_headers_footers("正文\n第 3 页\n更多正文")
    assert stats["lines_removed"] == 1
    assert "第 3 页" not in out


# ---- filter_html_noise ----

def test_filter_html_noise():
    text = (
        "[首页](/) | [技术](/tech) | [关于我们](/about)\n"
        "登录 / 注册\n"
        "\n"
        "🔥 双十一大促！云服务器 5 折起，点击领取优惠券 →\n"
        "\n"
        "# 如何构建 RAG 系统\n"
        "\n"
        "作者：陈工 · 发布于 2026-09-20\n"
        "\n"
        "### 相关推荐\n"
        "\n"
        "* 向量数据库选型指南\n"
        "* Embedding 模型对比\n"
        "\n"
        "📢 免费领取《LLM 应用白皮书》，扫码关注公众号\n"
        "\n"
        "© 2026 技术博客 · 京ICP备xxxxxx号\n"
    )
    out, stats = filter_html_noise(text)
    assert "首页" not in out
    assert "登录 / 注册" not in out
    assert "大促" not in out
    assert "相关推荐" not in out
    assert "向量数据库选型指南" not in out
    assert "扫码关注公众号" not in out
    # 有用信息保留；版权行是 strip_headers_footers 的职责，这里不动
    assert "# 如何构建 RAG 系统" in out
    assert "作者：陈工" in out
    assert "© 2026 技术博客" in out
    assert stats["lines_removed"] == 7  # 导航1+登录1+广告1+推荐标题1+推荐项2+广告1


def test_filter_html_noise_keeps_normal_links():
    text = "参考 [MarkItDown](https://example.com) 和 [Docling](https://example.org) 两个工具。\n"
    out, stats = filter_html_noise(text)
    assert stats["lines_removed"] == 0
    assert out == text


# ---- fix_tables ----

BROKEN_TABLE = (
    "|  |  |  |  |\n"
    "| --- | --- | --- | --- |\n"
    "| 阶段 | 时间 | 负责人 | 交付物 |\n"
    "| 需求评审 | 2026-10-15 | 张三 | PRD 定稿 |\n"
    "| 灰度 | 2026-12-01 起 |  | 灰度报告 |\n"
)


def test_fix_tables_repairs_broken_table():
    out, stats = fix_tables(BROKEN_TABLE)
    lines = [l for l in out.split("\n") if l]
    assert stats["lines_removed"] == 1  # 空表头占位行
    assert lines[0] == "| 阶段 | 时间 | 负责人 | 交付物 |"
    assert lines[1] == "| --- | --- | --- | --- |"
    assert all(line.count("|") == 5 for line in lines)  # 列数对齐


def test_fix_tables_removes_empty_column():
    text = "| a |  | b |\n| --- | --- | --- |\n| 1 |  | 2 |\n"
    out, stats = fix_tables(text)
    assert stats["columns_removed"] == 1
    assert out.split("\n")[0] == "| a | b |"


def test_fix_tables_clean_table_noop():
    text = (
        "| 日期 | 产品 | 数量 |\n"
        "| --- | --- | --- |\n"
        "| 2026-10-01 | 音箱 | 120 |\n"
    )
    out, stats = fix_tables(text)
    assert out == text
    assert stats["lines_removed"] == 0 and stats["lines_changed"] == 0


def test_fix_tables_pads_short_rows():
    text = "| a | b |\n| --- | --- |\n| 1 |\n"
    out, stats = fix_tables(text)
    assert out.split("\n")[2] == "| 1 |  |"


# ---- restore_headings ----

def test_restore_headings_pdf_style():
    text = (
        "1. Background\n"
        "\n"
        "1.1 Pain Points\n"
        "\n"
        "Some body text here.\n"
        "\n"
        "1.2 Targets\n"
        "\n"
        "2. Schedule\n"
    )
    out, stats = restore_headings(text)
    assert "# 1. Background" in out
    assert "## 1.1 Pain Points" in out
    assert "## 1.2 Targets" in out
    assert "# 2. Schedule" in out
    assert stats["lines_changed"] == 4


def test_restore_headings_skips_numbered_lists():
    text = (
        "1. Targets\n"
        "\n"
        "1.1 Overview\n"
        "\n"
        "1. First item\n"
        "\n"
        "2. Second item\n"
        "\n"
        "3. Third item\n"
    )
    out, stats = restore_headings(text)
    assert "# 1. Targets" in out
    assert "## 1.1 Overview" in out  # 父级已确认，下级编号可转
    assert "1. First item" in out and "# 1. First" not in out  # 3 项连续编号是列表，不动
    assert stats["lines_changed"] == 2


def test_restore_headings_skips_orphan_subsection():
    # 没有父级标题的 "1.2"（可能是 "3.5 亿" 这样的小数），保守跳过
    out, stats = restore_headings("1.2 增长\n\n正文。\n")
    assert stats["lines_changed"] == 0
    assert out == "1.2 增长\n\n正文。\n"


def test_restore_headings_skips_existing_structures():
    text = "# 已有标题\n\n| 1. x | y |\n\n- 1. 列表项\n\n```\n1. 代码\n```\n"
    out, stats = restore_headings(text)
    assert stats["lines_changed"] == 0
    assert out == text


def test_restore_headings_chinese_chapter():
    out, stats = restore_headings("第3章 系统架构\n\n这是正文。\n")
    assert "# 第3章 系统架构" in out
    assert stats["lines_changed"] == 1


def test_restore_headings_skips_colon_lines():
    # 带冒号的多半是句子不是标题
    text = "1. 注意：以下内容很重要，请仔细阅读。\n"
    out, stats = restore_headings(text)
    assert stats["lines_changed"] == 0


# ---- normalize_whitespace ----

def test_normalize_whitespace():
    text = "This  document   has issues.   \n\n\n\n下一段。\n| a  |  b |\n"
    out, stats = normalize_whitespace(text)
    assert out == "This document has issues.\n\n下一段。\n| a | b |\n"
    assert stats["lines_removed"] == 2  # 4 个空行→1 个，去掉 2 行
    assert stats["lines_changed"] == 2


def test_normalize_whitespace_keeps_table_pipes():
    text = "| 阶段 | 时间 |\n"
    out, stats = normalize_whitespace(text)
    assert out == text


# ---- detect_empty_extraction ----

def test_detect_empty_extraction_flags_short_text():
    _, stats = detect_empty_extraction("   \n  ")
    assert stats["needs_ocr"] == 1


def test_detect_empty_extraction_passes_normal_text():
    text = "这是一段正常的正文，长度足够，不应该被标记为需要 OCR。" * 5
    _, stats = detect_empty_extraction(text)
    assert stats["needs_ocr"] == 0
