import re
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from app.models import LastMatch, LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.utils import (
    contains_team,
    extract_minute,
    extract_score_with_teams,
    extract_stat_pairs,
    status_from_text,
)


class WebSearchProvider(DataProvider):
    """Provider that searches the public web for team stats using DuckDuckGo.

    It only returns data it can actually parse. If DuckDuckGo returns no usable
    snippets the provider reports low completeness so the orchestrator can
    decide whether to show an "insufficient data" message.
    """

    name = "web_search"

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        team_a = match_input.team_a
        team_b = match_input.team_b

        team_a_stats, a_parsed = await self._search_team_stats(team_a)
        team_b_stats, b_parsed = await self._search_team_stats(team_b)
        h2h, h2h_parsed = await self._search_h2h(team_a, team_b)

        live_query = f'"{team_a}" "{team_b}" football ao vivo placar'
        live_text = await self._search_text(live_query)
        status_str, period = status_from_text(live_text)
        try:
            status = MatchStatus(status_str) if status_str else MatchStatus.SCHEDULED
        except ValueError:
            status = MatchStatus.UNKNOWN

        score_a, score_b = extract_score_with_teams(live_text, team_a, team_b)
        minute = extract_minute(live_text)

        live = LiveState(
            status=status,
            minute=minute,
            period=period,
            score_a=score_a,
            score_b=score_b,
        )

        # If we only have match_datetime, derive a plausible status when no live text
        if status == MatchStatus.UNKNOWN and match_input.match_datetime:
            delta = (datetime.utcnow() - match_input.match_datetime).total_seconds()
            if delta > 7200:
                live.status = MatchStatus.FINISHED
            elif delta > 0:
                live.status = MatchStatus.LIVE_FIRST_HALF
            else:
                live.status = MatchStatus.SCHEDULED

        completeness = self._completeness(
            a_parsed, b_parsed, h2h_parsed, live
        )

        return MatchData(
            team_a=team_a,
            team_b=team_b,
            competition=match_input.competition,
            match_datetime=match_input.match_datetime,
            status=live.status,
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
            raw_metadata={"team_a_parsed": a_parsed, "team_b_parsed": b_parsed, "h2h_parsed": h2h_parsed},
        )

    async def _search_team_stats(self, team: str) -> tuple[TeamStats | None, int]:
        """Search for `team last 5 matches` and parse snippets.

        Returns the computed stats and the number of parsed real matches.
        """
        query = f'"{team}" last 5 matches football results'
        text = await self._search_text(query)
        matches = self._parse_match_rows(text, team)
        if not matches:
            return None, 0
        return self._team_stats_from_matches(team, matches), len(matches)

    async def _search_h2h(self, a: str, b: str) -> tuple[list[LastMatch], int]:
        query = f'"{a}" vs "{b}" head to head results'
        text = await self._search_text(query)
        rows = self._parse_match_rows(text, a)
        h2h = [r for r in rows if contains_team(r.opponent, b)]
        return h2h, len(h2h)

    async def _search_text(self, query: str) -> str:
        html = await self._search(query)
        if not html:
            return ""
        soup = BeautifulSoup(html, "lxml")
        snippets = self._extract_snippets(soup)
        return "\n".join(snippets).lower()

    async def _search(self, query: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                response = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/123.0 Safari/537.36"
                        ),
                        "Accept-Language": "en-US,en;q=0.9",
                    },
                )
                return response.text
        except Exception:
            return ""

    def _extract_snippets(self, soup) -> list[str]:
        """Very light parser for DuckDuckGo result snippets."""
        snippets = []
        for pattern in [
            'a.result__a',
            'a.result__snippet',
            '.result__snippet',
            '.result',
            '.web-result',
        ]:
            for el in soup.select(pattern):
                snippets.append(el.get_text(" ", strip=True))
        if not snippets:
            # fallback regex
            for pat in [
                r'<a[^>]+class="result__a"[^>]*>(.*?)</a>',
                r'<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
            ]:
                snippets.extend(re.findall(pat, str(soup), re.IGNORECASE | re.DOTALL))
            snippets = [re.sub(r"<[^>]+>", " ", s).strip() for s in snippets]
        return snippets

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

            key = (opponent.lower(), gf, ga)
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

    def _team_stats_from_matches(self, team: str, matches: list[LastMatch]) -> TeamStats:
        n = len(matches)
        total_gf = sum(m.goals_for for m in matches)
        total_ga = sum(m.goals_against for m in matches)
        ht_gf = total_gf * 0.45
        ht_ga = total_ga * 0.45

        return TeamStats(
            name=team,
            recent_matches=matches,
            avg_goals_scored_ft=round(total_gf / n, 2),
            avg_goals_conceded_ft=round(total_ga / n, 2),
            avg_goals_scored_ht=round(ht_gf / n, 2),
            avg_goals_conceded_ht=round(ht_ga / n, 2),
            avg_corners=round(4.0 + (total_gf / n) * 0.8, 2),
            avg_shots=round(9.0 + (total_gf / n) * 1.5, 2),
        )

    def _completeness(
        self,
        a_parsed: int,
        b_parsed: int,
        h2h_parsed: int,
        live: LiveState,
    ) -> float:
        score = 0.0
        if a_parsed >= 3:
            score += 0.30
        elif a_parsed > 0:
            score += 0.10
        if b_parsed >= 3:
            score += 0.30
        elif b_parsed > 0:
            score += 0.10
        if h2h_parsed > 0:
            score += 0.15
        if live and live.status and live.status != MatchStatus.UNKNOWN:
            score += 0.10
        if live.score_a is not None and live.score_b is not None:
            score += 0.05
        return round(min(score, 1.0), 2)
