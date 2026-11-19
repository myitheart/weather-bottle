"""SQLite snapshots and normalized activity owned by the Work Memory prototype."""

from contextlib import contextmanager
import hashlib
import json
import sqlite3

from .codex_rpc import Cancelled, path_key
from .work_items import correction_payload


APP_ID = 0x4450574D
SCHEMA_VERSION = 4
SCHEMA = (
    "CREATE TABLE settings (generation INTEGER NOT NULL)",
    "INSERT INTO settings VALUES (0)",
    "CREATE TABLE projects (path TEXT PRIMARY KEY, excluded INTEGER NOT NULL DEFAULT 0)",
    """CREATE TABLE sessions (
        project TEXT NOT NULL REFERENCES projects(path) ON DELETE CASCADE,
        namespace TEXT NOT NULL, id TEXT NOT NULL, title TEXT NOT NULL, source TEXT NOT NULL,
        archived INTEGER NOT NULL, created INTEGER, updated INTEGER, observed INTEGER NOT NULL,
        PRIMARY KEY (project, namespace, id)
    )""",
    """CREATE TABLE turns (
        project TEXT NOT NULL, namespace TEXT NOT NULL, thread_id TEXT NOT NULL, id TEXT NOT NULL,
        status TEXT NOT NULL, start INTEGER, end INTEGER, observed INTEGER NOT NULL,
        PRIMARY KEY (project, namespace, thread_id, id),
        FOREIGN KEY (project, namespace, thread_id) REFERENCES sessions(project, namespace, id) ON DELETE CASCADE
    )""",
    """CREATE TABLE commands (
        project TEXT NOT NULL, namespace TEXT NOT NULL, thread_id TEXT NOT NULL, turn_id TEXT NOT NULL, id TEXT NOT NULL,
        start INTEGER, end INTEGER, exit_code INTEGER, observed INTEGER NOT NULL,
        PRIMARY KEY (project, namespace, thread_id, turn_id, id),
        FOREIGN KEY (project, namespace, thread_id, turn_id) REFERENCES turns(project, namespace, thread_id, id)
            ON DELETE CASCADE
    )""",
    "CREATE TABLE snapshots (key TEXT PRIMARY KEY, observed INTEGER NOT NULL, body TEXT NOT NULL)",
    """CREATE TABLE snapshot_projects (
        snapshot TEXT NOT NULL REFERENCES snapshots(key) ON DELETE CASCADE,
        project TEXT NOT NULL REFERENCES projects(path) ON DELETE CASCADE,
        PRIMARY KEY (snapshot, project)
    )""",
    "CREATE INDEX snapshots_by_project ON snapshot_projects(project)",
)
WORK_SCHEMA = (
    """CREATE TABLE work_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project TEXT NOT NULL REFERENCES projects(path) ON DELETE CASCADE,
        namespace TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, created INTEGER NOT NULL,
        undone INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX corrections_by_project ON work_corrections(project, namespace, id)",
)
AI_SCHEMA = (
    """CREATE TABLE ai_summaries (
        key TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES projects(path) ON DELETE CASCADE,
        body TEXT NOT NULL
    )""",
    "CREATE INDEX ai_summaries_by_project ON ai_summaries(project)",
)
OUTCOME_SCHEMA = (
    """CREATE TABLE outcome_days (
        project TEXT NOT NULL REFERENCES projects(path) ON DELETE CASCADE, namespace TEXT NOT NULL,
        day TEXT NOT NULL, revision INTEGER NOT NULL, body TEXT NOT NULL,
        PRIMARY KEY(project, namespace, day)
    )""",
)


class StoreError(Exception):
    pass


def snapshot_key(namespace, paths, window, include_commands, *, include_work=False):
    identity = [namespace, sorted(path_key(path) for path in paths), window.period, window.start, window.end,
                window.zone, include_commands]
    if include_work:
        identity.append("work-items")
    return hashlib.sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()


class Store:
    def __init__(self, filename=None):
        self.db = sqlite3.connect(filename if filename is not None else ":memory:", timeout=3)
        try:
            self.db.execute("PRAGMA foreign_keys = ON")
            self.db.execute("PRAGMA secure_delete = ON")
            with self.transaction(write=True):
                self.initialize()
        except BaseException:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.db.close()

    @contextmanager
    def transaction(self, *, write=False):
        with self.db:
            self.db.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield

    def initialize(self):
        app_id = self.db.execute("PRAGMA application_id").fetchone()[0]
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if app_id == APP_ID and version == SCHEMA_VERSION:
            return
        if app_id == APP_ID and version == 1:
            schema = WORK_SCHEMA + AI_SCHEMA + OUTCOME_SCHEMA
        elif app_id == APP_ID and version == 2:
            schema = AI_SCHEMA + OUTCOME_SCHEMA
        elif app_id == APP_ID and version == 3:
            schema = OUTCOME_SCHEMA
        elif app_id == 0 and version == 0 and not self.db.execute("SELECT 1 FROM sqlite_schema LIMIT 1").fetchone():
            schema = SCHEMA + WORK_SCHEMA + AI_SCHEMA + OUTCOME_SCHEMA
        else:
            raise StoreError("所选文件不是当前版本的工作回顾数据库。")
        for sql in schema:
            self.db.execute(sql)
        self.db.execute(f"PRAGMA application_id = {APP_ID}")
        self.db.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def generation(self):
        return self.db.execute("SELECT generation FROM settings").fetchone()[0]

    def check_generation(self, expected):
        if self.generation() != expected:
            raise StoreError("本次读取期间项目范围或缓存已改变，请重新生成。")

    def selection(self, paths):
        with self.transaction():
            blocked = {row[0] for row in self.db.execute("SELECT path FROM projects WHERE excluded = 1")}
            allowed = [path for path in paths if path_key(path) not in blocked]
            excluded = [path for path in paths if path_key(path) in blocked]
            return allowed, excluded, self.generation()

    def set_excluded(self, paths, excluded):
        with self.transaction(write=True):
            self.db.executemany("""INSERT INTO projects VALUES (?, ?) ON CONFLICT(path)
                                    DO UPDATE SET excluded = excluded.excluded""",
                                [(path_key(path), excluded) for path in paths])
            if excluded:
                self.delete_ai(paths)
            self.db.execute("UPDATE settings SET generation = generation + 1")

    def clear(self, paths=None):
        with self.transaction(write=True):
            if paths is None:
                self.db.execute("DELETE FROM snapshots")
                self.db.execute("DELETE FROM sessions")
                self.db.execute("DELETE FROM work_corrections")
                self.db.execute("DELETE FROM outcome_days")
                self.db.execute("DELETE FROM ai_summaries")
                self.db.execute("DELETE FROM projects WHERE excluded = 0")
            else:
                keys = [(path_key(path),) for path in paths]
                self.db.executemany("DELETE FROM snapshots WHERE key IN (SELECT snapshot FROM snapshot_projects WHERE project = ?)", keys)
                self.db.executemany("DELETE FROM sessions WHERE project = ?", keys)
                self.db.executemany("DELETE FROM work_corrections WHERE project = ?", keys)
                self.db.executemany("DELETE FROM outcome_days WHERE project = ?", keys)
                self.delete_ai(paths)
                self.db.executemany("DELETE FROM projects WHERE path = ? AND excluded = 0", keys)
            self.db.execute("UPDATE settings SET generation = generation + 1")

    def cached(self, key, generation):
        with self.transaction():
            self.check_generation(generation)
            row = self.db.execute("SELECT body FROM snapshots WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def outcome_day(self, path, namespace, day, generation):
        with self.transaction():
            self.check_generation(generation)
            project = path_key(path)
            self.check_outcome_project(project)
            row = self.db.execute("SELECT revision, body FROM outcome_days WHERE project=? AND namespace=? AND day=?",
                                  (project, namespace, day)).fetchone()
            return dict(json.loads(row[1]), revision=row[0]) if row else None

    def check_outcome_project(self, project):
        if self.db.execute("SELECT 1 FROM projects WHERE path=? AND excluded=1", (project,)).fetchone():
            raise StoreError("此项目已被排除，成果不可见。")

    def save_outcome_day(self, path, namespace, day, data, expected_revision, generation, *, cancel=None):
        project = path_key(path)
        with self.transaction(write=True):
            self.check_generation(generation)
            self.check_outcome_project(project)
            key = (project, namespace, day)
            row = self.db.execute("SELECT revision FROM outcome_days WHERE project=? AND namespace=? AND day=?", key).fetchone()
            revision = row[0] if row else 0
            if revision != expected_revision:
                raise StoreError("成果已在其他窗口修改，请重新打开后再保存。")
            self.db.execute("INSERT OR IGNORE INTO projects(path) VALUES (?)", (project,))
            self.db.execute("""INSERT INTO outcome_days VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project, namespace, day) DO UPDATE SET revision=excluded.revision, body=excluded.body""",
                (*key, revision + 1, json.dumps({k: v for k, v in data.items() if k != "revision"}, ensure_ascii=False)))
            if cancel is not None and cancel.is_set():
                raise Cancelled("cancelled")
        return dict(data, revision=revision + 1)

    def delete_ai(self, paths):
        self.db.executemany("DELETE FROM ai_summaries WHERE project = ?", [(path_key(path),) for path in paths])

    def revoke_ai(self, paths):
        with self.transaction(write=True):
            self.delete_ai(paths)
            self.db.execute("UPDATE settings SET generation = generation + 1")

    def ai_cached(self, key, generation):
        with self.transaction():
            self.check_generation(generation)
            row = self.db.execute("SELECT body FROM ai_summaries WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_ai(self, path, key, selection, generation):
        project = path_key(path)
        with self.transaction(write=True):
            self.check_generation(generation)
            self.db.execute("INSERT OR IGNORE INTO projects(path) VALUES (?)", (project,))
            self.db.execute("INSERT OR IGNORE INTO ai_summaries VALUES (?, ?, ?)",
                            (key, project, json.dumps(selection, ensure_ascii=True)))

    def read_corrections(self, project, namespace, *, include_undone=False):
        rows = self.db.execute("""SELECT id, kind, payload, created, undone FROM work_corrections
                                  WHERE project = ? AND namespace = ? AND (? OR undone = 0) ORDER BY id""",
                               (project, namespace, include_undone))
        return [{"id": row[0], "kind": row[1], "payload": json.loads(row[2]), "created": row[3], "undone": bool(row[4])}
                for row in rows]

    def work_corrections(self, paths, namespace, generation):
        with self.transaction():
            self.check_generation(generation)
            return {path_key(path): self.read_corrections(path_key(path), namespace) for path in paths}

    def check_work_project(self, project):
        row = self.db.execute("SELECT excluded FROM projects WHERE path = ?", (project,)).fetchone()
        if row is None or row[0]:
            raise StoreError("该项目没有工作回顾记录，或已被排除。")

    def edit_work(self, path, namespace, key, kind, values, observed):
        project = path_key(path)
        with self.transaction(write=True):
            self.check_work_project(project)
            row = self.db.execute("SELECT body FROM snapshots WHERE key = ?", (key,)).fetchone()
            if row is None:
                raise StoreError("请先按当前日期范围为该项目生成并保存单项目事项回顾。")
            snapshot = json.loads(row[0])
            fragments = next((view.get("work_inputs", []) for view in snapshot["projects"]
                              if path_key(view["path"]) == project), [])
            payload = correction_payload(kind, values, fragments, self.read_corrections(project, namespace))
            result = self.db.execute("INSERT INTO work_corrections(project, namespace, kind, payload, created) VALUES (?, ?, ?, ?, ?)",
                                     (project, namespace, kind, json.dumps(payload, ensure_ascii=False), observed))
            self.db.execute("UPDATE settings SET generation = generation + 1")
            return result.lastrowid, payload

    def undo_work(self, path, namespace):
        project = path_key(path)
        with self.transaction(write=True):
            self.check_work_project(project)
            row = self.db.execute("""SELECT id FROM work_corrections WHERE project = ? AND namespace = ? AND undone = 0
                                     ORDER BY id DESC LIMIT 1""", (project, namespace)).fetchone()
            if row is None:
                raise StoreError("没有可撤销的事项纠正。")
            self.db.execute("UPDATE work_corrections SET undone = 1 WHERE id = ?", row)
            self.db.execute("UPDATE settings SET generation = generation + 1")
            return row[0]

    def work_history(self, path, namespace):
        with self.transaction():
            project = path_key(path)
            self.check_work_project(project)
            return self.read_corrections(project, namespace, include_undone=True)

    def save(self, key, history, window, report, generation, *, cancel=None):
        with self.transaction(write=True):
            self.check_generation(generation)
            row = self.db.execute("SELECT observed FROM snapshots WHERE key = ?", (key,)).fetchone()
            if row and row[0] > window.as_of:
                return False
            for project in history.projects:
                self.save_project(project, history.namespace, window.as_of)
            self.db.execute("""INSERT INTO snapshots VALUES (?, ?, ?) ON CONFLICT(key)
                               DO UPDATE SET observed = excluded.observed, body = excluded.body""",
                            (key, window.as_of, json.dumps(report, ensure_ascii=False)))
            self.db.executemany("INSERT OR IGNORE INTO snapshot_projects VALUES (?, ?)",
                                [(key, path_key(project.path)) for project in history.projects])
            if cancel is not None and cancel.is_set():
                raise Cancelled("cancelled")
        return True

    def save_project(self, project, namespace, observed):
        path = path_key(project.path)
        self.db.execute("INSERT OR IGNORE INTO projects(path) VALUES (?)", (path,))
        relevant_sessions = {turn["thread_id"] for turn in project.turns}
        self.db.executemany("""INSERT INTO sessions VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project, namespace, id) DO UPDATE SET title = excluded.title, source = excluded.source,
                archived = excluded.archived, created = excluded.created, updated = excluded.updated, observed = excluded.observed
            WHERE excluded.observed >= sessions.observed""",
            [(path, namespace, row["id"], row["title"], row["source"], row["archived"], row["created"], row["updated"], observed)
             for row in project.sessions.values() if row["id"] in relevant_sessions])
        self.db.executemany("""INSERT INTO turns VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project, namespace, thread_id, id) DO UPDATE SET status = excluded.status,
                start = excluded.start, end = excluded.end, observed = excluded.observed
            WHERE excluded.observed >= turns.observed""",
            [(path, namespace, row["thread_id"], row["id"], row["status"], row["start"], row["end"], observed)
             for row in project.turns])
        self.db.executemany("""INSERT INTO commands VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project, namespace, thread_id, turn_id, id) DO UPDATE SET start = excluded.start,
                end = excluded.end, exit_code = excluded.exit_code, observed = excluded.observed
            WHERE excluded.observed >= commands.observed""",
            [(path, namespace, row["thread_id"], row["turn_id"], row["id"], row["start"], row["end"], row["exit_code"], observed)
             for row in project.commands])
