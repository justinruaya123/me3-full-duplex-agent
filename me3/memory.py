"""Local text memory: bounded SQLite, explicit facts, no model writer.

Owner labels come from the trusted console/enrollment, never a spoken name.
Historical text is retrieval data, not authorization or current job truth.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from functools import wraps
from itertools import zip_longest
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


class MemoryAuthorizationError(PermissionError):
    """This session lacks current authority over this owner."""


def _storage_errors(operation):
    @wraps(operation)
    def guarded(*args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except MemoryAuthorizationError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise MemoryStorageError("Local memory storage is unavailable") from exc

    return guarded


_SECTIONS = {
    "public": "Public-approved bio",
    "private": "Private preferences",
    "vocabulary": "Project vocabulary",
}
_SCOPE = r"(?:project|task)/[\w-]{1,64}"
_KEY = r"[\w][\w .-]{0,63}"


class ScopeAmbiguity(ValueError):
    pass


def _scopes(text):
    return set(re.findall(r"(?<![\w/])" + _SCOPE + r"(?![\w/-])", text.casefold()))


def personal_site(prompt):
    return prompt.startswith("ME3_WEBSITE_REQUEST\n") and bool(
        re.search(
            r"\b(?:about me|myself|my (?:own |personal )?(?:bio|portfolio|website|site|profile|résumé|resume)|"
            r"personal (?:site|website|bio|portfolio))\b",
            prompt,
            re.I,
        )
    )


# Personal requests stay on the client. Only these presentation options and
# the approved public fields can enter a website worker's brief.
_DESIGN_TERMS = frozenset(
    """
blue red green purple yellow orange violet teal gray grey white black pink
gold silver dark light warm cool minimalist minimal bold simple clean elegant
modern classic responsive mobile desktop grid cards centered serif sans compact
bio gallery projects contact darker lighter
""".split()
)
_SITE_WORDS = frozenset(
    """
a an the me my myself about personal own website site page bio portfolio profile
build create design make use include with and in for of to it that as change
update please can could would you name is i am theme layout style palette color colour background
font text cards sections add new switch this more very section headline
email phone address employer age résumé resume
""".split()
)


def personal_design(prompt: str, public: dict[str, str]) -> tuple[str, ...]:
    request = prompt.removeprefix("ME3_WEBSITE_REQUEST\n").casefold()
    for value in sorted([*public, *public.values()], key=len, reverse=True):
        request = re.sub(
            r"(?<!\w)" + re.escape(value.casefold()) + r"(?!\w)", " ", request
        )
    sensitive = re.findall(r"\b(email|phone|address|employer|age)\b", request)
    missing = [key for key in sensitive if key not in public]
    if missing:
        raise ValueError("What public " + missing[0] + " should I use? "
                         "Save the approved field before requesting the website.")
    words = re.findall(r"[\w]+", request)
    if set(words) - _DESIGN_TERMS - _SITE_WORDS:
        raise ValueError(
            "Please approve personal details with /profile public KEY = VALUE. "
            "For the design, name a color, theme or layout such as blue or grid."
        )
    return tuple(dict.fromkeys(word for word in words if word in _DESIGN_TERMS))


def worker_clarification(memory, prompt):
    """Return an owner-facing preflight question before durable submission."""
    try:
        raw = memory.worker_context(prompt) if memory else ""
    except ScopeAmbiguity as exc:
        return str(exc)
    if personal_site(prompt):
        public = json.loads(raw)["public_approved"] if raw else {}
        if not public:
            return (
                "What name or bio may appear publicly? Save an approved detail with "
                "/profile public bio = TEXT, then request the website again."
            )
        try:
            personal_design(prompt, public)
        except ValueError as exc:
            return str(exc)
    return None


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
        base = path.parent
        if base.name == "runtime" and base.parent.name == ".local":
            base = base.parent
        self.profiles = base / "owners"
        self.max_messages, self.max_sessions = max_messages, max_sessions
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
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
            CREATE TABLE IF NOT EXISTS memory_entities (
                owner TEXT NOT NULL, scope TEXT NOT NULL, key TEXT NOT NULL,
                kind TEXT NOT NULL, value TEXT NOT NULL, version INTEGER NOT NULL,
                source TEXT NOT NULL, updated REAL NOT NULL,
                PRIMARY KEY (owner, scope, kind, key, version));
            CREATE INDEX IF NOT EXISTS memory_owner_messages
                ON memory_messages(owner, id);
        """)

    def profile_path(self, owner: str) -> Path:
        if not owner:
            raise ValueError("An owner is required")
        slug = (
            owner
            if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", owner)
            else ("~" + hashlib.sha256(owner.encode()).hexdigest())
        )
        directory = self.profiles / slug
        if self.profiles.is_symlink() or directory.is_symlink():
            raise MemoryStorageError("Unsafe local memory storage directory")
        return directory / "USER.md"

    def profile(self, owner: str) -> dict:
        current = {"version": 0, **{key: {} for key in _SECTIONS}}
        path = self.profile_path(owner)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return current
        with os.fdopen(fd, encoding="utf-8") as stream:
            raw = stream.read(100_001)
        try:
            lines = raw.splitlines()
            if len(raw) > 100_000 or lines[0] != "# USER":
                raise ValueError
            current["version"] = int(lines[1].removeprefix("version: "))
            section = None
            seen = set()
            for line in lines[2:]:
                if not line:
                    continue
                if line.startswith("## "):
                    section = next(k for k, v in _SECTIONS.items() if v == line[3:])
                    if section in seen:
                        raise ValueError
                    seen.add(section)
                    continue
                match = re.fullmatch(r"- (" + _KEY + r") = (.{1,1000})", line)
                if not match or section is None or match[1] in current[section]:
                    raise ValueError
                current[section][match[1]] = match[2]
            if seen != set(_SECTIONS) or current["version"] < 1:
                raise ValueError
        except (IndexError, StopIteration, ValueError) as exc:
            raise MemoryStorageError("Invalid local memory storage profile") from exc
        return current

    def edit_profile(self, owner, section, key, value):
        key = key.strip().casefold()
        if not re.fullmatch(_KEY, key) or section not in _SECTIONS:
            raise ValueError("Invalid profile key or section")
        if value is not None and (
            not 1 <= len(value) <= 1000
            or len(value.splitlines()) != 1
            or any(ord(ch) < 32 for ch in value)
        ):
            raise ValueError("Use one line of 1–1000 characters")
        current = self.profile(owner)
        old = current[section].get(key)
        if value is None and old is None:
            return False
        if value is None:
            del current[section][key]
        else:
            current[section][key] = value
        if sum(len(current[k]) for k in _SECTIONS) > self.max_notes:
            raise ValueError("Profile field limit reached")
        lines = ["# USER", "version: " + str(current["version"] + 1)]
        for group, title in _SECTIONS.items():
            lines.extend(["", "## " + title])
            lines.extend(f"- {k} = {v}" for k, v in current[group].items())
        path = self.profile_path(owner)
        self.profiles.mkdir(mode=0o700, exist_ok=True)
        path.parent.mkdir(mode=0o700, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            with self.db:
                if old and old != value:
                    self._purge_literal(owner, old)
                os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return True

    def entities(self, owner, scope, key=None):
        rows = self.db.execute(
            "SELECT scope, key, kind, value, version, source FROM memory_entities "
            "WHERE owner=? AND scope=? ORDER BY version DESC, key",
            (owner, scope.casefold()),
        )
        seen, result = set(), []
        for row in rows:
            ident = (row["kind"], row["key"])
            if key and row["key"] != key.casefold():
                continue
            item = dict(row)
            if ident in seen:
                if key is None:
                    continue
                item["status"] = "superseded"
            else:
                item["status"] = "current"
            seen.add(ident)
            result.append(item)
        return result

    def put_entity(self, owner, scope, kind, key, value, source):
        key, scope = key.strip().casefold(), scope.casefold()
        if not re.fullmatch(_KEY, key) or not 1 <= len(value) <= 1000:
            raise ValueError("Invalid alias or decision key/value")
        with self.db:
            count = self.db.execute(
                "SELECT count(*) FROM memory_entities WHERE owner=?", (owner,)
            ).fetchone()[0]
            if count >= self.max_notes:
                raise ValueError("Scoped history limit reached. Forget an entry first.")
            old = [r for r in self.entities(owner, scope, key) if r["kind"] == kind]
            version = old[0]["version"] + 1 if old else 1
            if old:
                self._purge_literal(owner, old[0]["value"])
            self.db.execute(
                "INSERT INTO memory_entities VALUES(?,?,?,?,?,?,?,?)",
                (owner, scope, key, kind, value, version, source, time.time()),
            )
        return version

    def forget_entity(self, owner, scope, key):
        history = self.entities(owner, scope, key.strip())
        with self.db:
            for row in history:
                self._purge_literal(owner, row["value"])
            self.db.execute(
                "DELETE FROM memory_entities WHERE owner=? AND scope=? AND key=?",
                (owner, scope.casefold(), key.strip().casefold()),
            )
        return bool(history)

    def resolve_scope(self, owner, query):
        scopes = _scopes(query)
        if not scopes:
            rows = self.db.execute(
                "SELECT DISTINCT scope,key FROM memory_entities WHERE owner=? AND kind='alias'",
                (owner,),
            )
            scopes = {row["scope"] for row in rows if re.search(
                r"(?<!\w)" + re.escape(row["key"]) + r"(?!\w)", query.casefold())}
        choices = sorted(scopes)
        return (choices[0], []) if len(choices) == 1 else (None, choices)


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

    def recall(self, owner: str, query: str, *, current_session: str | None = None) -> dict:
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
        sessions = [dict(row) for row in self.db.execute(
            "SELECT session,started,ended FROM memory_sessions WHERE owner=? "
            "ORDER BY ended DESC, rowid DESC LIMIT ?", (owner, self.max_sessions)
        )]
        if current_session is not None:
            previous = [s["session"] for s in sessions
                        if s["ended"] is not None and s["session"] != current_session]
            visible = {current_session, *previous[:2]}
            sessions = [s for s in sessions if s["session"] in visible]
            # Interleave each session's newest turns before stable keyword
            # ranking so a long current chat cannot fill every tied slot.
            groups = [[m for m in messages if m["session"] == s["session"]]
                      for s in sessions]
            messages = [m for batch in zip_longest(*groups) for m in batch
                        if m is not None]
        messages.sort(
            key=lambda m: len(terms & _tokens(m["content"])), reverse=True
        )
        return {"notes": notes, "messages": messages, "sessions": sessions}

    @_storage_errors
    def context(self, owner: str, query: str, *, worker=False,
                current_session: str | None = None) -> str:
        if not self.enabled(owner):
            return ""
        profile = self.profile(owner)
        scope, choices = self.resolve_scope(owner, query)
        if choices:
            raise ScopeAmbiguity("Which project or task do you mean? " + ", ".join(choices))
        scoped = self.entities(owner, scope) if scope else []
        if worker:
            personal = personal_site(query)
            terms = _tokens(query)
            public = {
                key: value for key, value in profile["public"].items()
                if personal or terms & _tokens(key + " " + value)
            }
            website = query.startswith("ME3_WEBSITE_REQUEST\n")
            snapshot = {
                "public_approved": public,
                "personal_site": personal,
                "scope": None if website else scope,
                "aliases": [], "current_decisions": [],
            }
            if not website:
                for item in scoped:
                    kind = "aliases" if item["kind"] == "alias" else "current_decisions"
                    snapshot[kind].append(item)
            encoded = json.dumps(snapshot, sort_keys=True)
            if len(encoded) > 2100:
                raise ScopeAmbiguity("The selected facts exceed the worker context limit. "
                                     "Please narrow the project or public profile.")
            return encoded
        data = self.recall(owner, query, current_session=current_session)
        if scope:
            # Exclude conversations explicitly attributed to another scope.
            data["messages"] = [m for m in data["messages"]
                                if scope in _scopes(m["content"])]
        notes = data["notes"][:8]
        messages = sorted(data["messages"][:12], key=lambda m: m["id"])
        return _bounded({
            "scoped_records": scoped, "profile": [
                {"section": section, "key": key, "value": value}
                for section in _SECTIONS for key, value in profile[section].items()
            ], "notes": notes, "messages": messages,
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
            self.profile_path(owner).unlink(missing_ok=True)
            for table in ("notes", "messages", "sessions", "entities"):
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
        r"^(?:/(?:profile|alias|decision|history|memory|remember|project|forget|recall)\b|remember that\b|"
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
            raise MemoryAuthorizationError("Memory requires the current verified owner")
        self.owner = owner
        return owner

    @_storage_errors
    def record(self, role: str, text: str) -> None:
        owner = self._owner()
        self.store.record(owner, self.jobs.session_id, role, text)

    @_storage_errors
    def worker_context(self, prompt):
        return self.store.context(self._owner(), prompt, worker=True)

    @_storage_errors
    def vocabulary(self, query):
        owner = self._owner()
        if not self.store.enabled(owner):
            return ()
        terms = _tokens(query)
        vocab = self.store.profile(owner)["vocabulary"]
        return tuple(v for k, v in vocab.items()
                     if len(v) <= 64 and terms & _tokens(k + " " + v))[:12]

    def profile_command(self, text):
        owner = self._owner()
        if not self.store.enabled(owner):
            return "Memory is paused. Use /memory on first."
        if text.strip().casefold() == "/profile":
            return json.dumps(self.store.profile(owner), ensure_ascii=False)[:3000]
        edit = re.fullmatch(
            r"/profile\s+(public|private|vocabulary)\s+([^=]+?)\s*=\s*(.+)", text, re.I)
        delete = re.fullmatch(
            r"/profile forget (public|private|vocabulary) (.+)", text, re.I)
        if edit or delete:
            match = edit or delete
            changed = self.store.edit_profile(owner, match[1].lower(), match[2],
                                              edit[3].strip() if edit else None)
            if changed:
                self.changed(owner)
            if edit:
                return "Saved your " + match[1].lower() + " profile field."
            return ("Removed the local field. Artifacts, backups, harness and provider records "
                    "are separate." if changed else "No such field in this section.")
        entry = re.fullmatch(r"/(alias|decision) (" + _SCOPE + r") ([^=]+?)\s*=\s*(.+)",
                             text, re.I)
        if entry:
            version = self.store.put_entity(owner, entry[2], entry[1].lower(),
                                            entry[3], entry[4], self.jobs.session_id)
            self.changed(owner)
            return f"Saved {entry[1]} version {version}."
        history = re.fullmatch(r"/history (" + _SCOPE + r") (.+)", text, re.I)
        if history:
            entries = self.store.entities(owner, history[1], history[2])
            return _bounded({"history": entries}, 3000) if entries else "No recorded decision or alias."
        return ("Use /profile public|private|vocabulary KEY = VALUE, /profile forget SECTION KEY, "
                "/alias or /decision project/NAME KEY = VALUE, or /history project/NAME KEY.")


    def context(self, query: str) -> str:
        return self.store.context(self._owner(), query, current_session=self.jobs.session_id)

    @_storage_errors
    def close(self) -> None:
        if self.owner:
            self.store.end_session(self.owner, self.jobs.session_id)

    @_storage_errors
    def command(self, text: str) -> str | None:
        """Only explicit owner commands write facts; models never call this."""
        lower = text.casefold().strip(" .?!")
        if re.match(r"^/(?:profile|alias|decision|history)\b", text, re.I):
            return self.profile_command(text)
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
                "Your local profile, notes and conversations were cleared. Memory is paused. "
                "Job artifacts, backups, harness and provider records are separate."
            )
        if forget:
            target = forget.group(1)
            scoped = re.fullmatch(r"(" + _SCOPE + r")\s+(.+)", target, re.I)
            if scoped:
                removed = self.store.forget_entity(owner, *scoped.groups())
            else:
                removed = self.store.forget(owner, target)
            self.changed(owner)
            return (
                "That local entry was forgotten. Artifacts, backups, harness and provider records are separate." if removed else
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
        data = self.store.recall(owner, recall.group(1) if recall else "",
                                 current_session=self.jobs.session_id)
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
