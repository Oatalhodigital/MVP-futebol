import logging
import os
import re

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import matches

logger = logging.getLogger(__name__)


def _normalize_origin(origin: str | None) -> str | None:
    """Return origin with trailing slash removed, or None if empty/invalid."""
    if not origin:
        return None
    origin = origin.strip()
    if not origin:
        return None
    return origin.rstrip("/")


def _build_cors_config() -> tuple[list[str], str]:
    """Build allow_origins and allow_origin_regex from environment."""
    frontend_url = _normalize_origin(os.getenv("FRONTEND_URL"))
    local_regex = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

    if frontend_url:
        logger.info("CORS configured for frontend: %s", frontend_url)
        return [frontend_url], local_regex

    logger.warning("FRONTEND_URL not set; CORS will only allow localhost/127.0.0.1")
    return [], local_regex


allow_origins, allow_origin_regex = _build_cors_config()

app = FastAPI(
    title="Painel de Análise Estatística de Futebol",
    description=(
        "Dashboard pessoal de análise estatística de futebol. "
        "Não realiza apostas, não exibe odds e não tem vínculo com casas de apostas."
    ),
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches.router, prefix="/api")


@app.get("/api/health")
def health():
    return {"status": "ok"}
