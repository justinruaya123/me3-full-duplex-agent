// Two-page AI231 machine exercise. Build with: typst compile bmo-machine-exercise.typ
// Frozen evidence used below:
//   docs/DUPLEX_STATUS.md, Nov 21, "Current chat, Brave results and edits to ongoing work"
//   .local/pr4-shipping-voice/routing.json (5 checks; callback times in milliseconds)
//   docs/BENCHMARK.md, "Final canonical ME3 run", 2026-11-07_06-10-46
// Implementation: .env.bmo.example, me3/{deepgram,parakeet_voice,course_mcp}.py,
// integrations/voicechat/{pi.mjs,prompts/SYSTEM.md,prompts/SOUL.md}.
// All artwork, text, and tables are native Typst. No imported template or assets.
#set page(width: 960pt, height: 540pt, margin: 0pt)
#set document(title: "BMO | Full-Duplex Voice Agent on a Raspberry Pi", author: "ME3 project")
#let navy = rgb("#17253d")
#let orange = rgb("#ed7524")
#let teal = rgb("#077d83")
#let ink = rgb("#1d2b3d")
#let muted = rgb("#53657a")
#let rule = rgb("#c6d2df")
#let pale = rgb("#edf2f7")
#let soft = rgb("#eaf5f4")
#let mono = "Menlo"
#let repo = "https://github.com/justinruaya123/me3-full-duplex-agent/blob/6b6bf3c7bcfa69ea7ce8e98ea22afe1e3f4ada0a/"
#set text(font: "Arial", size: 10pt, fill: ink)
#set par(leading: 0.45em)

#let at(x, y, body) = place(top + left, dx: x * 1pt, dy: y * 1pt, body)
#let area(x, y, w, body) = at(x, y, block(width: w * 1pt, body))
#let panel(w, h, color: pale, border: rule, r: 5pt) = rect(
  width: w * 1pt, height: h * 1pt, fill: color, stroke: 0.65pt + border, radius: r,
)
#let caption(body) = text(size: 8.7pt, weight: "bold", fill: teal, body)
#let header(title, subtitle) = {
  at(0, 0, rect(width: 960pt, height: 84pt, fill: navy, stroke: none))
  at(0, 84, rect(width: 960pt, height: 3pt, fill: orange, stroke: none))
  at(48, 17, text(size: 10pt, weight: "bold", fill: rgb("#ff9a53"))[AI231 MACHINE EXERCISE · BMO])
  at(48, 39, text(size: 22pt, weight: "bold", fill: white, title))
  area(672, 55, 240, align(right, text(size: 9.5pt, fill: rgb("#d8e3ef"), subtitle)))
}
#let section(n, title, detail: none) = box(height: 17pt)[
  #box(width: 16pt, height: 16pt, fill: orange, radius: 3pt,
    align(center + horizon, text(weight: "bold", fill: white, size: 11pt, n)))
  #h(3pt)#text(weight: "bold", size: 14pt, fill: navy, title)
  #if detail != none { h(5pt); text(size: 9.5pt, style: "italic", fill: muted, detail) }
]
#let footer(n) = {
  at(48, 506, line(length: 864pt, stroke: 0.55pt + rule))
  at(48, 513, text(size: 8pt, fill: muted)[AI231 · Machine Exercise 3 · BMO])
  area(255, 513, 450, align(center, text(size: 8pt, fill: muted)[Mac pilot · Raspberry Pi 5 deployment target · 21 November 2026]))
  area(806, 513, 106, align(right, text(size: 8pt, fill: muted)[#n / 2]))
}
#let dot(body) = grid(columns: (6pt, 1fr), column-gutter: 3pt,
  text(fill: orange, weight: "bold")[–], body)
#let item(head, copy) = dot([#strong(head) #copy])

// Draw connections in the page coordinate system. Orthogonal paths use short
// segments so the return transcript and the job branch have distinct routes.
#let wire(x1, y1, x2, y2) = at(x1, y1, line(
  start: (0pt, 0pt), end: ((x2 - x1)*1pt, (y2 - y1)*1pt), stroke: 1pt + teal))
#let tip(x, y, dir) = {
  let points = if dir == "right" { ((0pt, 0pt), (-4pt, -2.2pt), (-4pt, 2.2pt)) }
    else if dir == "left" { ((0pt, 0pt), (4pt, -2.2pt), (4pt, 2.2pt)) }
    else { ((0pt, 0pt), (-2.2pt, -4pt), (2.2pt, -4pt)) }
  at(x, y, polygon(..points, fill: teal, stroke: none))
}
#let node(x, y, w, name, hosted: false) = at(x, y, box(
  width: w*1pt, height: 24pt, radius: 3pt, fill: if hosted { soft } else { white },
  stroke: 0.65pt + (if hosted { rgb("#8fbfbd") } else { rule }),
  align(center + horizon, text(size: 9.3pt, weight: "bold", fill: navy, name))))
#let wirelabel(x, y, body) = at(x, y, text(size: 8pt, fill: teal, body))

#header([Full-Duplex Voice Agent on a Raspberry Pi], [Mac pilot · Raspberry Pi 5 target])
#at(48, 102, section("1", [SYSTEM DIAGRAM], detail: [BMO in Pi.dev duplex mode]))
#at(48, 129, panel(462, 153))
#at(348, 129, line(start: (0pt, 0pt), end: (0pt, 153pt), stroke: (paint: rule, thickness: 1pt, dash: "dashed")))
#at(59, 137, caption[CLIENT DEVICE · MAC IN THE PILOT])
#at(360, 137, caption[HOSTED SERVICES])
#node(60, 155, 123, [Mic + Silero VAD])
#node(360, 155, 138, [Deepgram Nova-3], hosted: true)
#wire(183, 167, 358, 167)#tip(359, 167, "right")#wirelabel(211, 155, [16 kHz mono audio])
#wire(429, 179, 429, 191)#wire(429, 191, 121, 191)#wire(121, 191, 121, 201)#tip(121, 201, "down")
#wirelabel(204, 179, [interim and final words])
#node(60, 202, 123, [SmartTurn + turn gate])
#node(221, 202, 109, [Pi.dev foreground])
#wire(183, 214, 219, 214)#tip(220, 214, "right")
#node(360, 202, 138, [OpenRouter / Brave], hosted: true)
#wire(332, 214, 357, 214)#tip(331, 214, "left")#tip(359, 214, "right")
#wire(276, 226, 276, 239)#wire(121, 239, 276, 239)
#wire(121, 239, 121, 248)#tip(121, 249, "down")#wire(276, 239, 276, 248)#tip(276, 249, "down")
#node(60, 250, 123, [Piper → speaker])
#node(206, 250, 130, [Local Pi job worker])
#area(360, 242, 138, text(size: 8.5pt, fill: muted)[Pi sends model requests to OpenRouter and public queries to Brave.])

#area(532, 131, 380, [
  #set text(size: 11pt)
  #stack(spacing: 8.5pt,
    item([Listen.], [Pipecat runs Silero and SmartTurn on the client. BMO displays partial words and acts on a committed turn.]),
    item([Speak.], [Local Piper voices replies. Cached greetings and acknowledgments use the same speaker queue.]),
    item([Delegate.], [Pi can start a local worker, keep talking, then retrieve the saved draft by job ID and revision.]),
    item([Course MCP mode.], [A separate launcher exposes ASR, TTS and task tools on the client. It uses server Whisper and local Kokoro by default.]),
  )
])
#at(48, 290, box(width: 462pt, height: 19pt, radius: 3pt, fill: navy,
  align(center + horizon, text(font: mono, size: 9pt, fill: white)[mic → VAD → ASR → Pi.dev + tools → Piper → speaker])))
#area(48, 315, 864, text(size: 10pt, weight: "bold", fill: rgb("#ae4e12"))[Barge-in pauses playback at speech onset. A committed interruption cancels the foreground reply. The delegated job keeps running.])

#at(48, 338, section("2", [PROMPT], detail: [excerpts from the versioned defaults]))
#at(532, 338, section("3", [CONTEXT ENGINEERING]))
#at(48, 364, panel(462, 124))
#area(59, 373, 440, [
  #caption[SYSTEM.md]
  #v(3pt)
  #text(font: mono, size: 9.3pt)[You are the user's hands-free coworker and secretary. Answer questions, make drafts, and keep track of delegated work.]
  #v(7pt)
  #caption[SOUL.md]
  #v(3pt)
  #text(font: mono, size: 9.3pt)[Lead with the answer, the action, or the one question that will move things along. Use everyday words.]
])
#area(532, 367, 183, [
  #caption[WHAT PI RECEIVES]
  #v(7pt)
  #stack(spacing: 6pt, dot([The committed transcript and current chat branch.]),
    dot([Private USER.md for identity and preferences.]),
    dot([Brave sources, job IDs, revisions and tool receipts.]))
])
#area(729, 367, 183, [
  #caption[HOW PI USES IT]
  #v(7pt)
  #stack(spacing: 6pt, dot([Prioritize the last relevant exchange and corrections.]),
    dot([Use older chats on request. Cap each prompt file at 8 KiB.]),
    dot([Discard stale speech. Read a job’s current revision before reporting it.]))
])
#footer(1)
#pagebreak()

#let matrix(widths, heads, rows, size: 9pt, inset-y: 3.3pt) = {
  set text(size: size)
  set par(leading: 0.32em)
  table(
    columns: widths, align: left + horizon,
    inset: (x: 5pt, y: inset-y),
    stroke: 0.4pt + rule,
    fill: (x, y) => if y == 0 { navy } else if calc.even(y) { pale } else { white },
    table.header(..heads.map(it => text(fill: white, weight: "bold", it))),
    ..rows.flatten(),
  )
}
#let services = (
  ([ASR], [BMO · secure WebSocket], [Stream 16 kHz PCM, receive word updates], [Deepgram Nova-3], [Cloud recognition. The client commits the turn.]),
  ([TTS], [BMO · local audio process], [Speak a reply or play a cached cue], [BMO Piper v1.0-voice], [Client CPU · 24 kHz mono PCM16 playback.]),
  ([LLM], [Project Pi.dev → OpenRouter], [Answer, call a tool or delegate], [DeepSeek V4.1 Flash], [Foreground reasoning off. Worker reasoning high.]),
  ([VAD / turn], [Pipecat · in-process], [Detect speech and evaluate pauses], [Silero + SmartTurn v3], [Client CPU · 16 kHz mono microphone input.]),
  ([Tasks / web], [BMO · Pi extension tools], [delegate_task, delegated_task_status, web_lookup], [Local Pi worker / Brave], [Local job store and artifacts. Brave supplies sources.]),
  ([Course MCP], [3 servers · HTTP over Unix socket], [transcribe, speak, tts_cancel, submit_job, get_job], [Whisper / Kokoro], [Client hosts MCP. Speech tools pass IDs. PCM stays outside MCP.]),
)
#let metrics = (
  ([E2E], [VAD end → output mark], [4.0], [2.552], [3.711], [29]),
  ([ASR final], [VAD end → transcript], [0.8], [1.470], [2.036], [30]),
  ([LLM TTFT], [Transcript → first text], [1.5], [0.402], [0.745], [29]),
  ([TTS TTFB], [Text → first PCM], [0.6], [0.424], [0.696], [29]),
  ([Barge-in], [Onset → output stop], [0.8], [0.337], [0.406], [3]),
  ([WER], [Word errors / 207 words], [15%], [1.45%], [—], [30]),
)
#let card(x, y, w, h, title, contents) = {
  at(x, y, panel(w, h))
  area(x + 8, y + 8, w - 16, stack(spacing: 6pt, caption(title), contents))
}
#let bar(label, ms) = grid(
  columns: (68pt, 1fr, 35pt), column-gutter: 3pt, align: (left + horizon, left + horizon, right + horizon),
  text(size: 8.7pt, label),
  block(width: 100%, height: 5pt, radius: 1pt, fill: white,
    block(width: (ms/4500)*100%, height: 5pt, radius: 1pt, fill: teal)),
  text(size: 8.7pt)[#(str(ms))],
)

#header([MCP Services, Evaluation & Model Serving], [BMO pilot and class benchmark])
#at(48, 100, section("4", [MCP SERVICES], detail: [Section 6 · model serving and deployment]))
#area(48, 123, 864, matrix((78pt, 158pt, 212pt, 143pt, 273pt),
  ([Component], [Interface / transport], [Operation or tool], [Model / service], [Runs where]), services))

#at(48, 246, section("5", [EVALUATION & BENCHMARK], detail: [class protocol]))
#area(48, 271, 383, [
  #caption[OFFICIAL MAC RUN · 07 NOV 2026]
  #v(5pt)
  #stack(spacing: 4pt,
    dot([Whisper Turbo + Qwen + Kokoro on the class digital rig. One host monotonic clock. Mac, 16 GB RAM.]),
    dot([10 phrases × 3 repeats, plus 3 duplex rounds. 29/30 had recorded replies. ASR covers all 30. WER pools 3 errors across 207 words.]),
    dot([ASR and TTS exceeded their p95 targets. Only 3 of 6 scheduled interruptions yielded a measurable stop.]),
  )
])
#area(450, 268, 462, [
  #caption[CLASS TARGETS AND OBSERVED TIMES · SECONDS EXCEPT WER]
  #v(4pt)
  #matrix((68pt, 150pt, 62pt, 67pt, 69pt, 46pt),
    ([Metric], [Definition], [Target ≤], [Mean], [p95], [n]), metrics, size: 8.35pt, inset-y: 2.3pt)
])

#card(48, 386, 277, 110, [DEMO · THREE HANDS-FREE TURNS], [
  #set text(size: 9.1pt)
  Start Pi with #raw("python3 setup.py run"), then toggle #raw("/me3 duplex").
  #v(4pt)
  #stack(spacing: 2.3pt,
    [1. “Draft a three-step soundcheck checklist.”],
    [2. “What is seven plus five?” → “12.”],
    [3. “Check the status of that checklist.”])
  #v(4pt)
  To try barge-in live, ask the second question while BMO is speaking.
])
#card(337, 386, 277, 110, [BMO RESULTS · MAC REPLAY, 21 NOV], [
  #set text(size: 8.7pt)
  VAD end to first task-specific speaker callback (ms).
  #v(3pt)
  #stack(spacing: 2pt, bar([Job accepted], 4260), bar([Answer “12”], 2207), bar([Same job status], 2814))
  #v(3pt)
  3/3 recorded replies · 5/5 routing checks · one saved draft. Each bar represents one digital turn.
])
#card(626, 386, 286, 110, [CHALLENGES & REFERENCES], [
  #set text(size: 9.1pt)
  The Pi 5 still needs a physical mic/speaker run. Measure interruption-to-silence (p95 ≤ 250 ms), substantive reply (p95 ≤ 1 s), and a 30-minute soak.
  #v(5pt)
  #text(size: 8.8pt, fill: teal)[
    #link(repo + "docs/BENCHMARK.md")[Class benchmark report] ·
    #link(repo + "docs/DUPLEX_STATUS.md")[BMO replay and status]
  ]
])
#footer(2)
