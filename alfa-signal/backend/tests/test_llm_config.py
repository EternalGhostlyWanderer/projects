import os
import unittest
from unittest import mock

from app.llm.config import LLMConfigError, get_settings

LLM_VARS = (
    "LLM_PROVIDER",
    "LLM_API_KEY",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_THINK_STYLE",
    "LLM_MODEL_EXTRACT",
    "LLM_MODEL_ANALYZE",
    "LLM_MODEL_VERIFY",
    "LLM_MODEL_VISION",
)


def env(**values: str) -> mock._patch:
    clean = {key: value for key, value in os.environ.items() if key not in LLM_VARS}
    return mock.patch.dict(os.environ, {**clean, **values}, clear=True)


class ProviderPresetTest(unittest.TestCase):
    def test_preset_fills_url_model_and_think_style(self) -> None:
        with env(LLM_PROVIDER="groq", LLM_API_KEY="k"):
            settings = get_settings()
        self.assertEqual(settings.base_url, "https://api.groq.com/openai/v1")
        self.assertEqual(settings.default_model, "qwen/qwen3.8-27b")
        self.assertIsNone(settings.think_off_body())
        self.assertEqual(settings.model_for("vision"), "qwen/qwen3.8-27b")

    def test_explicit_values_override_preset(self) -> None:
        with env(
            LLM_PROVIDER="openrouter",
            LLM_API_KEY="k",
            LLM_MODEL="google/gemma-4-26b-a4b-it:free",
            LLM_BASE_URL="",
        ):
            settings = get_settings()
        self.assertEqual(settings.base_url, "https://openrouter.ai/api/v1")
        self.assertEqual(settings.default_model, "google/gemma-4-26b-a4b-it:free")

    def test_ollama_needs_no_key(self) -> None:
        with env(LLM_PROVIDER="ollama"):
            settings = get_settings()
        self.assertTrue(settings.api_key)
        self.assertEqual(settings.base_url, "http://localhost:11434/v1")

    def test_cloud_provider_requires_key(self) -> None:
        with env(LLM_PROVIDER="gemini"), self.assertRaises(LLMConfigError):
            get_settings()

    def test_unknown_provider(self) -> None:
        with env(LLM_PROVIDER="nope", LLM_API_KEY="k"), self.assertRaises(LLMConfigError):
            get_settings()

    def test_hackathon_keeps_vision_default(self) -> None:
        with env(LLM_PROVIDER="hackathon", LLM_API_KEY="k"):
            settings = get_settings()
        self.assertEqual(settings.model_for("vision"), "qwen/qwen3-vl-30b-a3b-instruct")


if __name__ == "__main__":
    unittest.main()
