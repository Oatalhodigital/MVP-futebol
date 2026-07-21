import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta
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
                    created_at TIMESTAMP NOT NULL,
                    ttl_seconds INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_created_at
                ON match_cache(created_at)
                """
            )
            # Add ttl_seconds column if the table was created before this migration
            try:
                conn.execute("ALTER TABLE match_cache ADD COLUMN ttl_seconds INTEGER")
            except sqlite3.OperationalError:
                pass

    def _make_key(self, match_input: MatchInput, provider_name: str) -> str:
        norm = lambda s: " ".join(s.strip().lower().split())
        return f"{provider_name}:{norm(match_input.team_a)}_vs_{norm(match_input.team_b)}"

    def get(self, match_input: MatchInput, provider_name: str) -> MatchData | None:
        key = self._make_key(match_input, provider_name)
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT data, created_at, ttl_seconds FROM match_cache WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return None
        if self._is_expired(row):
            return None
        try:
            parsed = MatchData.model_validate(json.loads(row["data"]))
            parsed.updated_at = datetime.fromisoformat(row["created_at"])
            return parsed
        except Exception:
            return None

    def set(
        self,
        match_input: MatchInput,
        provider_name: str,
        data: MatchData,
        ttl_seconds: int | None = None,
    ) -> None:
        key = self._make_key(match_input, provider_name)
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO match_cache (key, provider, data, created_at, ttl_seconds) VALUES (?, ?, ?, ?, ?)",
                    (
                        key,
                        provider_name,
                        data.model_dump_json(),
                        datetime.utcnow().isoformat(),
                        ttl_seconds or self.ttl_seconds,
                    ),
                )

    def _is_expired(self, row: sqlite3.Row) -> bool:
        created = datetime.fromisoformat(row["created_at"])
        ttl = row["ttl_seconds"] if row["ttl_seconds"] is not None else self.ttl_seconds
        return (datetime.utcnow() - created) > timedelta(seconds=ttl)

    def clear_old(self, max_age_seconds: int = 3600) -> int:
        cutoff = (datetime.utcnow() - timedelta(seconds=max_age_seconds)).isoformat()
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("DELETE FROM match_cache WHERE created_at < ?", (cutoff,))
                return cursor.rowcount
