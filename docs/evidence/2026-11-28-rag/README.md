# Downloads retrieval trial · November 28, 2026

ME3 indexed a new, isolated Downloads subfolder on the Mac. Its `corpus/` directory held four public LE3 lecture PDFs copied from the checkout. Each SHA-256 matched the existing source manifest. All four indexed successfully, producing 142 passages across 138 pages. A separate `example-collection/` contained the two synthetic courier notes. No personal Downloads documents entered either collection.

## Production handoff

The shipped CLI reproduced the comparison on the same 138 pages. Native indexing took 0.16 seconds and supplied all required pages for 4/13 questions (8/23 evidence requirements). Local English OCR took 48.13 seconds for the complete index and supplied all pages for 7/13 questions (13/23 requirements). Both indexes contained 142 citable passages. These scores measure retrieval on a Mac, before answer generation.

To repeat the production test, obtain the four source PDFs listed under `decks` in the source manifest and place them in a directory by themselves. Run the command from an installed checkout with the context extra and Tesseract. The test verifies all four digests, builds two temporary indexes through the normal CLI and scores the frozen questions.

```sh
python docs/evidence/2026-11-28-rag/score_index.py /path/to/four-deck-folder
```

[Production ranks and timings](production.json) · [Corpus sources and hashes](../../../LE3/sources.json)

## Test design

The 13 existing LE3 questions cover diagrams, nearly identical slides, cross-document reasoning and a table with a missing value. The 23 evidence requirements come from the frozen answer key. Some requirements refer to different regions of one page. A question counts as complete when the top four passages include every required page. This metric tests the evidence available to the agent before generation. It gives no credit for interpreting an image or producing a correct answer.

Each method used the same documents, questions and final four-passage limit. The runner reopened every selected passage against the original file before scoring. It loaded the gold pages after generating all ranked lists. The collection and question set were previously used for ME3 evaluation, so these results measure this workload. Generalization needs a new collection.

- **Current search** uses the production SQLite FTS5 rank and compound-question handling.
- **Adjacent pages** spends a slot on the next physical page after each lexical hit until the budget is full.
- **Dense search** embeds the native passage text and query locally with MiniLM. It uses 256-token truncation, attention-mask mean pooling, normalized 384-dimensional vectors and exact cosine ranking on CPU.
- **Fusion** combines the first four lexical and first four dense candidates using reciprocal ranks with constant 60 and equal weights. Ties preserve insertion order, with lexical candidates entered first.
- **OCR** renders each original page locally and runs Tesseract 5.5.2 with English sparse-text mode. It appends extracted lines missing from the first passage on that page to a disposable search index. The same original page and passage IDs remain the only citable evidence. The experiment scores lexical, dense and fused ranks on this enriched index.

[Questions](../../../LE3/evaluation/questions.json) · [Evidence key](../../../LE3/evaluation/key.json) · [Source manifest](../../../LE3/sources.json) · [Pinned MiniLM model](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2/tree/1110a243fdf4706b3f48f1d95db1a4f5529b4d41)

## Measured page retrieval

| Search input and method | Questions with all required pages | Evidence requirements with the right page |
| --- | ---: | ---: |
| Native text, current keyword search | 4/13 | 8/23 |
| Current keyword search plus adjacent pages | 4/13 | 7/23 |
| Native text, MiniLM | 5/13 | 11/23 |
| Native text, keyword and MiniLM rank fusion | 3/13 | 8/23 |
| Native text plus OCR, keyword search | 7/13 | 13/23 |
| Native text plus OCR, MiniLM | 7/13 | 14/23 |
| Native text plus OCR, rank fusion | 6/13 | 12/23 |

The Flow++ results table on Flow page 28 has just one word in its native text layer, “Performance.” Neither native-text retriever found the table. All three OCR routes retrieved it. With OCR, lexical search recovered both GAN training diagrams. Dense search recovered the overview on Flow page 3 but lost one of the GAN pair. None of the seven methods found the required pair of VAE slides contrasting point clouds and decoded image grids. The two slides have identical 46-character native text.

On this Mac, rendering, checking sources and running OCR across all pages took 43.60 seconds once during indexing. Encoding the passages on two CPU threads took 1.55 seconds for native text and 2.25 seconds with OCR. Across the 13 questions, median query encoding and cosine ranking took 4.91 ms and 4.55 ms respectively. These measurements exclude model load, document verification after ranking, generation and speech. Raspberry Pi latency and contention remain unmeasured.

**D4 recommendation.** Add local OCR during PDF indexing and keep citation checks against the original page. Compare selective OCR against this full-page baseline on an unseen collection. Text embeddings remain a candidate for paraphrases. On these slides, embeddings added one covered evidence requirement after OCR, while the count of fully supported questions stayed at seven.

## End-to-end controls

The normal `scripts/me3.sh files ask` command used the configured Pi.dev foreground for the revised pickup and release question. It returned Thursday at 15:30 with an exact quotation from `dispatch.md` line 4 and required sealed crates with a blue inspection tag with an exact quotation from `release.txt` line 3. The time superseded the obsolete Tuesday plan. The model call took 6.66 seconds. A separate search for the absent term “zygomorphic” returned zero passages and `insufficient_evidence` without a model call.

The price-per-crate question matched the notes but had no supported answer. The sandboxed provider request failed. Automatic approval review declined a hosted retry because it would send the selected excerpts to the provider. This case has no measured model answer or abstention. The slide comparison above ran entirely on the Mac and scored retrieval only.

## Reproduction

Use an installed checkout with the PDF context extra, Tesseract with English data on PATH, and a second Python environment containing CPU PyTorch and Transformers. Supply the pinned MiniLM tokenizer and safetensors weights in a local directory. The runner accepts the directory containing exactly the four source PDFs. It keeps the search databases temporary and saves ranked pages, counts, model timing and the weights digest in the requested JSON file.

```sh
.venv313/bin/python docs/evidence/2026-11-28-rag/compare.py \
  /path/to/trial/corpus /path/to/results.json \
  --model /path/to/local/all-MiniLM-L6-v2 --encoder-python .speech-venv/bin/python
```

[Comparison runner](compare.py) · [Measured results and per-question ranks](retrieval.json)
