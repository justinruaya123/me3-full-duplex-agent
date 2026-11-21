"""Map explicit owner requests to the narrow operations the controller can accept."""

from __future__ import annotations

import re
from dataclasses import dataclass

from me3.lookup import EXPLICIT, lookup_intent


@dataclass(frozen=True)
class RequestedAction:
    kind: str
    argument: str
    command: str
    job_id: str | None = None


def requested_action(text: str) -> RequestedAction | None:
    """Preserve the complete request scope when validating an inference proposal."""
    if len(text) > 2048 or "\n" in text:
        return None
    polite = re.sub(
        r"^(?:please\s+|(?:can|could|would) you (?:please )?)", "", text, flags=re.I
    )
    if EXPLICIT.match(polite):
        intent = lookup_intent(polite)
        if intent:
            return RequestedAction("lookup", intent[0], polite)
    public_role = re.fullmatch(
        r"who (?:is|serves as) (?:the )?((?:mayor|president|prime minister|"
        r"governor|ceo|chairperson|leader) of [\w .'-]{1,100})\??",
        polite,
        re.I,
    )
    if public_role:
        return RequestedAction("lookup", public_role[1].rstrip(" ."), polite)
    delegate = re.fullmatch(r"delegate (?:a |the )?task to (.+)", polite, re.I)
    if delegate:
        return RequestedAction("job", delegate[1], "/task " + delegate[1])
    site = re.fullmatch(r"(?:build|create) (?:me )?(?:a )?website (.+)", polite, re.I)
    if site:
        return RequestedAction("job", site[1], "/site " + site[1])
    focus = re.fullmatch(r"focus on job ([a-zA-Z0-9]+)[.!]?", polite, re.I)
    if focus:
        return RequestedAction("focus", focus[1], "/focus " + focus[1], focus[1])
    memory = re.fullmatch(r"remember that (.+)", polite, re.I)
    if memory:
        return RequestedAction("memory", memory[1], polite)
    profile = re.fullmatch(
        r"(?:save|set) my (public|private|vocabulary) "
        r"profile field ([\w .-]{1,64}) (?:to|as) (.+)",
        polite,
        re.I,
    )
    if profile:
        command = f"/profile {profile[1].lower()} {profile[2]} = {profile[3]}"
        return RequestedAction("profile", profile[3], command)
    return None
