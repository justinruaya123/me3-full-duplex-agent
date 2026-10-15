# Apply this prototype to the requested branch

The GitHub write was blocked by a tool safety check. This package is the tested
source, not a claim of a remote commit. The original main branch was unchanged at
verification: 464200f390470a5b701247cadefb75c82400ef14.

Download me3-full-duplex-preliminary.patch, then run:

```sh
git clone https://github.com/justinruaya123/me3-full-duplex-agent.git
cd me3-full-duplex-agent
git switch -c preliminary
git apply --check /path/to/me3-full-duplex-preliminary.patch
git apply --index /path/to/me3-full-duplex-preliminary.patch
python -m me3 demo
git commit -m "Add preliminary OnIt duplex orchestration prototype"
git push -u origin preliminary
```

The patch only adds files and preserves the existing .gitignore. If a preliminary
branch or these files were added later, review/reconcile that work instead of
force-pushing or overwriting it. The source ZIP is an alternative to the patch.

The demo is credential-free and explicitly simulated. Real OnIt, MCP and audio
installation instructions and untested boundaries are in README.md/STATUS.md.
