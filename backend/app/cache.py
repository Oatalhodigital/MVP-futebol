import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
from typing import Any

from app.models import MatchData, MatchInput


class MatchCache:
    """Simple SQLite cache for provider MatchData, shared across users/requests."""

    def __init__(self, db_path: str | None = None, ttl_seconds: int = 60):
        self.db_path = db_path or os.path.join(os.getcwd(), "cache", "matches.db")
        self.ttl_seconds = ttl_seconds
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS match_cache (
                    key TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON match_cache(created_at)
                """
            )

    def _make_key(self, match_input: MatchInput, provider_name: str) -> str:
        norm = lambda s: " ".join(s.strip().lower().split())
        return f"{provider_name}:{norm(match_input.team_a)}_vs_{norm(match_input.team_b)}"

    def get(self, match_input: MatchInput, provider_name: str) -> MatchData | None:
        key = self._make_key(match_input, provider_name)
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT data, created_at FROM match_cache WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        data_json, created_at = row
        created = datetime.fromisoformat(created_at)
        if datetime.utcnow() - created > timedelta(seconds=self.ttl_seconds):
            return None
        try:
            parsed = MatchData.model_validate(json.loads(data_json))
            parsed.updated_at = created
            return parsed
        except Exception:
            return None

    def set(self, match_input: MatchInput, provider_name: str, data: MatchData) -> None:
        key = self._make_key(match_input, provider_name)
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO match_cache (key, provider, data, created_at) VALUES (?, ?, ?, ?)",
                    (key, provider_name, data.model_dump_json(), datetime.utcnow().isoformat()),
                )

    def clear_old(self, max_age_seconds: int = 3600) -> int:
        cutoff = (datetime.utcnow() - timedelta(seconds=max_age_seconds)).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM match_cache WHERE created_at < ?", (cutoff,))
                return cursor.rowcount
