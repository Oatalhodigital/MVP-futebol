from datetime import datetime

from app.models import LastMatch, MatchData, MatchInput, MatchStatus, TeamStats
from app.providers.base import DataProvider


class MockProvider(DataProvider):
    """Fallback provider that returns plausible synthetic data.

    Useful when all external sources fail. It never breaks and lets the
    dashboard still display estimates derived from the team names.
    """

    name = "mock"

    async def get_match_stats(self, match_input: MatchInput) -> MatchData:
        def _build(name: str, seed: int) -> TeamStats:
            # Deterministic synthetic stats based on team name length (demo only)
            base_score = (len(name) % 5) + 1
            return TeamStats(
                name=name,
                recent_matches=[
                    LastMatch(
                        opponent=f"Opponent {i}",
                        venue="home" if i % 2 == 0 else "away",
                        goals_for=max(0, (base_score + i) % 4),
                        goals_against=max(0, (base_score - i) % 3),
                        result=["W", "D", "L"][i % 3],
                    )
                    for i in range(5)
                ],
                avg_goals_scored_ft=1.4 + (base_score * 0.15),
                avg_goals_conceded_ft=1.2 + ((5 - base_score) * 0.1),
                avg_goals_scored_ht=0.6 + (base_score * 0.07),
                avg_goals_conceded_ht=0.5 + ((5 - base_score) * 0.05),
                avg_corners=4.5 + base_score,
                avg_shots=10.0 + base_score * 1.5,
            )

        return MatchData(
            team_a=match_input.team_a,
            team_b=match_input.team_b,
            competition=match_input.competition,
            match_datetime=match_input.match_datetime,
            status=MatchStatus.SCHEDULED,
            team_a_stats=_build(match_input.team_a, 1),
            team_b_stats=_build(match_input.team_b, 2),
            h2h=[
                LastMatch(
                    opponent=match_input.team_b,
                    venue="home",
                    goals_for=1,
                    goals_against=1,
                    result="D",
                )
            ],
            source=self.name,
            completeness=0.1,
            updated_at=datetime.utcnow(),
            raw_metadata={"note": "synthetic fallback data, completeness low"},
        )
