import json
import unittest

from app.ai.schemas import InsightDraft
from app.llm.compact import clip, compact_json
from app.llm.parsing import schema_for_prompt


class CompactJsonTest(unittest.TestCase):
    def test_drops_empty_values_and_spaces(self) -> None:
        text = compact_json({"a": None, "b": "", "c": [], "d": {}, "e": 0, "f": False, "g": ["", "x"]})
        self.assertEqual(text, '{"e":0,"f":false,"g":["x"]}')

    def test_keeps_cyrillic_and_collapses_whitespace(self) -> None:
        self.assertEqual(compact_json({"t": "Ключевая\n  ставка"}), '{"t":"Ключевая ставка"}')

    def test_clip_cuts_by_word(self) -> None:
        self.assertEqual(clip("один два три четыре", 12), "один два…")
        self.assertEqual(clip("коротко", 100), "коротко")


class SchemaForPromptTest(unittest.TestCase):
    def test_auto_titles_removed_but_title_fields_kept(self) -> None:
        schema = json.loads(schema_for_prompt(InsightDraft))
        self.assertNotIn("title", schema)
        risk = schema["$defs"]["Risk"]
        self.assertIn("title", risk["properties"])
        self.assertNotIn("title", risk["properties"]["title"])


if __name__ == "__main__":
    unittest.main()
