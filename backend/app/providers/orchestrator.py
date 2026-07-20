from datetime import datetime

from app.cache import MatchCache
from app.config import get_settings
from app.models import LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.browser_navigation_provider import BrowserNavigationProvider
from app.providers.google_sync_provider import GoogleSyncProvider
from app.providers.mock_provider import MockProvider
from app.providers.web_search_provider import WebSearchProvider


class DataProviderOrchestrator:
    """Tries real providers in priority order, caches results, and merges the
    best pieces from each source (live state from 365Scores, historical stats
    from Google/Bing, fallback snippets from web search). Mock data is used
    only as a structural placeholder when all real sources fail.
    """

    def __init__(
        self,
        providers: list[DataProvider] | None = None,
        cache: MatchCache | None = None,
    ):
        self.providers = providers or [
            BrowserNavigationProvider(),
            GoogleSyncProvider(),
            WebSearchProvider(),
        ]
        self.cache = cache or MatchCache()
        self.settings = get_settings()

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        # Try cache first for short-circuiting simultaneous users
        cached = self.cache.get(match_input, "merged")
        if cached:
            return cached

        results: list[MatchData] = []
        for provider in self.providers:
            try:
                cached_provider = self.cache.get(match_input, provider.name)
                if cached_provider:
                    data = cached_provider
                else:
                    data = await provider.get_match_stats(match_input)
                    if data:
                        self.cache.set(match_input, provider.name, data)

                if data and data.completeness > 0:
                    results.append(data)
                    # If one provider alone is very complete, use it immediately
                    if data.completeness >= 0.85:
                        break
            except Exception:  # noqa: BLE001
                continue

        # Exclude mock/placeholder results from being treated as real data
        real_results = [r for r in results if r.source not in ("mock", "none", "unknown")]

        merged = self._merge(real_results, match_input) if real_results else await self._empty(match_input)
        merged.source = self._source_label(merged, real_results)
        self.cache.set(match_input, "merged", merged)
        return merged

    async def _empty(self, match_input: MatchInput) -> MatchData:
        data = await MockProvider().get_match_stats(match_input)
        data.completeness = 0.0
        data.source = "none"
        return data

    def _merge(self, results: list[MatchData], match_input: MatchInput) -> MatchData:
        """Pick the best live state and the best historical stats among sources."""
        # Sort by completeness; better sources preferred for metadata
        results.sort(key=lambda d: d.completeness, reverse=True)
        base = results[0]

        best_live = self._best_live(results)
        best_a = self._best_team_stats(results, "a")
        best_b = self._best_team_stats(results, "b")
        best_h2h = max(results, key=lambda d: len(d.h2h)).h2h

        status = best_live.status if best_live and best_live.status != MatchStatus.UNKNOWN else base.status
        live = best_live

        merged = MatchData(
            team_a=match_input.team_a,
            team_b=match_input.team_b,
            competition=base.competition or match_input.competition,
            match_datetime=base.match_datetime or match_input.match_datetime,
            status=status,
            score_a=live.score_a if live else None,
            score_b=live.score_b if live else None,
            minute=live.minute if live else None,
            live=live,
            team_a_stats=best_a,
            team_b_stats=best_b,
            h2h=best_h2h,
            source="",
            completeness=round(self._completeness(live, best_a, best_b, best_h2h), 2),
            updated_at=datetime.utcnow(),
            raw_metadata={"providers": [d.source for d in results]},
        )
        return merged

    def _best_live(self, results: list[MatchData]) -> LiveState | None:
        for data in results:
            if data.live and data.live.status not in (MatchStatus.UNKNOWN, MatchStatus.SCHEDULED):
                return data.live
        for data in results:
            if data.live and data.live.status != MatchStatus.UNKNOWN:
                return data.live
        # If any result has score data but no LiveState, build one
        for data in results:
            if data.score_a is not None and data.score_b is not None:
                return LiveState(
                    status=data.status,
                    score_a=data.score_a,
                    score_b=data.score_b,
                    minute=data.minute,
                )
        return None

    def _best_team_stats(self, results: list[MatchData], side: str) -> TeamStats | None:
        candidates = [r.team_a_stats for r in results] if side == "a" else [r.team_b_stats for r in results]
        candidates = [c for c in candidates if c is not None and c.recent_matches]
        if not candidates:
            return None
        # Prefer the candidate with the most recent matches and real averages
        return max(
            candidates,
            key=lambda c: (len(c.recent_matches), c.avg_goals_scored_ft, c.avg_shots),
        )

    def _completeness(
        self,
        live: LiveState | None,
        a: TeamStats | None,
        b: TeamStats | None,
        h2h: list,
    ) -> float:
        score = 0.0
        if live and live.status and live.status != MatchStatus.UNKNOWN:
            score += 0.25
        if live and live.score_a is not None and live.score_b is not None:
            score += 0.10
        if live and live.minute is not None:
            score += 0.05
        if live and any(
            v is not None
            for v in [
                live.corners_a,
                live.shots_a,
                live.shots_on_target_a,
                live.possession_a,
            ]
        ):
            score += 0.10
        if a and len(a.recent_matches) >= 3:
            score += 0.20
        if b and len(b.recent_matches) >= 3:
            score += 0.20
        if h2h:
            score += 0.10
        return min(score, 1.0)

    def _source_label(self, merged: MatchData, results: list[MatchData]) -> str:
        names = {r.source for r in results}
        names.discard("unknown")
        return ",".join(sorted(names)) if names else "unknown"


def get_orchestrator() -> DataProviderOrchestrator:
    return DataProviderOrchestrator()
