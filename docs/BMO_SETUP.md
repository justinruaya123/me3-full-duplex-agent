# Install BMO on a Mac or a Raspberry Pi 5

Use a fresh checkout, a microphone and a speaker. Raspberry Pi OS must be 64-bit.
Run the installer as your regular user. On a Mac the system-dependency option
uses Homebrew. On Raspberry Pi OS it uses sudo for apt and Chromium's system
libraries. If the machine already has its OS prerequisites, omit that option.

```sh
python3 setup.py install-bmo --system-deps
python3 setup.py run
```

Enter `/me3 duplex` in Pi to toggle the microphone. The terminal works on Pi OS
Lite. On a desktop, `python3 setup.py run --window` opens the companion window.
The BMO profile uses Deepgram for streaming transcription, local Pi.dev with
OpenRouter for conversation and jobs, and local Piper for speech. The optional
Parakeet profile requires `ME3_ASR_BACKEND=parakeet`, `ME3_PARAKEET_URL`
and `ME3_ASR_TOKEN`. The older course launcher is available through `start.py`.

With the microphone on, say “Hey BMO” and pause for a short local greeting.
Say “Hey BMO, what is seven plus five?” in one breath to go straight to the
answer. When a completed request needs more time, a soft tone acknowledges
it once. A hesitation or unfinished thought normally stays quiet. For spoken
listening cues during longer explanations, use `/me3 overlap on`.
The default delay for the end-of-turn tone is 160 ms after commitment.
Set `ME3_WAIT_CUE_MS` to tune it for your device.

A follow-up continues the current chat. Ask a public factual question for a
short spoken answer. BMO answers confidently known stable facts directly. When a public fact is uncertain
or time-sensitive and a live lookup starts, the idle voice says “Searching.”
“Can you make a checklist?” is a Pi request, not a search. “Can you search for…”
explicitly requests a lookup. Personal questions stay in Pi. A recently named person can be referred
to as “he” or “she” on the next turn. Say “search for” to browse linked Brave results in
IntelligentUI. When the account lacks Brave Answers, Pi summarizes the Brave Web
excerpts. BMO speaks the main finding in one or two sentences, even when you
ask to see links. URLs and longer details stay on screen. For an edit to an
existing assignment, refer to it by name. Pi sends
the change to the same job at its next revision.

Setup creates a project Python environment (3.11 through 3.13), installs the locked
Pi CLI and Brave plugin, and prepares the bundled extensions, Superpowers skills,
renderer, Chromium, the original BMO face frames and the BMO voice. To repair
the thirteen face PNGs, run `python3 -m integrations.voicechat.face_assets`
from the checkout. The installer uses a compatible Node on PATH or downloads
a checksum-verified Node under `.local/node`. The project Pi profile and trust
store live under `.local/pi`. Trust is specific to the checkout. For a previously
denied folder, use `bash integrations/voicechat/start.sh --trust-project` after
reviewing the folder. System Pi settings are independent.

**Computer use.** Start a fresh terminal session with `python3 setup.py run --computer-use`.
The foreground Pi can find an app, read its controls and text, and request
approval to click or type. In duplex mode, answer the approval aloud. For a
read-only demo, open Calculator and say “What does Calculator display?”
On macOS, enable Accessibility and Screen & System Audio Recording for
`.local/pi/helpers/pi-computer-use.app` in System Settings → Privacy & Security.
The helper is installed inside the checkout. Desktop tools require a graphical session.

**Keys.** The wizard asks for OpenRouter and Deepgram for voice, Brave Search for
web lookups, and an optional separate Brave Answers key. Press Enter to preserve
a saved value or skip a service. To provision without a terminal, use
`python3 setup.py install-bmo --no-prompt`. To enter keys later, use
`python3 setup.py configure`. Shell environment credentials also work with the
fresh template. Edit the private `.env` to select foreground and worker models.
Run `python3 setup.py check` with the keys configured and audio devices attached
to check the local installation. This exercises SmartTurn with synthetic silence.

## Build a site with current sources or supplied copy

For example, ask “Build a website about the latest Python releases.” BMO
looks up the public topic first and sends the results to the website worker
for a sourced draft. If current evidence cannot be verified, it should say so
rather than publish guesses. For a personal page, include text you want on it
in the request, e.g. “Build a site for Ana Diaz. Include this introduction:
I build small wooden boats.” A name alone is enough for a starter, not a bio.

## Publish a BMO website to GitHub Pages

Launch `python3 setup.py run --window` for the updating IntelligentUI canvas.
Enable the microphone with `/me3 duplex`. Say **“Hey BMO, search more about me
and build a portfolio website on the canvas.”** Pi searches Brave using your
public search name and offers up to three sourced facts. Say **“Use the first
and third”** or **“Approve all.”** If BMO asks for a name, say **“Search for YOUR NAME”**
and confirm the name BMO reads back. Set **Public search name** in the private
`USER.md` under `.local/voice-prompts` to use that identity immediately.

The canvas embeds the draft as the website builds, then loads the verified
`index.html` and its local assets. The researched portfolio includes its CSS
inside the HTML. In **Agents**, **Download HTML** saves the portfolio as a
standalone page. **Download GitHub Pages ZIP** includes all assets for a
multi-file site.

Install `git` and `gh` on the BMO host. Sign in with `gh auth login` and check
`gh api user --jq .login` to see which account will be used. In the native
ME3 Pi terminal, resume the chat containing the completed website. Replace
`REPO` with an existing repository owned by the signed-in user:

- `/me3 push REPO` — commit the verified snapshot and run `git push` to
  `bmo-pages`, without changing Pages settings.
- `/me3 publish REPO` — do the same push, then configure GitHub Pages to
  serve the root of `bmo-pages`. A deployment is not necessarily live yet.

The command itself authorizes the push: **no second popup**. Both commands
also accept `OWNER/REPO`. In conversation, say “Push this site to GitHub for
OWNER/REPO” or “Publish this site to GitHub Pages for OWNER/REPO.” Never put
tokens in the request. The host checks the actual account, repository, write
access, job revision and file hashes. An unfinished site, another owner's repo
or a bare “push it” is not enough. The standalone branch is a full snapshot:
files no longer in the site are removed from that branch; other branches and
your project checkout are not modified. An existing Pages setup watching this
branch can automatically deploy even on a plain push.

## Move settings and private prompts

On the source checkout:

```sh
python3 setup.py export-config bmo-config.json
scp bmo-config.json your-pi:~/bmo-config.json
```

On the Pi, clone the same revision, enter the new checkout and run:

```sh
python3 setup.py import-config ~/bmo-config.json
python3 setup.py install-bmo --system-deps
python3 setup.py run
```

The export contains portable model, voice, reasoning and memory preferences and
the editable Markdown prompts, including any personal notes in `USER.md`.
Keep it private. Supply keys on the destination. Audio indices, runtime paths,
Pi login, chats, jobs, trust and installed models are device-local. The installer
rebuilds the environment and renders the canned replies on the destination.

For older installations that share an environment across Git worktrees, pass
`--env-file /path/to/.env` and `--prompt-dir /path/to/.local/voice-prompts`
to `export-config`. Import before first setup on a new device. On a configured
device, differing prompts require `--replace-prompts` to overwrite them.
For the historical class benchmark, the launcher applies its own pinned profile.

Mac installation and simulation results are recorded in
[DUPLEX_STATUS.md](DUPLEX_STATUS.md). Raspberry Pi 5 native dependencies,
microphone access, real-time synthesis and duplex latency need a board run.

For the digital spoken-routing benchmark, install its audio dependencies into
the same Python environment that runs `benchmark.py`. On macOS use
`.venv313/bin/python -m pip install -e '.[benchmark-audio]'`. On Linux use
`.venv-pi/bin/python`. The class rig uses SciPy to convert 24 kHz speaker
output to its 16 kHz measurement clock.

To replay the same three inputs, pass their previous output directory to
`--replay-inputs`. The command uses the live providers and creates a fresh
Pi chat and private draft worker. Set the paths to your class checkout and
private benchmark environment.

```sh
.venv313/bin/python benchmark.py spoken-routing --replay-inputs /path/to/previous-run \
  --fdbench /path/to/class-benchmark --env-file /path/to/benchmark.env
```

The output directory contains the recordings, the worker's saved `draft.md`
and `routing.json` with per-turn tool receipts and first reply-audio times.
