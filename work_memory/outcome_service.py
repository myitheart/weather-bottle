"""Generate, review, and reopen one authorized project/day at a time."""

from dataclasses import dataclass
from datetime import date
import os
from pathlib import Path
from time import time_ns

from . import outcome_ai, summary
from .codex_rpc import Cancelled, path_key
from .outcomes import merge_generation, protected, review_row, rule_rows
from .service import read_review
from .source_codex import collect, source_namespace
from .store import Store, StoreError
from .time_range import make_window


@dataclass(frozen=True)
class Preview:
    project: str
    day: str
    namespace: str
    generation: int
    revision: int
    body: bytes
    mapping: dict


@dataclass(frozen=True)
class OutcomeResult:
    document: dict | None
    notice: str = ""
    preview: Preview | None = None


def guard(cancel):
    if cancel is not None and cancel.is_set():
        raise Cancelled("cancelled")


def generate(store, path, day, window, current, generation, model, cancel, collector):
    result = read_review(store, [path], "today", as_of=window.as_of, selected_day=date.fromisoformat(day),
                         include_work=True, include_outcomes=True, cancel=cancel, collector=collector)
    store.check_generation(generation)
    report = result.report
    namespace = source_namespace()
    if report["status"] == "unavailable" or report.get("source_error") or result.namespace != namespace:
        return OutcomeResult(current, "本机 Codex 历史暂不可用。可继续查看和审核已保存的成果。")
    project, = report["projects"]
    rows = rule_rows(project, path, namespace, window)
    complete = project["status"] in {"complete", "empty"}
    merged = merge_generation(current["rows"] if current else [], rows, complete=complete)
    document = {"day": day, "rows": merged, "coverage": project["status"], "observed": window.as_of}
    saved = store.save_outcome_day(path, namespace, day, document, current["revision"] if current else 0,
                                   generation, cancel=cancel)
    if not model:
        return OutcomeResult(saved)
    if not complete:
        return OutcomeResult(saved, "本次历史覆盖不完整，已保存本机规则草稿。")
    fresh = {row["id"] for row in rows}
    eligible = [row for row in merged if row["id"] in fresh and not protected(row)]
    try:
        body, mapping = outcome_ai.prepare(eligible, model)
    except summary.ModelError:
        return OutcomeResult(saved, "模型名称无效，已保存本机规则草稿。")
    if not mapping:
        return OutcomeResult(saved, "当前没有可供模型整理的新草稿。")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        return OutcomeResult(saved, "未配置 OpenAI API 凭据，已保存本机规则草稿。")
    return OutcomeResult(saved, preview=Preview(path_key(path), day, namespace, generation, saved["revision"], body, mapping))


def enhance(store, path, day, namespace, generation, current, preview, cancel, model_request):
    if (not isinstance(preview, Preview) or not current or
            (preview.project, preview.day, preview.namespace, preview.generation, preview.revision) !=
            (path_key(path), day, namespace, generation, current["revision"])):
        raise StoreError("项目、日期或草稿已变化，请重新预览发送内容。")
    credentials = os.environ.get("OPENAI_API_KEY", "").strip()
    if not credentials:
        return OutcomeResult(current, "未配置 OpenAI API 凭据。")
    guard(cancel)
    store.check_generation(generation)
    try:
        value, _ = model_request(preview.body, credentials)
        guard(cancel)
        rows, accepted, rejected = outcome_ai.apply(value, current["rows"], preview.mapping)
    except summary.ModelError:
        guard(cancel)
        latest = store.outcome_day(path, namespace, day, generation)
        if latest is None or latest["revision"] != current["revision"]:
            raise StoreError("草稿已变化，请重新打开后继续审核。") from None
        return OutcomeResult(latest, "模型未返回可用成果，继续使用已保存的规则草稿。")
    document = dict(current, rows=rows)
    saved = store.save_outcome_day(path, namespace, day, document, current["revision"], generation, cancel=cancel)
    notice = f"已生成 {accepted} 条 AI 草稿。"
    if rejected:
        notice += f" 已拦截 {rejected} 条无效模型结果，请核对对应草稿。"
    return OutcomeResult(saved, notice)


def load_outcomes(database, paths, selected_day, action, cancel, payload, *, collector=collect,
                  model_request=summary.openai_request):
    if (len(paths) != 1 or not isinstance(paths[0], str) or not Path(paths[0]).is_absolute() or
            type(selected_day) is not date):
        raise StoreError("请选择一个已授权的项目和日期。")
    path = paths[0]
    try:
        window = make_window("today", time_ns() // 1_000_000, selected_day=selected_day)
    except ValueError as error:
        raise StoreError(str(error)) from None
    day = selected_day.isoformat()
    guard(cancel)
    if action == "load" and not database.is_file():
        return OutcomeResult(None)
    if action in {"generate", "preview"}:
        database.parent.mkdir(parents=True, exist_ok=True)
    with Store(database) as store:
        _, _, generation = store.selection(paths)
        namespace = source_namespace()
        current = store.outcome_day(path, namespace, day, generation)
        if action == "load":
            return OutcomeResult(current)
        if action in {"generate", "preview"}:
            return generate(store, path, day, window, current, generation,
                            payload if action == "preview" else None, cancel, collector)
        if action == "ai":
            return enhance(store, path, day, namespace, generation, current, payload, cancel, model_request)
        if action != "review" or not current or payload[0] != current["revision"]:
            raise StoreError("草稿已变化，请重新打开后再审核。")
        try:
            review_row(current["rows"], *payload[1:])
        except ValueError as error:
            raise StoreError(str(error)) from None
        saved = store.save_outcome_day(path, namespace, day, current, current["revision"], generation, cancel=cancel)
        return OutcomeResult(saved, "审核进度已保存。")
