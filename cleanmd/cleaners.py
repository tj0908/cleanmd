"""清洗规则：把转换器输出的"脏 Markdown"变干净。

每条规则都是纯函数：``rule(text) -> (new_text, stats)``，
``stats`` 形如 ``{"lines_removed": 2, "lines_changed": 1}``。

所有规则注册在 ``RULES`` 中，pipeline 按顺序执行；
CLI 可通过 ``--disable 规则名`` 单独关闭某条规则。
新增规则时只需写一个同签名函数并追加到 ``RULES`` 即可。
"""

from __future__ import annotations

import re
from typing import Callable, Dict, List, Tuple

Stats = Dict[str, int]
Rule = Callable[[str], Tuple[str, Stats]]


# ---------------------------------------------------------------------------
# 规则 1：去页眉页脚 / 页码 / 水印
# ---------------------------------------------------------------------------

_PAGE_RE = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)
_CN_PAGE_RE = re.compile(r"第\s*\d+\s*页")
_WATERMARK_WORDS = ("CONFIDENTIAL", "绝密", "内部机密", "机密", "SECRET", "草稿", "DRAFT")
_COPYRIGHT_RES = (re.compile(r"©"), re.compile(r"京ICP备"), re.compile(r"版权所有"))


def strip_headers_footers(text: str) -> Tuple[str, Stats]:
    """删除页眉页脚行、页码行、水印行和版权行。

    只处理"看起来像页眉页脚"的短行（带长度上限），避免误删正文。
    """
    removed = 0
    kept: List[str] = []
    for line in text.split("\n"):
        s = line.strip()
        if not s:
            kept.append(line)
            continue
        drop = False
        if len(s) <= 60 and (_PAGE_RE.search(s) or _CN_PAGE_RE.search(s)):
            drop = True  # Page 1 of 12 / 第 1 页
        elif len(s) <= 40 and any(w in s for w in _WATERMARK_WORDS):
            drop = True  # CONFIDENTIAL / 内部机密 / 机密 …
        elif len(s) <= 120 and any(p.search(s) for p in _COPYRIGHT_RES):
            drop = True  # © … / 京ICP备… / 版权所有
        if drop:
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), {"lines_removed": removed, "lines_changed": 0}


# ---------------------------------------------------------------------------
# 规则 2：过滤 HTML 转换残留的噪声（导航栏 / 广告 / 相关推荐 / 页脚）
# ---------------------------------------------------------------------------

_NAV_WORDS = {"登录", "注册", "首页", "关于我们", "联系我们", "隐私政策", "网站地图", "加入我们"}
_AD_WORDS = ("大促", "优惠券", "领取", "扫码", "公众号", "免费领取",
             "点击领取", "限时", "秒杀", "折起", "白皮书")
_RECOMMEND_TITLES = {"相关推荐", "相关阅读", "推荐阅读", "猜你喜欢", "延伸阅读"}
_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*([-*]|\d+[.)])\s+\S")


def filter_html_noise(text: str) -> Tuple[str, Stats]:
    """删除导航栏、广告行、"相关推荐"及其列表、页脚噪声行。"""
    lines = text.split("\n")
    kept: List[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        s = line.strip()

        # "### 相关推荐"（或纯文本行）+ 紧随其后的推荐列表，整块删掉
        title = None
        m = _HEADING_RE.match(s)
        if m:
            title = m.group(1)
        elif s in _RECOMMEND_TITLES:
            title = s
        if title in _RECOMMEND_TITLES:
            removed += 1  # 标题行本身
            i += 1
            # 跳过空行后连续的列表项
            while i < len(lines) and not lines[i].strip():
                i += 1
            while i < len(lines) and _LIST_ITEM_RE.match(lines[i]):
                removed += 1
                i += 1
            continue

        drop = False
        if s and len(s) <= 120:
            links = _LINK_RE.findall(s)
            if len(links) >= 3 and "|" in s:
                drop = True  # [首页](/) | [技术](/tech) | … 导航栏
            elif len(s) <= 60 and sum(1 for w in _NAV_WORDS if w in s) >= 2:
                drop = True  # 登录 / 注册
            elif any(w in s for w in _AD_WORDS):
                drop = True  # 大促 / 优惠券 / 扫码关注公众号 …
        if drop:
            removed += 1
        else:
            kept.append(line)
        i += 1
    return "\n".join(kept), {"lines_removed": removed, "lines_changed": 0}


# ---------------------------------------------------------------------------
# 规则 3：修复错乱的 Markdown 表格
# ---------------------------------------------------------------------------

_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")


def _split_row(line: str) -> List[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep_row(cells: List[str]) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.match(c) for c in cells)


def _fix_table_block(block: List[str]) -> Tuple[List[str], Stats]:
    stats: Stats = {"lines_removed": 0, "lines_changed": 0, "columns_removed": 0}
    rows = [_split_row(line) for line in block]

    # 1) 删除全空行（含"空表头占位行" | | | |）
    kept_rows = [r for r in rows if not all(c == "" for c in r)]
    stats["lines_removed"] = len(rows) - len(kept_rows)
    rows = kept_rows
    if not rows:
        return [], stats

    # 2) 删除全空列（判断时忽略分隔行）
    ncols = max(len(r) for r in rows)
    keep_cols = []
    for ci in range(ncols):
        vals = [r[ci] if ci < len(r) else "" for r in rows if not _is_sep_row(r)]
        if vals and all(v == "" for v in vals):
            stats["columns_removed"] += 1
        else:
            keep_cols.append(ci)
    rows = [[r[ci] if ci < len(r) else "" for ci in keep_cols] for r in rows]

    # 3) 分隔行错位修复：分隔行出现在表头之前时，把真正的表头换到前面
    if _is_sep_row(rows[0]) and len(rows) > 1 and not _is_sep_row(rows[1]):
        rows[0], rows[1] = rows[1], rows[0]

    # 4) 列数对齐：按表头宽度补齐 / 合并超长行的多余单元格（保守，不丢数据）
    header = next((r for r in rows if not _is_sep_row(r)), None)
    width = len(header) if header else 0
    for r in rows:
        if _is_sep_row(r):
            if len(r) != width:
                r[:] = ["---"] * width
        elif len(r) < width:
            r.extend([""] * (width - len(r)))
        elif len(r) > width:
            r[width - 1] = " ".join([r[width - 1]] + r[width:]).strip()
            del r[width:]

    out = []
    for r in rows:
        if _is_sep_row(r):
            out.append("| " + " | ".join(["---"] * width) + " |")
        else:
            out.append("| " + " | ".join(r) + " |")

    stats["lines_changed"] = sum(
        1 for idx, line in enumerate(out) if idx >= len(block) or line != block[idx]
    )
    return out, stats


def fix_tables(text: str) -> Tuple[str, Stats]:
    """解析 Markdown 表格：删全空列、删空表头占位行、修复分隔行错位、对齐列数。"""
    lines = text.split("\n")
    out: List[str] = []
    total = {"lines_removed": 0, "lines_changed": 0, "columns_removed": 0}
    i = 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|"):
            block = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                block.append(lines[i])
                i += 1
            fixed, stats = _fix_table_block(block)
            out.extend(fixed)
            for k in total:
                total[k] += stats.get(k, 0)
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), total


# ---------------------------------------------------------------------------
# 规则 4：恢复 PDF 转换丢失的标题层级
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_CN_CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*[章节条款部分]\s*(\S.*)?$")
_CN_NUM_RE = re.compile(r"^[一二三四五六七八九十]+\s*[、．.]\s*(\S.*)$")
_BAD_END_RE = re.compile(r"[。；：:!?，,.]$")
_DEPTH1_NUM_RE = re.compile(r"^(\d+)\.\s+")


def _find_list_lines(lines: List[str]) -> set:
    """找出属于连续编号列表（3 项及以上）的行号。

    标题后面跟的是正文或下级编号；真正的列表是同级编号连续递增 3 项以上。
    恰好 2 项的编号对无法区分是列表还是相邻两节，保守按标题处理。
    """
    numbered = []
    for idx, line in enumerate(lines):
        m = _DEPTH1_NUM_RE.match(line.strip())
        if m:
            numbered.append((idx, int(m.group(1))))
    in_list = set()
    i = 0
    while i < len(numbered):
        run = [numbered[i]]
        j = i + 1
        while (
            j < len(numbered)
            and numbered[j][0] - run[-1][0] <= 2  # 最多隔一个空行
            and numbered[j][1] == run[-1][1] + 1  # 编号连续递增
        ):
            run.append(numbered[j])
            j += 1
        if len(run) >= 3:
            in_list.update(idx for idx, _ in run)
        i = j
    return in_list


def restore_headings(text: str) -> Tuple[str, Stats]:
    """把 "1. Background" / "第X章" 这类编号标题恢复为 Markdown 标题。

    保守策略：
    - 只处理短行（≤60 字符）；跳过已有标题/表格/列表项/引用/代码块；
    - 行内含冒号、行尾是句末标点的不转换；
    - 连续 3 项以上的同级编号判定为列表，不转换；
    - "1.1" 这类下级编号要求其父级（如 "1."）已在本轮被确认为标题，
      避免把 "3.5 亿" 这样的小数误转成标题。
    """
    lines = text.split("\n")
    list_idx = _find_list_lines(lines)
    seen = set()  # 已确认为标题的编号前缀，如 {"1", "1.1"}
    out: List[str] = []
    changed = 0
    in_fence = False
    for idx, line in enumerate(lines):
        s = line.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence or not s or len(s) > 60 or idx in list_idx:
            out.append(line)
            continue
        if s[0] in "#|->*" or _BAD_END_RE.search(s):
            out.append(line)
            continue
        if ":" in s or "：" in s:
            out.append(line)
            continue

        level = 0
        num = ""
        m = _NUM_RE.match(s)
        if m:
            num = m.group(1)
            depth = num.count(".") + 1
            if depth == 1:
                level = 1
            elif depth <= 3 and num.rsplit(".", 1)[0] in seen:
                level = depth
        elif _CN_CHAPTER_RE.match(s) or _CN_NUM_RE.match(s):
            level = 1

        if level:
            out.append("#" * level + " " + s)
            if num:
                seen.add(num)
            changed += 1
        else:
            out.append(line)
    return "\n".join(out), {"lines_removed": 0, "lines_changed": changed}


# ---------------------------------------------------------------------------
# 规则 5：空白归一化
# ---------------------------------------------------------------------------

_MULTI_SPACE_RE = re.compile(r"[ \t\u3000]{2,}")
_BLANK_RUN_RE = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> Tuple[str, Stats]:
    """行内多空格→单空格（保留行首缩进与表格竖线），连续空行最多保留 1 个，去行尾空格。"""
    changed = 0
    out: List[str] = []
    for line in text.split("\n"):
        orig = line
        if line.lstrip().startswith("|"):
            # 表格行：只压缩单元格内的连续空格，不动竖线结构
            line = "|".join(_MULTI_SPACE_RE.sub(" ", cell) for cell in line.split("|"))
        else:
            m = re.match(r"^(\s*)", line)
            indent = m.group(1)
            rest = _MULTI_SPACE_RE.sub(" ", line[len(indent):])
            line = indent + rest
        line = line.rstrip()
        if line != orig:
            changed += 1
        out.append(line)
    merged = "\n".join(out)
    final = _BLANK_RUN_RE.sub("\n\n", merged)
    removed = merged.count("\n") - final.count("\n")
    return final, {"lines_removed": removed, "lines_changed": changed}


# ---------------------------------------------------------------------------
# 规则 6：空提取检测（扫描版 PDF / CJK 字体问题兜底提示）
# ---------------------------------------------------------------------------

def detect_empty_extraction(text: str, min_chars: int = 50) -> Tuple[str, Stats]:
    """正文过短或为空时标记 needs_ocr，pipeline 会据此给出明确警告。

    v1 只做检测与提示，不实现 OCR；建议改用 Docling / OCR 工具重试。
    """
    needs = 1 if len(text.strip()) < min_chars else 0
    return text, {"lines_removed": 0, "lines_changed": 0, "needs_ocr": needs}


# ---------------------------------------------------------------------------
# 规则注册表（执行顺序即列表顺序）
# ---------------------------------------------------------------------------

RULES: List[Tuple[str, Rule]] = [
    ("strip_headers_footers", strip_headers_footers),
    ("filter_html_noise", filter_html_noise),
    ("fix_tables", fix_tables),
    ("restore_headings", restore_headings),
    ("normalize_whitespace", normalize_whitespace),
    ("detect_empty_extraction", detect_empty_extraction),
]

RULE_NAMES: List[str] = [name for name, _ in RULES]
