"""The single-day outcomes view inside the Work Memory glass panel."""

from datetime import date, timedelta
from html import escape
import json
import os

from PySide6.QtCore import QDate, QSize, Qt, QThreadPool
from PySide6.QtWidgets import (QApplication, QComboBox, QDateEdit, QHBoxLayout, QPlainTextEdit,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from codex_links import open_codex_thread
from glass_dialog import GlassButton, GlassDialog, GlassTextInput
from pearl_style import palette, themed
from typography import font
from work_memory.codex_rpc import identifier
from work_memory.outcome_service import load_outcomes
from work_memory.outcomes import CATEGORIES, ORIGINS, REVIEW
from work_memory.review import COVERAGE, project_label
from work_memory.summary import ENDPOINT
from work_memory.time_range import local_time
from work_memory.work_items import GRADES
from work_memory_panel import ROLE, ReviewJob, label, list_style


def field_style():
    color = palette()
    return (f"color: {color.text}; background: {color.control}; border: 1px solid {color.line};"
            "border-radius: 7px; padding: 4px;")


def field(widget, name):
    widget.setFont(font("hint"))
    widget.setAccessibleName(name)
    themed(widget, field_style)
    return widget


class EditOutcome(GlassDialog):
    def __init__(self, host, row):
        super().__init__(host, "编辑成果", "修改标为人工填写，保留原始来源。", "保存修改")
        self.category = field(QComboBox(), "成果分类")
        for key, name in CATEGORIES.items():
            self.category.addItem(name, key)
        self.category.setCurrentIndex(self.category.findData(row["category"]))
        self.title = GlassTextInput(row["title"])
        self.title.setAccessibleName("成果标题")
        self.title.setMaxLength(100)
        self.summary = field(QPlainTextEdit(row["summary"]), "成果摘要")
        self.summary.setFixedHeight(65)
        self.follow = GlassTextInput(row["follow_up"])
        self.follow.setAccessibleName("下一步线索")
        self.follow.setMaxLength(160)
        for name, widget in (("分类", self.category), ("标题", self.title),
                             ("摘要（最多 600 字）", self.summary), ("下一步（可选）", self.follow)):
            self.content.addWidget(label(name, "hint", "muted"))
            self.content.addWidget(widget)
        self.title.textChanged.connect(self.validate)
        self.summary.textChanged.connect(self.validate)
        self.validate()

    def validate(self):
        summary = self.summary.toPlainText()
        self.primary.setEnabled(bool(self.title.text().strip() and summary.strip()) and len(summary) <= 600)

    def accept(self):
        if self.primary.isEnabled():
            super().accept()

    def values(self):
        return {"category": self.category.currentData(), "title": self.title.text(),
                "summary": self.summary.toPlainText(), "follow_up": self.follow.text()}


class OutcomePane(QWidget):
    def __init__(self, host, loader=load_outcomes):
        super().__init__(host)
        self.host = host
        self.loader = loader
        self.document = None
        self.job = None
        self.pending = None
        self.token = 0
        self.build()

    def build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(7)
        self.project = field(QComboBox(), "成果项目")
        self.project.setMinimumWidth(100)
        self.project.setPlaceholderText("选择项目")
        self.add = GlassButton("添加目录…")
        self.add.clicked.connect(self.host.pick_directory)
        layout.addLayout(self.row(self.project, self.add, stretch_first=True))
        self.range = field(QComboBox(), "成果日期范围")
        for key, title in (("today", "今天"), ("yesterday", "昨天"), ("date", "指定日期")):
            self.range.addItem(title, key)
        self.calendar = field(QDateEdit(QDate.currentDate()), "选择自然日")
        self.calendar.setCalendarPopup(True)
        self.calendar.setDisplayFormat("yyyy-MM-dd")
        self.calendar.setMaximumDate(QDate.currentDate())
        self.calendar.setEnabled(False)
        layout.addLayout(self.row(self.range, self.calendar, stretch_first=True))
        self.status = label("", "hint", "muted")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("成果状态")
        layout.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(13)
        self.tree.setFont(font("list_meta"))
        self.tree.setAccessibleName("成果和来源证据")
        self.tree.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tree.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.tree.itemSelectionChanged.connect(self.update_actions)
        themed(self.tree, list_style)
        layout.addWidget(self.tree, 1)
        self.empty = label("这里会显示基于 Codex 证据的成果草稿。", "hint", "muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)
        self.confirm = self.button("确认", lambda: self.review("confirmed"))
        self.edit = self.button("编辑…", self.edit_row)
        self.check = self.button("待核实", lambda: self.review("needs_check"))
        self.remove = self.button("移除", lambda: self.review("removed"))
        self.remove.setToolTip("仅移除该成果草稿。")
        self.review_bar = QWidget()
        self.review_bar.setLayout(self.row(self.confirm, self.edit, self.check, self.remove, equal=True))
        layout.addWidget(self.review_bar)
        self.open_source_button = self.button("打开 Codex", self.open_source)
        self.copy_source_button = self.button("复制来源", self.copy_source)
        self.source_bar = QWidget()
        self.source_bar.setLayout(self.row(self.open_source_button, self.copy_source_button, equal=True))
        layout.addWidget(self.source_bar)
        self.ai = self.button("AI 生成…", self.choose_model)
        self.generate = GlassButton("生成成果草稿", primary=True)
        self.generate.clicked.connect(self.generate_or_cancel)
        layout.addLayout(self.row(self.ai, self.generate, equal=True))
        self.project.currentIndexChanged.connect(self.change_view)
        self.range.currentIndexChanged.connect(self.choose_date)
        self.calendar.dateChanged.connect(self.change_view)
        self.render(None)

    @staticmethod
    def row(*widgets, stretch_first=False, equal=False):
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        for index, widget in enumerate(widgets):
            row.addWidget(widget, int(equal or (index == 0 and stretch_first)))
        return row

    @staticmethod
    def button(name, callback):
        button = GlassButton(name)
        button.clicked.connect(callback)
        return button

    def sync_scope(self):
        previous = self.project.currentData()
        self.project.blockSignals(True)
        self.project.clear()
        for path in self.host.projects:
            self.project.addItem(project_label(path), path)
            self.project.setItemData(self.project.count() - 1, path, Qt.ItemDataRole.ToolTipRole)
        selection = self.project.findData(previous) if previous else -1
        self.project.setCurrentIndex(0 if self.project.count() == 1 else selection)
        self.project.blockSignals(False)
        self.add.setEnabled(self.project.count() < 6)
        self.choose_date()

    def selected_day(self):
        if self.range.currentData() == "date":
            return self.calendar.date().toPython()
        return date.today() - timedelta(days=self.range.currentData() == "yesterday")

    def choose_date(self):
        self.calendar.blockSignals(True)
        self.calendar.setMaximumDate(QDate.currentDate())
        custom = self.range.currentData() == "date"
        self.calendar.setEnabled(custom)
        if not custom:
            self.calendar.setDate(QDate(self.selected_day()))
        self.calendar.blockSignals(False)
        self.change_view()

    def change_view(self, *_):
        self.cancel()
        self.render(None)
        if self.project.currentData() and self.host.isVisible() and self.host.showing_outcomes:
            self.request("load")

    def cancel(self):
        self.token += 1
        self.pending = None
        if self.job is not None:
            self.job.cancel.set()

    def request(self, action, payload=None):
        path = self.project.currentData()
        if path not in self.host.projects:
            return
        self.cancel()
        self.pending = action, payload, path, self.selected_day()
        self.status.setText({"load": "正在读取本机成果…", "generate": "正在整理本机成果草稿…",
                             "preview": "正在筛选模型输入…", "review": "正在保存审核进度…",
                             "ai": "正在等待模型草稿…"}[action])
        self.start()

    def start(self):
        if self.job is None and self.pending:
            action, payload, path, day = self.pending
            self.pending = None
            self.job = ReviewJob(self.token, self.loader, self.host.database, [path], day, action, payload)
            self.job.signals.done.connect(self.finish, Qt.ConnectionType.QueuedConnection)
            QThreadPool.globalInstance().start(self.job)
        self.update_actions()

    def finish(self, token, result, error):
        self.job = None
        if token == self.token and self.host.isVisible() and self.host.showing_outcomes:
            if error:
                self.status.setText(error)
                if "已变化" in error or "已改变" in error or "已被排除" in error or "其他窗口" in error:
                    self.render(None, error)
            elif result is not None:
                self.render(result.document, result.notice)
                if result.preview is not None:
                    self.approve(result.preview)
        self.start()

    def generate_or_cancel(self):
        if self.busy_action() in {"generate", "preview", "ai"}:
            self.cancel()
            self.render(self.document, "已取消本次生成。")
        elif not self.busy_action():
            self.request("generate")

    def busy_action(self):
        return self.pending[0] if self.pending else (self.job.action if self.job and self.token == self.job.token else "")

    def update_actions(self):
        running = self.busy_action()
        has_project = self.project.currentData() is not None
        self.generate.setEnabled(has_project and running not in {"load", "review"})
        self.generate.setText("取消" if running in {"generate", "preview", "ai"} else
                              "重新生成" if self.document else "生成成果草稿")
        self.ai.setEnabled(has_project and not running)
        row, evidence = self.selection()
        for button in (self.confirm, self.edit, self.check, self.remove):
            button.setEnabled(bool(row) and not running)
        if row:
            self.confirm.setEnabled(not running and row["review_state"] != "confirmed")
            self.check.setEnabled(not running and row["review_state"] != "needs_check")
        valid = bool(evidence and identifier(evidence["source"].get("thread_id")))
        self.review_bar.setVisible(bool(row) and evidence is None)
        self.source_bar.setVisible(bool(evidence))
        self.open_source_button.setEnabled(valid)
        self.copy_source_button.setEnabled(valid)

    def render(self, document, notice=""):
        selected, _ = self.selection()
        last_id = selected["id"] if selected else None
        expanded = {node.data(0, ROLE)["row"]["id"]
                    for i in range(self.tree.topLevelItemCount())
                    if (node := self.tree.topLevelItem(i)).isExpanded()}
        self.document = document
        self.tree.clear()
        rows = [row for row in document["rows"] if row["review_state"] != "removed"] if document else []
        order = {key: index for index, key in enumerate(CATEGORIES)}
        rows.sort(key=lambda row: order[row["category"]])
        for row in rows:
            node = self.add_outcome(row)
            if row["id"] in expanded:
                node.setExpanded(True)
            if row["id"] == last_id:
                self.tree.setCurrentItem(node)
        if rows and self.tree.currentItem() is None:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))
        self.tree.setVisible(bool(rows))
        self.empty.setVisible(not rows)
        if document:
            approved = sum(row["review_state"] == "confirmed" for row in rows)
            checking = sum(row["review_state"] == "needs_check" for row in rows)
            draft = len(rows) - approved - checking
            base = f"已保存 · {approved} 已审核 · {checking} 待核实 · {draft} 草稿待审核"
            if document["coverage"] not in {"complete", "empty"}:
                base += f"\n{COVERAGE[document['coverage']]}，本次可能遗漏部分成果。"
            self.empty.setText("当日没有可展示的成果。")
        else:
            base = "手动生成单日成果草稿。" if self.project.currentData() else "请选择一个已授权的项目。"
            self.empty.setText("草稿仅收录有工作事项和来源依据的候选成果。")
        self.status.setText(f"{base}\n{notice}" if notice else base)
        self.update_actions()

    def add_outcome(self, row):
        details = f"{CATEGORIES[row['category']]} · {ORIGINS[row['origin']]} · {REVIEW[row['review_state']]} · {len(row['refs'])} 来源"
        snippet = ("人工填写 · " if row["edited"] else "") + row["summary"]
        node = QTreeWidgetItem(self.tree, [f"{row['title']}\n{details}\n{snippet}"])
        node.setSizeHint(0, QSize(0, 68))
        node.setData(0, ROLE, {"row": row})
        node.setToolTip(0, escape(f"{row['title']}\n{details}\n{snippet}").replace("\n", "<br>"))
        lines = ["结论待核实" if row["review_state"] == "needs_check" else
                 f"{row['status']} · {GRADES[row['evidence_level']]}"]
        if row.get("source_changed"):
            lines.append("部分旧来源本次未找到，原审核内容已保留。")
        if row.get("model_issue"):
            lines.append("模型结果未通过来源或内容校验。")
        lines.append(snippet)
        if row["follow_up"]:
            lines.append("下一步 · " + row["follow_up"])
        for line in lines:
            child = QTreeWidgetItem(node)
            detail = label(line, "list_meta", "muted")
            detail.setWordWrap(True)
            width = max(125, min(416, self.host.width()) - 90)
            child.setSizeHint(0, QSize(0, max(29, detail.heightForWidth(width) + 5)))
            self.tree.setItemWidget(child, 0, detail)
        for ref in row["refs"]:
            when = local_time(ref["at_ms"])[5:16].replace("T", " ") if ref["at_ms"] is not None else "时间待确认"
            archived = " · 归档" if ref["source"]["archived"] else ""
            scope = f" · {ref['scope']}" if ref["scope"] else ""
            names = f" · {'、'.join(ref['file_names'])}" if ref.get("file_names") else ""
            child = QTreeWidgetItem(node, [f"{when} · {ref['label']} · {GRADES[ref['grade']]}{archived}"])
            child.setData(0, ROLE, {"evidence": ref})
            child.setToolTip(0, escape(f"{ref['label']} · {ref['source']['title']} · {GRADES[ref['grade']]}{scope}{names}"))
            if scope:
                QTreeWidgetItem(child, [f"适用范围{scope}"])
        return node

    def selection(self):
        node = self.tree.currentItem()
        if node is None:
            return None, None
        data = node.data(0, ROLE) or {}
        root = node
        while root.parent() is not None:
            root = root.parent()
        return root.data(0, ROLE)["row"], data.get("evidence")

    def review(self, action, values=None):
        row, _ = self.selection()
        if row and self.document and not self.busy_action():
            if self.document["day"] != self.selected_day().isoformat():
                self.choose_date()
                return
            self.request("review", (self.document["revision"], row["id"], action, values))

    def show_dialog(self, dialog, focus, on_accept):
        self.host.dialog = dialog

        def finished(result):
            self.host.release_dialog(dialog)
            if result and self.host.isVisible() and self.host.showing_outcomes:
                on_accept()

        dialog.finished.connect(finished)
        dialog.open_near_bottle(focus)

    def edit_row(self):
        row, _ = self.selection()
        if row and not self.host.dialog and not self.busy_action():
            dialog = EditOutcome(self.host, row)
            self.show_dialog(dialog, dialog.title, lambda: self.review("edit", dialog.values()))

    def choose_model(self):
        if self.host.dialog or self.busy_action():
            return
        dialog = GlassDialog(self.host, "选择草稿模型", "选择模型后可先预览输入。", "预览材料")
        model = GlassTextInput(os.environ.get("DYNAMIC_PEARL_OUTCOME_MODEL", ""))
        model.setAccessibleName("OpenAI 模型名称")
        model.setPlaceholderText("输入可用的 OpenAI 模型名称")
        model.setMaxLength(120)
        dialog.content.addWidget(model)
        dialog.primary.setEnabled(bool(model.text().strip()))
        model.textChanged.connect(lambda value: dialog.primary.setEnabled(bool(value.strip())))
        self.show_dialog(dialog, model, lambda: self.request("preview", model.text().strip()))

    def approve(self, preview):
        if self.host.dialog:
            return
        dialog = GlassDialog(self.host, "确认发送模型材料", "确认后将以下材料发送给 OpenAI。", "发送并生成")
        scope = label(f"{self.project.currentText()} · {preview.day}", "hint", "muted")
        scope.setWordWrap(True)
        dialog.content.addWidget(scope)
        destination = label(ENDPOINT, "hint", "muted")
        destination.setWordWrap(True)
        dialog.content.addWidget(destination)
        material = field(QPlainTextEdit(json.dumps(json.loads(preview.body), ensure_ascii=False, indent=2)), "实际请求内容")
        material.setReadOnly(True)
        material.setFixedHeight(150)
        dialog.content.addWidget(material)
        self.show_dialog(dialog, dialog.cancel_button, lambda: self.request("ai", preview))

    def open_source(self):
        _, evidence = self.selection()
        if evidence and open_codex_thread(evidence["source"]["thread_id"]):
            self.status.setText("已请求打开 Codex。可复制来源定位具体回合。")
        elif evidence:
            self.status.setText("无法打开 Codex。请复制来源后在桌面端定位。")

    def copy_source(self):
        _, evidence = self.selection()
        if evidence and identifier(evidence["source"].get("thread_id")):
            source = evidence["source"]
            fields = [source["title"], f"codex://threads/{source['thread_id']}", f"回合 {source['turn_id']}"]
            if source.get("item_id"):
                fields.append(f"条目 {source['item_id']}")
            if evidence["at_ms"] is not None:
                fields.append(local_time(evidence["at_ms"]))
            QApplication.clipboard().setText("\n".join(fields))
            self.status.setText("已复制来源定位。")
