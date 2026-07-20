from abc import ABC, abstractmethod
from datetime import datetime

from app.models import MatchData, MatchInput


class DataProvider(ABC):
    """Abstract interface for football data providers.

    New providers (paid APIs, scraping, browser automation) must implement
    this interface so they can be plugged into the orchestrator without
    touching the rest of the system.
    """

    name: str = "base"

    @abstractmethod
    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        """Return MatchData for the requested fixture.

        Implementations should set `source`, `completeness` and `updated_at`.
        """
        raise NotImplementedError

    def _normalize_name(self, name: str) -> str:
        return " ".join(name.strip().lower().split())
