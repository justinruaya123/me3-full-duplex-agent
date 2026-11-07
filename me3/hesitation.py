"""Finite English transcript-tail veto; not a general stutter classifier."""

import re


def holds_turn(text: str) -> bool:
    """Veto listed unfinished tails without changing any recognized text.

    This can only withhold commitment. Acoustic readiness is still required
    when a later full transcript no longer has a listed tail. Earlier fillers
    and repetitions are deliberately retained and do not veto a continuation.
    """
    tail = text.strip()
    words = " ".join(re.findall(r"[a-z]+", tail.casefold().replace("'", "")))
    if re.search(
        r"\b(?:give me (?:a|one) (?:second|moment)|"
        r"let me think(?: about (?:it|that))?|"
        r"(?:i(?:ve)? )?lost my train of thought|"
        r"i forgot what i was going to say)(?: please)?$",
        words,
    ):
        return True
    if re.search(r"\b(?:u+h+|u+m+|e+r+m*|h+m+)$", words):
        return True
    # Retain explicit cutoffs and repeated one-letter syllables at the end.
    # Do not collapse repetitions elsewhere, including completed stutters.
    if re.search(r"[-–—]\s*[.!?]*$", tail):
        return True
    if re.search(r"(?:\.{3,}|…)[!?]*$", tail):
        return True
    if re.search(r"\b([a-z])(?:-\1)+[.!?]*$", tail, re.I):
        return True
    if re.search(r"\b(i|we|you|a|an|the|to|and|but) \1$", words):
        return True
    # These few dangling function words are a baseline, not a grammar parser.
    # Completed questions can legitimately end in a preposition ("send to?").
    return not tail.endswith("?") and bool(re.search(
        r"\b(?:a|an|the|to|and|but|because|with)$", words,
    ))
