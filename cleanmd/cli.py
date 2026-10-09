"""命令行入口。

单文件：  cleanmd in.pdf -o out.md [--disable 规则名,...] [--report]
批量：    cleanmd batch ./in ./out [--recursive] [--disable ...] [--report]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import cleaners
from .pipeline import process


def _parse_disable(value: str | None) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in value.split(",") if x.strip()]


def _print_report(report: dict, to_stdout: bool) -> None:
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if to_stdout:
        print(payload)
    else:
        print(payload, file=sys.stderr)


def cmd_single(args: argparse.Namespace) -> int:
    try:
        md, report = process(args.input, disabled=_parse_disable(args.disable))
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    if args.output:
        out = Path(args.output)
        out.write_text(md, encoding="utf-8")
        print(f"已写入: {out}（{report['lines_after']} 行）")
    else:
        sys.stdout.write(md if md.endswith("\n") else md + "\n")
    for w in report["warnings"]:
        print(f"警告: {w}", file=sys.stderr)
    if args.report:
        _print_report(report, to_stdout=bool(args.output))
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    in_dir = Path(args.input_dir)
    out_dir = Path(args.output_dir)
    if not in_dir.is_dir():
        print(f"错误: 输入目录不存在: {in_dir}", file=sys.stderr)
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.recursive:
        files = [p for p in in_dir.rglob("*") if p.is_file() and not p.name.startswith(".")]
    else:
        files = [p for p in in_dir.iterdir() if p.is_file() and not p.name.startswith(".")]
    files.sort()

    disabled = _parse_disable(args.disable)
    all_reports: dict[str, dict] = {}
    fail = 0
    for f in files:
        rel = f.relative_to(in_dir)
        dest = out_dir / rel.parent / (rel.stem + ".md")
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            md, report = process(f, disabled=disabled)
        except Exception as e:  # 批量模式下单个文件失败只跳过，不中断整体
            print(f"跳过 {rel}: {type(e).__name__}: {e}", file=sys.stderr)
            fail += 1
            continue
        dest.write_text(md, encoding="utf-8")
        all_reports[str(rel)] = report
        trig = [
            n for n, r in report["rules"].items()
            if r.get("enabled") and (r["lines_removed"] or r["lines_changed"])
        ]
        flag = " [需OCR复核]" if report["needs_ocr"] else ""
        print(f"OK {rel} -> {dest.relative_to(out_dir)}"
              f"（触发规则: {', '.join(trig) if trig else '无'}）{flag}")
    print(f"完成: 成功 {len(all_reports)}，失败 {fail}")
    if args.report:
        rp = out_dir / "report.json"
        rp.write_text(json.dumps(all_reports, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"清洗报告: {rp}")
    return 0 if fail == 0 else 1


def _single_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cleanmd", description="把文档转成干净的 Markdown（RAG 预处理）")
    p.add_argument("input", help="输入文档路径")
    p.add_argument("-o", "--output", help="输出 Markdown 路径（缺省则打印到 stdout）")
    p.add_argument("--disable", default="",
                   help=f"关闭指定规则，逗号分隔。可选: {','.join(cleaners.RULE_NAMES)}")
    p.add_argument("--report", action="store_true", help="输出 JSON 清洗报告")
    return p


def _batch_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="cleanmd batch", description="批量转换目录下所有文档")
    p.add_argument("input_dir", help="输入目录")
    p.add_argument("output_dir", help="输出目录")
    p.add_argument("--recursive", action="store_true", help="递归处理子目录")
    p.add_argument("--disable", default="",
                   help=f"关闭指定规则，逗号分隔。可选: {','.join(cleaners.RULE_NAMES)}")
    p.add_argument("--report", action="store_true", help="在输出目录生成 report.json")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["batch"]:
        args = _batch_parser().parse_args(argv[1:])
        return cmd_batch(args)
    args = _single_parser().parse_args(argv)
    return cmd_single(args)


if __name__ == "__main__":
    raise SystemExit(main())
