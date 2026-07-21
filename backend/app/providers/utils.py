import re
import unicodedata
from difflib import SequenceMatcher


STOP_WORDS = {
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


def normalize(name: str) -> str:
    """Remove accents, punctuation and collapse whitespace."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s]", " ", s.lower())
    s = re.sub(r"\s+", " ", s).strip()
    return s


def token_set(name: str) -> set[str]:
    return {t for t in normalize(name).split() if t and t not in STOP_WORDS}


def fuzzy_match(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def contains_team(text: str, team: str) -> bool:
    """Check whether the text likely mentions the team name."""
    if not team or not text:
        return False
    norm_text = normalize(text)
    norm_team = normalize(team)
    if norm_team in norm_text:
        return True
    tokens = token_set(team)
    if not tokens:
        return False
    text_tokens = set(norm_text.split())
    return bool(tokens & text_tokens) and len(tokens & text_tokens) >= max(1, len(tokens) - 1)


def status_from_text(text: str) -> tuple[str, str | None]:
    """Detect live match status and a period label from free text."""
    lowered = text.lower()

    finished_markers = [
        "encerrado",
        "finalizado",
        "finished",
        "final whistle",
        "fim do jogo",
        "apito final",
        " ft ",
        "full time",
        "ended",
        "jogo encerrado",
        "final da partida",
    ]
    halftime_markers = ["intervalo", "half time", "half-time", "halftime", "ht", "meio-tempo"]
    second_half_markers = [
        "2º tempo",
        "2nd half",
        "segundo tempo",
        "second half",
        "2o tempo",
        "2° tempo",
    ]
    first_half_markers = [
        "ao vivo",
        "live",
        "1º tempo",
        "1st half",
        "primeiro tempo",
        "first half",
        "em andamento",
        "em curso",
        "em jogo",
    ]
    scheduled_markers = [
        "agendado",
        "scheduled",
        "not started",
        "não iniciado",
        "nao iniciado",
        "proximo",
        "próximo",
        "upcoming",
    ]

    for marker in finished_markers:
        if marker in lowered:
            return ("finished", "Encerrado")
    for marker in halftime_markers:
        if marker in lowered:
            return ("live_halftime", "Intervalo")
    for marker in second_half_markers:
        if marker in lowered:
            return ("live_second_half", "2º tempo")
    for marker in first_half_markers:
        if marker in lowered:
            return ("live_first_half", "1º tempo")
    for marker in scheduled_markers:
        if marker in lowered:
            return ("scheduled", "Agendado")

    return ("unknown", None)


def extract_minute(text: str) -> int | None:
    """Extract current match minute from text."""
    patterns = [
        r"(\d{1,3})\s*['′\"”]",
        r"(\d{1,3})\s*(?:min|minuto|minute|min)\b",
        r"(?:min|minuto|minute|min)\s*[:\-]?\s*(\d{1,3})",
        r"\b(\d{1,3})\s*'\s*\+",
    ]
    for pat in patterns:
        for m in re.finditer(pat, text, re.IGNORECASE):
            value = int(m.group(1))
            if 0 <= value <= 120:
                return value
    return None


def extract_score_with_teams(
    text: str, team_a: str, team_b: str
) -> tuple[int | None, int | None]:
    """Find the most likely score for a match between team_a and team_b."""
    if not text:
        return None, None

    norm_a = normalize(team_a)
    norm_b = normalize(team_b)
    norm_text = normalize(text)
    # Build regex positions on normalized text for proximity scoring
    pos_a = [m.start() for m in re.finditer(re.escape(norm_a), norm_text)]
    pos_b = [m.start() for m in re.finditer(re.escape(norm_b), norm_text)]

    score_regex = re.compile(r"(\d{1,2})\s*[-–:]\s*(\d{1,2})")
    candidates = []
    for m in score_regex.finditer(text):
        g_a = int(m.group(1))
        g_b = int(m.group(2))
        # Sanity filter: professional matches rarely exceed 15 goals total
        if g_a > 15 or g_b > 15 or (g_a + g_b) > 20:
            continue

        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        context = text[start:end].lower()

        # Strong signal: both team names near the score pattern
        if contains_team(context, team_a) and contains_team(context, team_b):
            candidates.append((3, m))
            continue

        # Medium signal: one team name nearby
        if pos_a or pos_b:
            window = 200
            near_a = any(abs(m.start() - p) < window for p in pos_a) or any(
                abs(m.end() - p) < window for p in pos_a
            )
            near_b = any(abs(m.start() - p) < window for p in pos_b) or any(
                abs(m.end() - p) < window for p in pos_b
            )
            if near_a and near_b:
                candidates.append((2, m))
            elif near_a or near_b:
                candidates.append((1, m))

    if candidates:
        # Prefer candidate with strongest signal; if tied, earliest in text
        candidates.sort(key=lambda x: (-x[0], x[1].start()))
        best = candidates[0][1]
        return int(best.group(1)), int(best.group(2))

    # Last resort: the first sane score-looking pair
    for m in score_regex.finditer(text):
        g_a = int(m.group(1))
        g_b = int(m.group(2))
        if g_a <= 15 and g_b <= 15 and (g_a + g_b) <= 20:
            return g_a, g_b
    return None, None


STAT_PATTERNS = {
    "score": r"(\d{1,2})\s*[-–:]\s*(\d{1,2})",
    "corners": r"(?:escanteios?|corners?)[:\s\-]*(\d{1,3})\s*[-–:]\s*(\d{1,3})",
    "shots": r"(?:chutes?|(?:shots?)(?:\s*(?:a\s*gol|on\s*target))?)[:\s\-]*(\d{1,3})\s*[-–:]\s*(\d{1,3})",
    "shots_on_target": r"(?:chutes?\s*a\s*gol|(?:shots?\s*on\s*target))[:\s\-]*(\d{1,3})\s*[-–:]\s*(\d{1,3})",
    "possession": r"(?:posse|possession)[:\s\-]*(\d{1,3})%?\s*[-–:]\s*(\d{1,3})%?",
    "yellow_cards": r"(?:cart(?:[ãa]o|oes)\s+amarelo|yellow\s+cards?)[:\s\-]*(\d{1,3})\s*[-–:]\s*(\d{1,3})",
    "red_cards": r"(?:cart(?:[ãa]o|oes)\s+vermelho|red\s+cards?)[:\s\-]*(\d{1,3})\s*[-–:]\s*(\d{1,3})",
}


def extract_stat_pairs(text: str) -> dict[str, tuple[int, int] | None]:
    """Extract common statistic pairs from a block of text."""
    results: dict[str, tuple[int, int] | None] = {}
    for key, pattern in STAT_PATTERNS.items():
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                results[key] = (int(m.group(1)), int(m.group(2)))
            except (IndexError, ValueError):
                results[key] = None
    return results
