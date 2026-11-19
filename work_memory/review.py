"""Build a calendar review from recorded events and their source references."""

from collections import Counter
from pathlib import Path

from .source_codex import SOURCES, clean_label
from .time_range import PERIODS, local_time
from .work_items import GRADES, build_inputs
from .work_signals import MILESTONES, OUTCOMES as MILESTONE_OUTCOMES


OUTCOMES = {"completed": "回合结束", "failed": "回合失败", "interrupted": "回合中断",
            "inProgress": "回合结束（记录状态待核实）", "unknown": "回合结束（结果未知）"}
COVERAGE = {"complete": "已读完本次查询范围", "empty": "本次查询无活动", "partial": "部分读取",
            "unavailable": "来源不可用"}


def project_label(path):
    return clean_label(Path(path).name) or "工作目录"


def locator(session, turn_id, item_id=None):
    return {"thread_id": session["id"], "turn_id": turn_id, "item_id": item_id,
            "open_url": f"codex://threads/{session['id']}", "source": session["source"],
            "archived": session["archived"], "title": session["title"] or f"聊天 {session['id'][:8]}"}


def event(kind, instant, source, label, *, exit_code=None):
    return {"kind": kind, "at_ms": instant, "local_time": local_time(instant) if instant is not None else None,
            "label": label, "exit_code": exit_code, "source": source}


def project_events(project, window):
    events = []
    undated = []
    for turn in project.turns:
        ref = locator(project.sessions[turn["thread_id"]], turn["id"])
        if window.contains(turn["start"]):
            events.append(event("turn_started", turn["start"], ref, "回合开始"))
        if window.contains(turn["end"]):
            events.append(event("turn_ended", turn["end"], ref, OUTCOMES[turn["status"]]))
        if turn["start"] is None and turn["end"] is None:
            label = "回合时间顺序异常" if turn.get("time_issue") else "回合时间缺失"
            undated.append(event("turn_undated", None, ref, label))
    for command in project.commands:
        ref = locator(project.sessions[command["thread_id"]], command["turn_id"], command["id"])
        if window.contains(command["end"]):
            code = command["exit_code"]
            text = "命令结束 · 退出码未知" if code is None else f"命令结束 · 退出码 {code}"
            events.append(event("command_ended", command["end"], ref, text, exit_code=code))
        elif window.contains(command["start"]):
            events.append(event("command_started", command["start"], ref, "命令开始"))
        if command["start"] is None and command["end"] is None:
            label = "命令时间顺序异常" if command.get("time_issue") else "命令时间缺失"
            undated.append(event("command_undated", None, ref, label))
    events.sort(key=lambda entry: (-entry["at_ms"], entry["source"]["thread_id"], entry["source"]["turn_id"], entry["kind"]))
    return events, undated


def build_report(history, window, *, include_commands=False, include_work=False, excluded=()):
    projects = []
    for project in history.projects:
        events, undated = project_events(project, window)
        fragments = build_inputs(project, events, undated, history.namespace, window, locator) if include_work else []
        unresolved = any(not reason.endswith(":duplicate_rows") for reason in project.issues)
        if not any(scan["pages"] for scan in project.listings.values()):
            status = "unavailable"
        elif not project.finished or unresolved:
            status = "partial"
        else:
            status = "complete" if events or undated or fragments else "empty"
        view = {"project": project_label(project.path), "path": project.path, "status": status,
                "listings": project.listings, "issues": dict(project.issues),
                "chats_examined": project.chats_examined, "counts": dict(Counter(row["kind"] for row in events)),
                "events": events, "undated": undated}
        if include_work:
            view["work_inputs"] = fragments
        projects.append(view)
    statuses = {project["status"] for project in projects}
    if statuses == {"unavailable"}:
        status = "unavailable"
    elif history.error or statuses & {"partial", "unavailable"}:
        status = "partial"
    else:
        status = "empty" if statuses == {"empty"} else "complete"
    return {"schema_version": 1, "mode": "live", "status": status, "source_error": history.error,
            "window": {"period": window.period, "start_ms": window.start, "end_ms": window.cutoff,
                       "generated_at": local_time(window.as_of), "zone": window.zone,
                       "local_start": local_time(window.start), "local_end": local_time(window.cutoff)},
            "sources": list(SOURCES), "commands": include_commands, "archive_coverage_validated": False,
            "excluded_projects": [project_label(path) for path in excluded], "projects": projects}


def render_work(lines, project):
    if not project["work_items"]:
        lines.append("  当前范围没有可展示的事项。")
    for item in project["work_items"]:
        grouping = {"manual": "用户已纠正", "explicit_key": "同一显式事项标识", "ambiguous": "多个标识，保留独立",
                    "isolated": "独立回合"}[item["grouping"]]
        lines.append(f"  {item['title']} · {grouping} · {item['id']}")
        for anchor in item["anchors"]:
            lines.append(f"    {anchor['id']} · {anchor['source']['open_url']} · 回合 {anchor['source']['turn_id']}")
        relevant = [(kind, result) for kind, entries in item["milestones"].items() for result in entries if result["grade"] != "Unknown"]
        if not relevant:
            lines.append("    业务里程碑待核实")
        for kind, result in relevant:
            scope = f" · {result['scope']}" if result["scope"] else " · 范围未核实"
            lines.append(f"    {MILESTONES[kind]} · {MILESTONE_OUTCOMES[result['outcome']]} · {GRADES[result['grade']]}{scope}")
        general = [row for row in item["evidence"] if row["kind"] != "follow_up"]
        hints = [row for row in item["evidence"] if row["kind"] == "follow_up"]
        for row in hints[:2] + general[:6]:
            date = local_time(row["at_ms"])[:19].replace("T", " ") if row["at_ms"] is not None else "时间待确认"
            line = "下一步线索 · " if row["kind"] == "follow_up" else ""
            lines.append(f"    {date} · {line}{row['label']} · {GRADES[row['grade']]}")
        remaining = max(0, len(general) - 6) + max(0, len(hints) - 2)
        if remaining:
            lines.append(f"    另有 {remaining} 条证据，可用 --format json 查看。")
    for candidate in project["merge_suggestions"]:
        lines.append(f"  归并候选 {' + '.join(candidate['items'])} · {candidate['reason']}")


def render_ai(lines, project):
    state = project.get("ai")
    if not state:
        return
    if state["status"] == "offline":
        descriptions = {"preview_only": "仅预览", "not_authorized": "未授权", "no_supported_evidence": "没有可选证据",
                        "missing_credentials": "模型凭据不可用", "rate_limited": "请求受限", "request_budget": "达到请求预算",
                        "incomplete_history": "历史读取不完整", "refusal": "模型拒绝返回结果",
                        "incomplete_response": "模型响应不完整", "invalid_selection": "返回的证据引用无效"}
        reason = descriptions.get(state["reason"], state["reason"])
        lines.append(f"  AI 增强已跳过 · {reason}。以上为本机规则回顾。")
        return
    mode = "缓存" if state["status"] == "cached" else "已生成"
    lines.append(f"  AI 证据选读 · {mode} · 纳入 {state['selected_items']} 项，省略 {state['omitted_items']} 项")
    usage = state.get("usage", {})
    if usage:
        counts = [f"{label} {usage[key]}" for key, label in (("input_tokens", "输入"), ("output_tokens", "输出")) if key in usage]
        lines.append(f"    Token 用量 · {'，'.join(counts)}")
    items = {item["id"]: item for item in project["work_items"]}
    for key in ("summary_lines", "follow_up_hints"):
        for choice in state[key]:
            item = items[choice["item_id"]]
            fact = next(record for record in item["evidence"] if record["id"] == choice["evidence_id"])
            ref = fact["source"]
            prefix = "续接线索 · " if key == "follow_up_hints" else ""
            lines.append(f"    {prefix}{item['title']} · {choice['label']} · {GRADES[choice['grade']]} · {ref['open_url']} · 回合 {ref['turn_id']}")
    for choice in state["merge_suggestions"]:
        lines.append(f"    优先核对 {' + '.join(choice['items'])} · {choice['reason']}")


def render_text(report):
    window = report["window"]
    mode = "缓存 · 生成于" if report["mode"] == "cached" else "生成于"
    lines = [f"工作回顾 · {PERIODS[window['period']]} · {COVERAGE[report['status']]}",
             f"{window['local_start']} 至 {window['local_end']}（不含上界）",
             f"{mode} {window['generated_at']} · 来源 {' / '.join(report['sources'])} · 精确工作目录",
             "归档覆盖仍待实测。" if not report["commands"] else "归档覆盖仍待实测。命令退出码仅表示进程结果。"]
    if report["excluded_projects"]:
        lines.append("已排除 " + "、".join(report["excluded_projects"]))
    if report["source_error"]:
        lines.append(f"来源错误 {report['source_error']}")
    if report.get("cache") == "unchanged":
        lines.append("本次未更新缓存。")
    for project in report["projects"]:
        lines.extend(("", f"{project['project']} · {COVERAGE[project['status']]} · 已读 {project['chats_examined']} 个聊天"))
        if project["issues"]:
            lines.append("  读取详情 " + "、".join(f"{issue} × {count}" for issue, count in sorted(project["issues"].items())))
        if "work_items" in project:
            render_work(lines, project)
            render_ai(lines, project)
            continue
        if not project["events"]:
            lines.append("  当前结果没有可归入区间的事件。")
        for row in project["events"] + project["undated"]:
            ref = row["source"]
            when = row["local_time"][:19].replace("T", " ") if row["local_time"] else "时间待确认"
            archived = " · 归档" if ref["archived"] else ""
            lines.append(f"  {when}  {row['label']}  {ref['title']} [{ref['source']}{archived}]")
            lines.append(f"    {ref['open_url']}  回合 {ref['turn_id']}")
    return "\n".join(lines)
