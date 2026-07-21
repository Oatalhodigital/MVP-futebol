import os
from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    google_api_key: str | None = None
    google_cx: str | None = None
    cache_ttl_seconds: int = 60
    completeness_threshold: float = 0.3
    playwright_headless: bool = True
    provider_timeout_seconds: float = 60.0

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Isolated CSS selectors / text patterns for the 365Scores provider.
# These can be adjusted without touching the provider code.
SCORES365_SELECTORS = {
    "accept_cookies_button": 'button:has-text("Aceitar"), button:has-text("Accept"), button:has-text("Concordar")',
    "search_input": 'input[placeholder*="buscar" i], input[placeholder*="search" i], input[type="search"]',
    "search_button": 'button[type="submit"], button[aria-label*="buscar" i]',
    "match_card": 'a[href*="/match/"], a[href*="/jogo/"], [data-testid*="match"], .match-row, .event-row',
    "match_team_names": '[class*="team"], [class*="participant"], [class*="name"]',
    "match_score": '[class*="score"], [class*="result"]',
    "match_status": '[class*="status"], [class*="period"], [class*="time"]',
    "match_minute": '[class*="minute"], [class*="clock"]',
    "stat_row": '[class*="stat"], [class*="statistics"] li, .stat-row',
    "stat_label": '*',
    "stat_home_value": '*',
    "stat_away_value": '*',
}

SCORES365_TEXT_PATTERNS = {
    "score": r"(\d+)\s*[-:]\s*(\d+)",
    "minute": r"(\d{1,3})[\s']*?",
    "status": r"(ao vivo|live|intervalo|half[ -]?time|encerrado|finalizado|finished|final whistle|1º tempo|1st half|2º tempo|2nd half|pré[- ]?jogo|not started|agendado)",
    "corner": r"(?:escanteios|corners?)\s*[:\-]?\s*(\d+)\s*[-:]?\s*(\d+)",
    "shot": r"(?:chutes|shots?)\s*[:\-]?\s*(\d+)\s*[-:]?\s*(\d+)",
    "possession": r"(?:posse|possession)\s*[:\-]?\s*(\d+)%?\s*[-:]?\s*(\d+)%?",
    "yellow_card": r"(?:cartões amarelos|yellow cards?)\s*[:\-]?\s*(\d+)\s*[-:]?\s*(\d+)",
    "red_card": r"(?:cartões vermelhos|red cards?)\s*[:\-]?\s*(\d+)\s*[-:]?\s*(\d+)",
}

SCORES365_URLS = {
    "home": "https://www.365scores.com/pt-br",
    "search": "https://www.365scores.com/pt-br/search",
}
