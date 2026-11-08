# API Альфа Сигнал

Базовый адрес локально: `http://localhost:8000`. Интерактивная документация: `/docs` (Swagger), схема — `/openapi.json`.
Формат инсайта — `docs/contracts/insight.schema.json`, пример — `docs/contracts/examples/insight.example.json`.
Все поля в **snake_case**.

## Сценарий для фронтенда

1. Список компаний: `GET /api/v1/companies?q=&limit=` → `{items, total}`.
2. Лента компании: `GET /api/v1/feed?company_id=SYN_001` — **бесплатно** (без LLM): события,
   отсортированные по совпадениям с признаками компании; у уже разобранных есть `insight`.
3. Открыть карточку:
   - если у элемента ленты есть `insight.insight_id` → `GET /api/v1/insights/{insight_id}`;
   - иначе запустить анализ `POST /api/v1/insights/analyze` с `{company_id, event_id}` (5–60 с, показывайте загрузку).
4. «Ход анализа»: `GET /api/v1/insights/{insight_id}/trace`.
5. Уточняющий вопрос: `POST /api/v1/insights/{insight_id}/ask`, история — `GET .../chat`.
6. «Разобрать новость»: `POST /api/v1/insights/analyze` с `{company_id, url}` или `{company_id, title, text}`.
7. «Полезен ли анализ?»: `POST /api/v1/insights/{insight_id}/feedback`.
8. Первоисточник банка: `GET /api/v1/research/documents/{doc_id}/file` (PDF, открыть с `#page=N`)
   или текст фрагмента `GET /api/v1/research/chunks/{chunk_id}`.

## Эндпоинты

### События
| Метод и путь | Тело / параметры | Ответ |
|---|---|---|
| `GET /api/v1/events` | `limit`, `offset` | `{items: NewsEvent[], total, limit, offset}` |
| `GET /api/v1/events/{event_id}` | — | `NewsEvent` |
| `POST /api/v1/events` | `{title, text}` или `{url}`; `use_llm` (по умолчанию `true`) | `NewsEvent`, 201 |
| `POST /api/v1/events/collect` | `{rss_urls?: [...], use_llm: false, limit_per_source: 30, official?: ["cbr", "moex"]}`; без `rss_urls` — ленты из `NEWS_RSS_URLS`, без `official` — из `NEWS_OFFICIAL_SOURCES` (`[]` — без официальных источников) | `{added, merged, skipped_known_urls, items}`: публикации об уже известных событиях приклеиваются к ним (`docs/news-dedup.md`) |

`NewsEvent`: `event_id, title, published_at, source, url, summary, text, event_type, impact_channels[],
entities{organizations, countries, regions, industries, okved_codes}, facts[], extraction_method`.
У новостей, вставленных текстом, `url` вида `https://alfa-signal.local/manual/...` — ссылку не показывать.

### Лента
`GET /api/v1/feed?company_id=&limit=20&only_relevant=true&group=true` — сортировка по `relevance.score` (0–100,
сумма `components` = `score`, `docs/scoring.md`); `only_relevant` скрывает события с баллом ниже 10; `group`
собирает публикации одного сюжета под одной карточкой: `related_count` и до пяти `related`
(`{event_id, title, source, url, published_at, score}`). Сводка `/feed/digest` группирует так же.

```json
{
  "company_id": "SYN_001",
  "total": 6,
  "items": [
    {
      "event": { "...": "NewsEvent" },
      "relevance": {
        "matched_factors": ["interest_rate", "leasing_cost"],
        "matched_entities": {"industry": "25.11"},
        "match_count": 2,
        "has_direct_matches": true,
        "score": 47,
        "level": "medium",
        "significance": 0.9,
        "components": [
          {"group": "industry", "label": "Отрасль компании", "points": 27, "max": 30,
           "reason": "событие касается отрасли компании: ... (ОКВЭД 25)", "certainty": "confirmed"},
          {"group": "channels", "label": "Финансовые каналы", "points": 18, "max": 25,
           "reason": "внешняя торговля → по ФТС компания торгует с: КИТАЙ", "certainty": "confirmed"}
        ],
        "explanation": "отрасль компании +27: ...; финансовые каналы +18: ..."
      },
      "insight": null
    }
  ]
}
```
Если событие уже разобрано: `insight = {insight_id, kind, score, level, primary_effect, quality_status}`.
Сначала идут разобранные (по `score`), затем по числу совпадений и дате.

### Инсайты
| Метод и путь | Тело / параметры | Ответ |
|---|---|---|
| `POST /api/v1/insights/analyze` | ровно одно из: `event_id` / `url` / `title` (+`text`); `company_id`; `force` | `Insight` |
| `GET /api/v1/insights?company_id=` | `limit` | `{items: Insight[], total}` |
| `GET /api/v1/insights/{insight_id}` | — | `Insight` |
| `GET /api/v1/insights/{insight_id}/trace` | — | `AgentTrace` |
| `POST /api/v1/insights/{insight_id}/ask` | `{question}` | `ChatResult` |
| `GET /api/v1/insights/{insight_id}/chat` | — | `{items: [{role, text, created_at, result?}]}` |
| `POST /api/v1/insights/{insight_id}/feedback` | `{useful: bool, comment?}` | 204 |

Повторный `analyze` для той же пары «компания × событие» возвращает сохранённый инсайт без LLM; `force: true` — пересчитать.

**Что показывать из `Insight`:**
- `quality_status`: `verified` (проверка пройдена), `partial` (есть ошибки проверки — показать `quality_issues`),
  `unverified` (проверка не выполнялась);
- у каждого утверждения (`Claim`) — бейдж `basis` и сноски на `evidence_ids` → элементы `evidence`;
- `bank_view.status = not_found` — «позиция банка не установлена» (не выдумывать);
- `evidence[].source_kind = bank_research`: `source_title`, `source_date`, `source_page`, `source_id` = `chunk_id`
  (документ: часть `chunk_id` до `-p` — это `doc_id`).

**`AgentTrace`:** `trace_id, goal, status, tool_calls, rounds, verification{passed, issues[]}, steps[]`, где шаг —
`{n, phase: plan|tool|synthesize|verify|revise|finalize, name, status: ok|error|skipped, reason, args,
output_summary, evidence_ids, duration_ms, llm{model, cached, attempts, usage}, error}`.

**`ChatResult`:** `{answer: Claim[], follow_up_questions: string[], evidence: Evidence[], calculation?}`.
`calculation` появляется, только если пользователь сам назвал сумму долга и изменение ставки
(например: «Что если ставка снизится на 1 п.п. при долге 500 млн руб.?»).

### Аналитика банка
| Метод и путь | Ответ |
|---|---|
| `GET /api/v1/research/documents` | `{items: [{doc_id, title, date, topics, file_available}]}` |
| `GET /api/v1/research/documents/{doc_id}/file` | PDF |
| `GET /api/v1/research/chunks/{chunk_id}` | `{chunk_id, doc_id, doc_title, doc_date, page, section, kind, text}` |
| `GET /api/v1/research/search?q=&channels=&top_k=` | `{items: [...]}` |

### Служебное
`GET /health`, `GET /api/v1/system/status` — модели по ролям, расход LLM за сутки, число событий и склеенных публикаций (`merged_publications`),
фрагментов банка, отзывов.

## Ошибки
| Код | Когда | Что показать |
|---|---|---|
| 400 | ссылка запрещена (внутренняя сеть, не http) или страницу не удалось прочитать | текст `detail`, предложить вставить текст |
| 403 | заголовок `X-Company-Id` не совпадает с компанией ресурса | «Нет доступа» |
| 404 | компания, событие, инсайт или документ не найдены | `detail` |
| 422 | неверное тело запроса | `detail` |
| 429 | исчерпан дневной лимит LLM | «Лимит анализа на сегодня исчерпан, сброс в 03:00 МСК» |
| 502 | модель не ответила или ответ не прошёл проверку | `detail` + «Повторить» |
| 503 | не настроен ключ LLM или нет данных компаний | `detail` |

## Изоляция компаний (прототип)
Если фронт передаёт заголовок `X-Company-Id`, сервер отдаёт только данные этой компании
(чужие инсайты → 403). В демо выбор компании = смена значения заголовка.


## Действия пользователя (PR #17)
| Метод | Тело | Ответ |
|---|---|---|
| `GET /api/v1/companies/{id}/links` | — | `group` (выручка группы, крупный бизнес), `related_companies` (группа — `confirmed`, общее физлицо — `hypothesis`), `counterparty_industries` |
| `GET /api/v1/companies/{id}/user-data` | — | сведения, которые указал пользователь |
| `PUT /api/v1/companies/{id}/user-data` | `{floating_debt_rub?, fixed_debt_rub?, contract_currencies?: ["CNY"], trade_countries?: ["КИТАЙ"], key_inputs?, note?}` | сохранённые сведения; учитываются в скоринге ленты, анализе и чате с пометкой «со слов пользователя» |
| `POST /api/v1/feed/hidden` | `{company_id, event_id, hidden: true}` | 204; скрытое не попадает в ленту (`include_hidden=true` — показать) |
| `POST /api/v1/insights/{id}/requests` | `{kind: "manager_callback" \| "analyst_question", text?, role?}` | `{request_id, status: "accepted", message}`; в прототипе заявка сохраняется, при внедрении — CRM банка |
| `GET /api/v1/companies/{id}/requests` | — | заявки компании |
| `POST /api/v1/insights/{id}/ask` | `{question, role?}` | `role` — `owner`, `ceo`, `cfo`, `accountant`, `treasury`, `other`: ответ расставляет акценты под задачи роли |

Все эндпоинты учитывают `X-Company-Id`: чужая компания — 403.


## Сбор новостей, сводка, демо-вход (PR #18)
| Метод | Что делает |
|---|---|
| `POST /api/v1/events/refresh` | 202; в фоне: сбор RSS из `NEWS_RSS_URLS` и предварительный анализ важного (`docs/news-collection.md`) |
| `GET /api/v1/feed/digest?company_id=&hours=24&limit=3` | главные события компании за период, по баллу |
| `POST /api/v1/auth/login` | `{login, password}` → пользователь и подписанная `access_token`; 401 при неверных данных (демо-вход) |
| `GET /api/v1/auth/roles` | `{items: [{id, label}], default}` — роли для переключателя |
| `GET /api/v1/system/status` → `scheduler` | включён ли сбор, последний запуск и результат, разобрано заранее сегодня, лимит |

`POST /api/v1/events/collect` и `scheduler.last_result.collected` дополнительно возвращают `skipped_old` —
сколько публикаций старше `NEWS_MAX_AGE_DAYS` пропущено. В ленте `relevance.freshness` и `relevance.rank`
(сортировка — по `rank`).

## Пользователи и роли
Сервис для людей, а не для юрлица: у компании несколько сотрудников с разными задачами. Фронт передаёт
пользователя в каждом запросе заголовками (оба необязательны — без них всё работает как раньше, на уровне компании):

| Заголовок | Значение |
|---|---|
| `X-User-Id` | `user_id` из ответа `/auth/login` |
| `X-User-Role` | `owner`, `ceo`, `cfo`, `accountant`, `treasury`, `other`; используется в совместимом режиме без Bearer-токена; неизвестная роль — 422 |
| `Authorization` | `Bearer <access_token>` из `/auth/login`; при `DEMO_AUTH_REQUIRED=1` обязателен для ленты и анализа, срок действия — 8 часов |

- **Лента и сводка** (`/feed`, `/feed/digest`): роль добавляет группу «Задачи роли» в балл (до 15, см. `docs/scoring.md`), в ответе — `user_id` и `role`.
- **Скрытые события** (`/feed/hidden`), **история чата** (`/insights/{id}/chat`, `/ask`) — свои у каждого пользователя.
- **Отзывы и заявки** сохраняют `user_id` и роль; `/system/status` → `feedback.by_role`, `/companies/{id}/requests` → `user_id`.
- При `DEMO_AUTH_REQUIRED=1` сервер игнорирует подменённые `X-User-Id` и `X-User-Role`, проверяет подпись
  токена и ограничивает пользователя компаниями из `DEMO_USERS`.
- **Разбор агента и сведения о компании** (`/user-data`) — общие для всех сотрудников компании.

## Мониторинг источников и обновление ленты
| Метод | Что делает |
|---|---|
| `GET /api/v1/system/sources` | здоровье источников: `items[]` — `name`, `kind` (`news`/`data`), `status` (`ok`/`degraded`/`down`/`stale`), `last_run_at`, `last_ok_at`, `last_new_at`, `last_error`, `last_items`, `last_added`, `last_merged`, `last_offtopic`, `last_old`, `last_known`, `last_duration_ms`, `runs`, `failures`; проблемные первыми |
| `GET /api/v1/system/status` | добавлено `sources: {total, counts, healthy}` и в `scheduler` — `mode`, `active_sessions`, `last_trigger` (`schedule`/`login`/`manual`), `last_skipped_at`, `last_skip_reason` |
| `POST /api/v1/events/collect` | в ответе добавлено `sources[]` — статус каждого источника в этом сборе |
| `POST /api/v1/auth/login` | в ответе добавлено `refresh`: `started` (сбор запущен в фоне), `fresh` (данные свежее 30 минут), `running`, `disabled` |

Инсайт: `quality_status` может быть `verified` (проверено автоматически), `partial`, `outdated`, `conflicting`,
`failed`; среди доказательств — `event.source.N`, `event.confirmed.N`, `event.conflict.N` (`docs/agent.md`).

## Ролевой блок и положение в отрасли
| Метод | Что делает |
|---|---|
| `GET /api/v1/insights/{id}/role-view` | «Что это значит для вас» для роли из `X-User-Role` или `?role=` (по умолчанию `cfo`): `{role, role_label, headline, points[], risk_order[], next_steps[], method: llm\|rules, issues[]}`; хранится по паре «разбор × роль», `?refresh=true` — пересчитать |
| `GET /api/v1/companies/{id}/profile` | добавлено `industry_position`: `{status, okved_class, peers, rank, percentile, share_of_sample, tier, tier_label, group?: {rank, players, share_of_sample}, basis}` |

## Сведения о компании из документов
| Метод | Что делает |
|---|---|
| `PUT /api/v1/companies/{id}/user-data` | новые поля: `export_share_pct`, `revenue_currencies`, `customer_industries`, `supplier_industries`, `investment_plans`, `borrowing_plans`, `covenants`, `interests`, `field_sources`; изменённые вручную поля получают источник `manual`, изменение пишется в журнал |
| `POST /api/v1/companies/{id}/user-data/extract` | `{filename, text?, file_base64?}` → предпросмотр `{document_type, fields: [{field, label, value, quote}], rejected, truncated}`; платно, ничего не сохраняет |
| `POST /api/v1/companies/{id}/user-data/apply-document` | `{document, fields: [{field, value, quote}]}` — сохранить выбранные поля с источником «документ» |
| `GET /api/v1/companies/{id}/user-data/history` | журнал изменений: `{user_id, source, document, fields, created_at}` |

Подробно — `docs/user-documents.md`.

## Строгая изоляция компаний
`API_REQUIRE_COMPANY_SCOPE=1` (для внешнего сервера): любой запрос к данным компании без `X-Company-Id` — 401,
с чужим — 403; это касается и `/companies/{id}`, `/profile`, `/relationships`, `/exposures` (раньше без проверки).
`GET /companies` в строгом режиме отдаёт только компании из `DEMO_COMPANY_IDS`. Фронтенд передаёт `X-Company-Id`
в каждом запросе (из адреса или выбранной компании). Локально по умолчанию выключено — Swagger работает без заголовка.

## Демо без ключа LLM
`python backend/scripts/export_demo.py --companies SYN_001 SYN_002` → `data/demo/demo_snapshot.json`
(события, разборы, журналы, ролевые блоки, сведения пользователя); `scripts/seed_demo.py` загружает снимок в
чистую базу (Docker — при первом запуске), иначе — синтетические новости. `DEMO_SNAPSHOT_FILE` — другой путь.

## Предварительный анализ ленты
`GET /api/v1/feed` дополнительно возвращает `preanalysis: {running, pending[], done[], enabled}`, а у карточек —
`preparing: true`, если событие стоит в фоновом разборе. Разбор верхних событий запускается самим запросом ленты
(`docs/news-collection.md`).
