export interface LastMatch {
  opponent: string
  venue: string
  goals_for: number
  goals_against: number
  result: string
  date?: string
}

export interface TeamStats {
  name: string
  recent_matches: LastMatch[]
  avg_goals_scored_ft: number
  avg_goals_conceded_ft: number
  avg_goals_scored_ht: number
  avg_goals_conceded_ht: number
  avg_corners: number
  avg_shots: number
  avg_shots_on_target?: number
  avg_possession?: number
}

export interface LiveState {
  status: string
  minute?: number
  period?: string
  score_a?: number
  score_b?: number
  corners_a?: number
  corners_b?: number
  shots_a?: number
  shots_b?: number
  shots_on_target_a?: number
  shots_on_target_b?: number
  possession_a?: number
  possession_b?: number
  cards_yellow_a?: number
  cards_yellow_b?: number
  cards_red_a?: number
  cards_red_b?: number
}

export interface MatchData {
  team_a: string
  team_b: string
  competition?: string
  match_datetime?: string
  status: string
  score_a?: number
  score_b?: number
  minute?: number
  live?: LiveState
  team_a_stats?: TeamStats
  team_b_stats?: TeamStats
  h2h: LastMatch[]
  source: string
  completeness: number
  updated_at: string
}

export interface DistributionPoint {
  goals: number
  probability: number
}

export interface ProbabilityOutput {
  team_a: number
  team_b: number
  draw: number
}

export interface ProjectionOutput {
  final_score_a: number
  final_score_b: number
  over_under_ft: Record<string, number>
  btts: number
  outcome: ProbabilityOutput
  remaining_minutes?: number
}

export interface MatchAnalysis {
  match: MatchData
  mode: string
  label: string
  reliable: boolean
  expected_goals_a?: number
  expected_goals_b?: number
  expected_goals_a_ht?: number
  expected_goals_b_ht?: number
  goal_distribution_ft: DistributionPoint[]
  goal_distribution_ht: DistributionPoint[]
  over_under_ft: Record<string, number>
  over_under_ht: Record<string, number>
  btts?: number
  outcome?: ProbabilityOutput
  corners_expected?: number
  corners_over_under: Record<string, number>
  shots_expected_a?: number
  shots_expected_b?: number
  h2h: LastMatch[]
  form_a: LastMatch[]
  form_b: LastMatch[]
  projection?: ProjectionOutput
  disclaimer?: string
}
