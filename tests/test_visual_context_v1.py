import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from me3.file_collection import build, open_collection
from me3.files import answer
from me3.lookup import lookup_intent


def diagram(label):
    image = Image.new("RGB", (600, 400), "white")
    ImageDraw.Draw(image).text((40, 220), label, fill="black")
    return image


class VisualContextTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name) / "slides"
        self.root.mkdir()
        self.cache = self.root.parent / "cache"

    def test_equation_page_and_bbox_are_bound_to_original(self):
        diagram("Introduction").save(
            self.root / "lecture.pdf",
            save_all=True,
            append_images=[diagram("ELBO = expected log likelihood - KL(q || prior)")],
        )
        status = build(self.root, self.cache, ocr=False)
        self.assertEqual(status["ready"], 1)
        with open_collection(self.root, self.cache) as collection:
            refs = collection.page_refs("lecture.pdf", 2)
            hit = collection.read(refs[0])
            self.assertEqual(hit["page"], 2)

            async def visual(prompt, images):
                self.assertIn("S1", prompt)
                self.assertEqual(len(images), 1)
                self.assertGreater(len(images[0]["data"]), 1000)
                return json.dumps(
                    {
                        "claims": [
                            {
                                "source": "S1",
                                "text": "The bound contains a prior KL.",
                                "bbox": [710, 390, 985, 499],
                            }
                        ]
                    }
                )

            result = asyncio.run(answer(collection, "Which bound?", visual, refs=refs))
            claim = result["claims"][0]
            self.assertEqual((claim["page"], claim["bbox"]), (2, [710, 390, 985, 499]))
            self.assertEqual(claim["sha256"], hit["sha256"])
            self.assertTrue(
                collection.crop(hit["id"], claim["bbox"]).startswith(b"\x89PNG")
            )
            (self.root / "lecture.pdf").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "changed"):
                collection.crop(hit["id"], claim["bbox"])

    def test_changed_image_and_invalid_boxes_are_rejected(self):
        path = self.root / "marked.png"
        diagram("First figure").save(path)
        self.assertEqual(build(self.root, self.cache)["ready"], 1)
        with open_collection(self.root, self.cache) as collection:
            refs = collection.page_refs("marked.png", 1)

            async def incorrect(prompt, images):
                return '{"claims":[{"text":"claim","source":"S1","bbox":[4,0,1,4]}]}'

            with self.assertRaisesRegex(ValueError, "box"):
                asyncio.run(answer(collection, "Which term?", incorrect, refs=refs))

            async def stale(prompt, images):
                diagram("Revised figure").save(path)
                return (
                    '{"claims":[{"text":"claim","source":"S1","bbox":[0,0,100,100]}]}'
                )

            with self.assertRaisesRegex(ValueError, "changed"):
                asyncio.run(answer(collection, "Which term?", stale, refs=refs))

    def test_document_references_remain_local(self):
        for question in [
            "Explain equation (8) on slide 14",
            "Search for the boxed term on page 37",
            "What is in example.png?",
            "What do the arrows in the attached diagram mean?",
        ]:
            with self.subTest(question=question):
                self.assertIsNone(lookup_intent(question, model_selected=True))
        self.assertEqual(
            lookup_intent("Search for variational inference original paper")[1], "web"
        )


class ResearchSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_site_filter_dates_excerpts_and_duplicate_links(self):
        import httpx

        from me3.lookup import BraveLookup

        def provider(request):
            self.assertEqual(request.url.params["q"], "site:mit.edu linear algebra")
            self.assertEqual(request.url.params["freshness"], "pw")
            hits = [
                {"url": url, "description": "Public course excerpt", "title": "Course"}
                for url in (
                    "https://mit.edu.evil.test/topic",
                    "https://ocw.mit.edu/course",
                    "https://ocw.mit.edu/course#extra",
                )
            ]
            return httpx.Response(200, json={"web": {"results": hits}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            search = BraveLookup("test", client=client)
            result = await search.web_lookup(
                "linear algebra", "web", "pw", site="MIT.EDU"
            )
            self.assertEqual(result.urls, ("https://ocw.mit.edu/course",))
            self.assertEqual(result.companion.count("Public course excerpt"), 1)
            with self.assertRaisesRegex(ValueError, "domain"):
                await search.web_lookup(
                    "linear algebra", "web", None, site="mit.edu/path"
                )


class ExplicitImageTests(unittest.TestCase):
    def test_named_image_can_be_asked_about_without_keyword_overlap(self):
        from me3.files import prepare

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "page.png"
            diagram("A marked figure").save(source)
            cache = root / "index"
            build(source, cache)
            with open_collection(source, cache) as collection:
                _, hits = prepare(collection, "Which divergence is enclosed?")
                self.assertEqual([h["path"] for h in hits], ["page.png"])


class ContextWebFailureTests(unittest.TestCase):
    def test_cli_reports_provider_status_without_a_traceback_or_query(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from unittest.mock import AsyncMock, patch

        import httpx

        from me3.files import main

        request = httpx.Request("GET", "https://example.test/?q=private-query")
        failure = httpx.HTTPStatusError(
            "example error",
            request=request,
            response=httpx.Response(429, request=request),
        )
        stream = StringIO()
        with (
            patch("sys.argv", ["context", "web", "linear algebra"]),
            patch.dict("os.environ", {"BRAVE_SEARCH_API_KEY": "fixture"}),
            patch("me3.lookup.BraveLookup.web_lookup", AsyncMock(side_effect=failure)),
            redirect_stderr(stream),
            self.assertRaises(SystemExit) as status,
        ):
            main(default_source=Path("context"))
        self.assertEqual(status.exception.code, 1)
        self.assertIn("429", stream.getvalue())
        self.assertNotIn("private-query", stream.getvalue())
