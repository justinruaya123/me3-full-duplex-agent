"""Score the production local PDF search on the frozen four-deck trial."""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from me3.file_collection import open_collection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    args = parser.parse_args()
    le3 = Path(__file__).resolve().parents[3] / "LE3"
    manifest = json.loads((le3 / "sources.json").read_text())
    questions = json.loads((le3 / "evaluation/questions.json").read_text())
    for deck in manifest["decks"].values():
        with (args.corpus / deck["file"]).open("rb") as file:
            if hashlib.file_digest(file, "sha256").hexdigest() != deck["sha256"]:
                raise ValueError("Slide PDF differs from the frozen source manifest")
    report = {}
    with tempfile.TemporaryDirectory() as temp:
        for mode, flags in (("native", ["--no-ocr"]), ("ocr", [])):
            cache = Path(temp) / mode
            start = time.perf_counter()
            proc = subprocess.run(
                [sys.executable, "-m", "me3.files", "--cache", str(cache),
                 "index", str(args.corpus), *flags],
                stdout=subprocess.PIPE, check=True, text=True,
            )
            elapsed = round(time.perf_counter() - start, 2)
            counts = json.loads(proc.stdout)
            if counts["ready"] != len(manifest["decks"]) or counts["skipped"]:
                raise ValueError("Select a directory containing only the four slide PDFs")
            with open_collection(args.corpus, cache) as collection:
                ranked = {
                    q["id"]: [[h["path"], h["page"]] for h in collection.search(q["question"])]
                    for q in questions
                }
            report[mode] = {"index_s": elapsed, "ocr_pages": counts["ocr_pages"],
                            "passages": counts["passages"], "ranked": ranked}
    key = json.loads((le3 / "evaluation/key.json").read_text())
    for run in report.values():
        complete = roles = 0
        for qid, pages in run["ranked"].items():
            required = [[r["deck"] + ".pdf", r["page"]] for r in key[qid]["evidence"].values()]
            complete += int(all(p in pages for p in required))
            roles += sum(p in pages for p in required)
        run.update(complete_questions=complete, retrieved_roles=roles)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
