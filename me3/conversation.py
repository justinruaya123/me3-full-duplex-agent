"""Small explicit conversation controls; no inferred authorization or model."""

import re


def wrapup(text: str) -> bool:
    words = " ".join(text.casefold().strip(" .!?").split())
    return words in {
        "that settles it", "that answers my question",
        "we're done with that topic", "let's wrap up this topic",
    }


def return_preference(text: str) -> tuple[str, str]:
    """Consume only a separate trailing return instruction."""
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


def listening_safe(text: str) -> bool:
    """Conservative English cue gate; this hint never commits recognition."""
    words = text.split()
    if len(words) < 4:
        return False
    if any(word[:1].isupper() for word in words[1:]):
        return False
    return re.search(
        r"[\d`{}<>/=]|\b(?:name|numbers?|digits?|code|python|address|password|"
        r"zero|one|two|three|four|five|six|seven|eight|nine|ten|"
        r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|"
        r"eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|"
        r"eighty|ninety|hundred|thousand|million|"
        r"approve|approval|cancel|delete|website|task|dictate|dictation|"
        r"spelling)\b", text, re.I,
    ) is None
