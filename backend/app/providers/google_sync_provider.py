import re
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
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


class GoogleSyncProvider(DataProvider):
    """Search-backed provider using Google Custom Search or Bing Web Search API.

    Falls back automatically if no API key is configured, returning empty data so
    the orchestrator can try the next provider.
    """

    name = "google_sync"

    def __init__(self):
        self.settings = get_settings()

    def is_configured(self) -> bool:
        """Return True when a paid search API key is configured."""
        return bool(
            (self.settings.google_api_key and self.settings.google_cx)
            or self.settings.bing_api_key
        )

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        try:
            return await self._fetch(match_input)
        except Exception as exc:
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
        team_a, team_b, alt_queries = resolve_team_names(
            match_input.team_a, match_input.team_b
        )

        # 1. Live / current match data
        live_text = await self._search_match_text(team_a, team_b, alt_queries, mode="live")
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

        # 2. Team recent form / history
        form_a = await self._team_form(team_a, match_input.team_a)
        form_b = await self._team_form(team_b, match_input.team_b)

        # 3. H2H
        h2h_text = await self._search_match_text(team_a, team_b, alt_queries, mode="h2h")
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
                "team_a": team_a,
                "team_b": team_b,
                "alt_queries": alt_queries,
                "team_a_found": bool(team_a_stats and team_a_stats.recent_matches),
                "team_b_found": bool(team_b_stats and team_b_stats.recent_matches),
                "live_data_found": bool(live_text),
            },
        )

    async def _search_match_text(
        self,
        team_a: str,
        team_b: str,
        alt_queries: list[str],
        mode: str = "live",
    ) -> str:
        """Search using canonical names, then fall back to original aliases.

        mode: "live" or "h2h"
        """
        if mode == "live":
            queries = [
                f'"{team_a}" "{team_b}" football ao vivo placar',
                f'"{team_a}" "{team_b}" football live score',
            ] + [f'"{q.split(" vs ")[0]}" "{q.split(" vs ")[1]}" football live score' for q in alt_queries if " vs " in q]
        else:
            queries = [
                f'"{team_a}" vs "{team_b}" head to head results',
                f'"{team_a}" vs "{team_b}" h2h',
            ] + [f'"{q.split(" vs ")[0]}" vs "{q.split(" vs ")[1]}" head to head results' for q in alt_queries if " vs " in q]

        for query in queries:
            text = await self._search_and_aggregate(query, top_n=2)
            if text:
                return text
        return ""

    async def _team_form(self, team: str, original: str) -> list[LastMatch]:
        queries = [
            f'"{team}" football last 5 matches results',
            f'"{original}" football last 5 matches results',
            f'"{team}" results',
            f'"{original}" results',
        ]
        for query in queries:
            text = await self._search_and_aggregate(query, top_n=3)
            matches = self._parse_match_rows(text, team) or self._parse_match_rows(text, original)
            if matches:
                return matches
        return []

    async def _search_and_aggregate(self, query: str, top_n: int = 3) -> str:
        """Return concatenated snippets and page text from the search query."""
        settings = self.settings
        snippets: list[str] = []

        if settings.google_api_key and settings.google_cx:
            snippets = await self._google_search(query)
        elif settings.bing_api_key:
            snippets = await self._bing_search(query)
        else:
            # No search API configured: rely on free WebSearch fallback later
            return ""

        # Also fetch the first result page for more structured text
        pages: list[str] = []
        for item in snippets[:top_n]:
            link = item.get("link") or item.get("url")
            if link:
                try:
                    pages.append(await self._fetch_page(link))
                except Exception:
                    pass

        all_text = "\n".join(pages)
        for item in snippets:
            all_text += "\n" + (item.get("title") or "")
            all_text += "\n" + (item.get("snippet") or "")
        return all_text.lower()

    async def _google_search(self, query: str) -> list[dict[str, Any]]:
        key = self.settings.google_api_key
        cx = self.settings.google_cx
        url = "https://www.googleapis.com/customsearch/v1"
        params = {"key": key, "cx": cx, "q": query, "num": 5, "hl": "pt"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
        return [
            {"title": it.get("title", ""), "snippet": it.get("snippet", ""), "link": it.get("link", "")}
            for it in data.get("items", [])
        ]

    async def _bing_search(self, query: str) -> list[dict[str, Any]]:
        key = self.settings.bing_api_key
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {"Ocp-Apim-Subscription-Key": key}
        params = {"q": query, "count": 5, "mkt": "pt-BR"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()
        return [
            {"title": it.get("name", ""), "snippet": it.get("snippet", ""), "link": it.get("url", "")}
            for it in data.get("webPages", {}).get("value", [])
        ]

    async def _fetch_page(self, url: str) -> str:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
                )
            }
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "lxml")
            return soup.get_text(" ", strip=True)

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
        if live and live.status != MatchStatus.UNKNOWN:
            score += 0.15
        if live.score_a is not None and live.score_b is not None:
            score += 0.10
        if live.minute is not None:
            score += 0.05
        if a and len(a.recent_matches) >= 3:
            score += 0.35
        if b and len(b.recent_matches) >= 3:
            score += 0.25
        if h2h:
            score += 0.10
        return round(min(score, 1.0), 2)


def _first(pair: tuple[int, int] | None) -> int | None:
    return pair[0] if pair else None


def _second(pair: tuple[int, int] | None) -> int | None:
    return pair[1] if pair else None
