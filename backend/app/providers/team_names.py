import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


def _load_aliases() -> dict[str, Any]:
    """Load team alias mappings from JSON."""
    default_path = Path(__file__).parent.parent / "data" / "team_aliases.json"
    path = Path(os.getenv("TEAM_ALIASES_PATH", str(default_path)))
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"mappings": {}, "synonyms": []}


_ALIASES = _load_aliases()


_STOP_WORDS = {
    "fc",
    "cf",
    "united",
    "club",
    "clube",
    "athletic",
    "atletico",
    "atlético",
    "real",
    "de",
    "do",
    "da",
    "e",
    "the",
    "a",
    "futebol",
    "football",
    "soccer",
    "team",
    "esporte",
    "sports",
    "rn",
    "mg",
    "sp",
    "rj",
    "rs",
    "sc",
    "pr",
    "ba",
    "ce",
    "pe",
    "pa",
    "go",
    "mt",
    "ms",
    "am",
    "ac",
    "ro",
    "rr",
    "ap",
    "to",
    "ma",
    "pi",
    "al",
    "se",
    "pb",
}


def normalize_name(name: str) -> str:
    """Remove accents, punctuation and collapse whitespace."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _key(name: str) -> str:
    """Canonical key used for alias lookups."""
    return " ".join(normalize_name(name).split())


def canonical_team_name(name: str) -> str:
    """Return the canonical English/official team name if an alias exists.

    Falls back to the original input when no alias matches.
    """
    key = _key(name)
    canonical = _ALIASES.get("mappings", {}).get(key)
    if canonical:
        return canonical

    # Try without common stop words and suffixes
    tokens = [t for t in key.split() if t not in _STOP_WORDS]
    for length in range(len(tokens), 0, -1):
        for i in range(len(tokens) - length + 1):
            sub = " ".join(tokens[i : i + length])
            canonical = _ALIASES.get("mappings", {}).get(sub)
            if canonical:
                return canonical

    # Try replacing dashes/hyphens with spaces
    alt = key.replace("-", " ")
    if alt != key:
        canonical = _ALIASES.get("mappings", {}).get(alt)
        if canonical:
            return canonical

    return name


def resolve_team_names(team_a: str, team_b: str) -> tuple[str, str, list[str]]:
    """Resolve both team names and return canonical forms plus alternatives.

    Returns (team_a_canonical, team_b_canonical, alternative_queries) where
    alternative_queries can be used by search providers to search with both
    the original and translated names.
    """
    a_canon = canonical_team_name(team_a)
    b_canon = canonical_team_name(team_b)

    alternatives = []
    if a_canon.lower() != team_a.lower() or b_canon.lower() != team_b.lower():
        alternatives.append(f"{a_canon} vs {b_canon}")
        alternatives.append(f"{team_a} vs {team_b}")
    return a_canon, b_canon, alternatives
