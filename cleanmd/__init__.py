"""cleanmd：文档转干净 Markdown 的 RAG 预处理 pipeline。

流程：格式转换（markitdown）→ 清洗规则链 → 干净 Markdown + 清洗报告。
"""

from .pipeline import process
from . import cleaners, converters

__version__ = "0.1.0"
__all__ = ["process", "cleaners", "converters"]
