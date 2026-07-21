import { useState } from 'react'
import GameForm from './components/GameForm'
import AnalysisPanel from './components/AnalysisPanel'
import { apiUrl } from './lib/api'
import type { MatchAnalysis } from './types'

function App() {
  const [analysis, setAnalysis] = useState<MatchAnalysis | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleAnalyze = async (payload: {
    team_a: string
    team_b: string
    competition?: string
    match_datetime?: string
  }) => {
    setLoading(true)
    setError('')
    try {
      const res = await fetch(apiUrl('/api/matches/analyze'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error('Não foi possível obter dados para este jogo.')
      const data = await res.json()
      setAnalysis(data)
    } catch (err: any) {
      setError(err.message || 'Erro desconhecido')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-primary text-white py-5 shadow">
        <div className="max-w-5xl mx-auto px-4">
          <h1 className="text-2xl font-bold">Painel de Análise Estatística de Futebol</h1>
          <p className="text-sm opacity-90">Uso pessoal · Estudo esportivo · Sem apostas</p>
        </div>
      </header>

      <main className="max-w-5xl mx-auto px-4 py-8">
        <GameForm onSubmit={handleAnalyze} loading={loading} />

        {error && (
          <div className="mt-6 p-4 bg-red-50 text-red-700 rounded-lg border border-red-100">
            {error}
          </div>
        )}

        {analysis && <AnalysisPanel analysis={analysis} />}
      </main>
    </div>
  )
}

export default App
