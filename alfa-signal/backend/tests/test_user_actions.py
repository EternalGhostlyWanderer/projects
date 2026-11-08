import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.agents.chat import _plan_errors, AskPlan
from app.api.deps import store_dependency
from app.db.store import AppStore
from app.main import app
from app.modules.companies import links, relationships, repository
from app.modules.news import service
from app.modules.personalization.scoring import score_event
from tests.test_api import keywords_only
from tests.test_scoring import CHINA_PAYMENTS, RATE, context

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"


class UserActionsApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patches = [
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
            patch.object(service, "extract_event", keywords_only),
        ]
        for item in cls.patches:
            item.start()
        cls.clear()

    @classmethod
    def tearDownClass(cls) -> None:
        for item in cls.patches:
            item.stop()
        cls.clear()

    @staticmethod
    def clear() -> None:
        repository.clear_company_cache()
        relationships.clear_relationship_cache()
        links.clear_links_cache()

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")
        app.dependency_overrides[store_dependency] = lambda: self.store
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        service.load_events_file(self.store, SYNTHETIC / "news.json", use_llm=False)

    def feed_titles(self, company_id: str, **params) -> list[str]:
        response = self.client.get("/api/v1/feed", params={"company_id": company_id, **params})
        return [item["event"]["title"] for item in response.json()["items"]]

    def test_user_data_roundtrip_and_validation(self) -> None:
        saved = self.client.put(
            "/api/v1/companies/SYN_002/user-data",
            json={"floating_debt_rub": 5e8, "contract_currencies": "cny, usd", "trade_countries": ["Китай"]},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["data"]["contract_currencies"], ["CNY", "USD"])

        loaded = self.client.get("/api/v1/companies/SYN_002/user-data").json()["data"]
        self.assertEqual(loaded["floating_debt_rub"], 5e8)
        self.assertIn("updated_at", loaded)

        bad = self.client.put("/api/v1/companies/SYN_002/user-data", json={"floating_debt_rub": -1})
        self.assertEqual(bad.status_code, 422)
        foreign = self.client.put(
            "/api/v1/companies/SYN_002/user-data", json={}, headers={"X-Company-Id": "SYN_001"}
        )
        self.assertEqual(foreign.status_code, 403)

    def test_user_data_changes_the_feed(self) -> None:
        # Розничная сеть без ФТС не видит новость о платежах в Китай, пока не сообщит о китайских поставщиках.
        title = "Банки ужесточили проверку платежей в Китай"
        self.assertNotIn(title, self.feed_titles("SYN_002"))

        self.client.put("/api/v1/companies/SYN_002/user-data", json={"trade_countries": ["КИТАЙ"]})

        self.assertIn(title, self.feed_titles("SYN_002"))

    def test_hide_and_restore_event(self) -> None:
        first = self.client.get("/api/v1/feed", params={"company_id": "SYN_001"}).json()["items"][0]
        event_id = first["event"]["event_id"]

        hidden = self.client.post("/api/v1/feed/hidden", json={"company_id": "SYN_001", "event_id": event_id})
        self.assertEqual(hidden.status_code, 204)
        self.assertNotIn(first["event"]["title"], self.feed_titles("SYN_001"))
        self.assertIn(first["event"]["title"], self.feed_titles("SYN_001", include_hidden=True))
        # Скрытие касается только этой компании.
        self.assertEqual(self.store.hidden_event_ids("SYN_004"), set())

        self.client.post(
            "/api/v1/feed/hidden", json={"company_id": "SYN_001", "event_id": event_id, "hidden": False}
        )
        self.assertIn(first["event"]["title"], self.feed_titles("SYN_001"))
        self.assertEqual(self.client.get("/api/v1/system/status").json()["hidden_events"], 0)

    def test_contact_manager_and_ask_analyst(self) -> None:
        from tests.test_chat import make_insight

        insight = make_insight()
        with patch.object(self.store, "get_insight", return_value=insight):
            callback = self.client.post(
                f"/api/v1/insights/{insight.insight_id}/requests", json={"kind": "manager_callback", "role": "cfo"}
            )
            question = self.client.post(
                f"/api/v1/insights/{insight.insight_id}/requests",
                json={"kind": "analyst_question", "text": "Какой прогноз курса юаня?"},
            )
            foreign = self.client.post(
                f"/api/v1/insights/{insight.insight_id}/requests",
                json={"kind": "manager_callback"},
                headers={"X-Company-Id": "SYN_001"},
            )

        self.assertEqual(callback.status_code, 201)
        self.assertIn("менеджер", callback.json()["message"])
        self.assertEqual(question.json()["status"], "accepted")
        self.assertEqual(foreign.status_code, 403)
        self.assertEqual(
            [item["kind"] for item in self.store.list_requests(insight.company_id)],
            ["analyst_question", "manager_callback"],
        )

    def test_links_endpoint(self) -> None:
        data = self.client.get("/api/v1/companies/SYN_001/links").json()

        self.assertEqual(data["group"]["revenue_rub"], 55e9)
        self.assertEqual({item["company_id"] for item in data["related_companies"]}, {"SYN_004", "SYN_007"})
        self.assertEqual(data["counterparty_industries"]["status"], "available")


class UserDataLogicTests(unittest.TestCase):
    def test_floating_debt_from_profile_enables_rate_scenario(self) -> None:
        plan = AskPlan.model_validate({"rate_scenario": {"debt_rub": 500000000, "rate_change_pp": -1}})

        self.assertTrue(_plan_errors(plan, "Что если ставка снизится на 1 п.п.?"))
        self.assertEqual(_plan_errors(plan, "Что если ставка снизится на 1 п.п.?", known_debt=5e8), [])

    def test_user_data_in_scoring(self) -> None:
        plain = context(profile={"products": {}, "risk_indicators": {}})
        with_debt = {**plain, "user_data": {"floating_debt_rub": 1e9}}
        with_countries = {**plain, "user_data": {"trade_countries": ["КИТАЙ"]}}

        self.assertEqual(score_event(plain, RATE)["score"], 0)
        self.assertEqual(score_event(with_debt, RATE)["score"], 25)
        self.assertIn("со слов пользователя", score_event(with_debt, RATE)["explanation"])
        self.assertGreater(score_event(with_countries, CHINA_PAYMENTS)["score"], 0)


class RequestsApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = AppStore(Path(self.temp_dir.name) / "app.sqlite3")

    def test_store_requests(self) -> None:
        first = self.store.add_request("SYN_001", "manager_callback", insight_id="i1", role="cfo")
        self.store.add_request("SYN_001", "analyst_question", insight_id="i1", text="Курс юаня?")

        items = self.store.list_requests("SYN_001")
        self.assertEqual([item["kind"] for item in items], ["analyst_question", "manager_callback"])
        self.assertEqual(items[1]["request_id"], first)
        self.assertEqual(self.store.count_requests(), {"analyst_question": 1, "manager_callback": 1})


if __name__ == "__main__":
    unittest.main()
