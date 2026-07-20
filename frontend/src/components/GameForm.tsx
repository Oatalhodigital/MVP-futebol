import React, { useState } from 'react'

interface Props {
  onSubmit: (payload: {
    team_a: string
    team_b: string
    competition?: string
    match_datetime?: string
  }) => void
  loading: boolean
}

export default function GameForm({ onSubmit, loading }: Props) {
  const [teamA, setTeamA] = useState('')
  const [teamB, setTeamB] = useState('')
  const [competition, setCompetition] = useState('')
  const [datetime, setDatetime] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!teamA.trim() || !teamB.trim()) return
    const payload: { team_a: string; team_b: string; competition?: string; match_datetime?: string } = {
      team_a: teamA.trim(),
      team_b: teamB.trim(),
    }
    if (competition.trim()) payload.competition = competition.trim()
    if (datetime) payload.match_datetime = new Date(datetime).toISOString()
    onSubmit(payload)
  }

  return (
    <section className="card">
      <h2 className="text-xl font-semibold mb-4 text-slate-800">Novo jogo</h2>
      <form onSubmit={handleSubmit} className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Time A (mandante)</label>
          <input
            type="text"
            value={teamA}
            onChange={(e) => setTeamA(e.target.value)}
            placeholder="Ex: Flamengo"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Time B (visitante)</label>
          <input
            type="text"
            value={teamB}
            onChange={(e) => setTeamB(e.target.value)}
            placeholder="Ex: Palmeiras"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
            required
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Competição (opcional)</label>
          <input
            type="text"
            value={competition}
            onChange={(e) => setCompetition(e.target.value)}
            placeholder="Ex: Brasileirão"
            className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">Data/Hora (opcional)</label>
          <input
            type="datetime-local"
            value={datetime}
            onChange={(e) => setDatetime(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-primary"
          />
        </div>
        <div className="md:col-span-2">
          <button type="submit" disabled={loading} className="btn-primary w-full md:w-auto">
            {loading ? 'Analisando...' : 'Analisar'}
          </button>
        </div>
      </form>
    </section>
  )
}
