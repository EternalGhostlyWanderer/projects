import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.agents.chat import RateScenarioParams, answer_question, calculate_rate_scenario
from app.ai.evidence import company_evidence, event_evidence
from app.ai.schemas import Insight
from app.llm.client import LLMClient
from app.llm.config import LLMSettings
from app.llm.store import LLMStore
from tests.test_agent import EVENT, claim, draft, make_context


class ChatLLM:
    def __init__(self, temp_dir: str, plans: list, answers: list) -> None:
        self.queues = {"plan": list(plans), "answer": list(answers)}
        self.requests: list[dict] = []
        settings = LLMSettings(api_key="k", state_db=Path(temp_dir) / "llm.sqlite3")
        self.client = LLMClient(
            settings=settings,
            client=SimpleNamespace(chat=SimpleNamespace(completions=self)),
            store=LLMStore(settings.state_db),
        )

    def create(self, **kwargs):
        self.requests.append(kwargs)
        route = "plan" if "Реши, нужны ли" in kwargs["messages"][0]["content"] else "answer"
        content = json.dumps(self.queues[route].pop(0), ensure_ascii=False)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content), finish_reason="stop")],
            usage=None,
        )


def make_insight() -> Insight:
    return Insight(
        **draft(),
        insight_id="i1",
        company_id="U_TEST",
        event_id=EVENT.event_id,
        evidence=[*event_evidence(EVENT.model_dump(mode="json")), *company_evidence(make_context())],
        model="m",
        created_at="2026-10-25T00:00:00+00:00",
        quality_status="verified",
    )


class ChatTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        patcher = patch("app.agents.chat.search_bank_research", return_value=[])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_rate_scenario_formula(self) -> None:
        result = calculate_rate_scenario(RateScenarioParams(debt_rub=500_000_000, rate_change_pp=-1))

        self.assertEqual(result["annual_interest_change_rub"], -5_000_000)

    def test_scenario_answer_cites_calculation(self) -> None:
        llm = ChatLLM(
            self.temp_dir.name,
            plans=[{"rate_scenario": {"debt_rub": 500000000, "rate_change_pp": -1}}],
            answers=[
                {
                    "answer": [
                        claim(
                            "При снижении ставки на 1 п.п. процентные расходы сократятся примерно на 5 млн руб. в год",
                            "AI_INFERENCE",
                            ["calc.rate_scenario", "company.product.loa"],
                        )
                    ]
                }
            ],
        )

        result = answer_question(
            make_insight(),
            "Что если ставка снизится на 1 п.п. при долге 500 млн руб.?",
            llm=llm.client,
        )

        self.assertEqual(result.calculation["annual_interest_change_rub"], -5_000_000)
        self.assertEqual({item.id for item in result.evidence}, {"calc.rate_scenario", "company.product.loa"})

    def test_invented_scenario_parameters_are_rejected(self) -> None:
        llm = ChatLLM(
            self.temp_dir.name,
            plans=[
                {"rate_scenario": {"debt_rub": 100000000, "rate_change_pp": 2}},
                {"rate_scenario": None},
            ],
            answers=[{"answer": [claim("Нужны сумма долга и тип ставки", "AI_INFERENCE", [])]}],
        )

        result = answer_question(make_insight(), "Что будет, если ставка вырастет?", llm=llm.client)

        self.assertIsNone(result.calculation)
        self.assertEqual(len([r for r in llm.requests if "Реши, нужны ли" in r["messages"][0]["content"]]), 2)

    def test_off_topic_question_answered_briefly_in_demo(self) -> None:
        recipe = {"answer": [claim("Растопите 200 г ирисок с 50 г масла, смешайте с тестом и выпекайте 30 минут.",
                                   "FACT", ["event.main"])]}
        llm = ChatLLM(self.temp_dir.name, plans=[{"on_topic": False}], answers=[recipe])

        result = answer_question(make_insight(), "Рецепт ирискового пирога", llm=llm.client)

        self.assertEqual(len(llm.requests), 2)
        self.assertIn("200 г ирисок", result.answer[0].text)  # числа рецепта не считаются выдуманными курсами
        self.assertEqual((result.answer[0].basis, result.answer[0].evidence_ids), ("AI_INFERENCE", []))
        self.assertEqual(result.evidence, [])
        self.assertNotIn("Курс", llm.requests[1]["messages"][1]["content"])  # данные разбора не передаются

    def test_off_topic_question_is_declined_without_second_request(self) -> None:
        llm = ChatLLM(self.temp_dir.name, plans=[{"on_topic": False}], answers=[])

        with patch.dict("os.environ", {"CHAT_OFF_TOPIC_ANSWERS": "0"}):
            result = answer_question(make_insight(), "Рецепт ирискового пирога", llm=llm.client)

        self.assertEqual(len(llm.requests), 1)  # только план, ответ модели не запрашивается
        self.assertEqual(len(result.answer), 1)
        self.assertIn("только на вопросы о событии", result.answer[0].text)
        self.assertEqual(result.evidence, [])
        self.assertTrue(result.follow_up_questions)

    def test_business_question_without_flag_is_answered(self) -> None:
        # Модель не вернула on_topic — по умолчанию вопрос считается по теме.
        answer = {"answer": [claim("Ставка влияет на стоимость кредитов компании.", "AI_INFERENCE", [])]}
        llm = ChatLLM(self.temp_dir.name, plans=[{}], answers=[answer])

        result = answer_question(make_insight(), "Что такое ключевая ставка?", llm=llm.client)

        self.assertEqual(len(llm.requests), 2)
        self.assertIn("Ставка", result.answer[0].text)

    def test_currency_rate_comes_from_central_bank(self) -> None:
        fact = {"id": "market.fx.SEK", "text": "Официальный курс ЦБ на 30.10.2026: 78,1234 руб. за 10 Шведских крон (SEK)",
                "url": "https://www.cbr.ru/currency_base/daily/", "date": "2026-10-30"}
        answer = {"answer": [claim("Курс ЦБ: 78,1234 руб. за 10 шведских крон.", "FACT", ["market.fx.SEK"])]}
        llm = ChatLLM(self.temp_dir.name, plans=[{"currencies": ["SEK"]}], answers=[answer])

        with patch("app.agents.chat.cbr.enabled", return_value=True), patch(
            "app.agents.chat.cbr.official_fx_facts", return_value=[fact]
        ) as rates:
            result = answer_question(make_insight(), "Курс шведской кроны", llm=llm.client)

        rates.assert_called_once_with(["SEK"])
        self.assertEqual(result.answer[0].basis, "FACT")
        self.assertEqual([item.id for item in result.evidence], ["market.fx.SEK"])

    def test_general_knowledge_allowed_as_inference(self) -> None:
        answer = {"answer": [claim("Валюта КНДР — северокорейская вона.", "AI_INFERENCE", [])]}
        llm = ChatLLM(self.temp_dir.name, plans=[{}], answers=[answer])

        result = answer_question(make_insight(), "Какая валюта в Северной Корее?", llm=llm.client)

        self.assertEqual((result.answer[0].text, result.answer[0].basis), ("Валюта КНДР — северокорейская вона.", "AI_INFERENCE"))
        prompt = llm.requests[1]["messages"][0]["content"]
        self.assertIn("общих знаний", prompt)

    def test_answer_with_invented_number_becomes_honest_no_data(self) -> None:
        bad = {"answer": [claim("Курс юаня сейчас 11,8 руб.", "AI_INFERENCE", [])]}
        llm = ChatLLM(self.temp_dir.name, plans=[{}], answers=[bad, bad, bad])

        result = answer_question(make_insight(), "Какой сейчас курс рубля к юаню?", llm=llm.client)

        self.assertEqual(len(result.answer), 1)
        self.assertEqual(result.answer[0].basis, "AI_INFERENCE")
        self.assertIn("нет сведений", result.answer[0].text)
        self.assertNotIn("11", result.answer[0].text)

    def test_unsourced_fact_and_advice_are_relabeled(self) -> None:
        answer = {
            "answer": [
                claim("В переданных данных отсутствует информация о курсе юаня.", "FACT", []),
                claim("Необходимо проверить валюту расчётов в контрактах", "FACT", ["company.product.loa"]),
                claim("У компании есть кредитные продукты", "FACT", ["company.product.loa"]),
            ]
        }
        llm = ChatLLM(self.temp_dir.name, plans=[{}], answers=[answer])

        result = answer_question(make_insight(), "курс юаня", llm=llm.client)

        self.assertEqual([item.basis for item in result.answer], ["AI_INFERENCE", "AI_INFERENCE", "FACT"])
        self.assertEqual(len([r for r in llm.requests if "Реши, нужны ли" not in r["messages"][0]["content"]]), 1)


if __name__ == "__main__":
    unittest.main()
