import unittest
from unittest.mock import patch

from app.api.v1.auth import hash_password, login_throttle, register_throttle
from tests import test_api

SECRET = "s" * 40
STRICT = {
    "AUTH_STRICT": "1",
    "DEMO_AUTH_SECRET": SECRET,
    "AUTH_USERS": f"ivan:{hash_password('correct horse battery', iterations=1000)}:SYN_001:cfo:Иван",
    "DEMO_USERS": "",
    "AUTH_REGISTRATION": "1",
    "AUTH_REGISTRATION_CODE": "",
}
NEW = {"login": "Olga.S", "password": "very-secret-pass", "name": "  Ольга   Смирнова ", "role": "accountant"}


class RegistrationTests(unittest.TestCase):
    setUpClass = classmethod(test_api.ApiTests.setUpClass.__func__)
    tearDownClass = classmethod(test_api.ApiTests.tearDownClass.__func__)

    def setUp(self) -> None:
        test_api.ApiTests.setUp(self)
        login_throttle.reset()
        register_throttle.reset()
        env = patch.dict("os.environ", STRICT)
        env.start()
        self.addCleanup(env.stop)

    def register(self, **overrides):
        return self.client.post("/api/v1/auth/register", json={**NEW, **overrides})

    def auth(self, token: str) -> dict:
        return {"Authorization": f"Bearer {token}"}

    def test_options_are_public(self) -> None:
        options = self.client.get("/api/v1/auth/options").json()
        self.assertTrue(options["registration"])
        self.assertFalse(options["registration_code_required"])
        self.assertIn({"id": "accountant", "label": "Главный бухгалтер"}, options["roles"])

    def test_register_logs_in_and_opens_api(self) -> None:
        response = self.register()
        self.assertEqual(response.status_code, 201, response.text)
        session = response.json()
        self.assertEqual((session["login"], session["name"], session["role"]), ("olga.s", "Ольга Смирнова", "accountant"))
        self.assertEqual(self.client.get("/api/v1/companies", headers=self.auth(session["access_token"])).status_code, 200)
        # Вход тем же логином в другом регистре и паролем.
        again = self.client.post("/api/v1/auth/login", json={"login": "OLGA.S", "password": NEW["password"]})
        self.assertEqual(again.status_code, 200)
        me = self.client.get("/api/v1/auth/me", headers=self.auth(again.json()["access_token"])).json()
        self.assertTrue(me["registered"])

    def test_validation_and_duplicates(self) -> None:
        self.assertEqual(self.register(password="short").status_code, 422)
        self.assertEqual(self.register(login="ab").status_code, 422)
        self.assertEqual(self.register(login="ivan petrov").status_code, 422)
        self.assertEqual(self.register(role="king").status_code, 422)
        self.assertEqual(self.register().status_code, 201)
        self.assertEqual(self.register().status_code, 409)
        self.assertEqual(self.register(login="ivan").status_code, 409)  # логин из AUTH_USERS занят

    def test_registration_can_be_disabled_or_need_code(self) -> None:
        with patch.dict("os.environ", {"AUTH_REGISTRATION": "0"}):
            self.assertEqual(self.register().status_code, 403)
        with patch.dict("os.environ", {"AUTH_REGISTRATION_CODE": "alfa-2026"}):
            self.assertTrue(self.client.get("/api/v1/auth/options").json()["registration_code_required"])
            self.assertEqual(self.register(code="wrong").status_code, 403)
            self.assertEqual(self.register(code="alfa-2026").status_code, 201)

    def test_registration_rate_limited_per_address(self) -> None:
        for index in range(5):
            self.assertEqual(self.register(login=f"user{index}").status_code, 201)
        self.assertEqual(self.register(login="user9").status_code, 429)

    def test_profile_update_name_role_password(self) -> None:
        token = self.register().json()["access_token"]
        updated = self.client.patch(
            "/api/v1/auth/me", json={"name": "Ольга С.", "role": "cfo"}, headers=self.auth(token)
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual((updated.json()["name"], updated.json()["role"]), ("Ольга С.", "cfo"))
        token = updated.json()["access_token"]

        wrong = self.client.patch(
            "/api/v1/auth/me", json={"current_password": "nope", "new_password": "another-long-pass"},
            headers=self.auth(token),
        )
        self.assertEqual(wrong.status_code, 403)
        changed = self.client.patch(
            "/api/v1/auth/me", json={"current_password": NEW["password"], "new_password": "another-long-pass"},
            headers=self.auth(token),
        )
        self.assertEqual(changed.status_code, 200)
        old = self.client.post("/api/v1/auth/login", json={"login": "olga.s", "password": NEW["password"]})
        new = self.client.post("/api/v1/auth/login", json={"login": "olga.s", "password": "another-long-pass"})
        self.assertEqual((old.status_code, new.status_code), (401, 200))

    def test_admin_user_profile_edit_and_removal(self) -> None:
        token = self.client.post(
            "/api/v1/auth/login", json={"login": "ivan", "password": "correct horse battery"}
        ).json()["access_token"]
        updated = self.client.patch("/api/v1/auth/me", json={"name": "Иван П."}, headers=self.auth(token))
        self.assertEqual(updated.json()["name"], "Иван П.")
        self.assertEqual(updated.json()["companies"], ["SYN_001"])  # компании задаёт администратор
        login = self.client.post("/api/v1/auth/login", json={"login": "ivan", "password": "correct horse battery"})
        self.assertEqual(login.json()["name"], "Иван П.")
        # Администратор удалил пользователя из AUTH_USERS — правки профиля доступ не возвращают.
        with patch.dict("os.environ", {"AUTH_USERS": ""}):
            gone = self.client.post("/api/v1/auth/login", json={"login": "ivan", "password": "correct horse battery"})
        self.assertEqual(gone.status_code, 401)


if __name__ == "__main__":
    unittest.main()
