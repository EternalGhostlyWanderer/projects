# План интеграции: что AI-часть ждёт от команды

> **Актуальный статус и задачи команды — в [`docs/status.md`](../status.md).** Этот документ —
> исходный план интеграции; часть пунктов уже выполнена.

> **Обновление (ветка `ai/agent-api`):** API, хранилище, сервис новостей и синтетические данные уже написаны
> участником 1 — см. `docs/api.md` и `docs/team/changes-for-backend.md`. Пункты ниже для участника 2
> частично закрыты; актуальный список остатка — в конце `changes-for-backend.md`.

Документ ведёт участник 1 (AI/ML). Цель — чтобы трое работали параллельно
и не ждали друг друга: **везде, где у соседа ещё нет готовой части, используем
заглушку с тем же интерфейсом**, а потом меняем одну функцию или один `fetch`.

Источник правды по формату ответа — Pydantic-модели в `backend/app/ai/schemas.py`.
JSON Schema: `docs/contracts/insight.schema.json`, пример: `docs/contracts/examples/insight.example.json`.
После изменения моделей: `python backend/scripts/export_contracts.py`.

## Что даёт участник 1 и когда

| Что | Интерфейс | Статус |
|---|---|---|
| Контракт `Insight` v2 + пример JSON | `docs/contracts/` | ✅ готово |
| LLM-клиент (кеш, бюджет, журнал) | `app.llm.get_llm_client().chat_json(...)` | ✅ готово |
| Анализ события под компанию | `app.ai.analyzer.analyze_event(context, event, relevance, bank_chunks=()) -> Insight` | ✅ работает на Qwen |
| Извлечение события из новости | `app.modules.news.extraction.extract_event(event, use_llm=True) -> NewsEvent` (заполняет `event_type`, `impact_channels`, `entities`, `facts`) | ✅ готово, см. `changes-for-backend.md` |
| Поиск по аналитике банка | `app.research.search.search_bank_research(query, channels, top_k) -> list[dict]` | ✅ готово, см. `docs/bank-research.md` |
| Агент + журнал шагов | `app.agents.orchestrator.run_agent(company_id, event) -> AgentResult(insight, trace, verification)` | ✅ готово, см. `docs/agent.md` |
| Ответ на уточняющий вопрос | `app.agents.chat.answer_question(insight, question, history) -> ChatResult` | ✅ готово |

Каждая функция сначала появится с упрощённой реализацией, но с финальной сигнатурой.
`run_agent` до шага 4 просто вызывает `analyze_event` и возвращает пустой журнал.

---

## Участник 2 — Data / Backend

### P0 — нужно сейчас

1. **Зависимости и lock-файл.** `backend/requirements.txt` (или `pyproject.toml` + `uv.lock`):
   `fastapi`, `uvicorn[standard]`, `pydantic>=2`, `openai>=1.40,<3`, `python-dotenv`,
   плюс то, что нужно для новостей. Lock-файл обязателен по условиям сдачи (стр. 8).
2. **Роутер инсайтов** `backend/app/api/v1/insights.py` (HTTP, хранение, ошибки — твои;
   логика анализа — функции участника 1 из таблицы выше):

   | Метод | Тело / параметры | Ответ |
   |---|---|---|
   | `POST /api/v1/insights/analyze` | `{company_id, event_id}` **или** `{company_id, url}` **или** `{company_id, title, text}` | `Insight` |
   | `GET /api/v1/insights?company_id=&limit=` | — | `{items: Insight[], total}` по убыванию `relevance.score` |
   | `GET /api/v1/insights/{insight_id}` | — | `Insight` |
   | `GET /api/v1/insights/{insight_id}/trace` | — | `AgentTrace` (до шага 4 — `{"trace_id": null, "steps": []}`) |
   | `POST /api/v1/insights/{insight_id}/ask` | `{question, history: [{role, text}]}` | `ChatAnswer` (до шага 6 — заглушка 501) |
   | `POST /api/v1/insights/{insight_id}/feedback` | `{useful: bool, comment?: str}` | `204` |

   Ошибки: `BudgetExceededError` → `429` с текстом «Лимит LLM исчерпан, сброс в 03:00 МСК»;
   `LLMRequestError` / `LLMResponseError` → `502` с понятным сообщением; компания не найдена → `404`.
   Анализ идёт 5–40 секунд — пока синхронно, без очередей.
3. **Хранение инсайтов.** SQLite-таблица `insights(insight_id, company_id, event_id, analysis_version, json, created_at)`.
   Перед вызовом LLM ищем готовый инсайт по `company_id + event_id + analysis_version` — повторное
   открытие карточки не должно тратить бюджет. Файл БД в `backend/var/` (уже в `.gitignore`).
4. **Сервис новостей** `app/modules/news/service.py`:
   - `get_event(event_id) -> NewsEvent | None`, `list_events(since=None, limit=100) -> list[NewsEvent]`;
   - `ingest_url(url) -> NewsEvent` — только `http/https`, запрет приватных/локальных IP (SSRF),
     таймаут, лимит размера, извлечение текста статьи (например `trafilatura`);
   - `ingest_text(title, text) -> NewsEvent` — запасной путь для демо.
   - Поле `NewsEvent.text` уже добавлено — заполнять его полным текстом статьи, когда он доступен.
   - Вызывать `extract_events(events, use_llm=False)` при загрузке (бесплатно) и `use_llm=True` для отобранных
     новостей; результат уже лежит в полях `NewsEvent`. Заглушка не нужна — подробности в `changes-for-backend.md`.
5. **Набор новостей для тестов.** `data/samples/news.json` — 15–20 реальных новостей
   (заголовок, текст, URL, дата, источник) из 2–3 работающих RSS. Нужен мне для отладки
   без живых источников и для eval. Сюда же 2 дубля одного события и 1 новость с «инструкцией» в тексте.
6. **Демо-компании.** 4–6 **реальных** `SYNTHETIC_U` с контрастными признаками → `data/samples/demo_companies.json`
   (`id`, отображаемое имя «Компания №00N», почему выбрана). Обязательно:
   - **выручка > 15 млрд руб.** — кейс про крупный бизнес (стр. 4). Тестовая `U_195486` имеет ~0,7 млрд, она не подходит;
   - есть кредит / нет кредита, но есть депозит;
   - есть страна в ФТС;
   - высокая концентрация платежей;
   - `CL_TYPE = CLIENT`.

### P1 — следом

7. **Скор релевантности 0–100 с причинами** в `assess_relevance` (или `rank_events(company_id, events)`).
   Сопоставление отрасли, региона и страны ФТС уже добавлено (`matched_entities`); осталось
   превратить совпадения в скор с учётом масштаба (выручка) и свежести.
   Выход: `{score, level, matched_factors, reasons: [str]}`. Дешёвое ранжирование без LLM,
   LLM-анализ — только топ-K событий.
8. **Связи компаний** для инструмента агента `get_company_relations`: компании той же `GROUP_ID`,
   компании через общих `SYNTHETIC_F` (файл физлиц), крупнейшие контрагенты.
   Проверить реальные имена CSV — на стр. 16 у физлиц и платежей указано одно и то же имя.
9. **Изоляция по компании** (тест T11): запросы к инсайту чужой компании должны отклоняться.
   Для прототипа достаточно заголовка `X-Company-Id` / демо-пользователя на компанию.
10. **Docker.** `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml`
    (backend + frontend, тома `data/` и `backend/var/`, `env_file: backend/.env`), CORS
    для `http://localhost:5173` или прокси Vite. README с пошаговым запуском, `THIRD_PARTY_NOTICES.md`.
11. **Синтетические данные** для жюри (`data/synthetic/`): маленький CSV компаний и платежей
    в том же формате, чтобы сценарий проходил без исходных данных организаторов.

---

## Участник 3 — Product / Frontend

### P0 — можно начинать сразу на заглушках

1. **Типы API.** Сгенерировать из `docs/contracts/insight.schema.json`
   (например `npx json-schema-to-typescript`) или написать вручную в `src/features/insights/api.ts`.
   API отдаёт **snake_case**, во фронте — camelCase: один маппер `fromApiInsight(api) -> BusinessInsight`.
2. **Обновить `model.ts` под v2.** Ключевые отличия от текущей модели:
   - каждое утверждение — `Claim {text, basis, evidenceIds, confidence}`; `basis` — те же 4 типа,
     что уже есть в `EvidenceBadge` (`FACT`, `BANK_ANALYSIS`, `AI_INFERENCE`, `HYPOTHESIS`);
   - `relevance {score, level, reasons: Claim[]}` вместо `relevanceReasons: string[]`;
   - `mechanism: string[]` — уже массив шагов; `ImpactChain` не нужно резать строку по «→»;
   - `risks` / `opportunities` — объекты с `title`, `severity` / `potential`;
   - `scenarios`, `bankView {status: "found" | "not_found", claims}`, `nextSteps {action, priority}`,
     `qualityStatus`, `evidence[]` с `sourceTitle / sourceUrl / sourceDate / sourcePage`.
3. **Заглушка = реальный формат.** Вместо данных в `demoInsightsAdapter.ts` — JSON в формате API
   (`docs/contracts/examples/insight.example.json`, можно размножить под 2 компании и 3–5 событий),
   прогоняемый через тот же маппер. Тогда переход на backend — это замена одного `fetch`.
   Флаг `VITE_USE_DEMO=1`, адрес `VITE_API_URL`.
4. **Карточка инсайта целиком из данных.** Сейчас в `InsightDetailsPage.tsx` захардкожены
   «Проверить план заимствований», цепочка «Ставка → фондирование → кредиты», «Что произошло»,
   «Мнение банка», чек-лист и источники. Нужно рендерить:
   - «Что произошло» ← `event_summary`; «Почему важно вам» ← `relevance.reasons`;
   - главный эффект ← `primary_effect`, цепочка ← `mechanism`, риски/возможности, сценарии;
   - «Позиция Альфа-Банка» ← `bank_view` (для `not_found` переиспользовать состояние из `BankAnalysisBlock`);
   - «Следующий шаг» ← `next_steps`, «Что пока неизвестно» ← `unknowns`;
   - у каждого утверждения — бейдж `basis` и сноски `[n]` на `evidence`, клик ведёт к источнику
     (`source_url` или документ банка со страницей).
   Позиция банка и выводы AI должны визуально различаться — это критерий 03.
5. **Лента** (`InsightsPage.tsx`): счётчики «Сегодня: N событий / рисков / возможностей»,
   «Сначала проверьте» и «Точность персонализации» — из данных (`next_steps`, `unknowns`),
   а не из `if company-001`. Список компаний — из `GET /api/v1/companies`.
6. **«Разобрать новость»:** поле URL **и** textarea для текста → `POST /insights/analyze`,
   состояние загрузки на 5–40 с, ошибки: 429 (лимит LLM), 502 (модель не ответила), 400 (плохой URL).

### P1 — следом

7. **«Ход анализа»** — экран или раскрывающийся блок из `GET /insights/{id}/trace`:
   шаги (план → инструмент → результат → проверка), вызванные инструменты, источники, ошибки.
   Формат `AgentTrace` пришлю на шаге 4; до этого — пустое состояние.
8. **Чат уточнений** → `POST /insights/{id}/ask` с историей; ответ тоже из `Claim` со ссылками.
   До шага 6 — заглушка с явной пометкой «демо».
9. **Главная**: блок «Альфа Сигнал» на `DashboardPage.tsx` сейчас захардкожен — брать топ-2 из ленты.
   Компания в шапке (`Header.tsx`) — из выбранной, а не «Компания №001/002».
10. **Обратная связь** «Полезен ли анализ?» → `POST /insights/{id}/feedback` (критерий 08).
11. Сценарий демо, презентация, запасная запись видео.

---

## Порядок интеграции

1. Участник 3 переходит на JSON в формате API через маппер (без backend).
2. Участник 2 поднимает `POST /insights/analyze` с `event_id` из `data/samples/news.json` → реальный `analyze_event`.
3. Фронт переключается на API для одной компании и одного события — **первый сквозной сценарий**.
4. Дальше каждый наращивает своё, не меняя интерфейсов из этого документа.
   Меняешь контракт — пиши в чат команды и обновляй этот файл.

## Зависимости, которые нужны backend-приложению

Для `requirements.txt` / lock-файла (участник 2): помимо `fastapi`, `uvicorn`, `pydantic`, `openai`,
`python-dotenv` нужен `pymupdf` — модуль `app/research` читает и рендерит PDF банка.
PDF Альфа-Банка лежат локально в `data/raw/` (любая подпапка) (в Git не попадают); в Docker папку `data/`
нужно подключать томом.

