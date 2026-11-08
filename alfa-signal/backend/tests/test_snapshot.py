import tempfile
import unittest
from pathlib import Path

from app.agents.trace import AgentTrace
from app.db.snapshot import export_snapshot, import_snapshot
from app.db.store import AppStore
from tests.test_agent import EVENT
from tests.test_chat import make_insight


class SnapshotTests(unittest.TestCase):
    def test_round_trip_without_llm(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            source = AppStore(Path(folder) / "source.sqlite3")
            source.save_event(EVENT)
            insight = make_insight().model_copy(update={"trace_id": "t1"})
            trace = AgentTrace(trace_id="t1", insight_id=insight.insight_id, company_id="U_TEST", event_id=EVENT.event_id, started_at="2026-10-26T00:00:00+00:00", goal="демо")
            source.save_analysis(insight, trace)
            source.save_role_view(insight.insight_id, "cfo", {"headline": "h"})

            snapshot = export_snapshot(source, ["U_TEST"], roles=["cfo", "owner"])
            target = AppStore(Path(folder) / "target.sqlite3")
            counts = import_snapshot(target, snapshot)

            self.assertEqual(counts, {"events": 1, "insights": 1, "role_views": 1})
            self.assertEqual(target.get_insight(insight.insight_id).insight_id, insight.insight_id)
            self.assertEqual(target.get_trace("t1").trace_id, "t1")
            self.assertEqual(target.get_role_view(insight.insight_id, "cfo"), {"headline": "h"})


if __name__ == "__main__":
    unittest.main()
