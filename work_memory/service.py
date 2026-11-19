"""Shared local review service for the CLI and the desktop panel."""

from dataclasses import dataclass
from time import time_ns

from .codex_rpc import Cancelled
from .review import build_report, project_label
from .source_codex import Limits, collect, source_namespace
from .store import StoreError, snapshot_key
from .time_range import Window, make_window
from .work_items import apply_work_view


@dataclass(frozen=True)
class ReviewResult:
    report: dict | None
    key: str
    namespace: str
    generation: int
    window: Window


def read_review(store, projects, period, *, cached=False, save=False, include_commands=False, include_outcomes=False,
                include_work=False, limits=Limits(), as_of=None, selected_day=None, cancel=None, collector=collect):
    paths, excluded, generation = store.selection(projects)
    if not paths:
        raise StoreError("选定项目均已排除。")
    window = make_window(period, time_ns() // 1_000_000 if as_of is None else as_of, selected_day=selected_day)
    commands = include_commands or include_work
    if cached:
        namespace = source_namespace()
        key = snapshot_key(namespace, paths, window, commands, include_work=include_work)
        report = store.cached(key, generation)
        if report is None:
            return ReviewResult(None, key, namespace, generation, window)
        report.update(mode="cached", cache="hit", excluded_projects=[project_label(path) for path in excluded])
    else:
        options = {"include_commands": commands, "include_work": include_work, "limits": limits}
        if include_outcomes:
            options["include_outcomes"] = True
        if cancel is not None:
            options["cancel"] = cancel
        history = collector(paths, window, **options)
        if cancel is not None and cancel.is_set():
            raise Cancelled("cancelled")
        namespace = history.namespace
        key = snapshot_key(namespace, paths, window, commands, include_work=include_work)
        store.check_generation(generation)
        report = build_report(history, window, include_commands=commands, include_work=include_work, excluded=excluded)
        if save:
            report["cache"] = "unchanged"
            if report["status"] in {"complete", "empty"}:
                report["cache"] = "saved"
                if not store.save(key, history, window, report, generation, cancel=cancel):
                    report["cache"] = "unchanged"
    if include_work:
        apply_work_view(report, store.work_corrections(paths, namespace, generation))
    store.check_generation(generation)
    return ReviewResult(report, key, namespace, generation, window)
