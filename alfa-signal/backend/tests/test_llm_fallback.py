import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from pydantic import BaseModel

from app.llm.client import BudgetExceededError, LLMClient, LLMRequestError, LLMResponseError
from app.llm.config import LLMSettings, ProviderRoute, parse_fallbacks
from app.llm.store import LLMStore
from tests.test_llm_client import FakeCompletions


class Answer(BaseModel):
    value: int


class ProviderError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"Error code: {status} - {message}")
        self.status_code = status


MESSAGES = [{"role": "user", "content": "Верни число"}]


def fake(contents: list):
    completions = FakeCompletions(contents)
    return SimpleNamespace(chat=SimpleNamespace(completions=completions)), completions


class FallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.db = Path(temp_dir.name) / "llm.sqlite3"

    def client(self, primary: list, backup: list, **settings):
        primary_client, primary_calls = fake(primary)
        backup_client, backup_calls = fake(backup)
        options = {
            "api_key": "primary-key",
            "state_db": self.db,
            "provider": "gemini",
            "think_style": "reasoning_effort",
            "fallbacks": (ProviderRoute("groq", "https://groq/v1", "llama", "none", "backup-key"),),
            **settings,
        }
        llm = LLMClient(
            settings=LLMSettings(**options),
            client=primary_client,
            store=LLMStore(self.db),
            fallback_clients={"groq": backup_client},
        )
        llm._sleep = lambda _: self.fail("с запасным маршрутом не ждём")
        return llm, primary_calls, backup_calls

    def test_disabled_model_switches_to_backup_and_pauses_primary(self) -> None:
        gone = ProviderError(404, "This model models/gemini-2.5-flash is no longer available to new users.")
        llm, primary, backup = self.client([gone], ['{"value": 1}', '{"value": 2}'])

        first = llm.chat_json(MESSAGES, Answer, task="t", use_cache=False)
        second = llm.chat_json(MESSAGES, Answer, task="t", use_cache=False)

        self.assertEqual((first.value.value, first.provider, first.model), (1, "groq", "llama"))
        self.assertEqual(second.value.value, 2)
        self.assertEqual(len(primary.requests), 1)  # отключённую модель второй раз не спрашиваем
        self.assertNotIn("extra_body", backup.requests[0])  # у запасного свой стиль рассуждений

    def test_rate_limit_goes_to_backup_without_waiting(self) -> None:
        llm, _, backup = self.client([ProviderError(429, "Rate limit exceeded")], ['{"value": 3}'])

        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t").value.value, 3)
        self.assertEqual(len(backup.requests), 1)

    def test_unsupported_reasoning_parameter_is_dropped(self) -> None:
        rejected = ProviderError(400, "Invalid argument: reasoning_effort 'none' is not supported for this model")
        llm, primary, backup = self.client([rejected, '{"value": 4}', '{"value": 5}'], [])

        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t", use_cache=False).value.value, 4)
        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t", use_cache=False).value.value, 5)
        self.assertIn("extra_body", primary.requests[0])
        self.assertNotIn("extra_body", primary.requests[1])
        self.assertNotIn("extra_body", primary.requests[2])  # запомнили для следующих запросов
        self.assertEqual(backup.requests, [])

    def test_generic_invalid_argument_drops_reasoning_parameter(self) -> None:
        # Так Gemini Flash-Lite отвечает на reasoning_effort=none — без названия параметра.
        vague = ProviderError(400, "[{'error': {'code': 400, 'message': 'Request contains an invalid argument.'}}]")
        llm, primary, _ = self.client([vague, '{"value": 10}'], [])

        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t", use_cache=False).value.value, 10)
        self.assertIn("extra_body", primary.requests[0])
        self.assertNotIn("extra_body", primary.requests[1])
        self.assertIn("response_format", primary.requests[1])  # JSON-режим не тронут

    def test_model_without_system_instructions(self) -> None:
        rejected = ProviderError(400, "Developer instruction is not enabled for models/gemma-4-26b-a4b-it")
        llm, primary, _ = self.client([rejected, '{"value": 6}', '{"value": 7}'], [])
        messages = [{"role": "system", "content": "Правила"}, {"role": "user", "content": "Вопрос"}]

        self.assertEqual(llm.chat_json(messages, Answer, task="t", use_cache=False).value.value, 6)
        llm.chat_json(messages, Answer, task="t", use_cache=False)
        for request in primary.requests[1:]:
            self.assertEqual([item["role"] for item in request["messages"]], ["user"])
            self.assertTrue(request["messages"][0]["content"].startswith("Правила"))

    def test_daily_quota_of_one_model_moves_to_next(self) -> None:
        quota = ProviderError(
            429, "Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-3.8-flash, "
            "description: Generate content requests per day limit exceeded",
        )
        llm, primary, backup = self.client([quota], ['{"value": 8}', '{"value": 9}'])

        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t", use_cache=False).value.value, 8)
        self.assertEqual(llm.chat_json(MESSAGES, Answer, task="t", use_cache=False).value.value, 9)
        self.assertEqual(len(primary.requests), 1)  # исчерпанную модель час не трогаем

    def test_invalid_answer_moves_to_backup_after_one_repair(self) -> None:
        incomplete = '{"other": 1}'
        llm, primary, backup = self.client([incomplete, incomplete, incomplete], ['{"value": 11}'])

        result = llm.chat_json(MESSAGES, Answer, task="t", use_cache=False, max_repairs=2)

        self.assertEqual((result.value.value, result.provider), (11, "groq"))
        self.assertEqual(len(primary.requests), 2)  # ответ + одно исправление, не два

    def test_invalid_answer_on_last_route_raises(self) -> None:
        llm, _, backup = self.client([ProviderError(503, "busy")], ['{"other": 1}', '{"other": 2}'])

        with self.assertRaises(LLMResponseError):
            llm.chat_json(MESSAGES, Answer, task="t", use_cache=False, max_repairs=1)
        self.assertEqual(len(backup.requests), 2)

    def test_own_daily_limit_does_not_spend_backup(self) -> None:
        llm, primary, backup = self.client([], [], daily_request_limit=0)
        llm.settings = LLMSettings(
            api_key="k", state_db=self.db, daily_request_limit=1, provider="gemini",
            fallbacks=llm.settings.fallbacks,
        )
        llm.store.log_call(task="t", model="m", status="ok", cached=False, attempt=1)

        with self.assertRaises(BudgetExceededError):
            llm.chat_json(MESSAGES, Answer, task="t")
        self.assertEqual((primary.requests, backup.requests), ([], []))

    def test_all_routes_failed_raises_last_error(self) -> None:
        llm, _, _ = self.client([ProviderError(500, "boom")], [ProviderError(503, "down")])

        with self.assertRaises(LLMRequestError) as context:
            llm.chat_json(MESSAGES, Answer, task="t")
        self.assertIn("down", str(context.exception))

    def test_backup_key_is_redacted(self) -> None:
        llm, _, _ = self.client([ProviderError(500, "boom")], [ProviderError(401, "bad key backup-key")])

        with self.assertRaises(LLMRequestError) as context:
            llm.chat_json(MESSAGES, Answer, task="t")
        self.assertNotIn("backup-key", str(context.exception))


class FallbackConfigTests(unittest.TestCase):
    def test_parse_skips_providers_without_key(self) -> None:
        with mock.patch.dict(os.environ, {"GROQ_API_KEY": "g", "OPENROUTER_API_KEY": ""}):
            routes = parse_fallbacks(
                "gemini:gemini-flash-latest, groq, openrouter, nope",
                primary_provider="gemini", primary_key="main",
            )
        self.assertEqual([(route.provider, route.model) for route in routes],
                         [("gemini", "gemini-flash-latest"), ("groq", "qwen/qwen3.8-27b")])
        self.assertEqual(routes[0].api_key, "main")  # тот же провайдер — ключ основного

    def test_deepseek_preset(self) -> None:
        with mock.patch.dict(os.environ, {"DEEPSEEK_API_KEY": "sk-d"}):
            (route,) = parse_fallbacks("deepseek", primary_provider="gemini", primary_key="main")
        self.assertEqual((route.base_url, route.model, route.api_key), ("https://api.deepseek.com/v1", "deepseek-chat", "sk-d"))

    def test_ollama_needs_no_key(self) -> None:
        with mock.patch.dict(os.environ, {"OLLAMA_BASE_URL": "http://host.docker.internal:11434/v1"}):
            (route,) = parse_fallbacks("ollama", primary_provider="gemini", primary_key="main")
        self.assertEqual(route.base_url, "http://host.docker.internal:11434/v1")


if __name__ == "__main__":
    unittest.main()
