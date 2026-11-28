"""PDF OCR contributes search terms while original pages supply evidence."""

import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFont

from me3.file_collection import build, open_collection


class PDFOCRTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.source = Path(folder.name) / "trial.pdf"
        self.cache = self.source.parent / "index"
        pages = [Image.new("RGB", (720, 260), "white") for _ in range(2)]
        for page, title in zip(pages, ("ALPINE STATION", "COBALT ORCHARD")):
            ImageDraw.Draw(page).text(
                (40, 80), title, fill="black", font=ImageFont.load_default(size=48)
            )
        pages[0].save(self.source, save_all=True, append_images=pages[1:])

    @unittest.skipUnless(shutil.which("tesseract"), "local Tesseract is not installed")
    def test_default_search_finds_scan_and_reopens_original_page(self):
        report = build(self.source, self.cache)
        with open_collection(self.source, self.cache) as c:
            hits = c.search("cobalt orchard")
            self.assertEqual([h["page"] for h in hits], [2])
            self.assertEqual(report["ocr_pages"], 2)
            self.assertEqual(c.status()["ocr_pages"], 2)
            self.assertEqual(hits[0]["text"], "[Image-only page]")
            self.assertEqual(c.search("COBALT ORCHARD", literal=True), [])
            self.assertTrue(c.pixels(hits[0]).startswith(b"\xff\xd8"))
            self.source.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                c.read(hits[0]["id"])

    def test_missing_engine_keeps_previous_index_and_explicit_native_mode_works(self):
        with patch.dict("os.environ", {"PATH": ""}):
            before = build(self.source, self.cache, ocr=False)
            with self.assertRaisesRegex(RuntimeError, "Tesseract"):
                build(self.source, self.cache)
            with open_collection(self.source, self.cache) as c:
                self.assertEqual(c.generation, before["generation"])
                self.assertEqual(c.status()["ocr_pages"], 0)
                self.assertEqual(c.search("cobalt orchard"), [])

    def test_native_index_and_citation_from_before_ocr_still_open(self):
        note = self.source.with_suffix(".txt")
        note.write_text("Meet in the orchard.")
        initial = build(note, self.cache)
        with open_collection(note, self.cache) as collection:
            ref = collection.search("orchard")[0]["id"]
            database = collection.target
        with closing(sqlite3.connect(database)) as db:
            db.executescript("""
                ALTER TABLE generation RENAME TO new_generation;
                CREATE TABLE generation(id TEXT NOT NULL);
                INSERT INTO generation SELECT id FROM new_generation;
                DROP TABLE new_generation;
                ALTER TABLE passages RENAME TO new_passages;
                CREATE VIRTUAL TABLE passages USING fts5(
                    body, path, member UNINDEXED, start UNINDEXED, end UNINDEXED,
                    first UNINDEXED, last UNINDEXED, tokenize='porter unicode61');
                INSERT INTO passages SELECT body,path,member,start,end,first,last FROM new_passages;
                DROP TABLE new_passages;
            """)
        with open_collection(note, self.cache) as collection:
            self.assertEqual(collection.status()["generation"], initial["generation"])
            self.assertEqual(collection.status()["ocr_pages"], 0)
            self.assertEqual(collection.search("orchard"), [collection.read(ref)])
