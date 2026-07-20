import math

from app.config import get_settings
from app.models import DistributionPoint, LiveState, MatchAnalysis, MatchData, MatchStatus, ProbabilityOutput, ProjectionOutput, TeamStats


def _safe(value: float) -> float:
    return max(0.0, float(value))


def expected_goals(
    attack_team_a: float,
    defense_team_a: float,
    attack_team_b: float,
    defense_team_b: float,
    league_avg: float = 1.35,
) -> tuple[float, float]:
    """Dixon-Coles-inspired attack/defence strength."""
    return (
        _safe(attack_team_a * defense_team_b * league_avg),
        _safe(attack_team_b * defense_team_a * league_avg),
    )


def _poisson_pmf(k: int, lambda_value: float) -> float:
    """Poisson probability mass function using only standard math."""
    if lambda_value <= 0:
        return 1.0 if k == 0 else 0.0
    return (lambda_value ** k) * math.exp(-lambda_value) / math.factorial(k)


def poisson_distribution(lambda_value: float, max_goals: int = 6) -> list[DistributionPoint]:
    return [
        DistributionPoint(
            goals=i,
            probability=round(_poisson_pmf(i, lambda_value), 4),
        )
        for i in range(max_goals + 1)
    ]


def _goals_distribution(lambda_a: float, lambda_b: float, max_goals: int = 6) -> dict[int, float]:
    """Joint distribution of total goals (a + b)."""
    dist: dict[int, float] = {}
    for i in range(max_goals + 1):
        for j in range(max_goals + 1):
            total = i + j
            p = _poisson_pmf(i, lambda_a) * _poisson_pmf(j, lambda_b)
            dist[total] = dist.get(total, 0.0) + p
    return dist


def over_under(lambda_a: float, lambda_b: float, thresholds: list[float]) -> dict[str, float]:
    """Probability of total goals being over/under each threshold."""
    results: dict[str, float] = {}
    dist = _goals_distribution(lambda_a, lambda_b)
    for threshold in thresholds:
        over = sum(p for goals, p in dist.items() if goals > threshold)
        over = round(min(max(over, 0.0), 1.0), 4)
        under = round(1 - over, 4)
        results[f"over_{threshold}"] = over
        results[f"under_{threshold}"] = under
    return results


def outcome_probabilities(lambda_a: float, lambda_b: float) -> ProbabilityOutput:
    """1x2 probabilities via independent Poisson convolution (grid 0..6)."""
    win_a = draw = win_b = 0.0
    for i in range(7):
        for j in range(7):
            p = _poisson_pmf(i, lambda_a) * _poisson_pmf(j, lambda_b)
            if i > j:
                win_a += p
            elif i == j:
                draw += p
            else:
                win_b += p
    total = win_a + draw + win_b
    return ProbabilityOutput(
        team_a=round(win_a / total, 4),
        team_b=round(win_b / total, 4),
        draw=round(draw / total, 4),
    )


def _remaining_minutes(live: LiveState) -> int:
    """Estimate minutes left in the match based on current period."""
    minute = live.minute or 0
    if live.status == MatchStatus.LIVE_FIRST_HALF:
        return max(0, 45 - minute) + 45
    if live.status == MatchStatus.LIVE_HALFTIME:
        return 45
    if live.status == MatchStatus.LIVE_SECOND_HALF:
        return max(0, 90 - minute)
    # generic fallback
    return max(0, 90 - minute)


def _pre_match_lambdas(match: MatchData) -> tuple[float, float, float, float]:
    """Return full-time and half-time Poisson lambdas for both teams."""
    a = match.team_a_stats
    b = match.team_b_stats

    avg_scored_a = a.avg_goals_scored_ft if a else 1.3
    avg_conceded_a = a.avg_goals_conceded_ft if a else 1.2
    avg_scored_b = b.avg_goals_scored_ft if b else 1.1
    avg_conceded_b = b.avg_goals_conceded_ft if b else 1.4

    avg_scored_a_ht = a.avg_goals_scored_ht if a else 0.6
    avg_conceded_a_ht = a.avg_goals_conceded_ht if a else 0.55
    avg_scored_b_ht = b.avg_goals_scored_ht if b else 0.55
    avg_conceded_b_ht = b.avg_goals_conceded_ht if b else 0.6

    league_avg = 1.35

    attack_a = avg_scored_a / league_avg
    defense_b = avg_conceded_b / league_avg
    attack_b = avg_scored_b / league_avg
    defense_a = avg_conceded_a / league_avg

    attack_a_ht = avg_scored_a_ht / (league_avg * 0.45)
    defense_b_ht = avg_conceded_b_ht / (league_avg * 0.45)
    attack_b_ht = avg_scored_b_ht / (league_avg * 0.45)
    defense_a_ht = avg_conceded_a_ht / (league_avg * 0.45)

    lambda_a_ft, lambda_b_ft = expected_goals(attack_a, defense_a, attack_b, defense_b)
    lambda_a_ht, lambda_b_ht = expected_goals(
        attack_a_ht, defense_a_ht, attack_b_ht, defense_b_ht, league_avg=league_avg * 0.45
    )

    return (
        _safe(min(lambda_a_ft, 4.0)),
        _safe(min(lambda_b_ft, 4.0)),
        _safe(min(lambda_a_ht, 2.5)),
        _safe(min(lambda_b_ht, 2.5)),
    )


def _pre_match_analysis(match: MatchData) -> MatchAnalysis:
    lambda_a_ft, lambda_b_ft, lambda_a_ht, lambda_b_ht = _pre_match_lambdas(match)
    thresholds = [0.5, 1.5, 2.5, 3.5, 4.5]

    a = match.team_a_stats
    b = match.team_b_stats
    corners_a = (a.avg_corners if a else 5.0) * 0.5
    corners_b = (b.avg_corners if b else 5.0) * 0.5
    corners_expected = corners_a + corners_b

    return MatchAnalysis(
        match=match,
        mode="pre",
        label="Análise Pré-Jogo",
        reliable=True,
        expected_goals_a=round(lambda_a_ft, 3),
        expected_goals_b=round(lambda_b_ft, 3),
        expected_goals_a_ht=round(lambda_a_ht, 3),
        expected_goals_b_ht=round(lambda_b_ht, 3),
        goal_distribution_ft=poisson_distribution(lambda_a_ft + lambda_b_ft),
        goal_distribution_ht=poisson_distribution(lambda_a_ht + lambda_b_ht),
        over_under_ft=over_under(lambda_a_ft, lambda_b_ft, thresholds),
        over_under_ht=over_under(lambda_a_ht, lambda_b_ht, thresholds),
        btts=btts_probability(lambda_a_ft, lambda_b_ft),
        outcome=outcome_probabilities(lambda_a_ft, lambda_b_ft),
        corners_expected=round(corners_expected, 2),
        corners_over_under=over_under(corners_a, corners_b, [5.5, 9.5, 10.5]),
        shots_expected_a=round(a.avg_shots if a else 11.0, 2),
        shots_expected_b=round(b.avg_shots if b else 10.0, 2),
        h2h=match.h2h[:5],
        form_a=(a.recent_matches if a else [])[:5],
        form_b=(b.recent_matches if b else [])[:5],
    )


def _live_analysis(match: MatchData) -> MatchAnalysis:
    live = match.live
    if not live:
        return _pre_match_analysis(match)

    current_a = live.score_a or 0
    current_b = live.score_b or 0
    remaining = _remaining_minutes(live)

    lambda_a_ft, lambda_b_ft, lambda_a_ht, lambda_b_ht = _pre_match_lambdas(match)

    # Scale per-90 expected goals to the time left in the match
    per_min_a = lambda_a_ft / 90.0
    per_min_b = lambda_b_ft / 90.0
    lambda_a_rem = _safe(per_min_a * remaining)
    lambda_b_rem = _safe(per_min_b * remaining)

    # Final expected score = already scored + expected in the remaining time
    final_a = current_a + lambda_a_rem
    final_b = current_b + lambda_b_rem

    # Outcome probabilities after the current score
    outcome = _outcome_from_current(current_a, current_b, lambda_a_rem, lambda_b_rem)

    # Over/under final uses the additional goals distribution shifted by the current total
    thresholds = [0.5, 1.5, 2.5, 3.5, 4.5]
    over_under_ft = _over_under_from_current(
        current_a + current_b, lambda_a_rem, lambda_b_rem, thresholds
    )
    over_under_ht = _over_under_from_current(
        current_a + current_b, lambda_a_ht, lambda_b_ht, thresholds
    )

    # BTTS final: already both scored?
    if current_a > 0 and current_b > 0:
        btts = 1.0
    elif current_a > 0:
        btts = round(1 - _poisson_pmf(0, lambda_b_rem), 4)
    elif current_b > 0:
        btts = round(1 - _poisson_pmf(0, lambda_a_rem), 4)
    else:
        btts = round(
            (1 - _poisson_pmf(0, lambda_a_rem)) * (1 - _poisson_pmf(0, lambda_b_rem)), 4
        )

    # Corners and shots projection
    a = match.team_a_stats
    b = match.team_b_stats
    current_corners = (live.corners_a or 0) + (live.corners_b or 0)
    avg_corners_a = (a.avg_corners if a else 5.0) / 90.0
    avg_corners_b = (b.avg_corners if b else 5.0) / 90.0
    projected_corners = current_corners + (avg_corners_a + avg_corners_b) * remaining
    corners_over_under = _over_under_from_current(
        current_corners, avg_corners_a * remaining, avg_corners_b * remaining, [5.5, 9.5, 10.5]
    )

    current_shots_a = live.shots_a or 0
    current_shots_b = live.shots_b or 0
    shots_a_final = current_shots_a + ((a.avg_shots if a else 11.0) / 90.0) * remaining
    shots_b_final = current_shots_b + ((b.avg_shots if b else 10.0) / 90.0) * remaining

    distribution_rem = poisson_distribution(lambda_a_rem + lambda_b_rem)

    projection = ProjectionOutput(
        final_score_a=round(final_a, 2),
        final_score_b=round(final_b, 2),
        over_under_ft=over_under_ft,
        btts=btts,
        outcome=outcome,
        remaining_minutes=remaining,
    )

    return MatchAnalysis(
        match=match,
        mode="live",
        label="Análise Ao Vivo",
        reliable=True,
        expected_goals_a=round(lambda_a_rem, 3),
        expected_goals_b=round(lambda_b_rem, 3),
        expected_goals_a_ht=round(lambda_a_ht, 3),
        expected_goals_b_ht=round(lambda_b_ht, 3),
        goal_distribution_ft=distribution_rem,
        goal_distribution_ht=poisson_distribution(lambda_a_ht + lambda_b_ht),
        over_under_ft=over_under_ft,
        over_under_ht=over_under_ht,
        btts=btts,
        outcome=outcome,
        corners_expected=round(projected_corners, 2),
        corners_over_under=corners_over_under,
        shots_expected_a=round(shots_a_final, 2),
        shots_expected_b=round(shots_b_final, 2),
        h2h=match.h2h[:5],
        form_a=(a.recent_matches if a else [])[:5],
        form_b=(b.recent_matches if b else [])[:5],
        projection=projection,
    )


def _finished_analysis(match: MatchData) -> MatchAnalysis:
    live = match.live
    score_a = live.score_a if live else (match.score_a or 0)
    score_b = live.score_b if live else (match.score_b or 0)
    return MatchAnalysis(
        match=match,
        mode="finished",
        label="Jogo Encerrado",
        reliable=True,
        h2h=match.h2h[:5],
        form_a=(match.team_a_stats.recent_matches if match.team_a_stats else [])[:5],
        form_b=(match.team_b_stats.recent_matches if match.team_b_stats else [])[:5],
    )


def _insufficient_data_analysis(match: MatchData) -> MatchAnalysis:
    return MatchAnalysis(
        match=match,
        mode="insufficient_data",
        label="Dados insuficientes",
        reliable=False,
        disclaimer="Não foi possível obter dados confiáveis para este jogo agora.",
    )


def _outcome_from_current(
    current_a: int, current_b: int, lambda_a: float, lambda_b: float
) -> ProbabilityOutput:
    """Compute final 1x2 probabilities given the current score and remaining lambdas."""
    win_a = draw = win_b = 0.0
    for i in range(7):
        for j in range(7):
            p = _poisson_pmf(i, lambda_a) * _poisson_pmf(j, lambda_b)
            final_a = current_a + i
            final_b = current_b + j
            if final_a > final_b:
                win_a += p
            elif final_a == final_b:
                draw += p
            else:
                win_b += p
    total = win_a + draw + win_b
    return ProbabilityOutput(
        team_a=round(win_a / total, 4),
        team_b=round(win_b / total, 4),
        draw=round(draw / total, 4),
    )


def _over_under_from_current(
    current_total: int, lambda_a: float, lambda_b: float, thresholds: list[float]
) -> dict[str, float]:
    """Compute over/under for the final total = current_total + additional goals."""
    results: dict[str, float] = {}
    for threshold in thresholds:
        over = 0.0
        for i in range(7):
            for j in range(7):
                if current_total + i + j > threshold:
                    over += _poisson_pmf(i, lambda_a) * _poisson_pmf(j, lambda_b)
        over = round(min(max(over, 0.0), 1.0), 4)
        under = round(1 - over, 4)
        results[f"over_{threshold}"] = over
        results[f"under_{threshold}"] = under
    return results


def btts_probability(lambda_a: float, lambda_b: float) -> float:
    """Probability that both teams score at least one goal."""
    p_a_scores = 1 - _poisson_pmf(0, lambda_a)
    p_b_scores = 1 - _poisson_pmf(0, lambda_b)
    return round(p_a_scores * p_b_scores, 4)


def analyze_match(match: MatchData) -> MatchAnalysis:
    """Main entry point: compute all statistical outputs for a MatchData."""
    settings = get_settings()
    if match.completeness < settings.completeness_threshold:
        return _insufficient_data_analysis(match)

    if match.status == MatchStatus.FINISHED:
        return _finished_analysis(match)

    if match.status in (
        MatchStatus.LIVE_FIRST_HALF,
        MatchStatus.LIVE_HALFTIME,
        MatchStatus.LIVE_SECOND_HALF,
    ):
        return _live_analysis(match)

    return _pre_match_analysis(match)
