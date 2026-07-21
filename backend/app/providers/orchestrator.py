import asyncio
import logging
from datetime import datetime

from app.cache import MatchCache
from app.config import get_settings
from app.models import LiveState, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider
from app.providers.browser_navigation_provider import BrowserNavigationProvider
from app.providers.browser_search_provider import BrowserSearchProvider
from app.providers.google_sync_provider import GoogleSyncProvider
from app.providers.mock_provider import MockProvider
from app.providers.thesportsdb_provider import TheSportsDbProvider
from app.providers.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


class DataProviderOrchestrator:
    """Tries real providers in priority order, caches results, and merges the
    best pieces from each source.

    Priority order (no paid API keys required by default):
      1. BrowserNavigationProvider (365Scores direct navigation)
      2. BrowserSearchProvider (DuckDuckGo / Google HTML, no API key)
      3. TheSportsDbProvider (free public API)
      4. GoogleSyncProvider (paid Google/Bing API, disabled when not configured)
      5. WebSearchProvider (Yahoo HTML snippets, lightweight fallback)

    Mock data is used only as a structural placeholder when all real sources fail.
    """

    def __init__(
        self,
        providers: list[DataProvider] | None = None,
        cache: MatchCache | None = None,
    ):
        self.providers = providers or self._default_providers()
        self.cache = cache or MatchCache()
        self.settings = get_settings()

    def _default_providers(self) -> list[DataProvider]:
        providers: list[DataProvider] = [
            BrowserNavigationProvider(),
            BrowserSearchProvider(),
            TheSportsDbProvider(),
        ]
        google = GoogleSyncProvider()
        if google.is_configured():
            providers.append(google)
        providers.append(WebSearchProvider())
        return providers

    def _provider_timeout(self, match_input: MatchInput) -> float:
        """Shorter timeout for live/upcoming matches; longer for historical lookups."""
        if match_input.match_datetime:
            delta = datetime.utcnow() - match_input.match_datetime
            if abs(delta.total_seconds()) < 7200:  # within 2 hours of kickoff
                return 15.0
        return 25.0

    def _cache_ttl(self, match_input: MatchInput) -> int:
        """Aggressive caching for future matches and completed games to reduce navigation."""
        if match_input.match_datetime:
            delta = datetime.utcnow() - match_input.match_datetime
            seconds = delta.total_seconds()
            if seconds < 0:
                # Future match: cache for 1 hour
                return 3600
            if seconds > 7200:
                # Finished match: cache for 6 hours
                return 21600
        # Live or unknown: cache for 2 minutes
        return 120

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        # Try cache first for short-circuiting simultaneous users
        cached = self.cache.get(match_input, "merged")
        if cached:
            return cached

        results: list[MatchData] = []
        provider_debug: list[dict[str, Any]] = []
        timeout = self._provider_timeout(match_input)
        for provider in self.providers:
            try:
                logger.info("Trying provider %s", provider.name)
                cached_provider = self.cache.get(match_input, provider.name)
                if cached_provider and cached_provider.completeness > 0:
                    data = cached_provider
                else:
                    data = await asyncio.wait_for(
                        provider.get_match_stats(match_input), timeout=timeout
                    )
                    if data and data.completeness > 0:
                        self.cache.set(
                            match_input, provider.name, data,
                            ttl_seconds=self._cache_ttl(match_input)
                        )

                logger.info(
                    "Provider %s returned source=%s completeness=%s",
                    provider.name,
                    data.source if data else None,
                    data.completeness if data else None,
                )
                provider_debug.append(
                    {
                        "provider": provider.name,
                        "source": data.source if data else None,
                        "completeness": data.completeness if data else None,
                        "error": (data.raw_metadata or {}).get("error") if data else None,
                        "team_a_found": (data.raw_metadata or {}).get("team_a_found") if data else None,
                        "team_b_found": (data.raw_metadata or {}).get("team_b_found") if data else None,
                    }
                )
                if data and data.completeness > 0:
                    results.append(data)
                    # If one provider alone is very complete, use it immediately
                    if data.completeness >= 0.85:
                        break
            except Exception as exc:  # noqa: BLE001
                logger.warning("Provider %s raised exception: %s", provider.name, exc, exc_info=True)
                provider_debug.append({"provider": provider.name, "error": repr(exc)})
                continue

        # Exclude mock/placeholder results from being treated as real data
        real_results = [r for r in results if r.source not in ("mock", "none", "unknown")]

        merged = self._merge(real_results, match_input) if real_results else await self._empty(match_input)
        merged.source = self._source_label(merged, real_results)
        merged.raw_metadata = {**merged.raw_metadata, "provider_debug": provider_debug}
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

        # Give partial credit when at least one provider recognised the teams,
        # so we can distinguish "teams not found" from "teams found, stats missing".
        has_basic_data = any(
            bool((r.raw_metadata or {}).get("team_a_found"))
            or bool((r.raw_metadata or {}).get("team_b_found"))
            for r in results
            if r.source != "mock"
        )

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
            completeness=round(
                self._completeness(live, best_a, best_b, best_h2h, has_basic_data), 2
            ),
            updated_at=datetime.utcnow(),
            raw_metadata={
                "providers": [d.source for d in results],
                "team_a_found": bool((base.raw_metadata or {}).get("team_a_found")),
                "team_b_found": bool((base.raw_metadata or {}).get("team_b_found")),
            },
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
        has_basic_data: bool = False,
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
        if has_basic_data:
            score += 0.05
        return min(score, 1.0)

    def _source_label(self, merged: MatchData, results: list[MatchData]) -> str:
        names = {r.source for r in results}
        names.discard("unknown")
        return ",".join(sorted(names)) if names else "unknown"


def get_orchestrator() -> DataProviderOrchestrator:
    return DataProviderOrchestrator()
