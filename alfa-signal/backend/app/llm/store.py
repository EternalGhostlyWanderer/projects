"""SQLite storage for the LLM response cache and the call log."""
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS llm_cache (
    cache_key TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS llm_calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    day TEXT NOT NULL,
    task TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    cached INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    seconds REAL,
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    reasoning_tokens INTEGER,
    cost REAL,
    error TEXT
);
CREATE INDEX IF NOT EXISTS llm_calls_day ON llm_calls(day);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LLMStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def get_cached(self, cache_key: str) -> Optional[str]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT content FROM llm_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
        return row[0] if row else None

    def put_cached(self, cache_key: str, model: str, content: str) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                "INSERT OR REPLACE INTO llm_cache VALUES (?, ?, ?, ?)",
                (cache_key, model, content, _now().isoformat()),
            )

    def log_call(
        self,
        *,
        task: str,
        model: str,
        status: str,
        cached: bool,
        attempt: int,
        seconds: Optional[float] = None,
        usage: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> None:
        usage = usage or {}
        now = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO llm_calls (
                    created_at, day, task, model, status, cached, attempt, seconds,
                    prompt_tokens, completion_tokens, reasoning_tokens, cost, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now.isoformat(),
                    now.date().isoformat(),
                    task,
                    model,
                    status,
                    int(cached),
                    attempt,
                    seconds,
                    usage.get("prompt_tokens"),
                    usage.get("completion_tokens"),
                    usage.get("reasoning_tokens"),
                    usage.get("cost"),
                    error,
                ),
            )

    def daily_usage(self, day: Optional[str] = None) -> dict[str, float]:
        """Запросы за сутки (UTC), на которые модель ответила. Отказы провайдера (ошибка, лимит, перегрузка)
        не считаются: они не тратят ни деньги, ни квоту, а с цепочкой запасных моделей их бывает много."""
        day = day or _now().date().isoformat()
        with closing(self._connect()) as connection:
            requests, cost = connection.execute(
                """
                SELECT COUNT(*), COALESCE(SUM(cost), 0)
                FROM llm_calls
                WHERE day = ? AND cached = 0 AND status IN ('ok', 'invalid', 'empty')
                """,
                (day,),
            ).fetchone()
        return {"requests": requests, "cost": float(cost)}
