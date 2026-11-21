"""Install the optional design-token projection into the project's Pi profile."""

import json
import sys
from pathlib import Path

from appearance import ROOT, pi_theme

profile = Path(sys.argv[1])
builtin = (
    ROOT.parent
    / "node_modules/@earendil-works/pi-coding-agent/dist/modes/interactive/theme/light.json"
)
destination = profile / "themes/bmo-readable.json"
destination.parent.mkdir(parents=True, exist_ok=True)
value = json.dumps(pi_theme(builtin), indent=2) + "\n"
if not destination.exists() or destination.read_text() != value:
    destination.write_text(value)
