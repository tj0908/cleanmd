"""每条清洗规则的单测。"""

from cleanmd.cleaners import (
    RULE_NAMES,
    detect_empty_extraction,
    filter_html_noise,
    fix_tables,
    normalize_unicode,
    normalize_whitespace,
    restore_headings,
    strip_headers_footers,
)


def test_rule_registry_complete():
    assert RULE_NAMES == [
        "normalize_unicode",
        "strip_headers_footers",
        "filter_html_noise",
        "fix_tables",
        "restore_headings",
        "normalize_whitespace",
        "detect_empty_extraction",
    ]


# ---- normalize_unicode ----

def test_normalize_unicode_removes_control_chars():
    text = "MindBridge\x01项目\x01·\x01面试\x01\n"
    out, stats = normalize_unicode(text)
    assert "\x01" not in out
    assert out == "MindBridge项目·面试\n"
    assert stats["control_chars_removed"] == 4


def test_normalize_unicode_nfkc_compat_chars():
    # CJK 兼容字符（如 ⽬ U+2F6F）应归一化为标准字（目）
    text = "项⽬⾯试⾖包"
    out, stats = normalize_unicode(text)
    assert out == "项目面试豆包"
    assert "项目" in out  # 检索"项目"能命中
    assert stats["chars_normalized"] >= 3


def test_normalize_unicode_keeps_newlines_and_tabs():
    text = "a\nb\tc\n"
    out, stats = normalize_unicode(text)
    assert out == text
    assert stats["control_chars_removed"] == 0
    assert stats["chars_normalized"] == 0


def test_normalize_unicode_clean_text_noop():
    text = "## 销售数据\n| 日期 | 产品 |\n"
    out, stats = normalize_unicode(text)
    assert out == text
    assert stats["control_chars_removed"] == 0


def test_normalize_unicode_simplified_radicals():
    # NFKC 覆盖不到的简化部首（如 ⻛ U+2EDB）→ 手动映射为简体字
    out, stats = normalize_unicode("低⻛险⻓期⻔⻅")
    assert out == "低风险长期门见"
    assert stats["chars_normalized"] >= 4


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


def test_strip_ai_generated_watermark():
    out, stats = strip_headers_footers("标题\n部分内容由豆包生成\n正文。\n")
    assert stats["lines_removed"] == 1
    assert "豆包" not in out
    assert "标题" in out and "正文。" in out


def test_strip_doc_header_in_first_lines():
    text = "MindBridge项目·央国企面试应对手册\n部分内容由豆包生成\n# 1. 开篇\n正文。\n"
    out, stats = strip_headers_footers(text)
    assert stats["lines_removed"] == 2
    assert "MindBridge项目" not in out
    assert "# 1. 开篇" in out


def test_strip_doc_header_only_in_first_five_lines():
    # 同样的"X·Y"式短行出现在文档深处时不删（避免误删正文）
    lines = ["正文第%d行。" % i for i in range(8)]
    lines.insert(6, "笔记·随手记")
    out, stats = strip_headers_footers("\n".join(lines))
    assert stats["lines_removed"] == 0
    assert "笔记·随手记" in out


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


def test_fix_tables_removes_stray_separators():
    # pdfminer 把一个表拆成多个小表，每个都带分隔行：只保留第一个
    text = (
        "| a | b |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "| --- | --- |\n"
        "| 3 | 4 |\n"
    )
    out, stats = fix_tables(text)
    assert out.count("| --- | --- |") == 1
    assert stats["lines_removed"] == 1
    assert "| 1 | 2 |" in out and "| 3 | 4 |" in out


def test_fix_tables_removes_blank_inside_table_head():
    # 表头与分隔行之间的空行应删掉（表块内部不允许空行）
    text = "| a | b |\n\n| --- | --- |\n| 1 | 2 |\n"
    out, stats = fix_tables(text)
    assert stats["lines_removed"] == 1
    lines = out.split("\n")
    assert lines[0] == "| a | b |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 | 2 |"


def test_fix_tables_merges_overflow_line():
    # 单元格文本溢出到无管道行：拼回上一行末单元格
    text = (
        "| a | b |\n"
        "| --- | --- |\n"
        "| 1 | 很长很长的单元格文本 |\n"
        "溢出的后半句\n"
        "| 3 | 4 |\n"
    )
    out, stats = fix_tables(text)
    assert stats["rows_merged"] == 1
    assert "| 1 | 很长很长的单元格文本 溢出的后半句 |" in out
    assert "溢出的后半句\n" not in out  # 不再是独立行


def test_fix_tables_overflow_after_stray_separator():
    # 溢出行前面隔了一个杂散分隔行：删分隔行后仍能合并
    text = (
        "| a | b |\n"
        "| --- | --- |\n"
        "| 1 | 2 |\n"
        "| --- | --- |\n"
        "溢出文本\n"
        "| 3 | 4 |\n"
    )
    out, stats = fix_tables(text)
    assert stats["rows_merged"] == 1
    assert out.count("| --- | --- |") == 1
    assert "| 1 | 2 溢出文本 |" in out


def test_fix_tables_does_not_merge_real_paragraph():
    # 表格之间的正文段落（以句末标点结尾 / 下一行不是表行）不能合并
    text = "| a |\n| --- |\n| 1 |\n\n这是正文段落。\n\n| b |\n| --- |\n| 2 |\n"
    out, stats = fix_tables(text)
    assert stats["rows_merged"] == 0
    assert "这是正文段落。" in out


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
    # 冒号后是长正文 → 句子不是标题
    text = "1. 注意：以下内容很重要，请仔细阅读。\n"
    out, stats = restore_headings(text)
    assert stats["lines_changed"] == 0


def test_restore_headings_allows_short_colon_subtitle():
    # 中文标题常见"编号+标题：短副标题"，冒号后 ≤12 字应转换
    text = "4. 会议流程\n\n4.1 会前准备：先脱敏，再开会\n"
    out, stats = restore_headings(text)
    assert "# 4. 会议流程" in out
    assert "## 4.1 会前准备：先脱敏，再开会" in out
    assert stats["lines_changed"] == 2


def test_restore_headings_document_chapter_sequence():
    # 全文档连续递增的章节号（文件2式 1→10）视为章节，全部转换
    text = "1. 简介\n\n正文。\n\n2. 背景\n\n正文。\n\n3. 方法\n"
    out, stats = restore_headings(text)
    assert "# 1. 简介" in out
    assert "# 2. 背景" in out
    assert "# 3. 方法" in out
    assert stats["lines_changed"] == 3


def test_restore_headings_restarted_numbering_is_list():
    # 小节内重新从 1 开始的 1./2./3. 是列表，不转换
    text = "4. 会议流程\n\n正文。\n\n1. 落库与留痕\n\n2. 生成报告\n\n3. 派发工具\n"
    out, stats = restore_headings(text)
    assert "# 4. 会议流程" in out
    assert "\n1. 落库与留痕" in out
    assert "\n2. 生成报告" in out
    assert "# 1. 落库" not in out
    assert stats["lines_changed"] == 1


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
