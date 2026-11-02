# Harness-neutral Duplex Implementation Plan

**Goal:** Add a Hermes-first voice controller without replacing the existing job supervisor.
**Architecture:** Pipecat transports audio; a transport-neutral controller owns the
floor; local harness adapters execute jobs behind the existing Backend contract.
**Tech stack:** Python 3.11+, asyncio, existing SQLite Supervisor, optional Pipecat.
**Spec:** ../specs/2026-11-02-duplex-design.md

## Constraints
Keep legacy modules intact. No live external tools in this increment. Preserve
explicit mock labelling, source pins, bounded resources and local ownership.
The user's request is to continue and implement; no additional approval round.

## Tasks
- [x] Write and observe failing controller/subprocess contract tests.
- [x] Implement policy, cancellation fencing, deferred notices and adapters.
- [x] Add an injected-transport Pipecat entry and a deterministic demo.
- [x] Run new tests, compilation and demo; record unavailable integration tests.
- [x] Publish on a new branch based on the existing `perliminary` commit.

## Review focus
Stale generation must not speak. User acknowledgments must not cancel jobs.
A failed or interrupted notice must not be marked delivered. Process stderr must
not deadlock or become protocol data. Input must not select executables or tools.

## Execution ledger
Implementation used an isolated local overlay because shell networking could not
clone the repository. The remote tree preserves the base commit. New tests went
RED then GREEN; review added two pending-ASR race regressions before the fix.
Final local verification: 31 tests, 30 passed, 1 skipped; demo and compilation pass.
The real Pipecat API import was skipped because Pipecat is not installed. Real
harness/provider, acoustic and benchmark qualification remain explicitly open.
