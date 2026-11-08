"""Check that a running prototype has the data required for a full demo."""
import argparse
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def request_json(url: str, *, body: dict | None = None, headers: dict[str, str] | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST" if body is not None else "GET",
    )
    try:
        with urlopen(request, timeout=5) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError) as exc:
        raise RuntimeError(f"Не удалось получить {url}: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Проверить готовность запущенного прототипа.")
    parser.add_argument("--url", default="http://localhost:8000", help="Адрес backend")
    parser.add_argument("--company-id", default="SYN_001", help="Компания для проверки ленты")
    parser.add_argument("--login", default=os.getenv("DEMO_CHECK_LOGIN", "demo"), help="Demo-логин")
    parser.add_argument(
        "--password",
        default=os.getenv("DEMO_CHECK_PASSWORD", "alfa-signal"),
        help="Demo-пароль; безопаснее передать через DEMO_CHECK_PASSWORD",
    )
    parser.add_argument("--require-llm", action="store_true", help="Считать отсутствие LLM ошибкой")
    parser.add_argument("--require-bank-index", action="store_true", help="Считать пустой индекс ошибкой")
    args = parser.parse_args()
    base = args.url.rstrip("/")

    health = request_json(f"{base}/health")
    session = request_json(
        f"{base}/api/v1/auth/login",
        body={"login": args.login, "password": args.password},
    )
    headers = {
        "Authorization": f"Bearer {session['access_token']}",
        "X-Company-Id": args.company_id,
    }
    status = request_json(f"{base}/api/v1/system/status", headers=headers)
    feed = request_json(f"{base}/api/v1/feed?company_id={args.company_id}&limit=1", headers=headers)

    print(f"health: {health.get('status', 'unknown')}")
    print(f"auth: {session.get('login', 'unknown')}")
    print(f"llm: {'configured' if status.get('llm', {}).get('configured') else 'not configured'}")
    print(f"bank_chunks: {status.get('bank_chunks', 0)}")
    print(f"company: {args.company_id}, events: {feed.get('total', 0)}")

    failures = []
    if health.get("status") != "ok":
        failures.append("backend healthcheck не прошёл")
    if args.require_llm and not status.get("llm", {}).get("configured"):
        failures.append("LLM_API_KEY не настроен")
    if args.require_bank_index and not status.get("bank_chunks"):
        failures.append("индекс аналитики банка пуст")
    if "items" not in feed:
        failures.append("feed не вернул items")
    if failures:
        print("Ошибки: " + "; ".join(failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
