"""Run the standalone, local Work Memory prototype."""

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from time import time_ns

from .codex_rpc import Cancelled, path_key
from .review import render_text
from .service import read_review
from .source_codex import Limits, clean_label, collect, source_namespace
from .store import Store, StoreError, snapshot_key
from .summary import DATA_POLICY, ENDPOINT, OUTPUT_TOKENS, enhance
from .time_range import PERIODS, make_window
from .work_items import CorrectionError
from .work_signals import MILESTONES


def add_correction_args(commands):
    correct = commands.add_parser("correct", help="纠正已保存的单项目事项回顾")
    correct.add_argument("--project", action="append", required=True, help="事项所在的绝对工作目录。")
    correct.add_argument("--range", choices=PERIODS, default="today")
    operations = correct.add_subparsers(dest="operation", required=True)
    merge = operations.add_parser("merge", help="归并两个事项")
    merge.add_argument("--into", required=True, help="保留的事项 ID。")
    merge.add_argument("--from", dest="from_item", required=True, help="并入的事项 ID。")
    split = operations.add_parser("split", help="将选中的回合移到新事项")
    split.add_argument("--item", required=True)
    split.add_argument("--anchor", action="append", required=True, help="要移出的回合锚点，可重复指定。")
    split.add_argument("--title", default="")
    confirm = operations.add_parser("confirm", help="添加有明确范围的用户确认")
    confirm.add_argument("--anchor", required=True)
    confirm.add_argument("--milestone", choices=MILESTONES, required=True)
    confirm.add_argument("--outcome", choices=("success", "failed", "pending"), required=True)
    confirm.add_argument("--scope", required=True, help="适用版本、测试范围或目标环境。")
    operations.add_parser("undo", help="撤销该项目最近一次有效纠正")
    operations.add_parser("history", help="查看该项目的纠正记录")


def parse_args(argv):
    parser = argparse.ArgumentParser(description="灵动珠工作回顾 · 本机离线原型")
    parser.add_argument("--db", type=Path, help="可选的工作回顾 SQLite 文件。默认仅使用内存。")
    commands = parser.add_subparsers(dest="action", required=True)
    for name, help_text in (("review", "读取授权目录并生成回顾"), ("cached", "读取上次完整快照"),
                            ("exclude", "排除目录"), ("include", "解除目录排除"), ("clear", "清除工作回顾缓存"),
                            ("revoke-ai", "移除所选项目的 AI 缓存")):
        command = commands.add_parser(name, help=help_text)
        if name == "clear":
            scope = command.add_mutually_exclusive_group(required=True)
            scope.add_argument("--project", action="append", help="要清除的绝对目录，可重复。")
            scope.add_argument("--all", action="store_true", help="清除该数据库内的所有回顾记录。")
            command.add_argument("--yes", action="store_true", required=True, help="确认清除工作回顾缓存。")
        else:
            command.add_argument("--project", action="append", required=True, help="授权的绝对工作目录，可重复。")
        if name in {"review", "cached"}:
            command.add_argument("--range", choices=PERIODS, default="today", help="按本机自然日选择范围。")
            command.add_argument("--format", choices=("text", "json"), default="text")
            command.add_argument("--commands", action="store_true", help="附带命令时点与退出码，或读取对应缓存。")
            command.add_argument("--work-items", action="store_true", help="本机提取显式事项标识与证据，或读取对应缓存。")
        if name == "review":
            command.add_argument("--list-pages", type=int, choices=range(1, 41), default=12, metavar="1..40")
            command.add_argument("--turn-pages", type=int, choices=range(1, 41), default=25, metavar="1..40")
            command.add_argument("--item-pages", type=int, choices=range(1, 21), default=8, metavar="1..20")
            command.add_argument("--ai-model", metavar="ID", help="启用指定 OpenAI API 模型的逐项目预览与授权。")
            command.add_argument("--ai-preview", action="store_true", help="预览请求。不会发送，也不会复用 AI 缓存。")
    add_correction_args(commands)
    args = parser.parse_args(argv)
    paths = args.project or []
    if len(paths) > 6 or any(not os.path.isabs(path) or len(path) > 1024 for path in paths):
        parser.error("请选择至多六个绝对工作目录，每个路径最多 1024 字符。")
    paths = [os.path.normpath(path) for path in paths]
    if len({path_key(path) for path in paths}) != len(paths):
        parser.error("工作目录重复。")
    args.project = paths
    if args.action == "review":
        if args.ai_preview and not args.ai_model:
            parser.error("--ai-preview 需要 --ai-model。")
        args.work_items = args.work_items or args.ai_model is not None
    if args.action == "correct" and len(paths) != 1:
        parser.error("事项纠正需要一个项目目录。")
    if args.action != "review" and args.db is None:
        parser.error("此操作需要在子命令前指定 --db。")
    if args.action in {"cached", "clear", "correct", "revoke-ai"} and not args.db.is_file():
        parser.error("指定的工作回顾数据库不存在。")
    return args


def approve_batch(project, batch, remaining, window, *, preview):
    title = clean_label(project["path"])
    approval = f"发送 {batch.approval}"
    print(f"\nAI 请求预览 · {title}\n日期 {window['local_start']} 至 {window['local_end']}\n"
          f"接收方 {ENDPOINT}\n数据政策 {DATA_POLICY}\n"
          f"匿名事项 {len(batch.items)} 个，未纳入 {batch.omitted} 个。请求 {len(batch.body)} 字节，"
          f"本轮剩余 {remaining} 字节，每次最多 {OUTPUT_TOKENS} 输出 tokens；限流时预算内最多重试一次。\n"
          f"{batch.body.decode('ascii')}", file=sys.stderr)
    if preview or not sys.stdin.isatty() or not sys.stderr.isatty():
        return "preview_only"
    print(f"同意发送此项目的预览内容或复用其缓存，请输入「{approval}」。直接回车跳过。", file=sys.stderr, flush=True)
    try:
        answer = input().strip()
    except EOFError:
        return "not_authorized"
    return "send" if answer == approval else "not_authorized"


def run_review(args, store):
    limits = Limits(args.list_pages, args.turn_pages, args.item_pages) if args.action == "review" else Limits()
    result = read_review(store, args.project, args.range, cached=args.action == "cached", save=args.db is not None,
                         include_commands=args.commands, include_work=args.work_items, limits=limits,
                         as_of=time_ns() // 1_000_000, collector=collect)
    report = result.report
    if report is None:
        raise StoreError("此项目和日期范围没有完整缓存。")
    if args.action == "review" and args.ai_model:
        enhance(report, args.ai_model, namespace=result.namespace, window=result.window,
                credentials=os.environ.get("OPENAI_API_KEY"), store=store, generation=result.generation,
                approve=lambda project, batch, remaining: approve_batch(project, batch, remaining, report["window"], preview=args.ai_preview))
        store.check_generation(result.generation)
    print(json.dumps(report, indent=2, ensure_ascii=False) if args.format == "json" else render_text(report))
    return {"unavailable": 1, "partial": 3}.get(report["status"], 0)


def run_correction(args, store):
    project = args.project[0]
    namespace = source_namespace()
    kind = args.operation
    if kind == "history":
        print(json.dumps(store.work_history(project, namespace), indent=2, ensure_ascii=False))
        return 0
    if kind == "undo":
        print(f"已撤销纠正 {store.undo_work(project, namespace)}。")
        return 0
    if kind == "confirm":
        if not args.scope or clean_label(args.scope) != args.scope:
            raise CorrectionError("请输入非空、简短且没有控制字符的确认范围。")
        values = {"anchor": args.anchor, "milestone": args.milestone, "outcome": args.outcome, "scope": args.scope}
    elif kind == "split":
        values = {"item": args.item, "anchors": args.anchor, "title": clean_label(args.title)}
    else:
        values = {"item": args.into, "from": args.from_item}
    observed = time_ns() // 1_000_000
    window = make_window(args.range, observed)
    key = snapshot_key(namespace, [project], window, True, include_work=True)
    record, _ = store.edit_work(project, namespace, key, kind, values, observed)
    print(f"已保存纠正 {record}。")
    return 0


def main(argv=None):
    args = parse_args(argv)
    try:
        with Store(args.db) as store:
            if args.action in {"review", "cached"}:
                return run_review(args, store)
            if args.action == "correct":
                return run_correction(args, store)
            if args.action == "revoke-ai":
                store.revoke_ai(args.project)
                print("已移除所选项目的本地 AI 缓存。")
            elif args.action == "clear":
                store.clear(None if args.all else args.project)
                print("已清除所选工作回顾缓存。")
            else:
                excluded = args.action == "exclude"
                store.set_excluded(args.project, excluded)
                print("已排除所选目录。" if excluded else "已解除目录排除。")
    except (Cancelled, KeyboardInterrupt):
        print("已取消工作回顾。", file=sys.stderr)
        return 130
    except (StoreError, CorrectionError) as error:
        print(str(error), file=sys.stderr)
        return 2
    except sqlite3.Error:
        print("无法读取或写入工作回顾数据库。请检查文件、权限或其他运行中的实例。", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
