"""格式转换层：封装 markitdown，把各种格式统一转成 Markdown。

已经是 Markdown / 纯文本的文件直接透传（方便对已有 md 做二次清洗）。
"""

from __future__ import annotations

import logging
from pathlib import Path

# pdfminer 在解析问题字体时会刷屏 "Could not get FontBBox …" 警告，直接压到 ERROR
logging.getLogger("pdfminer").setLevel(logging.ERROR)

_PASSTHROUGH = {".md", ".markdown", ".txt", ".text"}


def convert_to_markdown(input_path: str | Path) -> str:
    """把任意支持的文档转成 Markdown 字符串。"""
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")
    if path.suffix.lower() in _PASSTHROUGH:
        return path.read_text(encoding="utf-8", errors="replace")
    try:
        from markitdown import MarkItDown
    except ImportError as e:
        raise RuntimeError(
            "需要安装 markitdown：pip install 'markitdown[docx,pdf,xlsx]'"
        ) from e
    try:
        result = MarkItDown().convert(str(path))
    except Exception as e:
        if "MissingDependency" in type(e).__name__:
            raise RuntimeError(
                f"markitdown 缺少 {path.suffix} 格式的依赖，"
                "请安装：pip install 'markitdown[docx,pdf,xlsx]'"
            ) from e
        raise
    return result.text_content or ""
