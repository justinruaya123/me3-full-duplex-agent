# Full-Duplex Voice Agent on a Raspberry Pi

Student me3-local · run 2026-11-07_10-13-32 · 2026-11-07

## 5 · Evaluation & Benchmark

| Metric | Definition | Target | Mean | p95 | n |
|---|---|---|---|---|---|
| E2E latency | end of speech → audio out | < 4.00 s | 2.73 s | 4.24 s | 29 |
| ASR final | end of speech → transcript | < 0.80 s | 1.51 s | 1.96 s | 30 |
| LLM TTFT | transcript → first token | < 1.50 s | 0.60 s | 1.80 s | 29 |
| TTS TTFB | text → first audio chunk | < 0.60 s | 0.40 s | 0.74 s | 29 |
| Barge-in | speech → playback stopped | < 0.80 s | 0.25 s | 0.25 s | 3 |
| WER | ASR accuracy on test set | < 15 % | 1.4 % | — | 30 |

- One clock: the assistant machine's monotonic clock; every stage timestamped (VAD end → ASR final → LLM 1st token → TTS 1st audio → speaker)
- E2E = speaker − VAD end; barge-in = stop − speech start
- 10 phrases × 3 runs; mean + p95; JSON log per run: stage_latency.json (per turn: trials/<id>/stages.jsonl)

## Results (deck 2)

Latency chart: latency_chart.svg

- RPi model / RAM: Darwin 25.5.0 · 16 GB
- Cooling: not stated
- Network: cloud: unknown · benchmark link: same machine, 0 ms round trip
- Date: 2026-11-07
- Model versions: harness pipecat 1.15.1.dev12, ASR mlx-community/whisper-large-v3-turbo, LLM Qwen/Qwen3.8-27B, TTS mlx-community/Kokoro-82M-bf16, voice af_heart, VAD Silero, turn SmartTurn v3.2

## 3 · Context engineering: context size per run

| Context size | Median | Max | First → last call |
|---|---|---|---|
| Prompt tokens per LLM call (estimate) | 43 | 79 | 43 → 42 |
| Messages in context | 1 | 1 | 1 → 1 |
