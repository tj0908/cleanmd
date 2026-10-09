# cleanmd v1 验证报告

方法：对 `~/workspace/rag-demo/output/` 下 6 个 markitdown 转换样本
（sample_docx/pdf/xlsx/pptx/html/csv.md）运行 `process()`，对比清洗前后。
另做一次端到端验证：直接输入 `.docx` 走转换+清洗全链路。

## 总览

| 文件 | 行数 前→后 | 字符 前→后 | 删行 | 改行 | 触发的规则 | needs_ocr |
|---|---|---|---|---|---|---|
| sample_docx | 30→29 | 485→470 | 1 | 5 | 修复表格(-1/~4); 空白归一化(-0/~1) | False |
| sample_pdf | 67→64 | 959→895 | 3 | 5 | 去页眉页脚/水印(-2/~0); 恢复标题(-0/~4); 空白归一化(-1/~1) | False |
| sample_xlsx | 13→13 | 365→365 | 0 | 0 | 无 | False |
| sample_pptx | 17→16 | 296→271 | 1 | 0 | 去页眉页脚/水印(-1/~0) | False |
| sample_html | 34→24 | 500→318 | 9 | 0 | 去页眉页脚/水印(-1/~0); 过滤HTML噪声(-7/~0); 空白归一化(-1/~0) | False |
| sample_csv | 5→5 | 184→184 | 0 | 0 | 无 | False |

## 逐文件说明

### sample_docx

错乱表格被修复（空表头占位行删除、分隔行归位）；合并单元格导致的「2026-12-01 起 王五」串格被保守保留（不丢数据，语义拆分需解析源格式，见 README 局限）。

被删除的行（节选）：
- `|  |  |  |  |`
- `| 阶段 | 时间 | 负责人 | 交付物 |`
- `| 灰度 | 2026-12-01 起  王五 | | 灰度报告 |`

### sample_pdf

页眉 `CONFIDENTIAL…` 与页脚 `Page 1 of 12…` 被删除；`1. Background`→`#`、`1.1/1.2`→`##` 标题层级恢复；`1./2./3.` 目标列表未被误转；单词间双空格归一。

被删除的行（节选）：
- `CONFIDENTIAL - XX Tech Co., Ltd.`
- `This  document  describes  the  product  requirements  for  the  customer  service  RAG  s`
- `1. Background`
- `1.1 Pain Points`
- `1.2 Targets`
- `2. Schedule`
- `Page 1 of 12 - Revised 2024`
- ``

### sample_xlsx

无任何改动——干净文件通过 pipeline 原样输出，未过清洗。

### sample_pptx

标题页副标题中的 `内部机密` 水印行被删除；`<!-- Slide number -->` 注释保留（利于分块定位）。

被删除的行（节选）：
- `产品需求评审 · 2026年10月 · 内部机密`

### sample_html

导航栏、登录行、两处广告、`### 相关推荐`及其 2 条推荐、`©…京ICP备…` 页脚全部删除；作者行与正文完整保留。

被删除的行（节选）：
- `[首页](/) | [技术](/tech) | [关于我们](/about)`
- `登录 / 注册`
- `🔥 双十一大促！云服务器 5 折起，点击领取优惠券 →`
- `### 相关推荐`
- `* 向量数据库选型指南`
- `* Embedding 模型对比`
- ``
- `📢 免费领取《LLM 应用白皮书》，扫码关注公众号`
- …另有 2 行

### sample_csv

无任何改动——干净文件通过 pipeline 原样输出，未过清洗。

## 「未过清洗」证明

- sample_xlsx: 清洗后与原文✅ 完全一致（删行/改行均为 0）
- sample_csv: 清洗后与原文✅ 完全一致（删行/改行均为 0）

## 端到端验证（.docx → 转换 → 清洗）

- 输入：`~/workspace/rag-demo/samples/sample.docx`
- 行数：30→29，字符：485→470
- 触发规则：修复表格(-1/~4); 空白归一化(-0/~1)
- needs_ocr：False
- 结论：转换器链路正常，表格修复规则在真实 docx 转换结果上同样生效。
