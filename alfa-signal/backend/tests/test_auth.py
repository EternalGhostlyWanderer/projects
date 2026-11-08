import importlib.util
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from app.api.v1.auth import hash_password, login_throttle, verify_password
from tests import test_api

SECRET = "s" * 40
HASHED = hash_password("correct horse battery", iterations=1000)
STRICT = {
    "AUTH_STRICT": "1",
    "DEMO_AUTH_SECRET": SECRET,
    "AUTH_USERS": f"ivan:{HASHED}:SYN_001:cfo:Иван",
    "DEMO_USERS": "",
}


class PasswordTests(unittest.TestCase):
    def test_hash_roundtrip(self) -> None:
        self.assertTrue(verify_password("correct horse battery", HASHED))
        self.assertFalse(verify_password("wrong", HASHED))

    def test_plain_password_only_outside_strict_mode(self) -> None:
        self.assertTrue(verify_password("pw", "pw"))
        with patch.dict("os.environ", {"AUTH_STRICT": "1"}):
            self.assertFalse(verify_password("pw", "pw"))

    def test_script_hash_is_accepted(self) -> None:
        path = Path(__file__).resolve().parents[1] / "scripts" / "hash_password.py"
        spec = importlib.util.spec_from_file_location("hash_password_script", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        self.assertTrue(verify_password("секретный пароль", module.hash_password("секретный пароль", 1000)))


class StrictAuthApiTests(unittest.TestCase):
    setUpClass = classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_api.ApiTests.tearDownClass.__func__)

    def setUp(self) -> None:
        test_api.ApiTests.setUp(self)
        login_throttle.reset()
        env = patch.dict("os.environ", STRICT)
        env.start()
        self.addCleanup(env.stop)

    def login(self, login: str = "ivan", password: str = "correct horse battery"):
        return self.client.post("/api/v1/auth/login", json={"login": login, "password": password})

    def test_api_closed_without_session(self) -> None:
        for method, path in (
            ("get", "/api/v1/companies"),
            ("get", "/api/v1/feed?company_id=SYN_001"),
            ("post", "/api/v1/insights/analyze"),
            ("get", "/api/v1/research/documents"),
            ("get", "/api/v1/system/status"),
        ):
            response = getattr(self.client, method)(path)
            self.assertEqual(response.status_code, 401, path)
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/auth/roles").status_code, 200)

    def test_login_with_hash_opens_api(self) -> None:
        response = self.login()
        self.assertEqual(response.status_code, 200, response.text)
        token = response.json()["access_token"]
        self.assertFalse(response.json()["demo"])
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/v1/companies", headers=headers).status_code, 200)
        me = self.client.get("/api/v1/auth/me", headers=headers).json()
        self.assertEqual((me["login"], me["companies"]), ("ivan", ["SYN_001"]))
        # Чужая компания закрыта и с действующей сессией.
        other = self.client.get("/api/v1/feed?company_id=SYN_002", headers=headers)
        self.assertEqual(other.status_code, 403)

    def test_demo_accounts_disabled(self) -> None:
        self.assertEqual(self.login("demo", "alfa-signal").status_code, 401)

    def test_forged_or_foreign_token_rejected(self) -> None:
        token = self.login().json()["access_token"]
        with patch.dict("os.environ", {"DEMO_AUTH_SECRET": "x" * 40}):
            response = self.client.get("/api/v1/companies", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    def test_weak_secret_blocks_login(self) -> None:
        with patch.dict("os.environ", {"DEMO_AUTH_SECRET": "change-this-to-a-random-secret"}):
            self.assertEqual(self.login().status_code, 503)

    def test_missing_users_blocks_login_without_registration(self) -> None:
        with patch.dict("os.environ", {"AUTH_USERS": "", "AUTH_REGISTRATION": "0"}):
            self.assertEqual(self.login().status_code, 503)
        # С регистрацией пустой AUTH_USERS допустим: пользователи заведут учётные записи сами.
        with patch.dict("os.environ", {"AUTH_USERS": ""}):
            self.assertEqual(self.login().status_code, 401)

    def test_bruteforce_is_throttled(self) -> None:
        for _ in range(5):
            self.assertEqual(self.login(password="wrong").status_code, 401)
        blocked = self.login()
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_throttle_lasts_one_minute(self) -> None:
        for _ in range(5):
            self.login(password="wrong")
        self.assertEqual(self.login().status_code, 429)
        later = time.monotonic() + 61
        with patch("app.api.v1.auth.time.monotonic", return_value=later):
            self.assertEqual(self.login().status_code, 200)

    def test_refresh_slides_session(self) -> None:
        session = self.login().json()
        self.assertLess(session["refresh_after"], session["expires_at"])
        later = int(time.time()) + 3600
        with patch("app.api.v1.auth.time.time", return_value=later):
            renewed = self.client.post(
                "/api/v1/auth/refresh", headers={"Authorization": f"Bearer {session['access_token']}"}
            )
        self.assertEqual(renewed.status_code, 200, renewed.text)
        self.assertEqual(renewed.json()["expires_at"] - session["expires_at"], 3600)

    def test_refresh_never_passes_max_age(self) -> None:
        start = int(time.time())
        with patch.dict("os.environ", {"AUTH_SESSION_HOURS": "24", "AUTH_SESSION_MAX_DAYS": "2"}):
            token = self.login().json()["access_token"]
            # Продлеваем каждые 20 часов, пока токен действует.
            for step in range(1, 4):
                with patch("app.api.v1.auth.time.time", return_value=start + step * 20 * 3600):
                    response = self.client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})
                if response.status_code != 200:
                    break
                token = response.json()["access_token"]
                self.assertLessEqual(response.json()["expires_at"], start + 2 * 86400)
        self.assertEqual(response.status_code, 401)

    def test_feed_request_refreshes_stale_news(self) -> None:
        token = self.login().json()["access_token"]
        with patch(
            "app.modules.news.scheduler.NewsScheduler.refresh_if_stale", return_value="started"
        ) as refresh:
            response = self.client.get(
                "/api/v1/feed?company_id=SYN_001", headers={"Authorization": f"Bearer {token}"}
            )
        self.assertEqual(response.json()["refresh"], "started")
        refresh.assert_called_once_with(30, trigger="open")

    def test_removed_user_cannot_refresh(self) -> None:
        token = self.login().json()["access_token"]
        other = f"petr:{HASHED}::cfo:Пётр"
        with patch.dict("os.environ", {"AUTH_USERS": other}):
            response = self.client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 401)

    def test_document_file_accepts_query_token(self) -> None:
        token = self.login().json()["access_token"]
        closed = self.client.get("/api/v1/research/documents/unknown/file")
        opened = self.client.get(f"/api/v1/research/documents/unknown/file?access_token={token}")
        self.assertEqual(closed.status_code, 401)
        self.assertNotEqual(opened.status_code, 401)
        # Токен в адресе — только для файла документа.
        listing = self.client.get(f"/api/v1/research/documents?access_token={token}")
        self.assertEqual(listing.status_code, 401)


if __name__ == "__main__":
    unittest.main()
