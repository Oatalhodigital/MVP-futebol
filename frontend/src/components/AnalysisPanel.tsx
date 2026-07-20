import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { LiveState, MatchAnalysis } from '../types'

interface Props {
  analysis: MatchAnalysis
}

function pct(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(1)}%`
}

function Stat({ label, value }: { label: string; value: string | number | undefined }) {
  return (
    <div className="bg-slate-50 rounded-lg p-3">
      <p className="text-xs text-slate-500 uppercase font-medium">{label}</p>
      <p className="text-lg font-bold text-slate-800">{value ?? '-'}</p>
    </div>
  )
}

function OverUnderTable({ data }: { data: Record<string, number> }) {
  const thresholds = [0.5, 1.5, 2.5, 3.5, 4.5]
  return (
    <table className="w-full text-sm text-left">
      <thead>
        <tr className="border-b text-slate-600">
          <th className="py-2">Linha</th>
          <th className="py-2">Over</th>
          <th className="py-2">Under</th>
        </tr>
      </thead>
      <tbody>
        {thresholds.map((t) => (
          <tr key={t} className="border-b border-slate-100">
            <td className="py-2">{t} gols</td>
            <td className="py-2 font-medium text-primary">{pct(data?.[`over_${t}`])}</td>
            <td className="py-2 font-medium text-slate-700">{pct(data?.[`under_${t}`])}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function FormList({ title, matches }: { title: string; matches: any[] }) {
  return (
    <div className="card mt-4">
      <h3 className="font-semibold text-slate-800 mb-3">{title}</h3>
      {matches.length === 0 ? (
        <p className="text-sm text-slate-500">Sem dados de forma recente.</p>
      ) : (
        <ul className="space-y-2">
          {matches.map((m, idx) => (
            <li key={idx} className="text-sm flex justify-between border-b border-slate-100 pb-1">
              <span>
                {m.venue === 'home' ? 'C' : 'F'} vs {m.opponent}
              </span>
              <span className="font-medium">
                {m.goals_for}-{m.goals_against} ({m.result})
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function StatusBadge({ analysis }: { analysis: MatchAnalysis }) {
  const { mode, match } = analysis
  const live = match.live

  if (mode === 'finished') {
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-slate-200 text-slate-800">
        Encerrado
      </span>
    )
  }

  if (mode === 'live' && live) {
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-100 text-red-700 animate-pulse">
        Ao vivo · {live.minute ? `${live.minute}'` : ''} {live.period ? `· ${live.period}` : ''}
      </span>
    )
  }

  if (mode === 'insufficient_data') {
    return (
      <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">
        Dados insuficientes
      </span>
    )
  }

  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700">
      Pré-jogo
    </span>
  )
}

function LiveFacts({ live, teamA, teamB }: { live: LiveState; teamA: string; teamB: string }) {
  return (
    <div className="card bg-red-50 border-red-100">
      <h3 className="font-semibold text-red-900 mb-3">Placar e estatísticas ao vivo</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Placar" value={`${live.score_a ?? 0} x ${live.score_b ?? 0}`} />
        <Stat label="Minuto" value={live.minute !== undefined ? `${live.minute}'` : '-'} />
        <Stat label={`Escanteios (${teamA})`} value={live.corners_a ?? '-'} />
        <Stat label={`Escanteios (${teamB})`} value={live.corners_b ?? '-'} />
        <Stat label={`Chutes (${teamA})`} value={live.shots_a ?? '-'} />
        <Stat label={`Chutes (${teamB})`} value={live.shots_b ?? '-'} />
        <Stat label={`Posse (${teamA})`} value={live.possession_a !== undefined ? `${live.possession_a}%` : '-'} />
        <Stat label={`Posse (${teamB})`} value={live.possession_b !== undefined ? `${live.possession_b}%` : '-'} />
      </div>
    </div>
  )
}

function ProjectionPanel({ analysis }: { analysis: MatchAnalysis }) {
  const p = analysis.projection
  if (!p) return null
  return (
    <div className="card border-blue-200">
      <h3 className="font-semibold text-slate-800 mb-3">
        Projeção para o restante da partida
        {p.remaining_minutes !== undefined && <span className="text-sm font-normal text-slate-500 ml-2">(~{p.remaining_minutes} min restantes)</span>}
      </h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat label="Placar final estimado" value={`${p.final_score_a} x ${p.final_score_b}`} />
        <Stat label="Ambas marcam (final)" value={pct(p.btts)} />
        <Stat label={`Vitória ${analysis.match.team_a}`} value={pct(p.outcome?.team_a)} />
        <Stat label={`Vitória ${analysis.match.team_b}`} value={pct(p.outcome?.team_b)} />
      </div>
      <div className="mt-4">
        <OverUnderTable data={p.over_under_ft} />
      </div>
    </div>
  )
}

export default function AnalysisPanel({ analysis }: Props) {
  const { match, mode, label } = analysis
  const ftChartData = analysis.goal_distribution_ft.map((p) => ({
    goals: `${p.goals}`,
    prob: Number((p.probability * 100).toFixed(1)),
  }))
  const htChartData = analysis.goal_distribution_ht.map((p) => ({
    goals: `${p.goals}`,
    prob: Number((p.probability * 100).toFixed(1)),
  }))

  if (mode === 'insufficient_data') {
    return (
      <div className="mt-8 space-y-6">
        <section className="card">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-slate-800">
                {match.team_a} <span className="text-slate-400">x</span> {match.team_b}
              </h2>
              {match.competition && <p className="text-sm text-slate-500">{match.competition}</p>}
            </div>
            <StatusBadge analysis={analysis} />
          </div>
          <div className="mt-6 p-4 bg-yellow-50 text-yellow-800 rounded-lg border border-yellow-100">
            {analysis.disclaimer || 'Não foi possível obter dados confiáveis para este jogo agora. Tente novamente mais tarde ou verifique os nomes dos times.'}
          </div>
          <p className="mt-2 text-sm text-slate-500">Completude: {Math.round(match.completeness * 100)}%</p>
        </section>
      </div>
    )
  }

  const isFinished = mode === 'finished'
  const isLive = mode === 'live'

  return (
    <div className="mt-8 space-y-6">
      <section className="card">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h2 className="text-2xl font-bold text-slate-800">
              {match.team_a} <span className="text-slate-400">x</span> {match.team_b}
            </h2>
            {match.competition && <p className="text-sm text-slate-500">{match.competition}</p>}
          </div>
          <div className="text-right">
            <StatusBadge analysis={analysis} />
            <p className="text-sm text-slate-500 mt-1">{label}</p>
            <p className="text-xs text-slate-400">Fonte: {match.source || '—'}</p>
            <p className="text-xs text-slate-400">Completude: {Math.round(match.completeness * 100)}%</p>
          </div>
        </div>

        {isFinished && match.live && (
          <div className="mt-6 p-6 bg-slate-100 rounded-xl text-center">
            <p className="text-sm text-slate-500 uppercase tracking-wide">Resultado final</p>
            <p className="text-4xl font-extrabold text-slate-800 mt-1">
              {match.live.score_a ?? 0} <span className="text-slate-400">x</span> {match.live.score_b ?? 0}
            </p>
          </div>
        )}

        {!isFinished && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
            <Stat
              label={isLive ? `Gols esperados restantes (${match.team_a})` : `xG ${match.team_a}`}
              value={analysis.expected_goals_a?.toFixed(2)}
            />
            <Stat
              label={isLive ? `Gols esperados restantes (${match.team_b})` : `xG ${match.team_b}`}
              value={analysis.expected_goals_b?.toFixed(2)}
            />
            <Stat label="Ambas marcam" value={pct(analysis.btts)} />
            <Stat label={isLive ? 'Escanteios projetados (final)' : 'Escanteios esperados'} value={analysis.corners_expected?.toFixed(1)} />
          </div>
        )}
      </section>

      {isLive && match.live && <LiveFacts live={match.live} teamA={match.team_a} teamB={match.team_b} />}

      {isLive && <ProjectionPanel analysis={analysis} />}

      {!isFinished && (
        <section className="grid gap-6 md:grid-cols-2">
          <div className="card">
            <h3 className="font-semibold text-slate-800 mb-4">Chance de resultado</h3>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Vitória {match.team_a}</span>
                <span className="font-bold text-primary">{pct(analysis.outcome?.team_a)}</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-primary h-2 rounded-full"
                  style={{ width: `${(analysis.outcome?.team_a ?? 0) * 100}%` }}
                />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Empate</span>
                <span className="font-bold text-slate-700">{pct(analysis.outcome?.draw)}</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-slate-500 h-2 rounded-full"
                  style={{ width: `${(analysis.outcome?.draw ?? 0) * 100}%` }}
                />
              </div>
              <div className="flex justify-between items-center">
                <span className="text-slate-600">Vitória {match.team_b}</span>
                <span className="font-bold text-secondary">{pct(analysis.outcome?.team_b)}</span>
              </div>
              <div className="w-full bg-slate-100 rounded-full h-2">
                <div
                  className="bg-secondary h-2 rounded-full"
                  style={{ width: `${(analysis.outcome?.team_b ?? 0) * 100}%` }}
                />
              </div>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-slate-800 mb-4">Over/Under jogo completo</h3>
            <OverUnderTable data={analysis.over_under_ft} />
          </div>
        </section>
      )}

      {!isFinished && (
        <section className="grid gap-6 md:grid-cols-2">
          <div className="card">
            <h3 className="font-semibold text-slate-800 mb-4">
              {isLive ? 'Distribuição de gols no restante' : 'Distribuição de gols - Jogo completo'}
            </h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={ftChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="goals" />
                  <YAxis />
                  <Tooltip formatter={(value: number) => `${value}%`} />
                  <Bar dataKey="prob" fill="#1e40af" name="Probabilidade (%)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          <div className="card">
            <h3 className="font-semibold text-slate-800 mb-4">Distribuição de gols - 1º tempo</h3>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={htChartData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="goals" />
                  <YAxis />
                  <Tooltip formatter={(value: number) => `${value}%`} />
                  <Bar dataKey="prob" fill="#10b981" name="Probabilidade (%)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </section>
      )}

      {!isFinished && (
        <section className="grid gap-6 md:grid-cols-3">
          <div className="card">
            <h3 className="font-semibold text-slate-800 mb-3">
              {isLive ? 'Chutes a gol projetados (final)' : 'Chutes a gol esperados'}
            </h3>
            <p className="text-3xl font-bold text-primary">{analysis.shots_expected_a?.toFixed(1) ?? '-'}</p>
            <p className="text-sm text-slate-500">{match.team_a}</p>
            <p className="text-3xl font-bold text-secondary mt-4">{analysis.shots_expected_b?.toFixed(1) ?? '-'}</p>
            <p className="text-sm text-slate-500">{match.team_b}</p>
          </div>
          <div className="card md:col-span-2">
            <h3 className="font-semibold text-slate-800 mb-3">Over/Under escanteios</h3>
            <OverUnderTable data={analysis.corners_over_under} />
          </div>
        </section>
      )}

      <div className="grid gap-6 md:grid-cols-2">
        <FormList title={`Forma recente - ${match.team_a}`} matches={analysis.form_a} />
        <FormList title={`Forma recente - ${match.team_b}`} matches={analysis.form_b} />
      </div>

      {analysis.h2h.length > 0 && (
        <div className="card">
          <h3 className="font-semibold text-slate-800 mb-3">Histórico H2H</h3>
          <ul className="space-y-2">
            {analysis.h2h.map((m, idx) => (
              <li key={idx} className="text-sm flex justify-between border-b border-slate-100 pb-1">
                <span>
                  {m.venue === 'home' ? 'C' : 'F'} vs {m.opponent}
                </span>
                <span className="font-medium">
                  {m.goals_for}-{m.goals_against} ({m.result})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <p className="text-xs text-slate-500 italic text-center">{analysis.disclaimer}</p>
    </div>
  )
}
