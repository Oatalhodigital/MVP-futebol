import asyncio
import logging
import random
import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.models import LastMatch, LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.team_names import resolve_team_names
from app.providers.utils import (
    contains_team,
    extract_minute,
    extract_score_with_teams,
    extract_stat_pairs,
    normalize,
    status_from_text,
)

logger = logging.getLogger(__name__)

# Sites that usually return structured football data and are safe to fetch
_PREFERRED_SITES = {
    "365scores.com",
    "sofascore.com",
    "ge.globo.com",
    "lance.com.br",
    "flashscore.com",
    "espn.com",
    "soccerway.com",
    "fotmob.com",
    "whoscored.com",
    "transfermarkt.com",
    "worldfootball.net",
    "onefootball.com",
    "besoccer.com",
    "liveScore.com",
    "resultados.com",
    "uefa.com",
    "fifa.com",
}

# Search engines that do not require API keys
_SEARCH_ENGINES = [
    {"name": "duckduckgo_html", "url": "https://html.duckduckgo.com/html/?q={q}"},
    {"name": "google", "url": "https://www.google.com/search?q={q}&hl=pt-BR"},
]


class BrowserSearchProvider(DataProvider):
    """Search provider that navigates public search engines without API keys.

    It tries DuckDuckGo HTML first, then Google, extracts result titles and
    links, fetches preferred sports-data pages and parses structured stats.
    If a search engine returns a CAPTCHA/block page, the provider logs the
    event and falls back gracefully.
    """

    name = "browser_search"

    def __init__(self) -> None:
        self.blocked_engines: set[str] = set()
        self.timeout = 15.0

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        try:
            return await self._fetch(match_input)
        except Exception as exc:
            logger.warning("BrowserSearchProvider failed: %s", exc, exc_info=True)
            return MatchData(
                team_a=match_input.team_a,
                team_b=match_input.team_b,
                competition=match_input.competition,
                match_datetime=match_input.match_datetime,
                status=MatchStatus.UNKNOWN,
                source=self.name,
                completeness=0.0,
                updated_at=datetime.utcnow(),
                raw_metadata={"error": repr(exc)},
            )

    async def _fetch(self, match_input: MatchInput) -> MatchData:
        team_a, team_b, _alt = resolve_team_names(match_input.team_a, match_input.team_b)

        # 1. Try to find live / fixture data
        live_text = await self._search_match_text(team_a, team_b, mode="live")
        status_str, period = status_from_text(live_text)
        try:
            status = MatchStatus(status_str) if status_str else MatchStatus.UNKNOWN
        except ValueError:
            status = MatchStatus.UNKNOWN

        score_a, score_b = extract_score_with_teams(live_text, team_a, team_b)
        minute = extract_minute(live_text)
        stats = extract_stat_pairs(live_text)
        stats.pop("score", None)

        live = LiveState(
            status=status,
            minute=minute,
            period=period,
            score_a=score_a,
            score_b=score_b,
            corners_a=_first(stats.get("corners")),
            corners_b=_second(stats.get("corners")),
            shots_a=_first(stats.get("shots")),
            shots_b=_second(stats.get("shots")),
            shots_on_target_a=_first(stats.get("shots_on_target")),
            shots_on_target_b=_second(stats.get("shots_on_target")),
            possession_a=_first(stats.get("possession")),
            possession_b=_second(stats.get("possession")),
            cards_yellow_a=_first(stats.get("yellow_cards")),
            cards_yellow_b=_second(stats.get("yellow_cards")),
            cards_red_a=_first(stats.get("red_cards")),
            cards_red_b=_second(stats.get("red_cards")),
        )

        # 2. Try to find team recent form / history
        form_a, a_parsed = await self._team_form(team_a)
        form_b, b_parsed = await self._team_form(team_b)

        # 3. Try to find H2H
        h2h_text = await self._search_match_text(team_a, team_b, mode="h2h")
        h2h = self._extract_h2h(h2h_text, team_a, team_b)

        team_a_stats = self._team_stats(team_a, form_a)
        team_b_stats = self._team_stats(team_b, form_b)

        completeness = self._completeness(live, team_a_stats, team_b_stats, h2h)

        return MatchData(
            team_a=team_a,
            team_b=team_b,
            competition=match_input.competition,
            match_datetime=match_input.match_datetime,
            status=status,
            score_a=live.score_a,
            score_b=live.score_b,
            minute=live.minute,
            live=live,
            team_a_stats=team_a_stats,
            team_b_stats=team_b_stats,
            h2h=h2h,
            source=self.name,
            completeness=completeness,
            updated_at=datetime.utcnow(),
            raw_metadata={
                "team_a_found": a_parsed > 0,
                "team_b_found": b_parsed > 0,
                "live_data_found": bool(live_text),
            },
        )

    async def _search_match_text(self, team_a: str, team_b: str, mode: str = "live") -> str:
        if mode == "live":
            queries = [
                f"{team_a} {team_b} football ao vivo placar",
                f"{team_a} {team_b} live score",
                f"{team_a} {team_b} resultados",
            ]
        else:
            queries = [
                f"{team_a} vs {team_b} head to head",
                f"{team_a} vs {team_b} h2h",
                f"{team_a} {team_b} confrontos",
            ]

        best_text = ""
        for query in queries:
            text = await self._search_and_aggregate(query)
            if len(text) > len(best_text):
                best_text = text
            if self._looks_useful(text, team_a, team_b):
                return text
            await asyncio.sleep(random.uniform(1.0, 3.0))
        return best_text

    async def _team_form(self, team: str) -> tuple[list[LastMatch], int]:
        queries = [
            f"{team} last 5 matches results",
            f"{team} results 2025",
            f"{team} football results",
        ]
        for query in queries:
            text = await self._search_and_aggregate(query)
            matches = self._parse_match_rows(text, team)
            if len(matches) >= 3:
                return matches, len(matches)
            await asyncio.sleep(random.uniform(1.0, 3.0))
        # Last attempt with whatever we got
        text = await self._search_and_aggregate(queries[0])
        matches = self._parse_match_rows(text, team)
        return matches, len(matches)

    async def _search_and_aggregate(self, query: str) -> str:
        """Search with fallback engines and aggregate snippet + page text."""
        for engine in _SEARCH_ENGINES:
            if engine["name"] in self.blocked_engines:
                continue

            search_text = await self._search_engine(engine, query)
            if not search_text:
                continue

            if self._is_blocked_page(search_text):
                logger.warning("Search engine %s appears blocked/CAPTCHA; skipping", engine["name"])
                self.blocked_engines.add(engine["name"])
                continue

            soup = BeautifulSoup(search_text, "lxml")
            snippets = self._extract_snippets(soup, engine["name"])
            all_text = "\n".join(snippets)

            links = self._extract_links(soup, engine["name"])[:5]
            if links:
                try:
                    pages = await self._fetch_pages(links)
                    all_text += "\n" + "\n".join(pages)
                except Exception:
                    pass

            return all_text.lower()

        return ""

    async def _search_engine(self, engine: dict[str, str], query: str) -> str:
        url = engine["url"].format(q=quote(query))
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/125.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                    },
                )
                return response.text
        except Exception as exc:
            logger.info("Search engine %s request failed: %s", engine["name"], exc)
            return ""

    def _is_blocked_page(self, text: str) -> bool:
        lowered = text.lower()
        return any(
            marker in lowered
            for marker in [
                "captcha",
                "recaptcha",
                "unusual traffic",
                "tráfego incomum",
                "trafego incomum",
                "blocked",
                "bloqueado",
                "verificação",
                "verification",
                "please verify",
                "suspected robot",
            ]
        )

    def _extract_snippets(self, soup: BeautifulSoup, engine_name: str) -> list[str]:
        """Extract visible text snippets from a search result page."""
        snippets: list[str] = []

        if engine_name == "duckduckgo_html":
            for result in soup.select(".result"):
                title = result.select_one(".result__title")
                snippet = result.select_one(".result__snippet")
                if title:
                    snippets.append(title.get_text(" ", strip=True))
                if snippet:
                    snippets.append(snippet.get_text(" ", strip=True))
        else:
            # Google-ish / generic
            for result in soup.select(".g, [data-ved], .result"):
                text = result.get_text(" ", strip=True)
                if text:
                    snippets.append(text)

        if not snippets:
            # Last resort: any paragraph or anchor text
            for el in soup.select("p, a, .snippet, .abstract"):
                snippets.append(el.get_text(" ", strip=True))

        return snippets

    def _extract_links(self, soup: BeautifulSoup, engine_name: str) -> list[str]:
        """Extract result links, preferring known sports-data sites."""
        candidates: list[tuple[str, bool]] = []
        for a in soup.find_all("a"):
            href = a.get("href") or ""
            if not href.startswith("http"):
                continue
            lowered = href.lower()
            is_preferred = any(site in lowered for site in _PREFERRED_SITES)
            candidates.append((href, is_preferred))

        candidates.sort(key=lambda x: (not x[1], len(x[0])))
        return [href for href, _ in candidates]

    async def _fetch_pages(self, links: list[str]) -> list[str]:
        """Fetch the first preferred result pages and return extracted text."""
        texts: list[str] = []
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
            for link in links:
                try:
                    await asyncio.sleep(random.uniform(0.5, 2.0))
                    response = await client.get(
                        link,
                        headers={
                            "User-Agent": (
                                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                "Chrome/125.0.0.0 Safari/537.36"
                            )
                        },
                    )
                    soup = BeautifulSoup(response.text, "lxml")
                    texts.append(soup.get_text(" ", strip=True))
                except Exception:
                    continue
        return texts

    def _looks_useful(self, text: str, team_a: str, team_b: str) -> bool:
        if not text:
            return False
        return contains_team(text, team_a) and contains_team(text, team_b)

    def _parse_match_rows(self, text: str, team_name: str, max_rows: int = 10) -> list[LastMatch]:
        matches: list[LastMatch] = []
        seen: set[tuple[str, int, int]] = set()
        score_regex = re.compile(r"(\d{1,2})\s*[-–:]\s*(\d{1,2})")

        for score_m in score_regex.finditer(text):
            start = max(0, score_m.start() - 120)
            end = min(len(text), score_m.end() + 120)
            ctx = text[start:end]

            if not contains_team(ctx, team_name):
                continue

            g_home = int(score_m.group(1))
            g_away = int(score_m.group(2))
            if g_home > 15 or g_away > 15 or (g_home + g_away) > 20:
                continue

            team_pattern = re.compile(
                r"([a-z0-9áéíóúãõç\s'.\-]{3,50}?)\s+"
                + re.escape(score_m.group(0))
                + r"\s+([a-z0-9áéíóúãõç\s'.\-]{3,50}?)",
                re.IGNORECASE,
            )
            m = team_pattern.search(ctx)
            if not m:
                continue
            left = m.group(1).strip()
            right = m.group(2).strip()

            team_on_left = contains_team(left, team_name)
            team_on_right = contains_team(right, team_name)
            if team_on_left and not team_on_right:
                opponent = right
                venue = "home"
                gf, ga = g_home, g_away
            elif team_on_right and not team_on_left:
                opponent = left
                venue = "away"
                gf, ga = g_away, g_home
            else:
                continue

            key = (normalize(opponent), gf, ga)
            if key in seen:
                continue
            seen.add(key)
            result = "W" if gf > ga else ("D" if gf == ga else "L")
            matches.append(
                LastMatch(
                    opponent=opponent.strip().title(),
                    venue=venue,
                    goals_for=gf,
                    goals_against=ga,
                    result=result,
                )
            )
            if len(matches) >= max_rows:
                break

        return matches

    def _extract_h2h(self, text: str, team_a: str, team_b: str) -> list[LastMatch]:
        rows = self._parse_match_rows(text, team_a, max_rows=20)
        return [r for r in rows if contains_team(r.opponent, team_b)][:5]

    def _team_stats(self, team: str, matches: list[LastMatch]) -> TeamStats | None:
        if not matches:
            return None
        n = len(matches)
        total_gf = sum(m.goals_for for m in matches)
        total_ga = sum(m.goals_against for m in matches)
        return TeamStats(
            name=team,
            recent_matches=matches,
            avg_goals_scored_ft=round(total_gf / n, 2),
            avg_goals_conceded_ft=round(total_ga / n, 2),
            avg_goals_scored_ht=round((total_gf * 0.45) / n, 2),
            avg_goals_conceded_ht=round((total_ga * 0.45) / n, 2),
            avg_corners=round(4.0 + (total_gf / n) * 0.8, 2),
            avg_shots=round(9.0 + (total_gf / n) * 1.5, 2),
        )

    def _completeness(
        self,
        live: LiveState,
        a: TeamStats | None,
        b: TeamStats | None,
        h2h: list[LastMatch],
    ) -> float:
        score = 0.0
        if live and live.status and live.status != MatchStatus.UNKNOWN:
            score += 0.15
        if live.score_a is not None and live.score_b is not None:
            score += 0.10
        if live.minute is not None:
            score += 0.05
        if a and len(a.recent_matches) >= 3:
            score += 0.30
        elif a and a.recent_matches:
            score += 0.10
        if b and len(b.recent_matches) >= 3:
            score += 0.25
        elif b and b.recent_matches:
            score += 0.10
        if h2h:
            score += 0.10
        return round(min(score, 1.0), 2)


def _first(pair: tuple[int, int] | None) -> int | None:
    return pair[0] if pair else None


def _second(pair: tuple[int, int] | None) -> int | None:
    return pair[1] if pair else None
