import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.modules.companies import links, relationships, repository

SYNTHETIC = Path(__file__).resolve().parents[2] / "data" / "synthetic"


class CompanyScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        for patcher in (
            patch.object(repository, "COMPANIES_CSV", SYNTHETIC / "companies.csv"),
            patch.object(relationships, "PAYMENTS_CSV", SYNTHETIC / "payments.csv"),
            patch.object(links, "PEOPLE_CSV", SYNTHETIC / "people.csv"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        repository.clear_company_cache()
        self.addCleanup(repository.clear_company_cache)
        self.client = TestClient(app)

    def test_default_mode_keeps_swagger_working(self) -> None:
        self.assertEqual(self.client.get("/api/v1/companies/SYN_001/profile").status_code, 200)
        foreign = self.client.get("/api/v1/companies/SYN_001/profile", headers={"X-Company-Id": "SYN_002"})
        self.assertEqual(foreign.status_code, 403)

    def test_strict_mode_requires_company_context_everywhere(self) -> None:
        env = {"API_REQUIRE_COMPANY_SCOPE": "1", "DEMO_COMPANY_IDS": "SYN_001,SYN_002"}
        with patch.dict("os.environ", env):
            for path in ("", "/profile", "/relationships", "/exposures", "/links", "/user-data"):
                self.assertEqual(self.client.get(f"/api/v1/companies/SYN_001{path}").status_code, 401, path)
            self.assertEqual(self.client.get("/api/v1/feed", params={"company_id": "SYN_001"}).status_code, 401)
            ok = self.client.get("/api/v1/companies/SYN_001/profile", headers={"X-Company-Id": "SYN_001"})
            self.assertEqual(ok.status_code, 200)
            listed = self.client.get("/api/v1/companies").json()
        self.assertEqual({item["id"] for item in listed["items"]}, {"SYN_001", "SYN_002"})


if __name__ == "__main__":
    unittest.main()
