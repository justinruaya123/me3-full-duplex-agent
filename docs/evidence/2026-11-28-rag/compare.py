"""Offline, four-passage retrieval comparison on the frozen LE3 questions."""

import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
LE3 = ROOT / "LE3"
K = 4


def encode(model_dir):
    import torch
    from transformers import AutoModel, AutoTokenizer

    torch.set_num_threads(2)
    tokenizer = AutoTokenizer.from_pretrained(model_dir, local_files_only=True)
    model = AutoModel.from_pretrained(model_dir, local_files_only=True).eval()

    def vectors(texts):
        tokens = tokenizer(
            texts, padding=True, truncation=True, max_length=256, return_tensors="pt"
        )
        with torch.inference_mode():
            hidden = model(**tokens).last_hidden_state
            mask = tokens.attention_mask.unsqueeze(-1)
            pooled = (hidden * mask).sum(1) / mask.sum(1)
            return torch.nn.functional.normalize(pooled)

    data = json.load(sys.stdin)
    started = time.perf_counter()
    passages = data["passages"]
    matrix = torch.cat(
        [vectors(passages[i : i + 16]) for i in range(0, len(passages), 16)]
    )
    index_seconds = time.perf_counter() - started
    ranks, timings = [], []
    for question in data["questions"]:
        start = time.perf_counter()
        scores = (vectors([question]) @ matrix.T)[0]
        ranks.append(scores.argsort(descending=True, stable=True)[:K].tolist())
        timings.append(1000 * (time.perf_counter() - start))
    print(
        json.dumps(
            {
                "ranks": ranks,
                "encode_corpus_s": round(index_seconds, 3),
                "median_query_ms": round(statistics.median(timings), 2),
            }
        )
    )


def fuse(*lists):
    scores = {}
    for ranks in lists:
        for rank, ref in enumerate(ranks, 1):
            scores[ref] = scores.get(ref, 0) + 1 / (60 + rank)
    return sorted(scores, key=scores.get, reverse=True)[:K]


def rank_dense(args, passages, questions):
    child = subprocess.run(
        [args.encoder_python, __file__, "encode", str(args.model)],
        input=json.dumps(
            {"questions": [q["question"] for q in questions], "passages": passages}
        ),
        text=True,
        stdout=subprocess.PIPE,
        check=True,
    )
    return json.loads(child.stdout)


def add_ocr(c, scratch, rows):
    """Extend only the search text in a disposable copy, keeping citation IDs."""
    from me3.file_collection import Collection

    c.db.backup(scratch)
    scratch.row_factory = sqlite3.Row
    seen = set()
    for row in rows:
        key = row["path"], row["page"]
        if key in seen:
            continue
        seen.add(key)
        hit = c.read(f"{c.generation}.{row['rowid']}")
        out = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "11"],
            input=c.pixels(hit),
            capture_output=True,
            check=True,
            timeout=30,
            env={**os.environ, "OMP_THREAD_LIMIT": "1"},
        )
        extra = [
            s
            for s in out.stdout.decode().splitlines()
            if s.strip() and s.casefold() not in hit["text"].casefold()
        ]
        if extra:
            scratch.execute(
                "UPDATE passages SET body=body || ? WHERE rowid=?",
                ("\n" + "\n".join(extra), row["rowid"]),
            )
    return Collection(scratch, c.source, c.target)


def main():
    from me3.file_collection import build, open_collection

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--encoder-python", required=True)
    args = parser.parse_args()
    questions = json.loads((LE3 / "evaluation/questions.json").read_text())
    manifest = json.loads((LE3 / "sources.json").read_text())["decks"]
    for deck in manifest.values():
        if (
            hashlib.sha256((args.corpus / deck["file"]).read_bytes()).hexdigest()
            != deck["sha256"]
        ):
            raise ValueError("A lecture PDF differs from the frozen manifest")

    with tempfile.TemporaryDirectory() as tmp:
        cache = Path(tmp) / "index"
        index = build(args.corpus, cache, ocr=False)
        if index["ready"] != len(manifest) or index["skipped"]:
            raise ValueError("Select only the four frozen lecture PDFs")
        with (
            open_collection(args.corpus, cache) as c,
            closing(sqlite3.connect(":memory:")) as scratch,
        ):
            ordered_passages = (
                "SELECT p.rowid,p.path,p.body,l.page FROM passages p "
                "JOIN locations l ON l.passage=p.rowid ORDER BY p.path,l.page,p.rowid"
            )
            rows = c.db.execute(ordered_passages).fetchall()
            refs = [f"{c.generation}.{r['rowid']}" for r in rows]
            body = [r["body"] for r in rows]
            dense = rank_dense(args, body, questions)
            ocr_start = time.perf_counter()
            extended = add_ocr(c, scratch, rows)
            ocr_seconds = round(time.perf_counter() - ocr_start, 2)
            enriched = [r["body"] for r in scratch.execute(ordered_passages)]
            ocr_dense = rank_dense(args, enriched, questions)
            by_page = {}
            for row, ref in zip(rows, refs):
                by_page.setdefault((row["path"], row["page"]), ref)
            cases = {}
            for q, positions, ocr_positions in zip(
                questions,
                dense.pop("ranks"),
                ocr_dense.pop("ranks"),
                strict=True,
            ):
                lexical = c.candidates(q["question"])
                semantic = [refs[i] for i in positions]
                ocr_lexical = extended.candidates(q["question"])
                ocr_semantic = [refs[i] for i in ocr_positions]
                # Give the next page one of the four slots after each lexical hit.
                neighbors = []
                for hit in c.read_many(lexical):
                    neighbors.append(hit["id"])
                    following = by_page.get((hit["path"], hit["page"] + 1))
                    if following:
                        neighbors.append(following)
                routes = {
                    "current": lexical,
                    "adjacent": list(dict.fromkeys(neighbors))[:K],
                    "dense": semantic,
                    "hybrid": fuse(lexical, semantic),
                    "ocr_lexical": ocr_lexical,
                    "ocr_dense": ocr_semantic,
                    "ocr_hybrid": fuse(ocr_lexical, ocr_semantic),
                }
                cases[q["id"]] = {
                    route: [[h["path"], h["page"]] for h in c.read_many(ids)]
                    for route, ids in routes.items()
                }

    # The answer key is opened only after all ranked lists have been frozen.
    key = json.loads((LE3 / "evaluation/key.json").read_text())
    summary = {}
    for case, methods in cases.items():
        wanted = [
            [r["deck"] + ".pdf", r["page"]] for r in key[case]["evidence"].values()
        ]
        for route, pages in methods.items():
            counts = summary.setdefault(route, {"roles": 0, "complete": 0})
            counts["roles"] += sum(page in pages for page in wanted)
            counts["complete"] += int(all(page in pages for page in wanted))
    with (args.model / "model.safetensors").open("rb") as stream:
        weights_hash = hashlib.file_digest(stream, "sha256").hexdigest()
    result = {
        "index": {k: index[k] for k in ("ready", "skipped", "passages")},
        "question_count": len(questions),
        "role_count": sum(len(k["evidence"]) for k in key.values()),
        "model_weights_sha256": weights_hash,
        "dense_cpu": dense,
        "ocr_dense_cpu": ocr_dense,
        "ocr_index_s": ocr_seconds,
        "summary": summary,
        "cases": cases,
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    if sys.argv[1:2] == ["encode"]:
        encode(sys.argv[2])
    else:
        main()
