import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict

from app.llm.client import (
    BudgetExceededError,
    LLMClient,
    LLMRequestError,
    LLMResponseError,
)
from app.llm.config import LLMSettings
from app.llm.store import LLMStore


class Answer(BaseModel):
    value: int


class StrictItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int


class StrictAnswer(BaseModel):
    """Как контракт разбора: лишние поля запрещены."""

    model_config = ConfigDict(extra="forbid")
    value: int
    items: list[StrictItem] = []


class FakeUsage:
    def model_dump(self) -> dict:
        return {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "completion_tokens_details": {"reasoning_tokens": 0},
            "cost": 0.001,
        }


class FakeCompletions:
    def __init__(self, contents: list) -> None:
        self.contents = list(contents)
        self.requests: list[dict] = []

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content = self.contents.pop(0)
        if isinstance(content, Exception):
            raise content
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ],
            usage=FakeUsage(),
        )


def make_client(contents: list, **settings_overrides):
    temp_dir = tempfile.TemporaryDirectory()
    settings = LLMSettings(
        api_key="secret-key",
        state_db=Path(temp_dir.name) / "llm.sqlite3",
        **settings_overrides,
    )
    completions = FakeCompletions(contents)
    fake_openai = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client = LLMClient(
        settings=settings,
        client=fake_openai,
        store=LLMStore(settings.state_db),
    )
    return client, completions, temp_dir


MESSAGES = [{"role": "user", "content": "Верни число"}]


class LLMClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dirs: list[tempfile.TemporaryDirectory] = []

    def tearDown(self) -> None:
        for temp_dir in self._temp_dirs:
            temp_dir.cleanup()

    def client(self, contents: list, **overrides):
        client, completions, temp_dir = make_client(contents, **overrides)
        self._temp_dirs.append(temp_dir)
        return client, completions

    def test_parses_fenced_json_and_sends_json_mode(self) -> None:
        client, completions = self.client(['Вот ответ:\n```json\n{"value": 7}\n```'])

        result = client.chat_json(MESSAGES, Answer, task="test")

        self.assertEqual(result.value.value, 7)
        self.assertEqual(result.attempts, 1)
        request = completions.requests[0]
        self.assertEqual(request["response_format"], {"type": "json_object"})
        self.assertEqual(request["extra_body"], {"reasoning": {"enabled": False}})

    def test_second_identical_call_is_served_from_cache(self) -> None:
        client, completions = self.client(['{"value": 1}'])

        client.chat_json(MESSAGES, Answer, task="test")
        result = client.chat_json(MESSAGES, Answer, task="test")

        self.assertTrue(result.cached)
        self.assertEqual(len(completions.requests), 1)
        self.assertEqual(client.store.daily_usage()["requests"], 1)

    def test_timeout_is_sent_but_not_part_of_cache_key(self) -> None:
        client, completions = self.client(['{"value": 1}'])

        client.chat_json(MESSAGES, Answer, task="test", timeout=240)
        result = client.chat_json(MESSAGES, Answer, task="test")

        self.assertEqual(completions.requests[0]["timeout"], 240)
        self.assertTrue(result.cached)

    def test_repairs_invalid_answer_once(self) -> None:
        client, completions = self.client(['{"value": "много"}', '{"value": 3}'])

        result = client.chat_json(MESSAGES, Answer, task="test")

        self.assertEqual(result.value.value, 3)
        self.assertEqual(result.attempts, 2)
        repair_message = completions.requests[1]["messages"][-1]["content"]
        self.assertIn("value", repair_message)

    def test_raises_after_failed_repair(self) -> None:
        client, _ = self.client(["не json", "снова не json"])

        with self.assertRaises(LLMResponseError) as context:
            client.chat_json(MESSAGES, Answer, task="test")

        self.assertTrue(context.exception.errors)

    def test_custom_validator_triggers_repair(self) -> None:
        client, completions = self.client(['{"value": -1}', '{"value": 5}'])

        result = client.chat_json(
            MESSAGES,
            Answer,
            task="test",
            validate=lambda answer: [] if answer.value > 0 else ["value должен быть > 0"],
        )

        self.assertEqual(result.value.value, 5)
        self.assertIn("value должен быть > 0", completions.requests[1]["messages"][-1]["content"])

    def test_request_limit_blocks_before_calling_gateway(self) -> None:
        client, completions = self.client(['{"value": 1}', '{"value": 2}'], daily_request_limit=1)

        client.chat_json(MESSAGES, Answer, task="test")
        with self.assertRaises(BudgetExceededError):
            client.chat_json([{"role": "user", "content": "другой"}], Answer, task="test")

        self.assertEqual(len(completions.requests), 1)

    def test_gateway_error_is_redacted(self) -> None:
        client, _ = self.client([RuntimeError("bad key secret-key")])

        with self.assertRaises(LLMRequestError) as context:
            client.chat_json(MESSAGES, Answer, task="test")

        self.assertNotIn("secret-key", str(context.exception))

    def test_gateway_budget_error_maps_to_budget_exceeded(self) -> None:
        client, _ = self.client([RuntimeError("Error code: 400 - Budget has been exceeded")])

        with self.assertRaises(BudgetExceededError):
            client.chat_json(MESSAGES, Answer, task="test")

    def test_rate_limit_is_retried_after_pause(self) -> None:
        client, completions = self.client([RuntimeError("Error code: 429 - Rate limit exceeded"), '{"value": 3}'])
        waits: list[float] = []
        client._sleep = waits.append

        result = client.chat_json(MESSAGES, Answer, task="test")

        self.assertEqual(result.value.value, 3)
        self.assertEqual(len(completions.requests), 2)
        self.assertEqual(len(waits), 1)
        # Отклонённый провайдером запрос не тратит локальный дневной лимит.
        self.assertEqual(client.store.daily_usage()["requests"], 1)

    def test_daily_quota_429_stops_without_retry(self) -> None:
        client, completions = self.client(
            [RuntimeError("Error code: 429 - Rate limit exceeded: free-models-per-day")]
        )
        client._sleep = lambda _: self.fail("дневной лимит не пережидают")

        with self.assertRaises(BudgetExceededError):
            client.chat_json(MESSAGES, Answer, task="test")
        self.assertEqual(len(completions.requests), 1)

    def test_trailing_text_and_extra_fields_accepted_without_repair(self) -> None:
        # Gemma дописала текст после JSON, Flash-Lite — лишнее поле: переспрашивать не нужно.
        client, completions = self.client(['{"value": 5, "items": [{"n": 1, "basis": "FACT"}]} Готово {"x": 1}'])
        result = client.chat_json(MESSAGES, StrictAnswer, task="test").value
        self.assertEqual((result.value, result.items[0].n), (5, 1))
        self.assertEqual(len(completions.requests), 1)

    def test_wrong_field_still_triggers_repair(self) -> None:
        client, completions = self.client(['{"value": "пять", "extra": 1}', '{"value": 5, "items": []}'])
        self.assertEqual(client.chat_json(MESSAGES, StrictAnswer, task="test").value.value, 5)
        self.assertEqual(len(completions.requests), 2)

    def test_failed_requests_do_not_spend_daily_limit(self) -> None:
        client, _ = self.client([RuntimeError("Error code: 503 - busy"), '{"value": 1}'])
        with self.assertRaises(LLMRequestError):
            client.chat_json(MESSAGES, Answer, task="test")
        self.assertEqual(client.store.daily_usage()["requests"], 0)
        client.chat_json(MESSAGES, Answer, task="test")
        self.assertEqual(client.store.daily_usage()["requests"], 1)

    def test_think_mode_does_not_send_reasoning_off(self) -> None:
        client, completions = self.client([json.dumps({"value": 1})])

        client.chat_json(MESSAGES, Answer, task="test", think=True)

        self.assertNotIn("extra_body", completions.requests[0])


if __name__ == "__main__":
    unittest.main()
