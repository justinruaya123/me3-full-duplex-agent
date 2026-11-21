# Readable display

Open the project Pi window and select **Aa → Appearance → Readable**. The face, live captions, IntelligentUI dashboard, worker streams and embedded terminal share the palette in `integrations/voicechat/theme/design.tokens.json`. Classic is the initial setting. **Aa → Reset to defaults** restores Classic. The window saves settings on this host in `.local/window-appearance.json`. The font, size, spacing, reading surface and motion controls are available from either view.

The project launcher installs an optional native Pi palette in the ME3 agent profile. Select **bmo-readable** in Pi’s **/settings** to use it for the terminal’s ANSI content. Select the former Pi theme there to roll it back. Browser and native-terminal choices are independent. The adapter uses the installed Pi theme as a template and writes a single theme file. It leaves the operator’s settings file intact.

## Implementation map

At 800 × 600, the home face fits within the viewport at its original aspect ratio behind the controls and captions.
In IntelligentUI the same live face moves to the upper-right toolbar button.
Tap it to return home. The dashboard keeps its full content area below the toolbar.

| Surface | Implementation | Behavior |
| --- | --- | --- |
| Private Pi window | `integrations/voicechat/window.py`, `window.html`, `window.js`, `theme/readable.css` | Local PTY and WebSocket, device status, theme controls and validated local PNG inventory. Both themes draw the same verified original PNGs at their native proportions. |
| Playback and jobs | `integrations/voicechat/face.mjs`, `window.js` | Device playback events drive the speaking indicator. Recently ended playback receipts fence late events. Job snapshots update their own rows and the quiet count in Presence. |
| IntelligentUI | `integrations/voicechat/preview.mjs`, `visual.mjs`, `theme/display.mjs` | The host styles validated board rows and allowlisted semantic markup. The sandboxed preview can show source addresses as text. A mounted view has no speech or tool-dispatch authority. |
| Terminal | `theme/appearance.py`, `theme/install-pi.py` | Shared colors applied to the complete Pi 0.84.2 theme. The existing xterm.js 6.0.0 host sets terminal font metrics and refits the PTY. |

The speech inference service exposes model, ASR and TTS API routes. Its checkout has no inference-server dashboard to style. The display uses the existing controller’s interruption behavior. This theme adds no job-cancellation endpoint or camera integration.

## Publication and attribution

| Material | Origin and distribution |
| --- | --- |
| Original BMO face pack | Setup downloads thirteen pinned PNGs from the original project's repository and verifies their SHA-256 hashes. The window uses the speaking frames at 50 ms and cycles the listening and thinking frames at 500 ms. Reduce motion holds a single frame. The local PNGs and screenshots containing them stay outside public release archives. [Pinned original frames](https://github.com/brenpoly/be-more-agent/tree/5fb755809583c8338b1205075b2d465baa9b49ef/faces) |
| Atkinson Hyperlegible Next | Unmodified upright variable TTF. SHA-256 `5a455d1cfa099b601ab70751bb9673e8fe1854dc4500c80e1a220d0d75e31745`. Bundle `theme/fonts/atkinsonhyperlegiblenext-OFL.txt` with it. [Pinned source and notice](https://github.com/google/fonts/tree/afbb27a87bc4be2b0005e17c144831438e82ab37/ofl/atkinsonhyperlegiblenext) |
| Atkinson Hyperlegible Mono | Unmodified upright variable TTF. SHA-256 `5ce8b1698d1ded7dff2178c1a3ad159470085a58ea239e8b2cb88f4fb4a6f646`. Bundle `theme/fonts/atkinsonhyperlegiblemono-OFL.txt` with it. [Pinned source and notice](https://github.com/google/fonts/tree/3a0be2fdd3252b377a0851f0ba01c3609f99b7ab/ofl/atkinsonhyperlegiblemono) |
| Existing renderer and terminal dependencies | The partial-HTML processor retains its notice in `integrations/openintelligentui/LICENSE`. xterm.js, its fit addon and Pi retain their installed package notices. [Pinned OpenIntelligentUI source](https://github.com/CopilotKit/OpenIntelligentUI/tree/8391a94c1c3939c679e40ddd7bfc08a9ef690e70) |

The font licenses permit bundling with software when the copyright notice and license accompany each copy. All theme assets load locally. The typography and palette come from the operator-supplied handoff. Audio assets belong to the separate voice pilot. In particular, the pre-existing listening cue and two startup WAVs need their own provenance before including them in a public release. [SIL Open Font License 1.1](https://openfontlicense.org/open-font-license-official-text/)

## Reproduce the display check

After installing the existing window dependencies, run this command in the project environment with Playwright Chromium installed.

```sh
python -m integrations.voicechat.check_readable
python -m integrations.voicechat.check_readable --original-faces
```

The check opens a temporary loopback window backed by a real PTY, sends synthetic voice and job snapshots, and saves seven PNGs under `.local/theme-preview/`. It exercises both themes, large and narrow viewports, local font loading and fallback, malformed boards, settings persistence, reset, and the real IntelligentUI renderer and terminal. The second command also checks the installed images in Classic and Readable, exercises reduced motion, and masks the character in saved screenshots. No microphone, model provider or operator Pi session is needed. Physical display legibility, screen-reader use and before/after Pi latency, memory, frame timing and underruns still require target-device measurements.
