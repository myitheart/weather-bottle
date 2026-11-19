"""Project work items and evidence from a snapshot and its local corrections."""

from collections import defaultdict
from hashlib import sha256
from itertools import combinations
import json
from uuid import uuid4

from .codex_rpc import path_key
from .work_signals import MILESTONES, OUTCOMES


GRADES = {"Verified": "已核实记录", "UserConfirmed": "用户确认", "Reported": "会话报告",
          "Inferred": "推测", "Unknown": "待核实"}


class CorrectionError(Exception):
    pass


def stable_id(prefix, *parts):
    encoded = json.dumps(parts, ensure_ascii=True, separators=(",", ":")).encode()
    return f"{prefix}-{sha256(encoded).hexdigest()[:24]}"


def evidence(anchor, kind, label, instant, source, grade, *, milestone=None, outcome=None, scope=None):
    return {"id": stable_id("ev", anchor, kind, source.get("item_id"), source.get("correction_id"), milestone, outcome, label),
            "kind": kind, "label": label, "at_ms": instant, "source": source, "grade": grade,
            "milestone": milestone, "outcome": outcome, "scope": scope}


def signals_for(turn, ref, anchor, window):
    keys = defaultdict(list)
    observed = []
    for signal in turn.get("signals", []):
        source = {**ref, "item_id": signal["id"]}
        if turn.get("signals_complete"):
            for key in signal.get("keys", []):
                keys[key].append(source)
        at = signal["end"] if signal["end"] is not None else signal["start"]
        if at is not None and not window.contains(at):
            continue
        for milestone, outcome in signal.get("claims", []):
            observed.append(evidence(anchor, "claim", f"{MILESTONES[milestone]} · {OUTCOMES[outcome]}", at,
                                     source, "Reported", milestone=milestone, outcome=outcome))
        for milestone, label in signal.get("hints", []):
            observed.append(evidence(anchor, "follow_up", label, at, source, "Reported", milestone=milestone, outcome="pending"))
        if signal.get("changed_files"):
            observed.append(evidence(anchor, "file_change", f"补丁记录涉及 {signal['changed_files']} 个文件",
                                     signal["end"], source, "Verified"))
            if signal.get("file_names"):
                observed[-1]["file_names"] = signal["file_names"]
        if signal.get("intent") and at is not None:
            observed.append(evidence(anchor, "outcome_intent", signal["intent"], at, source, "Reported"))
        if (result := signal.get("test_result")) and window.contains(signal["end"]):
            label = (f"{result['runner']} 记录 {result['passed']} 项通过" if result["passed"] else
                     f"已执行 {result['runner']}，通过结果待核实")
            observed.append(evidence(anchor, "outcome_test", label, signal["end"], source, "Verified",
                                     outcome="success" if result["passed"] else None))
    return dict(keys), observed


def build_inputs(project, activity, undated, namespace, window, locator):
    by_turn = defaultdict(list)
    for row in activity + undated:
        ref = row["source"]
        by_turn[(ref["thread_id"], ref["turn_id"])].append(row)
    fragments = []
    path = path_key(project.path)
    for turn in project.turns:
        thread_id, turn_id = turn["thread_id"], turn["id"]
        ref = locator(project.sessions[thread_id], turn_id)
        anchor = stable_id("round", namespace, path, thread_id, turn_id)
        keys, observed = signals_for(turn, ref, anchor, window)
        for row in by_turn[(thread_id, turn_id)]:
            grade = "Unknown" if row["at_ms"] is None else "Verified"
            observed.append(evidence(anchor, row["kind"], row["label"], row["at_ms"], row["source"], grade))
        if observed:
            item_id = stable_id("item", namespace, path, *keys) if len(keys) == 1 else stable_id("item", anchor)
            fragments.append({"id": anchor, "default_item": item_id, "source": ref, "keys": keys, "evidence": observed})
    return fragments


def milestone_view(records):
    statuses = {}
    for milestone in MILESTONES:
        scoped = defaultdict(list)
        claims = []
        for record in records:
            if record["milestone"] != milestone:
                continue
            if record["grade"] == "UserConfirmed":
                scoped[record["scope"]].append(record)
            elif record["kind"] == "claim":
                claims.append(record)
        entries = []
        for scope, confirmations in sorted(scoped.items()):
            latest = max(record["at_ms"] for record in confirmations)
            entries.append(state_row([record for record in confirmations if record["at_ms"] == latest], "UserConfirmed", scope))
        if claims:
            entries.append(state_row(claims, "Reported", None))
        statuses[milestone] = entries or [{"grade": "Unknown", "outcome": "unknown", "scope": None, "evidence_ids": []}]
    return statuses


def state_row(records, grade, scope):
    outcomes = {record["outcome"] for record in records}
    return {"grade": grade, "scope": scope, "outcome": next(iter(outcomes)) if len(outcomes) == 1 else "conflict",
            "evidence_ids": [record["id"] for record in records]}


def project_items(fragments, corrections):
    assignments, titles, confirmations = {}, {}, defaultdict(list)
    merges = []
    split_pairs = set()
    for correction in corrections:
        payload = correction["payload"]
        if correction["kind"] in {"merge", "split"}:
            for anchor in payload["anchors"]:
                assignments[anchor] = payload["target"]
            if payload.get("title"):
                titles[payload["target"]] = payload["title"]
            if correction["kind"] == "split":
                split_pairs.add(frozenset((payload["target"], payload["original"])))
            else:
                merges.append(payload)
        elif correction["kind"] == "confirm":
            confirmations[payload["anchor"]].append(correction)

    groups = defaultdict(list)
    for fragment in fragments:
        groups[assignments.get(fragment["id"], fragment["default_item"])].append(fragment)
    redirects = defaultdict(set)
    for merge in merges:
        if merge["original"] in groups:
            continue
        targets = {assignments[anchor] for anchor in merge["from_anchors"]}
        if len(targets) == 1:
            redirects[targets.pop()].add(merge["original"])
    items = []
    for item_id, group in groups.items():
        keys = defaultdict(list)
        records = []
        for fragment in group:
            for key, links in fragment["keys"].items():
                keys[key].extend(links)
            records.extend(fragment["evidence"])
            for confirmation in confirmations[fragment["id"]]:
                payload = confirmation["payload"]
                source = {**fragment["source"], "source": "local_user", "correction_id": confirmation["id"]}
                label = f"{MILESTONES[payload['milestone']]} · {OUTCOMES[payload['outcome']]}"
                records.append(evidence(fragment["id"], "confirmation", label, confirmation["created"], source,
                                        "UserConfirmed", milestone=payload["milestone"], outcome=payload["outcome"], scope=payload["scope"]))
        records = sorted({record["id"]: record for record in records}.values(),
                         key=lambda row: (row["at_ms"] is not None, row["at_ms"] or 0, row["id"]), reverse=True)
        manual = any(fragment["id"] in assignments for fragment in group)
        title = titles.get(item_id) or (next(iter(keys)) if len(keys) == 1 else group[0]["source"]["title"])
        items.append({"id": item_id, "title": title, "keys": dict(keys), "aliases": sorted(redirects[item_id]),
                      "grouping": "manual" if manual else "explicit_key" if len(keys) == 1 else "ambiguous" if keys else "isolated",
                      "anchors": [{"id": fragment["id"], "source": fragment["source"]} for fragment in group],
                      "evidence": records, "milestones": milestone_view(records),
                      "follow_up": [row["id"] for row in records if row["kind"] == "follow_up"]})
    items.sort(key=lambda item: (-(item["evidence"][0]["at_ms"] or 0), item["id"]))
    return items, weak_suggestions(items, split_pairs)


def weak_suggestions(items, split_pairs):
    titles = defaultdict(list)
    for item in items:
        for title in {anchor["source"]["title"].casefold() for anchor in item["anchors"]}:
            if len(title) >= 6 and not title.startswith("聊天 "):
                if len(titles[title]) < 24:
                    titles[title].append(item)
    suggested = {}
    for items_with_title in titles.values():
        for left, right in combinations(items_with_title, 2):
            if left["keys"] and right["keys"]:
                continue
            pair = frozenset((left["id"], right["id"]))
            if pair in split_pairs or pair in suggested:
                continue
            threads = {anchor["source"]["thread_id"] for item in (left, right) for anchor in item["anchors"]}
            if len(threads) > 1:
                suggested[pair] = {"items": sorted(pair), "grade": "Inferred", "reason": "聊天标题相同，待人工核对"}
                if len(suggested) == 12:
                    return list(suggested.values())
    return list(suggested.values())


def apply_work_view(report, corrections):
    for project in report["projects"]:
        fragments = project.pop("work_inputs", None)
        if fragments is not None:
            project["work_items"], project["merge_suggestions"] = project_items(fragments, corrections.get(path_key(project["path"]), []))


def correction_payload(kind, values, fragments, corrections):
    items, _ = project_items(fragments, corrections)
    lookup = {item["id"]: item for item in items}
    if kind == "confirm":
        if values["anchor"] not in {fragment["id"] for fragment in fragments}:
            raise CorrectionError("该回合锚点不在当前缓存的项目与日期范围内。")
        return values
    target = lookup.get(values["item"])
    if target is None:
        raise CorrectionError("该事项不在当前缓存的项目与日期范围内。")
    anchors = {anchor["id"] for anchor in target["anchors"]}
    if kind == "merge":
        source = lookup.get(values["from"])
        if source is None or source is target:
            raise CorrectionError("请选择当前项目与日期范围内两个不同的事项。")
        source_anchors = {anchor["id"] for anchor in source["anchors"]}
        return {"anchors": sorted(anchors | source_anchors), "from_anchors": sorted(source_anchors),
                "target": target["id"], "original": source["id"], "title": target["title"]}
    selected = set(values["anchors"])
    if not selected or not selected < anchors:
        raise CorrectionError("拆分回合必须是当前事项的一部分，并至少留下一个回合。")
    return {"anchors": sorted(selected), "target": f"item-{uuid4().hex[:24]}",
            "original": target["id"], "title": values["title"]}
