import asyncio
import logging
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

import httpx

from app.models import LastMatch, LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.team_names import canonical_team_name, resolve_team_names
from app.providers.utils import normalize

logger = logging.getLogger(__name__)

BASE_URL = "https://www.thesportsdb.com/api/v1/json/3"


class TheSportsDbProvider(DataProvider):
    """Provider using the free public TheSportsDB API.

    No API key is required for the demo endpoints. It returns real fixture,
    result and form data whenever the teams are available in the database.
    """

    name = "thesportsdb"

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        try:
            return await self._fetch(match_input)
        except Exception as exc:
            logger.warning("TheSportsDbProvider failed: %s", exc, exc_info=True)
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
        team_a, team_b, _alt_queries = resolve_team_names(
            match_input.team_a, match_input.team_b
        )

        # Resolve teams and fixture in parallel
        team_a_info, team_b_info, fixture = await asyncio.gather(
            self._search_team(team_a),
            self._search_team(team_b),
            self._find_fixture(team_a, team_b),
        )

        live = LiveState(status=MatchStatus.UNKNOWN)
        match_datetime = None
        if fixture:
            match_datetime = self._parse_datetime(fixture)
            status, period = self._status_from_event(fixture)
            live = LiveState(
                status=status,
                period=period,
                score_a=self._int_or_none(fixture.get("intHomeScore")),
                score_b=self._int_or_none(fixture.get("intAwayScore")),
                minute=None,
            )

        # Recent form for each team in parallel
        form_a, form_b = await asyncio.gather(
            self._team_form(team_a_info),
            self._team_form(team_b_info),
        )

        # H2H from team A form filtered by opponent
        h2h = [m for m in form_a if normalize(m.opponent) == normalize(team_b)][:5]

        team_a_stats = self._team_stats(team_a, form_a)
        team_b_stats = self._team_stats(team_b, form_b)

        # If the team itself is known but has no recent form (common in smaller
        # leagues or early season), still give partial credit so the result is
        # not discarded as "unknown".
        has_basic_data = bool(team_a_info or team_b_info or fixture)

        completeness = self._completeness(live, team_a_stats, team_b_stats, h2h, has_basic_data)

        return MatchData(
            team_a=team_a,
            team_b=team_b,
            competition=match_input.competition or fixture.get("strLeague") if fixture else None,
            match_datetime=match_datetime or match_input.match_datetime,
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
            raw_metadata={
                "fixture": fixture,
                "team_a_found": bool(team_a_info),
                "team_b_found": bool(team_b_info),
            },
        )

    async def _api_get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Make a GET request to TheSportsDB with retries and longer timeout."""
        url = f"{BASE_URL}/{endpoint}"
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.get(url, params=params)
                    response.raise_for_status()
                    return response.json()
            except Exception as exc:
                last_exc = exc
                logger.info("TheSportsDB request failed (attempt %d): %s", attempt + 1, exc)
        logger.warning("TheSportsDB request failed after retries: %s", last_exc)
        return None

    async def _search_team(self, team_name: str) -> dict[str, Any] | None:
        """Find the best matching team using canonical/alias names and fuzzy scoring."""
        canonical = canonical_team_name(team_name)
        searches = {team_name, canonical, team_name.replace("FC", "").strip(), canonical.replace("FC", "").strip()}

        all_teams: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for query in searches:
            if not query:
                continue
            data = await self._api_get("searchteams.php", {"t": query})
            if not data:
                continue
            for team in data.get("teams") or []:
                team_id = team.get("idTeam")
                if not team_id or team_id in seen_ids:
                    continue
                seen_ids.add(team_id)
                all_teams.append(team)

        if not all_teams:
            return None

        norm_input = normalize(team_name)
        norm_canonical = normalize(canonical)

        def _score(team: dict[str, Any]) -> float:
            norm_team = normalize(team.get("strTeam", ""))
            norm_alt = normalize(team.get("strTeamAlternate", ""))
            short = (team.get("strTeamShort") or "").lower()

            if norm_team in (norm_input, norm_canonical) or norm_alt in (norm_input, norm_canonical):
                return 1.0
            if short in (team_name.lower(), canonical.lower()):
                return 0.95
            if norm_input in norm_team or norm_canonical in norm_team:
                return 0.85
            if norm_input in norm_alt or norm_canonical in norm_alt:
                return 0.80
            # Fuzzy similarity for cases like "Larne FC" vs "Larne"
            return max(
                SequenceMatcher(None, norm_input, norm_team).ratio(),
                SequenceMatcher(None, norm_canonical, norm_team).ratio(),
                SequenceMatcher(None, norm_input, norm_alt).ratio(),
                SequenceMatcher(None, norm_canonical, norm_alt).ratio(),
            )

        best = max(all_teams, key=_score)
        if _score(best) < 0.5:
            return None
        return best

    async def _find_fixture(self, team_a: str, team_b: str) -> dict[str, Any] | None:
        """Search for a fixture involving both teams.

        Tries multiple phrasings to cover domestic leagues, qualifiers and cups.
        """
        queries = [
            f"{team_a}_vs_{team_b}",
            f"{team_b}_vs_{team_a}",
            f"{team_a} {team_b}",
        ]
        for query in queries:
            data = await self._api_get("searchevents.php", {"e": query})
            if not data:
                continue
            events = data.get("event") or []
            if not events:
                continue
            norm_a = normalize(team_a)
            norm_b = normalize(team_b)
            for event in events:
                home = normalize(event.get("strHomeTeam", ""))
                away = normalize(event.get("strAwayTeam", ""))
                if (norm_a in home or home in norm_a) and (norm_b in away or away in norm_b):
                    return event
                if (norm_b in home or home in norm_b) and (norm_a in away or away in norm_a):
                    return event
            return events[0]
        return None

    async def _team_form(self, team_info: dict[str, Any] | None) -> list[LastMatch]:
        """Return the last finished matches for a team."""
        if not team_info:
            return []
        team_id = team_info.get("idTeam")
        if not team_id:
            return []
        data = await self._api_get("eventslast.php", {"id": team_id})
        if not data:
            return []

        results = data.get("results") or []
        matches: list[LastMatch] = []
        for event in results:
            match = self._event_to_last_match(event, team_info.get("strTeam", ""))
            if match:
                matches.append(match)
        return matches

    def _event_to_last_match(self, event: dict[str, Any], team_name: str) -> LastMatch | None:
        home = event.get("strHomeTeam", "")
        away = event.get("strAwayTeam", "")
        home_score = self._int_or_none(event.get("intHomeScore"))
        away_score = self._int_or_none(event.get("intAwayScore"))
        if home_score is None or away_score is None:
            return None

        norm_team = normalize(team_name)
        norm_home = normalize(home)
        norm_away = normalize(away)

        if norm_team in norm_home or norm_home in norm_team:
            venue = "home"
            gf, ga = home_score, away_score
            opponent = away
        elif norm_team in norm_away or norm_away in norm_team:
            venue = "away"
            gf, ga = away_score, home_score
            opponent = home
        else:
            return None

        result = "W" if gf > ga else ("D" if gf == ga else "L")
        return LastMatch(
            opponent=opponent.strip().title(),
            venue=venue,
            goals_for=gf,
            goals_against=ga,
            result=result,
        )

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

    def _status_from_event(self, event: dict[str, Any]) -> tuple[MatchStatus, str | None]:
        status = (event.get("strStatus") or "").upper()
        if status in ("FT", "FINISHED", "AET", "PEN"):
            return MatchStatus.FINISHED, "Encerrado"
        if status in ("HT", "HALFTIME"):
            return MatchStatus.LIVE_HALFTIME, "Intervalo"
        if status in ("LIVE", "1H", "2H", "1ST", "2ND", "IN_PLAY"):
            return MatchStatus.LIVE_FIRST_HALF, "1º tempo"
        # Scheduled / not started
        if status in ("NS", "SCHED", "POSTP") or not status:
            return MatchStatus.SCHEDULED, "Agendado"
        return MatchStatus.UNKNOWN, None

    def _parse_datetime(self, event: dict[str, Any]) -> datetime | None:
        ts = event.get("strTimestamp")
        if ts:
            try:
                return datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                pass
        date_str = event.get("dateEvent")
        time_str = event.get("strTime") or "00:00:00"
        if date_str:
            try:
                return datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        return None

    def _int_or_none(self, value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    def _completeness(
        self,
        live: LiveState,
        a: TeamStats | None,
        b: TeamStats | None,
        h2h: list[LastMatch],
        has_basic_data: bool = False,
    ) -> float:
        score = 0.0
        if live and live.status and live.status != MatchStatus.UNKNOWN:
            score += 0.35
        if live.score_a is not None and live.score_b is not None:
            score += 0.10
        if a and len(a.recent_matches) >= 3:
            score += 0.20
        elif a and a.recent_matches:
            score += 0.05
        if b and len(b.recent_matches) >= 3:
            score += 0.20
        elif b and b.recent_matches:
            score += 0.05
        if h2h:
            score += 0.10
        if has_basic_data:
            score += 0.05
        return round(min(score, 1.0), 2)
