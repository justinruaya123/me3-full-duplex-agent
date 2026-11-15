"""Opt-in local text memory: bounded SQLite, explicit facts, no model writer.

Owner labels come from the trusted console/enrollment, never a spoken name.
Historical text is retrieval data, not authorization or current job truth.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from functools import wraps
from pathlib import Path


_STOP_WORDS = set(
    "a an and are about did do for from have how i in is it me my of on or "
    "our that the this to we what with you your remember recall "
    "discuss".split()
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\w+", text.casefold())) - _STOP_WORDS


def _bounded(data: dict, limit: int) -> str:
    """Keep valid JSON and complete entries within the prompt budget."""
    result = {key: [] for key in data}
    for key, entries in data.items():
        for entry in entries:
            result[key].append(entry)
            if len(json.dumps(result, ensure_ascii=True)) > limit:
                result[key].pop()
                break
    return json.dumps(result, ensure_ascii=True)


class MemoryStorageError(RuntimeError):
    """Storage failures must not become provider errors or silent fallback."""


def _storage_errors(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except sqlite3.Error as exc:
            raise MemoryStorageError(
                "Local memory storage is unavailable"
            ) from exc

    return guarded


class MemoryStore:
    """One host runtime owns this private store under its supervisor lock.

    Per-owner defaults: 64 notes, 32 sessions, 256 text messages.
    No audio, embeddings, inference, or automatic personality extraction.
    """

    def __init__(
        self, path: Path, *, max_notes=64, max_messages=256, max_sessions=32
    ) -> None:
        if min(max_notes, max_messages, max_sessions) < 1:
            raise ValueError("Memory retention limits must be positive")
        self.max_notes = max_notes
        self.max_messages, self.max_sessions = max_messages, max_sessions
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(
            path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        try:
            self._initialize()
        except Exception:
            self.db.close()
            raise

    def _initialize(self) -> None:
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS memory_owners (
                owner TEXT PRIMARY KEY, enabled INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS memory_notes (
                owner TEXT NOT NULL, key TEXT NOT NULL, kind TEXT NOT NULL,
                content TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY(owner, key));
            CREATE TABLE IF NOT EXISTS memory_sessions (
                owner TEXT NOT NULL, session TEXT NOT NULL,
                started REAL NOT NULL, ended REAL,
                PRIMARY KEY(owner, session));
            CREATE TABLE IF NOT EXISTS memory_messages (
                id INTEGER PRIMARY KEY, owner TEXT NOT NULL,
                session TEXT NOT NULL, role TEXT NOT NULL,
                content TEXT NOT NULL, truncated INTEGER NOT NULL,
                created REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS memory_owner_messages
                ON memory_messages(owner, id);
        """)

    def enabled(self, owner: str) -> bool:
        row = self.db.execute(
            "SELECT enabled FROM memory_owners WHERE owner=?", (owner,)
        ).fetchone()
        return row is None or bool(row["enabled"])

    def set_enabled(self, owner: str, enabled: bool) -> None:
        with self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO memory_owners VALUES (?,?)",
                (owner, int(enabled)),
            )

    def remember(self, owner: str, key: str, kind: str, content: str) -> str:
        key, content = key.strip().casefold(), content.strip()
        if (
            not owner or not re.fullmatch(r"[\w][\w .-]{0,63}", key)
            or kind not in {"fact", "project"}
            or not 1 <= len(content) <= 1000
        ):
            raise ValueError(
                "Use a key of 1-64 and a value of 1-1000 characters"
            )
        if not self.enabled(owner):
            raise ValueError("Memory is paused; use /memory on first")
        exists = self.db.execute(
            "SELECT content FROM memory_notes WHERE owner=? AND key=?",
            (owner, key),
        ).fetchone()
        count = self.db.execute(
            "SELECT COUNT(*) FROM memory_notes WHERE owner=?", (owner,)
        ).fetchone()[0]
        if not exists and count >= self.max_notes:
            raise ValueError("Saved note limit reached; forget a note first")
        with self.db:
            if exists and exists["content"] != content:
                self._purge_literal(owner, exists["content"])
            self.db.execute(
                "INSERT OR REPLACE INTO memory_notes VALUES (?,?,?,?,?)",
                (owner, key, kind, content, time.time()),
            )
        return key

    def record(
        self, owner: str, session: str, role: str, content: str
    ) -> None:
        if not self.enabled(owner):
            return
        if not owner or not session or role not in {"user", "assistant"}:
            raise ValueError("Memory requires an owner, session and text role")
        now = time.time()
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO memory_sessions VALUES (?,?,?,NULL)",
                (owner, session, now),
            )
            self.db.execute(
                "INSERT INTO memory_messages "
                "(owner,session,role,content,truncated,created) "
                "VALUES (?,?,?,?,?,?)",
                (
                    owner, session, role, content[:4000],
                    len(content) > 4000, now,
                ),
            )
            self.db.execute(
                "DELETE FROM memory_sessions WHERE owner=? AND session NOT IN "
                "(SELECT session FROM memory_sessions WHERE owner=? "
                "ORDER BY started DESC LIMIT ?)",
                (owner, owner, self.max_sessions),
            )
            self.db.execute(
                "DELETE FROM memory_messages WHERE owner=? AND "
                "(id NOT IN (SELECT id FROM memory_messages WHERE owner=? "
                "ORDER BY id DESC LIMIT ?) OR session NOT IN "
                "(SELECT session FROM memory_sessions WHERE owner=?))",
                (owner, owner, self.max_messages, owner),
            )

    def end_session(self, owner: str, session: str) -> None:
        with self.db:
            self.db.execute(
                "UPDATE memory_sessions SET ended=? "
                "WHERE owner=? AND session=?",
                (time.time(), owner, session),
            )

    def recall(self, owner: str, query: str) -> dict:
        terms = _tokens(query)
        notes = [dict(row) for row in self.db.execute(
            "SELECT key,kind,content,updated FROM memory_notes "
            "WHERE owner=? ORDER BY updated DESC", (owner,)
        )]
        messages = [dict(row) for row in self.db.execute(
            "SELECT id,session,role,content,truncated,created "
            "FROM memory_messages WHERE owner=? ORDER BY id DESC LIMIT ?",
            (owner, self.max_messages),
        )]
        notes.sort(
            key=lambda n: len(terms & _tokens(n["key"] + " " + n["content"])),
            reverse=True,
        )
        messages.sort(
            key=lambda m: len(terms & _tokens(m["content"])), reverse=True
        )
        sessions = [dict(row) for row in self.db.execute(
            "SELECT session,started,ended FROM memory_sessions WHERE owner=? "
            "ORDER BY started DESC LIMIT ?", (owner, self.max_sessions)
        )]
        return {"notes": notes, "messages": messages, "sessions": sessions}

    @_storage_errors
    def context(self, owner: str, query: str, *, worker=False) -> str:
        if not self.enabled(owner):
            return ""
        data = self.recall(owner, query)
        notes = data["notes"][:8]
        if worker:
            terms = _tokens(query)
            notes = [n for n in notes if terms & _tokens(
                n["key"] + " " + n["content"]
            )]
            return _bounded({"notes": notes}, 2500) if notes else ""
        messages = sorted(data["messages"][:12], key=lambda m: m["id"])
        return _bounded({
            "notes": notes, "messages": messages,
            "sessions": data["sessions"][:4],
        }, 7500)

    def forget(self, owner: str, key: str) -> bool:
        key = key.strip().casefold()
        row = self.db.execute(
            "SELECT content FROM memory_notes WHERE owner=? AND key=?",
            (owner, key),
        ).fetchone()
        if row is None:
            return False
        with self.db:
            self._purge_literal(owner, row["content"])
            self.db.execute(
                "DELETE FROM memory_notes WHERE owner=? AND key=?",
                (owner, key),
            )
        return True

    def _purge_literal(self, owner: str, content: str) -> None:
        # Purge literal repetitions; semantic paraphrases need /memory clear.
        ids = [row["id"] for row in self.db.execute(
            "SELECT id,content FROM memory_messages WHERE owner=?", (owner,)
        ) if content.casefold() in row["content"].casefold()]
        self.db.executemany(
            "DELETE FROM memory_messages WHERE owner=? AND id=?",
            [(owner, message_id) for message_id in ids],
        )

    def clear(self, owner: str) -> None:
        with self.db:
            for table in ("notes", "messages", "sessions"):
                self.db.execute(
                    f"DELETE FROM memory_{table} WHERE owner=?", (owner,)
                )
            self.db.execute(
                "INSERT OR REPLACE INTO memory_owners VALUES (?,0)", (owner,)
            )

    def close(self) -> None:
        self.db.close()


def is_memory_command(text: str) -> bool:
    return bool(re.match(
        r"^(?:/(?:memory|remember|project|forget|recall)\b|remember that\b|"
        r"remember project\b|forget memory\b|recall\b|"
        r"turn memory (?:on|off)\b|"
        r"forget all memories\b|what do you remember[ .?!]*$|"
        r"what do you remember about me[ .?!]*$)", text, re.I,
    ))


class SessionMemory:
    """Lazy binding permits enrollment but never a mid-session owner switch."""

    def __init__(self, store, jobs, authorized, changed) -> None:
        self.store, self.jobs = store, jobs
        self.authorized, self.changed = authorized, changed
        self.owner = None

    def _owner(self) -> str:
        owner = self.jobs.owner
        if (
            not owner or not self.authorized()
            or (self.owner is not None and self.owner != owner)
        ):
            raise PermissionError("Memory requires the current verified owner")
        self.owner = owner
        return owner

    @_storage_errors
    def record(self, role: str, text: str) -> None:
        owner = self._owner()
        self.store.record(owner, self.jobs.session_id, role, text)

    def context(self, query: str) -> str:
        return self.store.context(self._owner(), query)

    @_storage_errors
    def close(self) -> None:
        if self.owner:
            self.store.end_session(self.owner, self.jobs.session_id)

    @_storage_errors
    def command(self, text: str) -> str | None:
        """Only explicit owner commands write facts; models never call this."""
        lower = text.casefold().strip(" .?!")
        action = None
        if lower in {
            "/memory", "what do you remember", "what do you remember about me"
        }:
            action = "list"
        elif lower in {"/memory on", "turn memory on"}:
            action = "on"
        elif lower in {"/memory off", "turn memory off"}:
            action = "off"
        elif lower in {"/memory clear", "forget all memories"}:
            action = "clear"
        remember = re.fullmatch(
            r"/(remember|project)\s+([^=]+)\s*=\s*(.+)", text, re.I | re.S
        )
        natural = re.fullmatch(r"remember that\s+(.+)", text, re.I | re.S)
        project = re.fullmatch(
            r"remember project\s+([^:]+):\s*(.+)", text, re.I | re.S
        )
        forget = re.fullmatch(r"(?:/forget|forget memory)\s+(.+)", text, re.I)
        recall = re.fullmatch(r"(?:/recall|recall)\s+(.+)", text, re.I | re.S)
        if not (action or remember or natural or project or forget or recall):
            return (
                "Use /remember KEY = VALUE, /project NAME = DETAILS, "
                "/forget KEY, or /memory."
            )
        owner = self._owner()
        if action in {"on", "off"}:
            self.store.set_enabled(owner, action == "on")
            self.changed(owner)
            return (
                "Memory is on." if action == "on" else
                "Memory is paused; saved data remains."
            )
        if action == "clear":
            self.store.clear(owner)
            self.changed(owner)
            return (
                "Your saved notes and conversations were cleared. "
                "Memory is paused. Job records remain."
            )
        if forget:
            removed = self.store.forget(owner, forget.group(1))
            self.changed(owner)
            return (
                "That note was forgotten." if removed else
                "No saved note has that key."
            )
        if remember or natural or project:
            if natural:
                key = "fact-" + uuid.uuid4().hex[:8]
                kind, value = "fact", natural.group(1)
            elif project:
                key, kind = project.group(1), "project"
                value = project.group(2)
            else:
                key, value = remember.group(2), remember.group(3)
                kind = (
                    "project" if remember.group(1).lower() == "project"
                    else "fact"
                )
            key = self.store.remember(owner, key, kind, value)
            self.changed(owner)
            return "Saved memory " + key + "."
        if not self.store.enabled(owner):
            return "Memory is paused. Use /memory on to retrieve or retain it."
        data = self.store.recall(owner, recall.group(1) if recall else "")
        if recall:
            return (
                "Saved history (not current task status): "
                + _bounded(data, 3000)
            )
        notes = data["notes"]
        if not notes:
            return (
                "No saved notes. Committed conversations are retained "
                "while memory is on."
            )
        return "Saved notes: " + "; ".join(
            n["key"] + ": " + n["content"] for n in notes
        )[:3000]
