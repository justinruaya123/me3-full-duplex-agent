"""Local passage index with collection-generation and source-version citations."""

import fcntl
import hashlib
import os
import re
import sqlite3
import tempfile
import uuid
from contextlib import ExitStack, closing, contextmanager
from pathlib import Path
from zipfile import BadZipFile

from me3 import file_visual
from me3.file_sources import TOTAL_BYTES, Source, selected_path

PASSAGE_CHARS = 1000
MAX_HITS = 4
STOP = {
    "a",
    "an",
    "the",
    "of",
    "for",
    "to",
    "or",
    "and",
    "if",
    "in",
    "at",
    "on",
    "by",
    "as",
    "is",
    "are",
    "was",
    "were",
    "which",
    "what",
    "where",
    "who",
    "how",
    "why",
    "does",
    "do",
    "did",
    "can",
    "could",
    "would",
    "should",
    "i",
    "we",
    "my",
    "me",
    "you",
    "your",
    "it",
    "its",
    "that",
    "this",
    "those",
    "these",
    "be",
    "been",
    "with",
    "from",
    "about",
    "please",
    "tell",
}


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _decode(data):
    if b"\0" in data:
        raise ValueError("binary content")
    return data.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")


def passages(text):
    """Adjacent character spans; line numbers refer to the decoded original."""
    offset = 0
    first = 1
    while offset < len(text):
        end = min(len(text), offset + PASSAGE_CHARS)
        if end < len(text):
            lower = offset + PASSAGE_CHARS // 3
            for delimiter in ("\n\n", "\n", " "):
                boundary = text.rfind(delimiter, lower, end)
                if boundary >= 0:
                    end = boundary + len(delimiter)
                    break
        body = text[offset:end]
        breaks = body.count("\n")
        if body.strip():
            yield (offset, end, first, first + breaks - int(body.endswith("\n")), body)
        first += breaks
        offset = end


def _index_path(source, cache):
    return Path(cache).expanduser().absolute() / (
        _digest(os.fsencode(source)) + ".sqlite3"
    )


def _status(db):
    ready, total = db.execute(
        "SELECT count(CASE WHEN issue='' THEN 1 END), count(*) FROM members"
    ).fetchone()
    generation = db.execute("SELECT * FROM generation").fetchone()
    return {
        "generation": generation[0],
        "ocr_pages": generation[1] if len(generation) > 1 else 0,
        "ready": ready,
        "skipped": total - ready,
        "passages": db.execute("SELECT count(*) FROM passages").fetchone()[0],
        "skip_reasons": dict(
            db.execute(
                "SELECT issue, count(*) FROM members WHERE issue!='' GROUP BY issue"
            )
        ),
        "skipped_examples": [
            {"path": name, "member": ordinal, "reason": issue}
            for name, ordinal, issue in db.execute(
                "SELECT path,ordinal,issue FROM members "
                "WHERE issue!='' ORDER BY id LIMIT 20"
            )
        ],
    }


def build(source, cache, *, ocr=True):
    source = selected_path(source)
    target = _index_path(source, cache)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.parent.is_symlink() or target.parent.stat().st_mode & 0o077:
        raise ValueError("Choose a private index directory (mode 0700)")
    with (target.with_suffix(".lock")).open("a") as lock, ExitStack() as stack:
        fcntl.flock(lock, fcntl.LOCK_EX)
        fd, scratch = tempfile.mkstemp(dir=target.parent)
        os.close(fd)
        stack.callback(Path(scratch).unlink, missing_ok=True)
        src = Source(source, stack)
        with closing(sqlite3.connect(scratch)) as db:
            db.executescript("""
                CREATE TABLE generation(id TEXT NOT NULL, ocr_pages INTEGER NOT NULL);
                CREATE TABLE locations(passage INTEGER PRIMARY KEY, member INTEGER, page INTEGER);
                CREATE INDEX page_location ON locations(member,page);
                CREATE TABLE members(id INTEGER PRIMARY KEY, path, ordinal, digest, issue);
                CREATE VIRTUAL TABLE passages USING fts5(
                    body, path, member UNINDEXED, start UNINDEXED, end UNINDEXED,
                    first UNINDEXED, last UNINDEXED, ocr, tokenize='porter unicode61');
            """)
            byte_count = 0
            extracted_bytes = 0
            ocr_pages = 0
            for name, ordinal, issue in src.entries():
                digest, sections = "", []
                if not issue:
                    try:
                        data = src.read(name, ordinal)
                        byte_count += len(data)
                        digest = _digest(data)
                        if Path(name).suffix.lower() in file_visual.VISUAL_SUFFIXES:
                            sections = list(file_visual.pages(name, data))
                        else:
                            sections = [(None, _decode(data))]
                        if not any(text.strip() for _, text in sections):
                            issue = "empty text"
                    except UnicodeDecodeError:
                        issue = "invalid UTF-8"
                    except (ValueError, BadZipFile, OSError) as exc:
                        issue = (
                            str(exc)
                            if isinstance(exc, ValueError)
                            else type(exc).__name__
                        )
                extracted_bytes += sum(len(text.encode()) for _, text in sections)
                if max(byte_count, extracted_bytes) > TOTAL_BYTES:
                    raise ValueError(
                        "Collection exceeds the 64 MiB decoded-input limit"
                    )
                row = db.execute(
                    "INSERT INTO members(path,ordinal,digest,issue) VALUES(?,?,?,?)",
                    (name, ordinal, digest, issue),
                )
                if not issue:
                    for page, text in sections:
                        extra = ""
                        if ocr and Path(name).suffix.lower() == ".pdf":
                            extra = file_visual.ocr_terms(name, data, page, text)
                            ocr_pages += 1
                            extracted_bytes += len(extra.encode())
                            if extracted_bytes > TOTAL_BYTES:
                                raise ValueError(
                                    "Collection exceeds the 64 MiB decoded-input limit"
                                )
                        for start, end, first, last, body in passages(text):
                            passage = db.execute(
                                "INSERT INTO passages VALUES(?,?,?,?,?,?,?,?)",
                                (
                                    body,
                                    name,
                                    row.lastrowid,
                                    start,
                                    end,
                                    first,
                                    last,
                                    extra,
                                ),
                            )
                            extra = ""  # One ranked OCR entry per page.
                            if page is not None:
                                db.execute(
                                    "INSERT INTO locations VALUES(?,?,?)",
                                    (passage.lastrowid, row.lastrowid, page),
                                )
            db.execute(
                "INSERT INTO generation VALUES (?,?)", (uuid.uuid4().hex, ocr_pages)
            )
            db.commit()
            report = _status(db)
        os.replace(scratch, target)
        return report


def _terms(query):
    words = [w for w in re.findall(r"\w+", query.lower()) if w not in STOP]
    return list(dict.fromkeys(words))


class Collection:
    def __init__(self, db, source, target):
        self.db, self.source, self.target = db, source, target
        self.page_index = bool(
            db.execute("SELECT 1 FROM sqlite_master WHERE name='locations'").fetchone()
        )
        self.generation = db.execute("SELECT id FROM generation").fetchone()[0]

    def status(self):
        return _status(self.db)

    def current(self):
        with closing(
            sqlite3.connect(self.target.as_uri() + "?mode=ro", uri=True)
        ) as latest:
            if (
                latest.execute("SELECT id FROM generation").fetchone()[0]
                != self.generation
            ):
                raise ValueError("Collection generation changed; repeat the request")

    def _ref(self, rowid):
        return f"{self.generation}.{rowid}"

    def candidates(self, question, *, filename=None, literal=False):
        if not question.strip() or len(question.encode()) > 1024:
            raise ValueError("Use a question of 1 to 1024 UTF-8 bytes")
        # Give independent parts of a question a chance to contribute evidence.
        parts = re.split(r"\s+and\s+|[?;]\s*", question, flags=re.IGNORECASE)
        parts = [part for part in parts if len(_terms(part)) >= 2]
        branches = parts if 1 < len(parts) <= MAX_HITS and not literal else [question]
        ranked = []
        for part in branches:
            words = _terms(part) if not literal else re.findall(r"\w+", part)
            if not words:
                continue
            match = " OR ".join(f'"{w}"' for w in words)
            sql = "SELECT rowid FROM passages WHERE passages MATCH ?"
            args = [match]
            if filename is not None:
                sql += " AND path=?"
                args.append(filename)
            if literal:
                sql += " AND instr(body, ?)>0"
                args.append(question)
            sql += " ORDER BY rank LIMIT ?"
            ranked.append([r[0] for r in self.db.execute(sql, (*args, MAX_HITS))])
        ids = dict.fromkeys(
            branch[i] for i in range(MAX_HITS) for branch in ranked if i < len(branch)
        )
        return [self._ref(i) for i in list(ids)[:MAX_HITS]]

    def passage_count(self, filename=None):
        if filename is None:
            return self.db.execute("SELECT count(*) FROM passages").fetchone()[0]
        return self.db.execute(
            "SELECT count(*) FROM passages WHERE path=?", (filename,)
        ).fetchone()[0]

    def sample(self, filename=None):
        where = " WHERE path=?" if filename is not None else ""
        args = (filename,) if filename is not None else ()
        n = self.passage_count(filename)
        count = min(MAX_HITS, n)
        offsets = [i * (n - 1) // max(1, count - 1) for i in range(count)]
        ids = [
            self.db.execute(
                "SELECT rowid FROM passages"
                + where
                + " ORDER BY rowid LIMIT 1 OFFSET ?",
                (*args, offset),
            ).fetchone()[0]
            for offset in offsets
        ]
        return [self._ref(i) for i in ids], n

    def page_refs(self, filename, page):
        if not self.page_index or type(page) is not int or page < 1:
            raise ValueError("Page unavailable; rebuild the index or check the page")
        rows = self.db.execute(
            """SELECT min(l.passage) FROM locations l JOIN members m
            ON m.id=l.member WHERE m.path=? AND l.page=? GROUP BY l.member""",
            (filename, page),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError("Page unavailable or ambiguous; select a citation ID")
        return [self._ref(rows[0][0])]

    def pixels(self, hit, box=None, *, mark=False):
        if "page" not in hit:
            raise ValueError("A visual citation is required")
        self.current()
        with ExitStack() as stack:
            data = Source(self.source, stack).read(hit["path"], hit["member"])
            if _digest(data) != hit["sha256"]:
                raise ValueError("Source changed; rebuild the index")
            result = file_visual.render(hit["path"], data, hit["page"], box, mark=mark)
        self.current()
        return result

    def crop(self, ref, box, *, mark=False):
        return self.pixels(self.read(ref), file_visual.checked_box(box), mark=mark)

    def read_many(self, refs):
        if len(refs) > MAX_HITS:
            raise ValueError("Too many evidence references")
        self.current()
        result, originals = [], {}
        with ExitStack() as stack:
            src = Source(self.source, stack)
            for ref in refs:
                prefix, _, rowid = ref.partition(".")
                if prefix != self.generation or not re.fullmatch(
                    r"[1-9]\d{0,12}", rowid
                ):
                    raise ValueError("Unknown citation or collection generation")
                row = self.db.execute(
                    """
                    SELECT p.start, p.end, p.first, p.last, p.body, m.*
                    FROM passages p JOIN members m ON p.member=m.id WHERE p.rowid=?
                """,
                    (int(rowid),),
                ).fetchone()
                if row is None:
                    raise ValueError("Unknown evidence reference")
                key = row["id"]
                if key not in originals:
                    data = src.read(row["path"], row["ordinal"])
                    if _digest(data) != row["digest"]:
                        raise ValueError("Source changed; rebuild the index")
                    originals[key] = data
                location = (
                    self.db.execute(
                        "SELECT page FROM locations WHERE passage=?", (rowid,)
                    ).fetchone()
                    if self.page_index
                    else None
                )
                if location:
                    ((_, original),) = file_visual.pages(
                        row["path"], originals[key], location[0]
                    )
                else:
                    original = _decode(originals[key])
                body = original[row["start"] : row["end"]]
                if body != row["body"]:
                    raise ValueError("Indexed passage differs from source")
                result.append(
                    {
                        "id": ref,
                        "path": row["path"],
                        "member": row["ordinal"],
                        "sha256": row["digest"],
                        "line_start": row["first"],
                        "line_end": row["last"],
                        "char_start": row["start"],
                        "char_end": row["end"],
                        "text": body,
                        **({"page": location[0]} if location else {}),
                    }
                )
        self.current()
        return result

    def read(self, ref):
        return self.read_many([ref])[0]

    def search(self, question, **options):
        return self.read_many(self.candidates(question, **options))


@contextmanager
def open_collection(source, cache):
    source = selected_path(source)
    target = _index_path(source, cache)
    if not target.is_file():
        raise ValueError("Run index for this source first")
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        yield Collection(db, source, target)
