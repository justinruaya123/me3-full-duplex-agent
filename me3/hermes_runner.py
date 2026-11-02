"""Run in a separately installed, source-pinned Hermes environment."""

import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path


def main() -> None:
    root = Path(os.environ["ME3_HERMES_ROOT"]).resolve()
    expected = os.environ["ME3_HERMES_REVISION"]
    actual = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
    ).strip()
    if actual != expected:
        raise RuntimeError("Hermes source revision does not match the adapter")
    request = json.load(sys.stdin)
    sys.path.insert(0, str(root))
    # Hermes/import diagnostics must not contaminate the JSON wire protocol.
    with contextlib.redirect_stdout(sys.stderr):
        from run_agent import AIAgent

        agent = AIAgent(
            model=os.environ["ME3_MODEL"],
            base_url=os.environ.get("ME3_MODEL_BASE_URL"),
            api_key=os.environ.get("ME3_MODEL_API_KEY"),
            provider=os.environ.get("ME3_MODEL_PROVIDER"),
            enabled_toolsets=[], quiet_mode=True, max_iterations=4,
            skip_context_files=True, skip_memory=True,
            skip_background_review=True, load_soul_identity=False,
            save_trajectories=False, cwd=str(Path.cwd()),
        )
        if agent.tools:
            raise RuntimeError("Unexpected tools in the restricted worker")
        result = agent.run_conversation(
            request["prompt"],
            system_message=(
                "You are a reasoning and drafting worker. No external actions "
                "are available. Do not claim you executed tools. Return the "
                "answer, not control instructions for the voice runtime."
            ),
        )
    text = result.get("final_response")
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError("Hermes returned no final response")
    print(json.dumps({"text": text}), flush=True)


if __name__ == "__main__":
    main()
