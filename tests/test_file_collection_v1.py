import asyncio
import tempfile
import unittest
import warnings
from pathlib import Path
from zipfile import ZipFile

from me3.file_collection import build, open_collection
from me3.files import answer, prepare


class FileCollectionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "source"
        self.root.mkdir()
        self.cache = Path(tmp.name) / "indexes"
        (self.root / "decision.md").write_text(
            "# Courier decision\n\nThe revised dispatch is Thursday.\n"
            "Only sealed crates qualify.\n\nA receipt is optional.\n"
        )
        (self.root / "prior.txt").write_text("The former dispatch was Friday.\n")

    def test_folder_search_read_and_generation(self):
        build(self.root, self.cache)
        with open_collection(self.root, self.cache) as collection:
            hit = collection.search("revised dispatch")[0]
            self.assertEqual(hit["path"], "decision.md")
            self.assertIn("Only sealed crates", hit["text"])
            self.assertEqual(collection.read(hit["id"]), hit)
            (self.root / "decision.md").write_text("The revised dispatch is Monday.")
            with self.assertRaisesRegex(ValueError, "changed"):
                collection.read(hit["id"])
        build(self.root, self.cache)
        with (
            open_collection(self.root, self.cache) as collection,
            self.assertRaisesRegex(ValueError, "generation"),
        ):
            collection.read(hit["id"])

    def test_duplicate_zip_members_and_skipped_entries(self):
        source = self.root / "batch.zip"
        with warnings.catch_warnings(), ZipFile(source, "w") as archive:
            warnings.simplefilter("ignore", UserWarning)
            for name, body in [
                ("a.txt", "green crate"),
                ("a.txt", "orange box"),
                ("../escape.txt", "private"),
                ("image.png", b"PNG"),
                ("invalid.txt", b"\xff"),
                (".env", "secret"),
            ]:
                archive.writestr(name, body)
        status = build(source, self.cache)
        self.assertEqual(status["ready"], 2)
        self.assertEqual(status["skipped"], 4)
        with open_collection(source, self.cache) as collection:
            self.assertEqual(collection.search("orange")[0]["member"], 1)
            self.assertEqual(collection.search("green")[0]["member"], 0)
            self.assertEqual(collection.search("private"), [])

    def test_replaced_directory_link_and_hidden_files(self):
        sub = self.root / "sub"
        sub.mkdir()
        (sub / "data.txt").write_text("calibration reading")
        (self.root / ".hidden.txt").write_text("calibration secret")
        (self.root / "alias").symlink_to(sub, target_is_directory=True)
        build(self.root, self.cache)
        with open_collection(self.root, self.cache) as collection:
            (hit,) = collection.search("calibration")
            sub.rename(self.root / "moved")
            sub.symlink_to(self.root / "moved", target_is_directory=True)
            with self.assertRaises((OSError, ValueError)):
                collection.read(hit["id"])

    def test_long_line_and_bounded_summary(self):
        source = self.root / "long.txt"
        source.write_text("begin " + "calibration " * 4000 + "tailmarker")
        build(source, self.cache)
        with open_collection(source, self.cache) as collection:
            hit = collection.search("tailmarker")[0]
            self.assertIn("tailmarker", hit["text"])
            self.assertEqual(hit["line_start"], 1)
            prompt, evidence = prepare(collection, None, summary=True)
            self.assertIn("sample", prompt.lower())
            self.assertLessEqual(len(prompt.encode()), 16000)
            self.assertLessEqual(len(evidence), 4)

    def test_answer_requires_real_quote_and_rechecks_after_inference(self):
        import json

        build(self.root, self.cache)
        with open_collection(self.root, self.cache) as collection:

            async def provider(prompt):
                self.assertIn("Only sealed crates qualify.", prompt)
                return json.dumps(
                    {
                        "claims": [
                            {
                                "text": "Sealed crates qualify.",
                                "source": "S1",
                                "quote": "Only sealed crates qualify.",
                            }
                        ]
                    }
                )

            self.assertEqual(
                asyncio.run(answer(collection, "sealed crates", provider))["claims"][0][
                    "path"
                ],
                "decision.md",
            )

            async def invalid(prompt):
                return '{"claims":[{"text":"All crates qualify","source":"S1","quote":"All crates qualify"}]}'

            with self.assertRaisesRegex(ValueError, "quote"):
                asyncio.run(answer(collection, "sealed crates", invalid))

            async def replaced(prompt):
                value = await provider(prompt)
                (self.root / "decision.md").write_text("Updated")
                return value

            with self.assertRaisesRegex(ValueError, "changed"):
                asyncio.run(answer(collection, "sealed crates", replaced))

    def test_empty_search_skips_inference(self):
        source = self.root / "prior.txt"
        build(source, self.cache)
        with open_collection(source, self.cache) as collection:
            out = asyncio.run(answer(collection, "xyloturbine9000", None))
            self.assertEqual(out["claims"], [])
            self.assertFalse(out["model_called"])

    def test_abstention_with_candidates_and_partial_summary_disclosure(self):
        long_file = self.root / "large.md"
        long_file.write_text("Inspection report for a sealed crate.\n" * 300)
        build(self.root, self.cache)
        with open_collection(self.root, self.cache) as collection:

            async def abstain(prompt):
                return '{"claims":[]}'

            result = asyncio.run(answer(collection, "price per sealed crate", abstain))
            self.assertTrue(result["model_called"])
            self.assertEqual(result["status"], "insufficient_evidence")
            summary = asyncio.run(answer(collection, None, abstain, summary=True))
            self.assertLess(summary["evidence_count"], summary["selection_passages"])

    def test_failed_refresh_keeps_the_previous_generation(self):
        from unittest.mock import patch

        first = build(self.root, self.cache)
        with (
            patch("me3.file_collection.TOTAL_BYTES", 8),
            self.assertRaisesRegex(ValueError, "limit"),
        ):
            build(self.root, self.cache)
        with open_collection(self.root, self.cache) as collection:
            self.assertEqual(collection.generation, first["generation"])
            self.assertTrue(collection.search("crates"))

    def test_file_model_uses_a_tool_free_system_prompt_on_selected_route(self):
        import sys

        from me3.foreground import configured_foreground

        config = {
            "ME3_FOREGROUND_PROFILE": "pi-fast",
            "ME3_FOREGROUND_PROVIDER": "demo",
            "ME3_FOREGROUND_MODEL": "fixture",
            "ME3_PI_BIN": sys.executable,
        }
        model = configured_foreground(
            env=config, system_prompt="Return a single JSON object"
        )
        self.assertIn("--no-tools", model.command)
        self.assertEqual(
            model.command[model.command.index("--system-prompt") + 1],
            "Return a single JSON object",
        )
