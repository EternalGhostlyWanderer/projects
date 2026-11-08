"""SQLite storage for events, insights, agent traces, feedback and chat history.

Инсайты общие для компании, а скрытые события, отзывы, чат и заявки — у каждого пользователя
свои (user_id; пустая строка — запрос без пользователя, как до появления ролей).
"""
import json
import logging
import os
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from app.agents.trace import AgentTrace
from app.ai.schemas import Insight
from app.schemas.event import NewsEvent

BACKEND_DIR = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = BACKEND_DIR / "var" / "app.sqlite3"

# Меняйте при изменении логики анализа: старые инсайты перестанут браться из хранилища.
ANALYSIS_VERSION = "agent-1"

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id TEXT PRIMARY KEY,
    published_at TEXT,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_aliases (
    alias_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    method TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS insights (
    insight_id TEXT PRIMARY KEY,
    company_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    analysis_version TEXT NOT NULL,
    relevance_score INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS insights_company ON insights(company_id, event_id, analysis_version);
CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    insight_id TEXT,
    company_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id TEXT NOT NULL,
    useful INTEGER NOT NULL,
    comment TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS client_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    insight_id TEXT,
    kind TEXT NOT NULL,
    text TEXT,
    role TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS hidden_events (
    company_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (company_id, event_id)
);
CREATE TABLE IF NOT EXISTS user_hidden_events (
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (company_id, user_id, event_id)
);
CREATE TABLE IF NOT EXISTS user_data_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id TEXT NOT NULL,
    user_id TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    document TEXT,
    fields TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS role_views (
    insight_id TEXT NOT NULL,
    role TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (insight_id, role)
);
CREATE TABLE IF NOT EXISTS source_health (
    source_key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS offtopic_items (
    event_id TEXT PRIMARY KEY,
    title TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS company_user_data (
    company_id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS accounts (
    login TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL,
    companies TEXT NOT NULL DEFAULT '[]',
    origin TEXT NOT NULL DEFAULT 'self',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_id TEXT NOT NULL,
    role TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


# Колонки, добавленные после первых демо-баз: в старой базе их добавляет миграция при старте.
_ADDED_COLUMNS = (
    ("feedback", "user_id", "TEXT NOT NULL DEFAULT ''"),
    ("feedback", "role", "TEXT"),
    ("chat_messages", "user_id", "TEXT NOT NULL DEFAULT ''"),
    ("client_requests", "user_id", "TEXT NOT NULL DEFAULT ''"),
)


def _migrate(connection: sqlite3.Connection) -> None:
    for table, column, declaration in _ADDED_COLUMNS:
        columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")
    # Скрытые до появления пользователей события остаются скрытыми для запросов без пользователя.
    connection.execute(
        "INSERT OR IGNORE INTO user_hidden_events SELECT company_id, '', event_id, created_at FROM hidden_events"
    )
    connection.execute("DELETE FROM hidden_events")


def _insight(data: str) -> Optional[Insight]:
    """Разбор из базы; запись, которая больше не проходит проверку контракта, пропускается с предупреждением,
    а не роняет ленту (так было с разбором, сохранённым до исправления repair_draft)."""
    try:
        return Insight.model_validate_json(data)
    except ValidationError as exc:
        logger.warning("Сохранённый разбор не прошёл проверку контракта и пропущен: %s", str(exc)[:300])
        return None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AppStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection, connection:
            connection.executescript(_SCHEMA)
            _migrate(connection)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=10)

    def _write(self, sql: str, params: tuple) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(sql, params)

    def _rows(self, sql: str, params: tuple = ()) -> list[tuple]:
        with closing(self._connect()) as connection:
            return connection.execute(sql, params).fetchall()

    # События
    def save_event(self, event: NewsEvent) -> None:
        self._write(
            "INSERT OR REPLACE INTO events VALUES (?, ?, ?, ?)",
            (
                event.event_id,
                event.published_at.isoformat() if event.published_at else None,
                _now(),
                event.model_dump_json(),
            ),
        )

    def get_event(self, event_id: str) -> Optional[NewsEvent]:
        """Событие по id; id склеенной публикации ведёт к каноническому событию."""
        rows = self._rows("SELECT data FROM events WHERE event_id = ?", (self.resolve_event_id(event_id),))
        return NewsEvent.model_validate_json(rows[0][0]) if rows else None

    def resolve_event_id(self, event_id: str) -> str:
        rows = self._rows("SELECT event_id FROM event_aliases WHERE alias_id = ?", (event_id,))
        return rows[0][0] if rows else event_id

    def add_event_alias(self, alias_id: str, event_id: str, method: str) -> None:
        if alias_id != event_id:
            self._write(
                "INSERT OR REPLACE INTO event_aliases VALUES (?, ?, ?, ?)",
                (alias_id, event_id, method, _now()),
            )

    def count_event_aliases(self) -> int:
        return self._rows("SELECT COUNT(*) FROM event_aliases")[0][0]

    def recent_events(self, since: datetime, limit: int = 500) -> list[NewsEvent]:
        """События с публикацией (или добавлением) не раньше since — кандидаты для склейки."""
        rows = self._rows(
            """
            SELECT data FROM events
            WHERE COALESCE(published_at, created_at) >= ?
            ORDER BY COALESCE(published_at, created_at) DESC LIMIT ?
            """,
            (since.isoformat(), limit),
        )
        return [NewsEvent.model_validate_json(row[0]) for row in rows]

    def list_events(self, limit: int = 100, offset: int = 0) -> list[NewsEvent]:
        rows = self._rows(
            "SELECT data FROM events ORDER BY COALESCE(published_at, created_at) DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        return [NewsEvent.model_validate_json(row[0]) for row in rows]

    def delete_event(self, event_id: str) -> None:
        """Убрать событие из ленты (разборы по нему остаются в базе, но в ленту не попадут)."""
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM events WHERE event_id = ?", (event_id,))
            connection.execute("DELETE FROM event_aliases WHERE event_id = ?", (event_id,))

    def count_events(self) -> int:
        return self._rows("SELECT COUNT(*) FROM events")[0][0]

    # Инсайты и журналы
    def save_analysis(self, insight: Insight, trace: AgentTrace) -> None:
        # Изменения через model_copy не проверяются: проверяем контракт перед записью, чтобы в базу
        # не попал разбор, который потом не прочитается (ValidationError — ошибка анализа, а не ленты).
        insight = Insight.model_validate(insight.model_dump(mode="json"))
        self._write(
            "INSERT OR REPLACE INTO insights VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                insight.insight_id,
                insight.company_id,
                insight.event_id,
                ANALYSIS_VERSION,
                insight.relevance.score,
                insight.created_at,
                insight.model_dump_json(),
            ),
        )
        self.save_trace(trace)

    def save_trace(self, trace: AgentTrace) -> None:
        self._write(
            "INSERT OR REPLACE INTO traces VALUES (?, ?, ?, ?, ?, ?)",
            (
                trace.trace_id,
                trace.insight_id,
                trace.company_id,
                trace.event_id,
                trace.started_at,
                trace.model_dump_json(),
            ),
        )

    def get_insight(self, insight_id: str) -> Optional[Insight]:
        rows = self._rows("SELECT data FROM insights WHERE insight_id = ?", (insight_id,))
        return _insight(rows[0][0]) if rows else None

    def find_insight(self, company_id: str, event_id: str) -> Optional[Insight]:
        rows = self._rows(
            """
            SELECT data FROM insights
            WHERE company_id = ? AND event_id = ? AND analysis_version = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (company_id, event_id, ANALYSIS_VERSION),
        )
        return _insight(rows[0][0]) if rows else None

    def list_insights(self, company_id: str, limit: int = 50) -> list[Insight]:
        rows = self._rows(
            """
            SELECT data FROM insights
            WHERE company_id = ? AND analysis_version = ?
            ORDER BY relevance_score DESC, created_at DESC LIMIT ?
            """,
            (company_id, ANALYSIS_VERSION, limit),
        )
        return [insight for insight in (_insight(row[0]) for row in rows) if insight is not None]

    def insight_ids_by_event(self, company_id: str) -> dict[str, Insight]:
        return {insight.event_id: insight for insight in reversed(self.list_insights(company_id, limit=500))}

    def get_trace(self, trace_id: str) -> Optional[AgentTrace]:
        rows = self._rows("SELECT data FROM traces WHERE trace_id = ?", (trace_id,))
        return AgentTrace.model_validate_json(rows[0][0]) if rows else None

    # Обратная связь и чат
    def save_feedback(
        self,
        insight_id: str,
        useful: bool,
        comment: Optional[str],
        *,
        user_id: str = "",
        role: Optional[str] = None,
    ) -> None:
        self._write(
            "INSERT INTO feedback (insight_id, useful, comment, created_at, user_id, role) VALUES (?, ?, ?, ?, ?, ?)",
            (insight_id, int(useful), comment, _now(), user_id, role),
        )

    def feedback_summary(self) -> dict[str, Any]:
        useful, total = self._rows("SELECT COALESCE(SUM(useful), 0), COUNT(*) FROM feedback")[0]
        # По ролям: видно, кому разборы полезнее, а кому нет (мониторинг качества, критерий 08).
        by_role = {
            role or "unknown": {"useful": role_useful, "total": role_total}
            for role, role_useful, role_total in self._rows(
                "SELECT role, COALESCE(SUM(useful), 0), COUNT(*) FROM feedback GROUP BY role"
            )
        }
        return {"useful": useful, "total": total, "by_role": by_role}

    def add_chat_message(self, insight_id: str, role: str, data: dict[str, Any], *, user_id: str = "") -> None:
        self._write(
            "INSERT INTO chat_messages (insight_id, role, data, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (insight_id, role, json.dumps(data, ensure_ascii=False), _now(), user_id),
        )

    def chat_history(self, insight_id: str, *, user_id: str = "") -> list[dict[str, Any]]:
        """История чата по инсайту у этого пользователя: коллеги не видят чужих вопросов."""
        rows = self._rows(
            "SELECT role, data, created_at FROM chat_messages WHERE insight_id = ? AND user_id = ? ORDER BY id",
            (insight_id, user_id),
        )
        return [{"role": role, "created_at": created, **json.loads(data)} for role, data, created in rows]


    # Заявки клиента: обратный звонок менеджера, вопрос аналитику банка
    def add_request(
        self,
        company_id: str,
        kind: str,
        *,
        insight_id: Optional[str] = None,
        text: Optional[str] = None,
        role: Optional[str] = None,
        user_id: str = "",
    ) -> int:
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO client_requests (company_id, insight_id, kind, text, role, status, created_at, user_id)"
                " VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?)",
                (company_id, insight_id, kind, text, role, _now(), user_id),
            )
            return int(cursor.lastrowid)

    def list_requests(self, company_id: str) -> list[dict[str, Any]]:
        """Все заявки компании (менеджер видит, кто из сотрудников и в какой роли обратился)."""
        rows = self._rows(
            "SELECT id, insight_id, kind, text, role, user_id, status, created_at FROM client_requests"
            " WHERE company_id = ? ORDER BY id DESC",
            (company_id,),
        )
        keys = ("request_id", "insight_id", "kind", "text", "role", "user_id", "status", "created_at")
        return [dict(zip(keys, row)) for row in rows]

    def count_requests(self) -> dict[str, int]:
        return dict(self._rows("SELECT kind, COUNT(*) FROM client_requests GROUP BY kind"))

    # Скрытые пользователем события ленты: у каждого сотрудника компании свои
    def hide_event(self, company_id: str, event_id: str, user_id: str = "") -> None:
        self._write(
            "INSERT OR REPLACE INTO user_hidden_events VALUES (?, ?, ?, ?)",
            (company_id, user_id, self.resolve_event_id(event_id), _now()),
        )

    def unhide_event(self, company_id: str, event_id: str, user_id: str = "") -> None:
        self._write(
            "DELETE FROM user_hidden_events WHERE company_id = ? AND user_id = ? AND event_id = ?",
            (company_id, user_id, self.resolve_event_id(event_id)),
        )

    def hidden_event_ids(self, company_id: str, user_id: str = "") -> set[str]:
        return {
            row[0]
            for row in self._rows(
                "SELECT event_id FROM user_hidden_events WHERE company_id = ? AND user_id = ?", (company_id, user_id)
            )
        }

    # Ролевой слой разбора: «Что это значит для вас» по паре «разбор × роль» (agents/role_view.py)
    def save_role_view(self, insight_id: str, role: str, data: dict[str, Any]) -> None:
        self._write(
            "INSERT OR REPLACE INTO role_views VALUES (?, ?, ?, ?)",
            (insight_id, role, json.dumps(data, ensure_ascii=False), _now()),
        )

    def get_role_view(self, insight_id: str, role: str) -> Optional[dict[str, Any]]:
        rows = self._rows("SELECT data FROM role_views WHERE insight_id = ? AND role = ?", (insight_id, role))
        return json.loads(rows[0][0]) if rows else None

    # Здоровье источников новостей (source_health.py)
    def record_source_run(self, key: str, name: str, kind: str, run: dict[str, Any]) -> dict[str, Any]:
        """Добавить результат запуска к истории источника и вернуть обновлённую запись."""
        rows = self._rows("SELECT data FROM source_health WHERE source_key = ?", (key,))
        record = json.loads(rows[0][0]) if rows else {"first_seen_at": run["at"], "runs": 0, "failures": 0}
        record.update(
            {
                "source_key": key,
                "name": name,
                "kind": kind,
                "runs": record.get("runs", 0) + 1,
                "last_run_at": run["at"],
                "last_status": run["status"],
                "last_error": run.get("error"),
                "last_duration_ms": run.get("duration_ms"),
                "last_items": run.get("items", 0),
                "last_added": run.get("added", 0),
                "last_merged": run.get("merged", 0),
                "last_offtopic": run.get("offtopic", 0),
                "last_old": run.get("old", 0),
                "last_known": run.get("known", 0),
                "last_clickbait": run.get("clickbait", 0),
            }
        )
        if run["status"] == "ok" or (run.get("items") and not run.get("error")):
            record["last_ok_at"] = run["at"]
        else:
            record["failures"] = record.get("failures", 0) + 1
        if run.get("added") or run.get("merged"):
            record["last_new_at"] = run["at"]
        self._write(
            "INSERT OR REPLACE INTO source_health VALUES (?, ?, ?, ?)",
            (key, name, kind, json.dumps(record, ensure_ascii=False)),
        )
        return record

    def source_health(self) -> list[dict[str, Any]]:
        return [json.loads(row[0]) for row in self._rows("SELECT data FROM source_health ORDER BY name")]

    # Публикации не про бизнес: не сохраняются в ленту, но запоминаются, чтобы не классифицировать снова
    def mark_offtopic(self, event_id: str, title: str) -> None:
        self._write("INSERT OR REPLACE INTO offtopic_items VALUES (?, ?, ?)", (event_id, title, _now()))

    def is_offtopic(self, event_id: str) -> bool:
        return bool(self._rows("SELECT 1 FROM offtopic_items WHERE event_id = ?", (event_id,)))

    def count_offtopic(self) -> int:
        return self._rows("SELECT COUNT(*) FROM offtopic_items")[0][0]

    def count_hidden(self) -> int:
        return self._rows("SELECT COUNT(*) FROM user_hidden_events")[0][0]

    # Сведения о компании от пользователя (вебинар, вопросы 28 и 33)
    def save_user_data(self, company_id: str, data: dict[str, Any]) -> None:
        self._write(
            "INSERT OR REPLACE INTO company_user_data VALUES (?, ?, ?)",
            (company_id, json.dumps(data, ensure_ascii=False), _now()),
        )

    def log_user_data_change(
        self, company_id: str, *, user_id: str, source: str, fields: list[str], document: Optional[str] = None
    ) -> None:
        """Журнал изменений сведений о компании: кто, когда, какие поля и откуда (без самих значений)."""
        self._write(
            "INSERT INTO user_data_log (company_id, user_id, source, document, fields, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (company_id, user_id, source, document, json.dumps(fields, ensure_ascii=False), _now()),
        )

    def user_data_history(self, company_id: str, limit: int = 50) -> list[dict[str, Any]]:
        rows = self._rows(
            "SELECT user_id, source, document, fields, created_at FROM user_data_log WHERE company_id = ? ORDER BY id DESC LIMIT ?",
            (company_id, limit),
        )
        return [
            {"user_id": user_id or None, "source": source, "document": document, "fields": json.loads(fields), "created_at": created}
            for user_id, source, document, fields, created in rows
        ]

    # Учётные записи: зарегистрированные на сайте (origin=self) и правки профиля пользователей
    # из AUTH_USERS (origin=env). Пароль — только хеш pbkdf2.
    def get_account(self, login: str) -> Optional[dict[str, Any]]:
        rows = self._rows(
            "SELECT login, password_hash, name, role, companies, origin FROM accounts WHERE login = ?", (login,)
        )
        if not rows:
            return None
        login, password_hash, name, role, companies, origin = rows[0]
        return {
            "login": login,
            "password_hash": password_hash,
            "name": name,
            "role": role,
            "companies": json.loads(companies),
            "origin": origin,
        }

    def save_account(
        self, *, login: str, password_hash: str, name: str, role: str, companies: list[str], origin: str
    ) -> None:
        now = _now()
        self._write(
            """
            INSERT INTO accounts (login, password_hash, name, role, companies, origin, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(login) DO UPDATE SET password_hash = excluded.password_hash, name = excluded.name,
                role = excluded.role, companies = excluded.companies, updated_at = excluded.updated_at
            """,
            (login, password_hash, name, role, json.dumps(companies, ensure_ascii=False), origin, now, now),
        )

    def get_user_data(self, company_id: str) -> dict[str, Any]:
        rows = self._rows("SELECT data, updated_at FROM company_user_data WHERE company_id = ?", (company_id,))
        return {**json.loads(rows[0][0]), "updated_at": rows[0][1]} if rows else {}


@lru_cache(maxsize=1)
def get_store() -> AppStore:
    # Относительный путь считается от корня репозитория.
    return AppStore(BACKEND_DIR.parent / (os.getenv("APP_DB_PATH", "") or DEFAULT_DB_PATH))
