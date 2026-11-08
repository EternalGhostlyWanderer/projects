"""Write JSON Schemas of the Pydantic contracts to docs/contracts/ (no API calls)."""
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.ai.schemas import Insight, InsightDraft  # noqa: E402

CONTRACTS_DIR = BACKEND_DIR.parent / "docs" / "contracts"

CONTRACTS = {
    "insight.schema.json": Insight,
    "insight_draft.schema.json": InsightDraft,
}


def main() -> int:
    CONTRACTS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, model in CONTRACTS.items():
        path = CONTRACTS_DIR / filename
        schema = model.model_json_schema()
        path.write_text(
            json.dumps(schema, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"Записано: {path.relative_to(BACKEND_DIR.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
