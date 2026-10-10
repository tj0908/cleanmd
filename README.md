# cleanmd

把文档转成**干净的 Markdown**：格式转换 + 清洗，专为 RAG 预处理设计。

做 RAG 时大家都会遇到同一个坑：PDF / Word / PPT / 网页转成 Markdown 之后是"脏"的——
页眉页脚混进正文、表格错乱、标题层级丢失、广告导航残留。直接把这种文本切分进向量库，
检索质量会大打折扣。cleanmd 就是解决这一层的：先统一转成 Markdown，再过一遍可插拔的清洗规则。

## 安装

```bash
pip install .
# 需要转换 docx/pdf/xlsx 时，markitdown 的可选依赖会自动装好
```

## 快速开始

```bash
# 单个文件
cleanmd in.pdf -o out.md

# 批量转换目录
cleanmd batch ./docs ./cleaned --report

# 只打印清洗报告（JSON）
cleanmd in.pdf -o out.md --report

# 关闭某条规则
cleanmd in.html -o out.md --disable filter_html_noise,restore_headings
```

Python API：

```python
from cleanmd import process

md, report = process("in.pdf")                     # 全部规则开启
md, report = process("in.pdf", disabled=["filter_html_noise"])
print(report["rules"]["strip_headers_footers"])    # {'enabled': True, 'lines_removed': 2, ...}
```

## 清洗规则

| 规则名 | 说明 |
|---|---|
| `normalize_unicode` | Unicode 归一化（最先执行）：删除 `\x00-\x1F` 控制字符（保留换行/制表），NFKC 归一化 CJK 兼容字符，手动映射 NFKC 覆盖不到的简化部首（如 `⻛`→`风`） |
| `strip_headers_footers` | 去页眉页脚：`Page X of Y`、第 X 页、CONFIDENTIAL/内部机密等水印行、`©`/`京ICP备`版权行、AI 生成水印（`部分内容由…生成`）、文档前 5 行内的 `X项目·Y` 式页眉（只处理短行，避免误删正文） |
| `filter_html_noise` | 过滤 HTML 噪声：导航栏（多个链接用 `|` 分隔的行）、广告行（大促/优惠券/扫码/公众号…）、"相关推荐"及其列表、页脚 |
| `fix_tables` | 修复错乱表格：删全空列、删空表头占位行、删杂散分隔行（只保留表头后的第一个）、删表头内空行、把溢出到无管道行的单元格文本拼回上一行末单元格、分隔行错位时把表头换回前面、按表头宽度对齐列数 |
| `restore_headings` | 恢复 PDF 转换丢失的标题：`1. Background`→`#`、`1.1 Pain Points`→`##`、`第X章`→`#`；冒号后 ≤12 字允许转换（如 `4.1 会前准备：先脱敏，再开会`）；全文档连续递增的章节号视为章节，小节内重新编号的 1./2./3. 视为列表不转换 |
| `normalize_whitespace` | 空白归一化：行内多空格→单空格（不动表格竖线、保留行首缩进），连续空行最多保留 1 个，去行尾空格 |
| `detect_empty_extraction` | 空提取检测：正文过短/为空时在报告中标记 `needs_ocr=true` 并给出明确警告（v1 只检测提示，不实现 OCR） |

规则按上表顺序执行，全部默认开启；`--disable` 可单独关闭；新增规则只需在 `cleanmd/cleaners.py` 里写一个
`(text) -> (new_text, stats)` 纯函数并追加到 `RULES`。

## 清洗报告

每次 `process()` 返回 `(clean_md, report)`，report 示例：

```json
{
  "source": "in.pdf",
  "chars_before": 1200, "chars_after": 980,
  "lines_before": 40, "lines_after": 33,
  "rules": {
    "strip_headers_footers": {"enabled": true, "lines_removed": 2, "lines_changed": 0},
    "fix_tables": {"enabled": true, "lines_removed": 1, "lines_changed": 4, "columns_removed": 0}
  },
  "needs_ocr": false,
  "warnings": []
}
```

## 项目结构

```
cleanmd/
  cleanmd/
    converters.py   # 封装 markitdown 做格式转换（.md/.txt 直接透传）
    cleaners.py     # 清洗规则（纯函数 + RULES 注册表）
    pipeline.py     # process(input_path) -> (clean_md, report)
    cli.py          # 命令行：单文件 / 批量 / --report / --disable
  tests/            # pytest 单测（每条规则 + pipeline）
  VALIDATION.md     # v1 在 6 个真实转换样本上的清洗前后对比
```

## 开发

```bash
pytest              # 运行全部单测
```

## 更新日志

### v1.1（2026-10-10）
- 新增 `normalize_unicode` 规则（最先执行）：删除 pdfminer 混入的 `\x01` 等控制字符，NFKC 归一化 CJK 兼容字符，并手动映射 NFKC 覆盖不到的简化部首（`⻛`→`风`等）——真实中文 PDF 实测发现的盲区，对 RAG 检索危害最大
- `fix_tables` 增强：删除 pdfminer 拆表产生的杂散分隔行、表头内空行，把溢出到无管道行的单元格文本拼回上一行末单元格
- `restore_headings` 微调：冒号守卫放宽（冒号后 ≤12 字允许转换）；连续编号改用"是否在小节内重新从 1 开始"区分章节与列表
- `strip_headers_footers` 补模式：AI 生成水印（`部分内容由…生成`）、文档前 5 行内的 `X项目·Y` 式页眉
- `converters.py` 屏蔽 pdfminer 的 `Could not get FontBBox…` 警告刷屏

## 局限与路线图

- 中文 PDF（CJK 子集字体）或扫描版 PDF 可能提取为空：v1 只做检测 + 明确警告，建议改用 Docling / OCR 工具重试。
- docx 合并单元格导致的"内容串行到相邻格"只能保守保留（不丢数据），语义级拆分需要解析源格式，计划在后续版本支持。
- HTML 广告/导航词表目前是内置启发式规则，欢迎提 PR 扩展。
- 纯文本伪表格（markitdown 未识别成表格的）暂不处理，建议上游换 Docling。

## License

MIT
