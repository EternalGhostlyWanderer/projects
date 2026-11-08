"""Строка пользователя для AUTH_USERS с паролем в виде хеша (вход на сервере, AUTH_STRICT=1).

Без зависимостей проекта — запускается обычным python3 на сервере:

    python3 backend/scripts/hash_password.py ivan --role cfo --name "Иван Петров" --companies SYN_001,SYN_002

Пароль спрашивается без отображения на экране. Полученную строку добавьте в AUTH_USERS
в корневом .env; несколько пользователей разделяются «;».
"""
import argparse
import base64
import getpass
import hashlib
import secrets
import sys

# Должно совпадать с app/api/v1/auth.py (hash_password).
HASH_SCHEME = "pbkdf2_sha256"
HASH_ITERATIONS = 390_000
ROLES = ("owner", "ceo", "cfo", "accountant", "treasury", "other")


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def hash_password(password: str, iterations: int = HASH_ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return f"{HASH_SCHEME}.{iterations}.{_encode(salt)}.{_encode(digest)}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("login")
    parser.add_argument("--role", default="cfo", choices=ROLES)
    parser.add_argument("--name", default="", help="Имя в шапке сайта")
    parser.add_argument("--companies", default="", help="SYNTHETIC_U через запятую; пусто — все из VITE_COMPANY_IDS")
    args = parser.parse_args()

    for value, label in ((args.login, "логин"), (args.name, "имя"), (args.companies, "компании")):
        if any(char in value for char in ":;|"):
            print(f"{label} не должен содержать символы : ; |", file=sys.stderr)
            return 1

    password = getpass.getpass("Пароль: ")
    if len(password) < 10:
        print("Пароль должен быть не короче 10 символов", file=sys.stderr)
        return 1
    if getpass.getpass("Повторите пароль: ") != password:
        print("Пароли не совпадают", file=sys.stderr)
        return 1

    companies = "|".join(item.strip() for item in args.companies.split(",") if item.strip())
    print(f"{args.login}:{hash_password(password)}:{companies}:{args.role}:{args.name or args.login}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
