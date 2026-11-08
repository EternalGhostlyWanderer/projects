"""Who is using the service right now: active sessions drive the news refresh.

Лента обновляется, пока ею пользуются: если за последние NEWS_ACTIVE_WINDOW_MIN минут
(по умолчанию 30) был запрос от пользователя или компании, плановый сбор идёт; если никого
нет — пропускается, чтобы не тратить запросы к источникам и бюджет LLM впустую.
Активность хранится в памяти процесса: после перезапуска сервера сессии считаются заново.
"""
import os
import threading
import time
from typing import Optional

_lock = threading.Lock()
_seen: dict[tuple[str, str], float] = {}


def window_seconds() -> float:
    try:
        return float(os.getenv("NEWS_ACTIVE_WINDOW_MIN", "") or 30) * 60
    except ValueError:
        return 30 * 60


def touch(company_id: Optional[str], user_id: Optional[str] = None, *, now: Optional[float] = None) -> None:
    if not company_id and not user_id:
        return
    with _lock:
        _seen[(company_id or "", user_id or "")] = now if now is not None else time.monotonic()


def active(*, now: Optional[float] = None) -> list[tuple[str, str]]:
    """Пары (компания, пользователь), активные в окне; устаревшие записи удаляются."""
    moment = now if now is not None else time.monotonic()
    horizon = moment - window_seconds()
    with _lock:
        for key in [key for key, seen in _seen.items() if seen < horizon]:
            del _seen[key]
        return sorted(_seen)


def active_companies(*, now: Optional[float] = None) -> list[str]:
    return sorted({company for company, _ in active(now=now) if company})


def clear() -> None:
    with _lock:
        _seen.clear()
