"""Agent trace: a structured log of what the agent did and why (no hidden reasoning)."""
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

Phase = Literal["plan", "tool", "synthesize", "verify", "revise", "finalize"]
StepStatus = Literal["ok", "error", "skipped"]


class TraceStep(BaseModel):
    n: int
    phase: Phase
    name: str = Field(description="Инструмент или действие")
    status: StepStatus = "ok"
    reason: Optional[str] = Field(default=None, description="Зачем шаг выполнен")
    args: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    llm: Optional[dict[str, Any]] = Field(
        default=None,
        description="Модель, попытки, токены и стоимость, если шаг вызывал LLM",
    )
    error: Optional[str] = None


class AgentTrace(BaseModel):
    trace_id: str
    company_id: str
    event_id: str
    goal: str
    started_at: str
    finished_at: Optional[str] = None
    status: Literal["running", "completed", "failed"] = "running"
    steps: list[TraceStep] = Field(default_factory=list)
    tool_calls: int = 0
    rounds: int = 0
    verification: Optional[dict[str, Any]] = None
    insight_id: Optional[str] = None


class TraceRecorder:
    def __init__(self, company_id: str, event_id: str, goal: str) -> None:
        self.trace = AgentTrace(
            trace_id=uuid.uuid4().hex,
            company_id=company_id,
            event_id=event_id,
            goal=goal,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

    def step(self, phase: Phase, name: str, **fields: Any) -> TraceStep:
        step = TraceStep(n=len(self.trace.steps) + 1, phase=phase, name=name, **fields)
        self.trace.steps.append(step)
        if phase == "tool":
            self.trace.tool_calls += 1
        return step

    def timed(self) -> "_Timer":
        return _Timer()

    def finish(self, status: Literal["completed", "failed"]) -> AgentTrace:
        self.trace.status = status
        self.trace.finished_at = datetime.now(timezone.utc).isoformat()
        return self.trace


class _Timer:
    def __enter__(self) -> "_Timer":
        self.started = time.perf_counter()
        self.ms = 0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.ms = int((time.perf_counter() - self.started) * 1000)
