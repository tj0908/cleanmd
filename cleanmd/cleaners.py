"""清洗规则：把转换器输出的"脏 Markdown"变干净。

每条规则都是纯函数：``rule(text) -> (new_text, stats)``，
``stats`` 形如 ``{"lines_removed": 2, "lines_changed": 1}``。

所有规则注册在 ``RULES`` 中，pipeline 按顺序执行；
CLI 可通过 ``--disable 规则名`` 单独关闭某条规则。
新增规则时只需写一个同签名函数并追加到 ``RULES`` 即可。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Callable, Dict, List, Tuple

Stats = Dict[str, int]
Rule = Callable[[str], Tuple[str, Stats]]


# ---------------------------------------------------------------------------
# 规则 1：Unicode 归一化（必须第一个执行）
# ---------------------------------------------------------------------------

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f]")

# NFKC 覆盖不到的 CJK 简化部首（U+2E80–U+2EF3 "C-SIMPLIFIED" 系列，
# Unicode 未给它们兼容分解映射）：按部首英文名的本义手动映射为简体字。
# 如 ⻛（CJK RADICAL C-SIMPLIFIED WIND）→ 风。键覆盖不全时欢迎提 PR 补充。
_CJK_RADICAL_FIX = {
    "⻛": "风",  # U+2EDB C-SIMPLIFIED WIND
    "⻓": "长",  # U+2ED3 C-SIMPLIFIED LONG
    "⻔": "门",  # U+2ED4 C-SIMPLIFIED GATE
    "⻅": "见",  # U+2EC5 C-SIMPLIFIED SEE
    "⻆": "角",  # U+2EC6 SIMPLIFIED HORN
    "⻢": "马",  # U+2EE2 C-SIMPLIFIED HORSE
    "⻬": "齐",  # U+2EEC C-SIMPLIFIED EVEN
    "⻚": "页",  # U+2EDA C-SIMPLIFIED LEAF
}
_RADICAL_RE = re.compile("[" + "".join(_CJK_RADICAL_FIX) + "]")


def normalize_unicode(text: str) -> Tuple[str, Stats]:
    """删除不可见控制字符，并做 Unicode 归一化。

    pdfminer 提取的中文 PDF 常混入 ``\\x01`` 等控制字符（几乎每行都有），
    以及 CJK 兼容字符（如 ``⽬`` U+2F6F 实为 ``目`` 的兼容形式），
    会导致 embedding 污染与检索失配（搜"项目"搜不到"项⽬"）。
    保留 ``\\n`` 与 ``\\t``。

    归一化分两步：NFKC + 简化部首手动映射（NFKC 覆盖不到的部分）。
    """
    cleaned, n_removed = _CONTROL_RE.subn("", text)
    normalized = unicodedata.normalize("NFKC", cleaned)
    fixed = _RADICAL_RE.sub(
        lambda m: _CJK_RADICAL_FIX[m.group(0)], normalized
    )
    # 估算发生变化的字符数：逐字符对比 + 长度差（部首替换已含在逐字符对比中）
    n_changed = sum(1 for a, b in zip(cleaned, fixed) if a != b)
    n_changed += abs(len(cleaned) - len(fixed))
    return fixed, {
        "control_chars_removed": n_removed,
        "chars_normalized": n_changed,
    }


# ---------------------------------------------------------------------------
# 规则 2：去页眉页脚 / 页码 / 水印
# ---------------------------------------------------------------------------

_PAGE_RE = re.compile(r"Page\s+\d+\s+of\s+\d+", re.IGNORECASE)
_CN_PAGE_RE = re.compile(r"第\s*\d+\s*页")
_WATERMARK_WORDS = ("CONFIDENTIAL", "绝密", "内部机密", "机密", "SECRET", "草稿", "DRAFT")
_COPYRIGHT_RES = (re.compile(r"©"), re.compile(r"京ICP备"), re.compile(r"版权所有"))
_AI_GEN_RE = re.compile(r"部分内容由.*生成")  # 部分内容由豆包生成 / 由AI生成 …
# 文档首部页眉：形如 "MindBridge项目·央国企面试应对手册"（短行，只看前 5 行）
_DOC_HEADER_RE = re.compile(r"^[\w\u4e00-\u9fa5-]{2,16}·[\w\u4e00-\u9fa5\s-]{2,16}$")


def strip_headers_footers(text: str) -> Tuple[str, Stats]:
    """删除页眉页脚行、页码行、水印行和版权行。

    只处理"看起来像页眉页脚"的短行（带长度上限），避免误删正文。
    """
    removed = 0
    kept: List[str] = []
    for idx, line in enumerate(text.split("\n")):
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
        elif len(s) <= 40 and _AI_GEN_RE.search(s):
            drop = True  # 部分内容由豆包生成（AI 生成水印）
        elif idx < 5 and len(s) < 25 and _DOC_HEADER_RE.match(s):
            drop = True  # 文档前 5 行内的 "X项目·Y" 式页眉
        if drop:
            removed += 1
        else:
            kept.append(line)
    return "\n".join(kept), {"lines_removed": removed, "lines_changed": 0}


# ---------------------------------------------------------------------------
# 规则 3：过滤 HTML 转换残留的噪声（导航栏 / 广告 / 相关推荐 / 页脚）
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
# 规则 4：修复错乱的 Markdown 表格
# ---------------------------------------------------------------------------

_SEP_CELL_RE = re.compile(r"^:?-{1,}:?$")
_TERMINAL_PUNCT_RE = re.compile(r"[。？！.!?;；]$")


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


def _is_pipe_line(line: str) -> bool:
    return line.lstrip().startswith("|")


def _is_sep_line(line: str) -> bool:
    return _is_pipe_line(line) and _is_sep_row(_split_row(line))


def _is_data_row_line(line: str) -> bool:
    return _is_pipe_line(line) and not _is_sep_line(line)


def _is_overflow_candidate(line: str, next_line: str | None) -> bool:
    """判断某行是否为表格溢出行的候选。

    溢出行：无管道符的非空行，不是标题 / 引用 / 代码围栏 / 列表项，
    不以句末标点结尾（完整句子多半是正文而非单元格溢出），
    且下一行是表行或文档结束（防止把两个表格之间的正文段落误合并）。
    """
    s = line.strip()
    if not s or s.startswith("|"):
        return False
    if s.startswith(("#", ">", "```")):
        return False
    if _LIST_ITEM_RE.match(s):
        return False
    if _TERMINAL_PUNCT_RE.search(s):
        return False
    return next_line is None or _is_pipe_line(next_line)


def _merge_target_is_data(items: List[Tuple[str, str]]) -> bool:
    """往前找溢出行的合并目标：跳过空行项与杂散分隔行（第 2 个及之后），
    若最近的管道行是数据行则返回 True（此时拼回其末单元格是安全的）。"""
    total_seps = sum(
        1 for kind, pl in items if kind == "pipe" and _is_sep_line(pl)
    )
    skipped = 0
    for kind, pl in reversed(items):
        if kind in ("blank", "overflow"):
            continue  # 空行 / 已接受的溢出行：穿透
        if _is_sep_line(pl):
            # 只跳过杂散分隔行；遇到第 1 个（表头后的）分隔行则停止
            if total_seps - skipped > 1:
                skipped += 1
                continue
            return False
        return True  # 数据行
    return False


def _assemble_region(
    lines: List[str], start: int
) -> Tuple[List[Tuple[str, str]], int]:
    """从 start（必为管道行）开始组装一个表格区域。

    区域 = 连续的管道行，中间允许夹杂：
    - 空行：仅表头未结束时（分隔行之后的首个数据行出现前），
      且向前看下一个非空行是管道行（已见分隔行，或它本身就是分隔行）；
    - 溢出行：见 _is_overflow_candidate，且 _merge_target_is_data 为真。
    返回 ([(kind, line)], 下一个未处理行号)，kind ∈ {"pipe","blank","overflow"}。
    """
    items: List[Tuple[str, str]] = []
    i = start
    sep_seen = False
    body_rows = 0  # 分隔行之后的数据行数；为 0 表示表头还没结束
    while i < len(lines):
        line = lines[i]
        if _is_pipe_line(line):
            if _is_sep_line(line):
                sep_seen = True
            elif sep_seen:
                body_rows += 1
            items.append(("pipe", line))
            i += 1
        elif not line.strip() and body_rows == 0:
            # 表头内的空行：向前看，确认后面紧接着还有表行才吞入
            k = i + 1
            while k < len(lines) and not lines[k].strip():
                k += 1
            if (
                k < len(lines)
                and _is_pipe_line(lines[k])
                and (sep_seen or _is_sep_line(lines[k]))
            ):
                items.append(("blank", line))
                i += 1
            else:
                break
        elif _is_overflow_candidate(
            line, lines[i + 1] if i + 1 < len(lines) else None
        ) and _merge_target_is_data(items):
            items.append(("overflow", line))
            i += 1
        else:
            break
    return items, i


def _process_region(items: List[Tuple[str, str]]) -> Tuple[List[str], Stats]:
    """处理一个表格区域：删表内空行 / 杂散分隔行，合并溢出行，再做列级修复。"""
    stats: Stats = {
        "lines_removed": 0,
        "lines_changed": 0,
        "columns_removed": 0,
        "rows_merged": 0,
    }
    # 1) 删表内空行；2) 删杂散分隔行（只保留第一个）
    seq: List[Tuple[str, str]] = []
    sep_kept = False
    for kind, line in items:
        if kind == "blank":
            stats["lines_removed"] += 1
            continue
        if kind == "pipe" and _is_sep_line(line):
            if sep_kept:
                stats["lines_removed"] += 1
                continue
            sep_kept = True
        seq.append((kind, line))
    # 3) 溢出行拼回上一数据行的末单元格；无法合并的原样透传为正文
    out: List[str] = []
    pending: List[str] = []  # 当前累积的纯管道行

    def flush() -> None:
        if pending:
            fixed, s2 = _fix_table_block(pending)
            out.extend(fixed)
            for k in ("lines_removed", "lines_changed", "columns_removed"):
                stats[k] += s2.get(k, 0)
            pending.clear()

    for kind, line in seq:
        if kind == "overflow":
            if pending and _is_data_row_line(pending[-1]):
                prev = pending[-1].rstrip()
                if prev.endswith("|"):
                    prev = prev[:-1].rstrip()
                pending[-1] = prev + " " + line.strip() + " |"
                stats["rows_merged"] += 1
            else:  # 防御：组装期已保证可合并，走到这里说明逻辑有缺口
                flush()
                out.append(line)
        else:
            pending.append(line)
    flush()
    return out, stats


def fix_tables(text: str) -> Tuple[str, Stats]:
    """解析 Markdown 表格：删全空列/空表头占位行/杂散分隔行/表内空行，
    把溢出到无管道行的单元格文本拼回上一行末单元格，
    修复分隔行错位，对齐列数。"""
    lines = text.split("\n")
    out: List[str] = []
    total = {
        "lines_removed": 0,
        "lines_changed": 0,
        "columns_removed": 0,
        "rows_merged": 0,
    }
    i = 0
    while i < len(lines):
        if _is_pipe_line(lines[i]):
            items, i = _assemble_region(lines, i)
            fixed, stats = _process_region(items)
            out.extend(fixed)
            for k in total:
                total[k] += stats.get(k, 0)
        else:
            out.append(lines[i])
            i += 1
    return "\n".join(out), total


# ---------------------------------------------------------------------------
# 规则 5：恢复 PDF 转换丢失的标题层级
# ---------------------------------------------------------------------------

_NUM_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+(\S.*)$")
_CN_CHAPTER_RE = re.compile(r"^第\s*[一二三四五六七八九十百千万\d]+\s*[章节条款部分]\s*(\S.*)?$")
_CN_NUM_RE = re.compile(r"^[一二三四五六七八九十]+\s*[、．.]\s*(\S.*)$")
_BAD_END_RE = re.compile(r"[。；：:!?，,.]$")
_DEPTH1_NUM_RE = re.compile(r"^(\d+)\.\s+")


def _find_list_lines(lines: List[str]) -> set:
    """两遍扫描，找出真正的列表行（小节内重新编号的 1./2./3.）。

    第一遍：收集所有一级编号行 (行号, 编号)。
    第二遍：按编号连续性分组；若某组"重新从小编号开始"
    （组首编号 <= 之前各组出现过的最大编号），且组长度 >= 3，
    则判定为小节内重启的列表。
    全文档连续递增的章节序列（如 1→10）会被视为章节，不标记。
    恰好 2 项的编号对无法区分是列表还是相邻两节，保守按标题处理。
    """
    numbered = []
    for idx, line in enumerate(lines):
        m = _DEPTH1_NUM_RE.match(line.strip())
        if m:
            numbered.append((idx, int(m.group(1))))
    runs: List[List[Tuple[int, int]]] = []
    for idx, num in numbered:
        if runs and num == runs[-1][-1][1] + 1:
            runs[-1].append((idx, num))
        else:
            runs.append([(idx, num)])
    in_list = set()
    max_seen = 0
    for run in runs:
        if len(run) >= 3 and run[0][1] <= max_seen:
            in_list.update(idx for idx, _ in run)
        max_seen = max(max_seen, max(num for _, num in run))
    return in_list


def _colon_tail_too_long(s: str, limit: int = 12) -> bool:
    """冒号后的文本过长 → 更像句子而非标题（如"1. 注意：以下内容很重要…"）。

    中文标题常带短副标题（"4.1 会前准备：先脱敏，再开会"），冒号后
    只有几个字时应允许转换。
    """
    idxs = [i for i in (s.find(":"), s.find("：")) if i >= 0]
    if not idxs:
        return False
    tail = s[min(idxs) + 1:].strip()
    return len(tail) > limit


def restore_headings(text: str) -> Tuple[str, Stats]:
    """把 "1. Background" / "第X章" 这类编号标题恢复为 Markdown 标题。

    保守策略：
    - 只处理短行（≤60 字符）；跳过已有标题/表格/列表项/引用/代码块；
    - 冒号后文本过长（>12 字）、行尾是句末标点的不转换；
    - 小节内重新编号的连续 3 项以上判定为列表，不转换；
      全文档连续递增的章节序列（如 1→10）视为章节，予以转换；
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
        if _colon_tail_too_long(s):
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
# 规则 6：空白归一化
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
# 规则 7：空提取检测（扫描版 PDF / CJK 字体问题兜底提示）
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
    ("normalize_unicode", normalize_unicode),
    ("strip_headers_footers", strip_headers_footers),
    ("filter_html_noise", filter_html_noise),
    ("fix_tables", fix_tables),
    ("restore_headings", restore_headings),
    ("normalize_whitespace", normalize_whitespace),
    ("detect_empty_extraction", detect_empty_extraction),
]

RULE_NAMES: List[str] = [name for name, _ in RULES]
