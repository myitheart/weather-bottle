"""Single-day outcome candidates, with evidence and document-review state kept separate."""

from collections import Counter
from copy import deepcopy
from datetime import datetime

from .codex_rpc import identifier, path_key
from .outcome_signals import CATEGORIES, actionable_topic, classify
from .source_codex import clean_label
from .work_items import stable_id


REVIEW = {"draft": "草稿待审核", "confirmed": "已审核", "needs_check": "待核实", "removed": "已移除"}
ORIGINS = {"rule": "规则草稿", "ai": "AI 草稿"}
MATERIAL = {"file_change", "claim", "confirmation", "outcome_intent", "outcome_test", "follow_up"}
REF_ORDER = {key: index for index, key in enumerate(("outcome_test", "confirmation", "follow_up",
                                                     "file_change", "claim", "outcome_intent"))}


def day_key(window):
    return datetime.fromtimestamp(window.start / 1000).date().isoformat()


def allowed_refs(item, window):
    anchors = {(a["source"]["thread_id"], a["source"]["turn_id"]) for a in item["anchors"]}
    dated = {(e["source"]["thread_id"], e["source"]["turn_id"]) for e in item["evidence"] if window.contains(e["at_ms"])}
    for evidence in item["evidence"]:
        source = evidence["source"]
        anchor = source.get("thread_id"), source.get("turn_id")
        if anchor not in anchors or not all(identifier(piece) for piece in anchor):
            continue
        if window.contains(evidence["at_ms"]) or (evidence["kind"] == "confirmation" and anchor in dated):
            yield evidence


def describe(item, refs):
    intents = [r["label"] for r in refs if r["kind"] == "outcome_intent"]
    names = [*intents, item["title"], *(a["source"]["title"] for a in item["anchors"])]
    task = next((name for name in names if actionable_topic(name)), "")
    kind = classify(task) if task else None
    patches = [r for r in refs if r["kind"] == "file_change" and r["grade"] == "Verified"]
    passed = [r for r in refs if r["kind"] == "outcome_test" and r["outcome"] == "success" and r["grade"] == "Verified"]
    ran = any(r["kind"] == "outcome_test" for r in refs)
    claims = [r for r in refs if r["kind"] in {"claim", "confirmation"}]
    hints = [r["label"] for r in refs if r["kind"] == "follow_up"]
    if not any(r["kind"] in MATERIAL for r in refs):
        return None

    details = []
    files = Counter(name for patch in patches for name in patch.get("file_names", ()))
    primary = {name: count for name, count in files.items()
               if not name.casefold().startswith(("test_", "spec_")) and not name.casefold().endswith((".md", ".rst"))}
    ranked = Counter(primary or files).most_common(2)
    main_files = "、".join(name for name, _ in ranked)
    if patches:
        details.append(f"记录到 {len(patches)} 条补丁变更。")
    if passed:
        details.append(passed[0]["label"] + "。")
    elif ran:
        details.append("已记录测试执行，是否通过待核实。")
    if patches:
        details.append("业务结果待核实。")
        if main_files:
            details.append(f"涉及 {main_files}。")
    if claims:
        details.append("另有会话报告或人工确认，请按来源和适用范围核对。")
    if any(state["outcome"] == "conflict" for states in item["milestones"].values() for state in states):
        details.append("状态记录存在冲突。")
    if not details:
        details.append("有工作意图或后续线索，实际成果待核实。")

    if patches:
        category = kind if kind in {"feature", "fix", "engineering"} else "engineering"
        grade = "Verified"
    elif passed or ran:
        category, grade = "validation", "Verified"
    else:
        category, grade = "pending", "Reported"
    if not task:
        task = {"engineering": f"调整 {main_files}" if main_files else "代码变更",
                "validation": "本地测试记录", "pending": "待核实的工作进展"}[category]
    status = "变更已记录" if patches else "该次测试有通过记录" if passed else "待核实"
    return category, clean_label(task)[:100], "".join(details), status, grade, next(iter(hints), ""), kind is not None


def rule_rows(project, path, namespace, window):
    if path_key(project["path"]) != path_key(path):
        raise ValueError("项目来源不匹配。")
    rows = []
    for item in project["work_items"]:
        refs = list(allowed_refs(item, window))
        decision = describe(item, refs)
        if decision is None:
            continue
        category, title, summary, status, grade, follow_up, named_topic = decision
        refs.sort(key=lambda ref: REF_ORDER.get(ref["kind"], len(REF_ORDER)))
        rows.append({"id": stable_id("outcome", namespace, path_key(path), day_key(window), item["id"]),
                     "work_item": item["id"], "category": category, "title": title, "summary": summary,
                     "status": status, "evidence_level": grade, "refs": refs[:20], "follow_up": follow_up,
                     "origin": "rule", "review_state": "draft", "edited": False, "named_topic": named_topic})
    return rows


def source_anchors(row):
    return {(r["source"]["thread_id"], r["source"]["turn_id"]) for r in row["refs"]}


def protected(row):
    return row["edited"] or row["review_state"] != "draft"


def merge_generation(previous, generated, *, complete):
    if not previous:
        return generated
    saved = [deepcopy(row) for row in previous if protected(row) or not complete]
    latest = {row["id"]: row for row in generated}
    for row in saved:
        if row["id"] in latest and not protected(row):
            row.update(latest[row["id"]])
        current = next((candidate for candidate in generated if candidate["id"] == row["id"] or
                        source_anchors(candidate) & source_anchors(row)), None)
        if complete and protected(row):
            visible_refs = {ref["id"] for ref in current["refs"]} if current else set()
            row["source_changed"] = any(ref["id"] not in visible_refs for ref in row["refs"])
    reserved = {anchor for row in saved if protected(row) for anchor in source_anchors(row)}
    known = {row["id"] for row in saved}
    return saved + [row for row in generated if row["id"] not in known and not reserved.intersection(source_anchors(row))]


def review_row(rows, row_id, action, values=None):
    row = next((row for row in rows if row["id"] == row_id and row["review_state"] != "removed"), None)
    if row is None:
        raise ValueError("这条成果已变化，请重新打开。")
    if action == "edit":
        title = clean_label(values.get("title"))[:100]
        raw_summary = values.get("summary")
        summary = clean_label(raw_summary, limit=600)
        if not title or not summary or len(raw_summary) > 600 or values.get("category") not in CATEGORIES:
            raise ValueError("请填写标题、分类和 600 字以内的摘要。")
        row.update(title=title, summary=summary, category=values["category"],
                   follow_up=clean_label(values.get("follow_up")), edited=True, review_state="draft")
    elif action in {"confirmed", "needs_check", "removed"}:
        row["review_state"] = action
    else:
        raise ValueError("无效审核操作。")
