# Checklist de Deploy — MVP Futebol (Render + Vercel)

Preencha os valores reais nos dashboards do Render e da Vercel (não commitar chaves/segredos no repositório).

---

## 1. Render (backend)

Vá até o serviço `football-analysis-api` (ou equivalente) em https://dashboard.render.com.

### Environment Variables

| Nome | Valor esperado | Obrigatório? |
|------|----------------|--------------|
| `FRONTEND_URL` | `https://mvp-futebol.vercel.app` (sem barra no final) | **Sim** |
| `GOOGLE_API_KEY` | sua chave real | Não |
| `GOOGLE_CX` | seu CX real | Não (se usar Google) |
| `COMPLETENESS_THRESHOLD` | `0.3` | Não |
| `CACHE_TTL_SECONDS` | `60` | Não |
| `PLAYWRIGHT_HEADLESS` | `true` | Não |

**Importante:**
- `FRONTEND_URL` **não** pode ter `/` no final.
- NÃO adicione `VITE_API_URL` aqui — essa variável pertence ao Vercel.
- `PORT` é injetado automaticamente pelo Render; não precisa criar.

### Após salvar

1. Dispare o deploy no Render.
2. Aguarde o build terminar.

---

## 2. Vercel (frontend)

Vá até o projeto em https://vercel.com/dashboard.

### Environment Variables

| Nome | Valor esperado |
|------|----------------|
| `VITE_API_URL` | `https://mvp-futebol.onrender.com` (sem barra no final) |

### Após salvar

1. Redeploy o frontend para que o Vite injete a variável no build.

---

## 3. Verificações pós-deploy

### Backend isolado

```bash
curl https://mvp-futebol.onrender.com/api/health
```

Deve retornar:

```json
{"status":"ok"}
```

Se retornar algo diferente, verifique os logs do Render.

### Frontend + CORS

1. Abra `https://mvp-futebol.vercel.app`.
2. Abra o DevTools (F12) na aba Console.
3. Preencha dois times reais (ex: `Flamengo` x `Palmeiras`) e clique em **Analisar**.
4. Verifique:
   - Nenhum erro `CORS` no console.
   - Nenhuma requisição para `localhost:8000`.
   - A chamada para `https://mvp-futebol.onrender.com/api/matches/analyze` retorna `200 OK`.

---

## 4. O que foi corrigido no código

- `backend/app/main.py`: CORS lê `FRONTEND_URL`, remove `/` no final e loga o valor usado.
- `backend/Dockerfile`: usa a porta injetada pelo Render (`$PORT`) e reinstala/garante o Chromium do Playwright.
- `backend/.env.example` e `frontend/.env.example`: listam apenas variáveis de cada lado, sem cruzamento.
- `render.yaml`: corrige o caminho do Dockerfile e adiciona `PLAYWRIGHT_HEADLESS`.
- `frontend/vercel.json`: adiciona rewrite catch-all para SPA.
