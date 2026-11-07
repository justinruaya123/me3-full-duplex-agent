"""Small explicit conversation controls; no inferred authorization or model."""

import re


def wrapup(text: str) -> bool:
    words = " ".join(text.casefold().strip(" .!?").split())
    return words in {
        "that settles it", "that answers my question",
        "we're done with that topic", "let's wrap up this topic",
    }


def return_preference(text: str) -> tuple[str, str]:
    """Consume only a separate trailing instruction, never a quoted fragment."""
    match = re.fullmatch(
        r"(.+)[;.]\s*(only tell me when i ask|"
        r"tell me after we finish talking)[.!]?", text, re.I | re.S,
    )
    if match is None:
        return text, "ask_first"
    policy = (
        "ask_first" if match[2].casefold().startswith("only")
        else "after_topic"
    )
    return match[1].strip(), policy
