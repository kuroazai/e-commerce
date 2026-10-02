"""Matching a marketplace listing title to something you own.

Nobody lists a card as "Dark Magician". They list it as
"Yugioh Dark Magician LOB-005 1st Edition Ultra Rare NM Near Mint". Exact-name
matching against inventory therefore fails on almost every real sale, which is
how a sales pipeline silently stops decrementing stock.

This is deliberately deterministic. Token overlap handles the overwhelming
majority for free, and only genuinely ambiguous cases are worth escalating to an
LLM - see `cardshop.agents`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Words that appear in nearly every listing title and carry no identity.
NOISE_WORDS = frozenset({
    "yugioh", "yu", "gi", "oh", "ygo", "card", "cards", "tcg", "ccg",
    "1st", "first", "edition", "unlimited", "limited",
    "ultra", "super", "secret", "rare", "common", "ghost", "starlight",
    "nm", "mint", "near", "lp", "played", "ex", "excellent", "good",
    "english", "eng", "genuine", "official", "konami",
    "free", "post", "postage", "uk", "fast", "dispatch",
})

#: Two candidates within this much of each other are not distinguishable by
#: name alone, and only a set code can separate them.
AMBIGUITY_GAP = 0.1

SET_CODE = re.compile(r"\b[A-Z]{2,4}[- ]?(?:EN)?\d{3}\b", re.IGNORECASE)
NON_WORD = re.compile(r"[^a-z0-9 ]+")


def extract_set_code(title: str) -> str:
    """Pull a set code like LOB-005 or SDK-EN001 out of a title, if present.

    A set code is the single most reliable signal in a messy title, because it is
    unambiguous where the name may not be.
    """
    found = SET_CODE.search(title or "")
    return found.group(0).upper().replace(" ", "-") if found else ""


def tokenise(title: str) -> list[str]:
    """Lowercase, strip punctuation and set codes, drop noise words."""
    text = SET_CODE.sub(" ", (title or "").lower())
    text = NON_WORD.sub(" ", text)
    return [t for t in text.split() if t and t not in NOISE_WORDS and len(t) > 1]


@dataclass(frozen=True)
class TitleMatch:
    item: dict
    score: float
    set_code_matched: bool

    @property
    def confident(self) -> bool:
        """A set code agreeing is strong evidence on its own; without one, the
        name tokens have to overlap heavily."""
        return self.set_code_matched or self.score >= 0.80


def score_title(title: str, card_name: str, set_code: str = "") -> tuple[float, bool]:
    """How well a listing title matches a known card. Returns (score, code_matched)."""
    title_tokens = set(tokenise(title))
    name_tokens = set(tokenise(card_name))
    if not name_tokens:
        return 0.0, False

    overlap = len(title_tokens & name_tokens) / len(name_tokens)
    code = extract_set_code(title)
    wanted = set_code.upper().replace("-", "")
    code_matched = bool(code and wanted and code.replace("-", "") == wanted)

    # A matching set code lifts a partial name match over the line; it cannot
    # rescue a score of zero, which would mean the name shares nothing at all.
    score = min(1.0, overlap + 0.25) if code_matched and overlap > 0 else overlap
    return round(score, 3), code_matched


def match_title(title: str, items: list[dict], *, limit: int = 3) -> list[TitleMatch]:
    """Rank inventory items against a marketplace listing title."""
    matches = []
    for item in items:
        score, code_matched = score_title(
            title, item.get("card_name", ""), item.get("set_code", "")
        )
        if score > 0:
            matches.append(TitleMatch(item, score, code_matched))
    matches.sort(key=lambda m: (-m.score, not m.set_code_matched))
    return matches[:limit]


def best_match(title: str, items: list[dict]) -> TitleMatch | None:
    """The single best match, or None when it is too close to call.

    Returns None on an ambiguous tie rather than guessing: picking arbitrarily
    decrements the wrong card and the error is invisible until someone tries to
    post an order.
    """
    matches = match_title(title, items)
    if not matches or not matches[0].confident:
        return None
    too_close = (
        len(matches) > 1
        and (matches[0].score - matches[1].score) < AMBIGUITY_GAP
        and not matches[0].set_code_matched
    )
    return None if too_close else matches[0]
