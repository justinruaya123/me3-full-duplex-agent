# Readable display

Open the project Pi window and select **Aa → Appearance → Readable**. The face, live captions, IntelligentUI dashboard, worker streams and embedded terminal share the palette in `integrations/voicechat/theme/design.tokens.json`. Classic is the initial setting. **Aa → Reset to defaults** restores Classic. The window saves settings on this host in `.local/window-appearance.json`. The font, size, spacing, reading surface and motion controls are available from either view.

The project launcher installs an optional native Pi palette in the ME3 agent profile. Select **bmo-readable** in Pi’s **/settings** to use it for the terminal’s ANSI content. Select the former Pi theme there to roll it back. Browser and native-terminal choices are independent. The adapter uses the installed Pi theme as a template and writes a single theme file. It leaves the operator’s settings file intact.

## Implementation map

At 800 × 600, the home face fills the viewport behind the controls and captions.
In IntelligentUI the same live face moves to the upper-right toolbar button.
Tap it to return home. The dashboard keeps its full content area below the toolbar.

| Surface | Implementation | Behavior |
| --- | --- | --- |
| Private Pi window | `integrations/voicechat/window.py`, `window.html`, `window.js`, `theme/readable.css` | Local PTY and WebSocket, device status, theme controls and validated local PNG inventory. The default public artwork uses HTML and CSS. |
| Playback and jobs | `integrations/voicechat/face.mjs`, `window.js` | Device playback events drive the speaking indicator. Recently ended playback receipts fence late events. Job snapshots update their own rows and the quiet count in Presence. |
| IntelligentUI | `integrations/voicechat/preview.mjs`, `visual.mjs`, `theme/display.mjs` | The host styles validated board rows and allowlisted semantic markup. The sandboxed preview can show source addresses as text. A mounted view has no speech or tool-dispatch authority. |
| Terminal | `theme/appearance.py`, `theme/install-pi.py` | Shared colors applied to the complete Pi 0.84.2 theme. The existing xterm.js 6.0.0 host sets terminal font metrics and refits the PTY. |

The speech inference service exposes model, ASR and TTS API routes. Its checkout has no inference-server dashboard to style. The display uses the existing controller’s interruption behavior. This theme adds no job-cancellation endpoint or camera integration.

## Publication and attribution

| Material | Origin and distribution |
| --- | --- |
| Public display artwork | The geometric instrument, lens and activity bars are drawn in the project stylesheet. The seven browser-check screenshots use that design, even on a machine with private face frames installed. |
| Optional local face pack | Classic and Readable both display the installed BMO frames, including the error face on disconnect. The reference author describes the repository and voice model as a non-commercial fan project. We could verify an MIT notice for source code and could not establish redistribution permission for the character images. The local PNGs are ignored by Git. An image release or transfer archive must also exclude them and any screenshots reproducing them. [Pinned upstream README](https://github.com/brenpoly/be-more-agent/blob/5fb755809583c8338b1205075b2d465baa9b49ef/README.md) |
| Atkinson Hyperlegible Next | Unmodified upright variable TTF. SHA-256 `5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745`. Bundle `theme/fonts/atkinsonhyperlegiblenext-OFL.txt` with it. [Pinned source and notice](https://github.com/google/fonts/tree/afbb27a87bc4be2b0005e17c144831438e82ab37/ofl/atkinsonhyperlegiblenext) |
| Atkinson Hyperlegible Mono | Unmodified upright variable TTF. SHA-256 `5ce8b1698d1ded7dff2178c1a3ad159470085a58ea239e8b2cb88f4fb4a6f646`. Bundle `theme/fonts/atkinsonhyperlegiblemono-OFL.txt` with it. [Pinned source and notice](https://github.com/google/fonts/tree/3a0be2fdd3252b377a0851f0ba01c3609f99b7ab/ofl/atkinsonhyperlegiblemono) |
| Existing renderer and terminal dependencies | The partial-HTML processor retains its notice in `integrations/openintelligentui/LICENSE`. xterm.js, its fit addon and Pi retain their installed package notices. [Pinned OpenIntelligentUI source](https://github.com/CopilotKit/OpenIntelligentUI/tree/8391a94c1c3939c679e40ddd7bfc08a9ef690e70) |

The font licenses permit bundling with software when the copyright notice and license accompany each copy. All theme assets load locally. The typography and palette come from the operator-supplied handoff. Audio assets belong to the separate voice pilot. In particular, the pre-existing listening cue and two startup WAVs need their own provenance before including them in a public release. [SIL Open Font License 1.1](https://openfontlicense.org/open-font-license-official-text/)

## Reproduce the display check

After installing the existing window dependencies, run this command in the project environment with Playwright Chromium installed.

```sh
python -m integrations.voicechat.check_readable
```

The check opens a temporary loopback window backed by a real PTY, sends synthetic voice and job snapshots, and saves seven PNGs under `.local/theme-preview/`. It exercises both themes, large and narrow viewports, local font loading and fallback, malformed boards, settings persistence, reset, and the real IntelligentUI renderer and terminal. No microphone, model provider or operator Pi session is needed. Physical display legibility, screen-reader use and before/after Pi latency, memory, frame timing and underruns still require target-device measurements.
