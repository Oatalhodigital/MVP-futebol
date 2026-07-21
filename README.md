# Painel de Análise Estatística de Futebol

Aplicativo web pessoal para análise estatística de futebol. **Não realiza apostas, não exibe odds de mercado e não possui qualquer vínculo com casas de apostas.**

O objetivo é puramente analítico/didático: você informa um confronto e o sistema busca dados públicos na web, processa com modelos estatísticos (Poisson e médias móveis) e exibe probabilidades e estatísticas para interpretação pessoal.

## Arquitetura

```
ROBO/
├── backend/   # FastAPI + motor estatístico + camada de providers + cache
└── frontend/  # React + Tailwind + Recharts
```

### Backend

- **FastAPI** expõe o endpoint `/api/matches/analyze`.
- **Camada `DataProvider`**: abstração para provedores de dados. Implementações atuais:
  - `BrowserNavigationProvider`: Playwright headless navegando no 365Scores para extrair status ao vivo (placar, minuto, escanteios, chutes, posse, cartões) e forma recente.
  - `BrowserSearchProvider`: busca pública sem API key em DuckDuckGo/Google HTML, busca páginas de estatísticas esportivas e extrai dados (fallback inteligente).
  - `TheSportsDbProvider`: API pública gratuita do TheSportsDB, com busca por nome de time e cobertura ampliada para ligas menores.
  - `GoogleSyncProvider`: busca estruturada via Google Custom Search ou Bing Search API — **opcional**, só entra no orquestrador quando configurado.
  - `WebSearchProvider`: busca pública no Yahoo + parsing de snippets (fallback leve).
  - `MockProvider`: retorna dados sintéticos de segurança quando nenhuma fonte funciona.
- **Orquestrador**: tenta os provedores em ordem (`BrowserNavigation → BrowserSearch → TheSportsDB → GoogleSync [se configurado] → Web → Mock`), respeita timeout curto por fonte, reaproveita cache SQLite com TTL adaptativo e mescla os melhores pedaços de cada fonte.
- **Cache SQLite** (`backend/cache/matches.db`): evita múltiplas navegações simultâneas para o mesmo jogo. TTL configurável (padrão 60s).
- **Motor estatístico** (`app/stats/engine.py`): Poisson para xG, over/under, BTTS, cantos e chutes; análise se adapta a pré-jogo, ao vivo e encerrado.

### Frontend

- React + Vite + Tailwind CSS + Recharts.
- Painel único que se adapta conforme o status do jogo:
  - **Pré-jogo**: probabilidades HT/FT, over/under, BTTS, cantos, chutes e gráficos.
  - **Ao vivo**: placar/minuto real, estatísticas já ocorridas e projeção para o restante da partida.
  - **Encerrado**: resultado final e estatísticas finais reais.
  - **Dados insuficientes**: aviso claro quando nenhum provider consegue dados confiáveis.

## Variáveis de ambiente

Copie `backend/.env.example` para `backend/.env` e `frontend/.env.example` para `frontend/.env`.

### Backend (`backend/.env`)

```env
FRONTEND_URL=https://meu-painel.vercel.app

# Opcional: Google Custom Search / Bing Search API. O sistema funciona 100%
# sem essas chaves, usando DuckDuckGo/Google HTML e APIs publicas gratuitas.
# GOOGLE_API_KEY=...
# GOOGLE_CX=...
# BING_API_KEY=...

COMPLETENESS_THRESHOLD=0.3
CACHE_TTL_SECONDS=60
```

### Frontend (`frontend/.env`)

```env
VITE_API_URL=http://localhost:8000
# em produção:
# VITE_API_URL=https://meu-backend.onrender.com
```

## Como rodar localmente

### 1. Backend

```bash
cd backend
python -m venv .venv
. .venv\Scripts\activate      # Windows
# source .venv/bin/activate    # Linux/Mac
pip install -r requirements.txt
playwright install chromium   # baixa o navegador usado pelo BrowserNavigationProvider
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

O frontend roda em `http://localhost:5173` e proxya chamadas `/api` para `VITE_API_URL` (padrão `http://localhost:8000`).

## Deploy público (link compartilhável)

### Backend (Render)

1. Crie um `Web Service` no [Render](https://render.com) e conecte este repositório.
2. Use `Docker` como runtime com `backend/Dockerfile`.
3. Defina as variáveis de ambiente:
   - `FRONTEND_URL` = URL do frontend na Vercel
   - `GOOGLE_API_KEY` / `GOOGLE_CX`
4. O arquivo `render.yaml` já prepara a configuração (substitua `YOUR-FRONTEND-URL`).

### Frontend (Vercel)

1. Crie um projeto no [Vercel](https://vercel.com) e conecte este repositório.
2. Configure `frontend` como `Root Directory` (ou importe apenas a pasta `frontend`).
3. Defina `VITE_API_URL` apontando para a URL do backend Render.
4. O `vercel.json` já está preparado.

Após o deploy, qualquer pessoa com o link pode cadastrar um jogo e ver a análise.

## Cache e uso responsável

- Cada confronto é cacheado por 60 segundos; consultas repetidas no mesmo minuto não disparam novas navegações.
- Playwright navega de forma enxuta, sem flood de requisições.
- O `BrowserNavigationProvider` possui seletores configuráveis em `backend/app/config.py`; se o 365Scores mudar, ajuste os seletores sem alterar o código principal.
- Se a completude dos dados for menor que `COMPLETENESS_THRESHOLD`, a interface mostra "Dados insuficientes" em vez de inventar números.

## Aviso legal e de uso

Este projeto é **para fins de estudo e análise pessoal**. Não recomenda, executa ou facilita apostas. As estimativas são baseadas em modelos estatísticos sobre dados históricos/públicos e não garantem resultados futuros. O uso de scraping deve respeitar os `robots.txt` e termos de uso dos sites consultados.
