"""Durable FIFO journal. Captures commit before callers are notified.

Control connections can coexist; only a connection holding the OS worker lock
may call a client. An interrupted call is uncertain until explicitly retried.
"""

import contextlib
import json
import os
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .prompt import (COMPACTION_PROMPT, DEVELOPER_PROMPT, run_message,
                     merge_context, summary_message, text_message)


class TranslationError(Exception):
    """An intentionally safe message, never copied from a remote response."""

    def __init__(self, code="request_failed", message=None):
        self.code = code
        super().__init__(message or {
            "context_overflow": "Context limit reached; discuss next steps before retrying.",
            "uncertain": "Interrupted request may have been charged; explicit retry required.",
            "worker_busy": "Another translation worker owns this journal.",
            "paused": "Translation is paused; explicit retry required.",
            "context_rebuild": "Context rebuild stopped; stop Luna and use rebuild-context --retry.",
        }.get(code, "Translation failed; explicit retry required."))


class _WorkerLock:
    def __init__(self, path):
        self.file = open(path, "a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise TranslationError("worker_busy") from None

    def close(self):
        if os.name == "nt":
            import msvcrt
            self.file.seek(0)
            msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.file.fileno(), fcntl.LOCK_UN)
        self.file.close()


class Journal:
    def __init__(self, path, prompt=DEVELOPER_PROMPT):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mutex = threading.RLock()
        self._processing = threading.Lock()
        self._worker = None
        self._closed = False
        self._db = sqlite3.connect(str(self.path), timeout=30, isolation_level=None,
                                   check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        try:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=FULL")
            with self._transaction():
                self._db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
                self._db.execute("""CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL,
                    run_id INTEGER NOT NULL, original TEXT, window_id TEXT,
                    translation TEXT, state TEXT NOT NULL, error_code TEXT,
                    metadata TEXT, created REAL NOT NULL, started REAL, completed REAL,
                    attempts INTEGER NOT NULL DEFAULT 0)""")
                self._db.execute("CREATE INDEX IF NOT EXISTS events_state ON events(kind, state, id)")
                self._db.execute("""CREATE TABLE IF NOT EXISTS summaries (
                    run_id INTEGER NOT NULL, through_id INTEGER NOT NULL,
                    text TEXT NOT NULL, metadata TEXT NOT NULL, created REAL NOT NULL,
                    PRIMARY KEY(run_id, through_id))""")
                self._db.execute("""CREATE TABLE IF NOT EXISTS context_checkpoints (
                    id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL,
                    through_id INTEGER NOT NULL, text TEXT NOT NULL,
                    metadata TEXT NOT NULL, created REAL NOT NULL,
                    format_version INTEGER NOT NULL,
                    UNIQUE(run_id,through_id,created))""")
                self._db.execute("""INSERT OR IGNORE INTO context_checkpoints
                    (run_id,through_id,text,metadata,created,format_version)
                    SELECT run_id,through_id,text,metadata,created,1 FROM summaries""")
                old = self._get_meta("prompt")
                if old is not None and old != prompt:
                    raise ValueError("Journal prompt is immutable; use its original prompt.")
                if old is None:
                    self._set_meta("prompt", prompt)
                    self._set_meta("cache_key", "grisaia-" + uuid.uuid4().hex)
                    self._set_meta("active_run", "1")
                    self._db.execute("INSERT INTO events(kind,run_id,original,state,created) VALUES('run',1,'Initial run','marker',?)", (time.time(),))
        except BaseException:
            self._db.close()
            self._closed = True
            raise
        self.prompt = prompt
        self.cache_key = self._get_meta("cache_key")

    @contextlib.contextmanager
    def _transaction(self):
        with self._mutex:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise

    def _get_meta(self, key):
        row = self._db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key, value):
        self._db.execute("INSERT OR REPLACE INTO meta(key,value) VALUES(?,?)", (key, value))

    def capture(self, text, window_id=None, deduplicate_all=False):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("A capture must contain text.")
        with self._transaction():
            run = int(self._get_meta("active_run"))
            if window_id is not None:
                if deduplicate_all:
                    previous = self._db.execute("SELECT id,run_id,window_id FROM events WHERE kind='capture' AND run_id=? AND window_id=? LIMIT 1",
                                                (run, str(window_id))).fetchone()
                else:
                    previous = self._db.execute("SELECT id,run_id,window_id FROM events WHERE kind='capture' ORDER BY id DESC LIMIT 1").fetchone()
                if previous and previous["run_id"] == run and previous["window_id"] == str(window_id):
                    return previous["id"]
            cursor = self._db.execute("""INSERT INTO events(kind,run_id,original,window_id,state,created)
                VALUES('capture',?,?,?,'pending',?)""",
                (run, text,
                 None if window_id is None else str(window_id), time.time()))
            return cursor.lastrowid

    def new_run(self, reason="Manual new run"):
        # The reason is journal metadata, not model instructions.
        if not isinstance(reason, str):
            raise ValueError("Run reason must be text.")
        with self._transaction():
            run = int(self._get_meta("active_run")) + 1
            self._set_meta("active_run", str(run))
            self._db.execute("INSERT INTO events(kind,run_id,original,state,created) VALUES('run',?,?,'marker',?)", (run, reason, time.time()))
            return run

    def entry(self, entry_id):
        with self._mutex:
            row = self._db.execute("SELECT * FROM events WHERE id=?", (entry_id,)).fetchone()
            if row is None:
                raise KeyError(entry_id)
            result = dict(row)
            result["metadata"] = json.loads(result["metadata"]) if result["metadata"] else {}
            return result

    def latest_capture(self):
        """Recover the last captured window, including a pending translation."""
        with self._mutex:
            row = self._db.execute("SELECT id FROM events WHERE kind='capture' ORDER BY id DESC LIMIT 1").fetchone()
            return self.entry(row["id"]) if row else None

    def status(self):
        with self._mutex:
            counts = {r[0]: r[1] for r in self._db.execute("SELECT state,count(*) FROM events WHERE kind='capture' GROUP BY state")}
            head = self._db.execute("SELECT id,state,error_code FROM events WHERE kind='capture' AND state!='completed' ORDER BY id LIMIT 1").fetchone()
            rebuild = self._get_meta("context_rebuild_state")
            return {"active_run": int(self._get_meta("active_run")),
                    "counts": counts, "head": dict(head) if head else None,
                    "paused": rebuild in ("inflight", "failed") or bool(head and head["state"] in ("failed", "uncertain", "inflight")),
                    "context_rebuild_state": rebuild,
                    "cache_key": self.cache_key}

    def messages_for(self, entry_id):
        with self._mutex:
            target = self.entry(entry_id)
            if target["kind"] != "capture":
                raise ValueError("Expected capture event.")
            rows = self._db.execute("SELECT * FROM events WHERE id<=? ORDER BY id", (entry_id,)).fetchall()
            messages = [text_message("developer", self.prompt, breakpoint=True)]
            summaries = {r["run_id"]: r for r in self._db.execute(
                "SELECT * FROM context_checkpoints WHERE through_id<? ORDER BY through_id,id", (entry_id,))}
            recent = {}
            for row in rows:
                summary = summaries.get(row["run_id"])
                if row["kind"] == "capture" and summary and row["id"] <= summary["through_id"]:
                    recent.setdefault(row["run_id"], []).append(row["id"])
            retained = {i for ids in recent.values() for i in ids[-20:]}
            if summaries:
                messages.append(text_message("developer", "Run-specific reference summaries "
                    "below represent preceding original/translation pairs and are permitted "
                    "translation context. Apply the same uncertainty and archived-run "
                    "restrictions to them. Translate only the final dialogue window."))
            for row in rows:
                if row["kind"] == "run":
                    messages.append(run_message(row["run_id"]))
                    summary = summaries.get(row["run_id"])
                    if summary:
                        messages.append(summary_message(row["run_id"], summary["text"]))
                else:
                    summary = summaries.get(row["run_id"])
                    if summary and row["id"] <= summary["through_id"] and row["id"] not in retained:
                        continue
                    if row["id"] != entry_id and row["state"] != "completed":
                        raise TranslationError("paused")
                    messages.append(text_message("user", row["original"]))
                    if row["id"] != entry_id:
                        messages.append(text_message("assistant", row["translation"]))
            return messages

    def _compact_for(self, entry_id, client):
        # The worker owns this operation; captures/control remain free during HTTP.
        interval = getattr(client, "compact_every", 0)
        if not interval:
            return
        with self._mutex:
            runs = [r[0] for r in self._db.execute("""SELECT e.run_id FROM events e
                WHERE e.kind='capture' AND e.id<? AND e.id>COALESCE(
                    (SELECT MAX(s.through_id) FROM context_checkpoints s
                     WHERE s.run_id=e.run_id AND s.format_version=2),0)
                GROUP BY e.run_id HAVING count(*)>=? ORDER BY e.run_id""", (entry_id, interval))]
        for run in runs:
            self._compact_run(run, entry_id, client, interval)

    def _compact_run(self, run, entry_id, client, interval, rebuild=False):
        with self._mutex:
            previous = None if rebuild else self._db.execute(
                "SELECT * FROM context_checkpoints WHERE run_id=? AND format_version=2 "
                "ORDER BY through_id DESC,id DESC LIMIT 1", (run,)).fetchone()
            after = previous["through_id"] if previous else 0
            rows = self._db.execute("""SELECT * FROM events WHERE kind='capture'
                AND run_id=? AND id>? AND id<? ORDER BY id""", (run, after, entry_id)).fetchall()
            count = len(rows) // interval * interval
            if not count:
                return
            rows = rows[:count]
            if any(r["state"] != "completed" for r in rows):
                raise TranslationError("paused")
            messages = [text_message("developer", COMPACTION_PROMPT), run_message(run)]
            if previous:
                messages.append(summary_message(run, previous["text"]))
            for row in rows:
                messages.extend((text_message("user", row["original"]),
                                 text_message("assistant", row["translation"])))
        result = client.compact(messages, self.cache_key)
        try:
            text = merge_context(json.loads(previous["text"]) if previous else {}, result.text)
        except (TypeError, ValueError):
            raise TranslationError("invalid_response") from None
        metadata = json.dumps({**result.metadata, "rebuild": rebuild,
                              "source_windows": count, "source_first_id": rows[0]["id"],
                              "previous_checkpoint_id": previous["id"] if previous else None},
                              ensure_ascii=False, separators=(",", ":"))
        checkpoint = {"run_id": run, "through_id": rows[-1]["id"], "source_windows": count,
                      "reference_subjects": len(json.loads(text)["reference"])}
        with self._transaction():
            self._db.execute("""INSERT INTO context_checkpoints
                (run_id,through_id,text,metadata,created,format_version) VALUES(?,?,?,?,?,2)""",
                (run, rows[-1]["id"], text, metadata, time.time()))
            if rebuild:
                self._set_meta("context_rebuild_state", "completed")
        return checkpoint

    def rebuild_context(self, client, retry=False):
        """Explicit paid rebuild from original pairs; never use old summaries."""
        with self._processing:
            self._acquire_worker()
            with self._transaction():
                status = self.status()
                state = self._get_meta("context_rebuild_state")
                if state in ("inflight", "failed") and not retry:
                    raise TranslationError("uncertain")
                if state in ("inflight", "failed"):
                    target = json.loads(self._get_meta("context_rebuild_target"))
                    run, end = target["run_id"], target["end"]
                else:
                    if status["head"]:
                        raise TranslationError("paused")
                    run = status["active_run"]
                    end = self._db.execute("SELECT max(id) FROM events").fetchone()[0] + 1
                    self._set_meta("context_rebuild_target", json.dumps({"run_id": run, "end": end}))
                self._set_meta("context_rebuild_state", "inflight")
            try:
                result = self._compact_run(run, end, client, 1, rebuild=True)
                if result is None:
                    with self._transaction():
                        self._set_meta("context_rebuild_state", "completed")
                return result
            except Exception as exc:
                with self._transaction():
                    self._set_meta("context_rebuild_state", "failed")
                allowed = {"context_overflow", "incomplete", "refusal", "empty_output",
                           "egress_failed", "configuration", "request_failed", "invalid_response"}
                code = exc.code if isinstance(exc, TranslationError) and exc.code in allowed else "request_failed"
                raise TranslationError(code) from None

    def retry(self):
        with self._transaction():
            head = self._db.execute("SELECT id,state FROM events WHERE kind='capture' AND state!='completed' ORDER BY id LIMIT 1").fetchone()
            if head is None or head["state"] not in ("failed", "uncertain"):
                return False
            self._db.execute("UPDATE events SET state='pending',error_code=NULL WHERE id=?", (head["id"],))
            return True

    def _acquire_worker(self):
        with self._mutex:
            if self._worker is None:
                self._worker = _WorkerLock(str(self.path) + ".worker.lock")
                with self._transaction():
                    self._db.execute("UPDATE events SET state='uncertain',error_code='uncertain' WHERE state='inflight'")

    def claim_worker(self):
        """Claim lifetime ownership and recover orphaned calls without HTTP.

        Use at adapter startup before checking pause state. Ordinary status,
        capture, new_run and retry control connections never need this call.
        """
        with self._processing:
            self._acquire_worker()
            return self.status()

    def process_one(self, client):
        # No database/mutex lock is held during HTTP: captures and CLI controls
        # must commit promptly even during a slow response.
        with self._processing:
            self._acquire_worker()
            with self._transaction():
                if self._get_meta("context_rebuild_state") in ("inflight", "failed"):
                    raise TranslationError("context_rebuild")
                head = self._db.execute("SELECT id,state,error_code FROM events WHERE kind='capture' AND state!='completed' ORDER BY id LIMIT 1").fetchone()
                if head is None:
                    return None
                if head["state"] != "pending":
                    raise TranslationError(head["error_code"] or "paused")
                entry_id = head["id"]
                self._db.execute("UPDATE events SET state='inflight',started=?,attempts=attempts+1 WHERE id=?", (time.time(), entry_id))
            try:
                self._compact_for(entry_id, client)
                messages = self.messages_for(entry_id)
                result = client.translate(messages, self.cache_key)
                if not isinstance(result.text, str) or not result.text.strip():
                    raise TranslationError("empty_output")
                metadata = json.dumps(result.metadata, ensure_ascii=False, separators=(",", ":"))
                with self._transaction():
                    self._db.execute("UPDATE events SET state='completed',translation=?,metadata=?,completed=?,error_code=NULL WHERE id=?", (result.text, metadata, time.time(), entry_id))
            except Exception as exc:
                # A foreign client may include headers, corpus or credentials in
                # its exception. Persist only our allowlisted symbolic codes.
                allowed = {"context_overflow", "incomplete", "refusal", "empty_output", "egress_failed", "configuration", "request_failed", "invalid_response"}
                code = exc.code if isinstance(exc, TranslationError) and exc.code in allowed else "request_failed"
                with self._transaction():
                    self._db.execute("UPDATE events SET state='failed',error_code=? WHERE id=?", (code, entry_id))
                raise TranslationError(code) from None
            return self.entry(entry_id)

    def close(self):
        with self._processing, self._mutex:
            if not self._closed:
                self._db.close()
                if self._worker:
                    self._worker.close()
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
