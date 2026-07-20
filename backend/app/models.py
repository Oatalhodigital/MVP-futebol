from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class MatchStatus(str, Enum):
    SCHEDULED = "scheduled"
    LIVE_FIRST_HALF = "live_first_half"
    LIVE_HALFTIME = "live_halftime"
    LIVE_SECOND_HALF = "live_second_half"
    FINISHED = "finished"
    UNKNOWN = "unknown"

    @property
    def is_live(self) -> bool:
        return self in {
            MatchStatus.LIVE_FIRST_HALF,
            MatchStatus.LIVE_HALFTIME,
            MatchStatus.LIVE_SECOND_HALF,
        }


class LastMatch(BaseModel):
    opponent: str
    venue: str  # home / away / neutral
    goals_for: int
    goals_against: int
    result: str  # W / D / L
    date: str | None = None


class TeamStats(BaseModel):
    name: str
    recent_matches: list[LastMatch] = Field(default_factory=list)
    avg_goals_scored_ft: float = 0.0
    avg_goals_conceded_ft: float = 0.0
    avg_goals_scored_ht: float = 0.0
    avg_goals_conceded_ht: float = 0.0
    avg_corners: float = 0.0
    avg_shots: float = 0.0
    avg_shots_on_target: float | None = None
    avg_possession: float | None = None


class LiveState(BaseModel):
    status: MatchStatus = MatchStatus.UNKNOWN
    minute: int | None = None
    period: str | None = None  # e.g. "1st half", "halftime", "2nd half"
    score_a: int | None = None
    score_b: int | None = None
    corners_a: int | None = None
    corners_b: int | None = None
    shots_a: int | None = None
    shots_b: int | None = None
    shots_on_target_a: int | None = None
    shots_on_target_b: int | None = None
    possession_a: float | None = None  # percentage
    possession_b: float | None = None
    cards_yellow_a: int | None = None
    cards_yellow_b: int | None = None
    cards_red_a: int | None = None
    cards_red_b: int | None = None


class MatchData(BaseModel):
    team_a: str
    team_b: str
    competition: str | None = None
    match_datetime: datetime | None = None
    status: MatchStatus = MatchStatus.UNKNOWN
    score_a: int | None = None
    score_b: int | None = None
    minute: int | None = None
    live: LiveState | None = None
    team_a_stats: TeamStats | None = None
    team_b_stats: TeamStats | None = None
    h2h: list[LastMatch] = Field(default_factory=list)
    source: str = "unknown"
    completeness: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class MatchInput(BaseModel):
    team_a: str
    team_b: str
    competition: str | None = None
    match_datetime: datetime | None = None


class ProbabilityOutput(BaseModel):
    team_a: float
    team_b: float
    draw: float


class DistributionPoint(BaseModel):
    goals: int
    probability: float


class ProjectionOutput(BaseModel):
    final_score_a: float
    final_score_b: float
    over_under_ft: dict[str, float]
    btts: float
    outcome: ProbabilityOutput
    remaining_minutes: int | None = None


class MatchAnalysis(BaseModel):
    match: MatchData
    mode: str = "pre"  # pre / live / finished / insufficient_data
    label: str = "Análise"
    reliable: bool = True
    expected_goals_a: float | None = None
    expected_goals_b: float | None = None
    expected_goals_a_ht: float | None = None
    expected_goals_b_ht: float | None = None
    goal_distribution_ft: list[DistributionPoint] = Field(default_factory=list)
    goal_distribution_ht: list[DistributionPoint] = Field(default_factory=list)
    over_under_ft: dict[str, float] = Field(default_factory=dict)
    over_under_ht: dict[str, float] = Field(default_factory=dict)
    btts: float | None = None
    outcome: ProbabilityOutput | None = None
    corners_expected: float | None = None
    corners_over_under: dict[str, float] = Field(default_factory=dict)
    shots_expected_a: float | None = None
    shots_expected_b: float | None = None
    h2h: list[LastMatch] = Field(default_factory=list)
    form_a: list[LastMatch] = Field(default_factory=list)
    form_b: list[LastMatch] = Field(default_factory=list)
    projection: ProjectionOutput | None = None
    disclaimer: str = "Estimativas estatísticas baseadas em histórico. Não são previsões garantidas."
