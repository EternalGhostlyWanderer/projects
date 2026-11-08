from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from app.agents.chat import ChatResult, answer_question
from app.agents.orchestrator import persist_enriched_event, run_agent
from app.agents.role_view import RoleView, build_role_view, llm_available
from app.agents.trace import AgentTrace
from app.api.deps import UserContext, check_company_access, check_user_company, current_user, require_company, store_dependency
from app.ai.schemas import Insight
from app.db.store import AppStore
from app.modules.news.service import ingest_text, ingest_url
from app.modules.news.sources.article import ArticleFetchError
from app.modules.personalization.roles import Role

router = APIRouter(prefix="/insights", tags=["Insights"])


class AnalyzeRequest(BaseModel):
    company_id: str = Field(min_length=1)
    event_id: Optional[str] = None
    url: Optional[str] = Field(default=None, max_length=2000)
    title: Optional[str] = Field(default=None, max_length=500)
    text: str = Field(default="", max_length=50_000)
    force: bool = Field(default=False, description="Пересчитать, даже если анализ уже есть")

    @model_validator(mode="after")
    def _one_source(self) -> "AnalyzeRequest":
        if sum(bool(value) for value in (self.event_id, self.url, self.title)) != 1:
            raise ValueError("Укажите ровно одно: event_id, url или title (+ text)")
        return self


class FeedbackRequest(BaseModel):
    useful: bool
    comment: Optional[str] = Field(default=None, max_length=2000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    role: Optional[Role] = Field(
        default=None, description="Роль пользователя: ответ учитывает её задачи (иначе — из X-User-Role)"
    )


class ClientRequestBody(BaseModel):
    kind: Literal["manager_callback", "analyst_question"]
    text: Optional[str] = Field(default=None, max_length=2000)
    role: Optional[Role] = None


def _get_insight(store: AppStore, insight_id: str, x_company_id: Optional[str], user: UserContext) -> Insight:
    insight = store.get_insight(insight_id)
    if insight is None:
        raise HTTPException(status_code=404, detail="Инсайт не найден")
    check_company_access(insight.company_id, x_company_id)
    check_user_company(insight.company_id, user)
    return insight


@router.post("/analyze", response_model=Insight)
def analyze(
    body: AnalyzeRequest,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> Insight:
    """Run the agent for a company and an event (stored, by URL or pasted text). Takes 5–60 s."""
    require_company(body.company_id, x_company_id)
    check_user_company(body.company_id, user)

    try:
        if body.event_id:
            event = store.get_event(body.event_id)
            if event is None:
                raise HTTPException(status_code=404, detail="Событие не найдено")
        elif body.url:
            event = ingest_url(store, body.url, submitted_by=body.company_id)
        else:
            event = ingest_text(store, title=body.title or "", text=body.text, submitted_by=body.company_id)
    except ArticleFetchError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not body.force:
        existing = store.find_insight(body.company_id, event.event_id)
        if existing is not None:
            return existing

    result = run_agent(body.company_id, event, user_data=store.get_user_data(body.company_id))
    persist_enriched_event(store, result)
    if result.insight is None:
        store.save_trace(result.trace)
        # Настоящая причина — в шаге анализа или инструмента; финальный шаг пишет только общее
        # «Анализ не получен», и пользователь не узнавал, что сломалось (например, дневной лимит).
        failed = next(
            (step.error for step in reversed(result.trace.steps) if step.error and step.phase != "finalize"),
            None,
        )
        raise HTTPException(
            status_code=502,
            detail={"message": failed or "Анализ не получен", "trace_id": result.trace.trace_id},
        )
    store.save_analysis(result.insight, result.trace)
    return result.insight


@router.get("")
def list_insights(
    company_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    check_company_access(company_id, x_company_id)
    check_user_company(company_id, user)
    items = store.list_insights(company_id, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/{insight_id}", response_model=Insight)
def get_insight(
    insight_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> Insight:
    return _get_insight(store, insight_id, x_company_id, user)


@router.get("/{insight_id}/role-view", response_model=RoleView)
def get_role_view(
    insight_id: str,
    refresh: bool = Query(default=False, description="Пересчитать ролевой блок (платно)"),
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> RoleView:
    """«Что это значит для вас»: выводы, порядок рисков и шаги для роли смотрящего (X-User-Role или ?role=)."""
    insight = _get_insight(store, insight_id, x_company_id, user)
    role = user.role or "cfo"
    cached = None if refresh else store.get_role_view(insight_id, role)
    # Блок, собранный моделью, — окончательный; собранный по правилам (снимок демо, нет ключа) пробуем улучшить.
    if cached is not None and (cached.get("method") == "llm" or not llm_available()):
        return RoleView.model_validate(cached)
    view = build_role_view(insight, role)
    store.save_role_view(insight_id, role, view.model_dump(mode="json"))
    return view


@router.get("/{insight_id}/trace", response_model=AgentTrace)
def get_trace(
    insight_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> AgentTrace:
    insight = _get_insight(store, insight_id, x_company_id, user)
    trace = store.get_trace(insight.trace_id) if insight.trace_id else None
    if trace is None:
        raise HTTPException(status_code=404, detail="Журнал анализа не найден")
    return trace


@router.post("/{insight_id}/feedback", status_code=204)
def feedback(
    insight_id: str,
    body: FeedbackRequest,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> None:
    _get_insight(store, insight_id, x_company_id, user)
    store.save_feedback(insight_id, body.useful, body.comment, user_id=user.user_id, role=user.role)


@router.get("/{insight_id}/chat")
def chat_history(
    insight_id: str,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    _get_insight(store, insight_id, x_company_id, user)
    return {"items": store.chat_history(insight_id, user_id=user.user_id)}


@router.post("/{insight_id}/ask", response_model=ChatResult)
def ask(
    insight_id: str,
    body: AskRequest,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> ChatResult:
    insight = _get_insight(store, insight_id, x_company_id, user)
    history = [
        {"role": item["role"], "text": item.get("text", "")}
        for item in store.chat_history(insight_id, user_id=user.user_id)
    ]
    try:
        result = answer_question(
            insight,
            body.question,
            history,
            role=body.role or user.role,
            user_data=store.get_user_data(insight.company_id),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    store.add_chat_message(insight_id, "user", {"text": body.question}, user_id=user.user_id)
    store.add_chat_message(
        insight_id,
        "assistant",
        {
            "text": " ".join(claim.text for claim in result.answer),
            "result": result.model_dump(),
        },
        user_id=user.user_id,
    )
    return result


@router.post("/{insight_id}/requests", status_code=201)
def client_request(
    insight_id: str,
    body: ClientRequestBody,
    store: AppStore = Depends(store_dependency),
    x_company_id: Optional[str] = Header(default=None, alias="X-Company-Id"),
    user: UserContext = Depends(current_user),
) -> dict[str, Any]:
    """Связаться с менеджером или задать вопрос аналитику банка по инсайту.

    В прототипе заявка сохраняется (видна в /companies/{id}/requests и /system/status);
    при внедрении — передаётся в CRM банка (вебинар, вопрос 51).
    """
    insight = _get_insight(store, insight_id, x_company_id, user)
    request_id = store.add_request(
        insight.company_id,
        body.kind,
        insight_id=insight_id,
        text=body.text,
        role=body.role or user.role,
        user_id=user.user_id,
    )
    message = (
        "Заявка принята: персональный менеджер свяжется с вами в рабочее время."
        if body.kind == "manager_callback"
        else "Вопрос передан аналитикам Альфа-Банка; ответ придёт в этот раздел."
    )
    return {"request_id": request_id, "status": "accepted", "message": message, "demo": True}
