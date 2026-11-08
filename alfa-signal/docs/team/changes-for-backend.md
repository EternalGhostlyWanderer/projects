# Изменения в зоне Data / Backend (участник 2)

Сделано участником 1 в ветке `ai/event-extraction` в рамках извлечения событий.
Все правки **обратно совместимы**: старые вызовы и тесты работают без изменений
(`python -m unittest discover -s tests` из `backend/` — 37/37).

## 1. `app/schemas/event.py`
- Список каналов вынесен в тип `ImpactChannel` — теперь его можно импортировать,
  а не копировать `Literal`. Значения не менялись.
- В `NewsEvent` добавлены необязательные поля:

  | Поле | Тип | Зачем |
  |---|---|---|
  | `text` | `Optional[str]` | полный текст статьи; если заполнить, извлечение фактов будет точнее, чем по `summary` |
  | `entities` | `EventEntities` | организации, страны, регионы, отрасли, разделы ОКВЭД из новости |
  | `facts` | `list[str]` | проверяемые утверждения из текста, становятся доказательствами в инсайте |
  | `extraction_method` | `"llm" \| "keywords" \| None` | как классифицировано событие |

  Поля заполняет `extract_event`; нормализация их не трогает.

## 2. `app/modules/news/normalization.py`
- Новая функция `clean_text()`: из `summary` удаляются HTML-теги и сущности (`&nbsp;` и т.п.),
  которые RSS-ленты часто кладут в `<description>`. В `normalize_news_item` применяется к `summary`.
  `event_id`, URL и заголовок считаются как раньше.

## 3. `app/modules/personalization/relevance.py`
- `assess_relevance` дополнительно сравнивает `event["entities"]` (если есть) с профилем компании:
  - `okved_codes` события ↔ первые две цифры `industry.code` → фактор `industry`;
  - `regions` ↔ `location.region` → фактор `region`;
  - `countries` ↔ `risk_indicators.fts_country` → фактор `trade_country`.
- Найденные факторы добавляются в конец `matched_factors`, детали — в новое поле `matched_entities`.
  Для событий без `entities` (как в существующих тестах) результат прежний.
- Числовой скор 0–100 по-прежнему за тобой — `matched_factors` и `matched_entities` можно
  использовать как входы.

## 4. Новое: `app/modules/news/extraction.py`
Готово к подключению в твой сервис новостей:

```python
from app.modules.news.extraction import extract_event, extract_events

events = collect_news(sources)                    # как раньше
events = extract_events(events, use_llm=False)    # бесплатно: ключевые слова
events = extract_events(top_events, use_llm=True) # через Gemma/Qwen, с кешем
```

- `use_llm=False` — классификация по ключевым словам, без запросов к API. Её можно запускать
  на всём потоке новостей; заглушку из плана интеграции писать **не нужно**.
- `use_llm=True` — модель роли `extract` (`LLM_MODEL_EXTRACT`, иначе `LLM_MODEL`). Если LLM
  недоступна или кончился бюджет, функция сама откатывается на ключевые слова и не падает.
- Решение по ключевой ставке автоматически получает каналы `interest_rate`, `deposit_yield`,
  `leasing_cost` — так оно совпадает с факторами компаний с кредитом, депозитом или лизингом.
- Новости без влияния на бизнес (спорт, происшествия) получают пустой `impact_channels`.

Рекомендация по бюджету: на всём потоке — `use_llm=False`, а LLM — только для новостей,
которые прошли дешёвый отбор, и для «Разобрать новость». Повторный вызов на ту же новость
берётся из кеша `backend/var/llm.sqlite3`.

## 5. Скрипт проверки
`backend/scripts/test_extraction.py` — прогоняет ленту или текст через извлечение
и показывает совпадения с компанией:

```bash
python backend/scripts/test_extraction.py --rss https://www.cbr.ru/rss/eventrss --limit 5 --company U_195486
python backend/scripts/test_extraction.py --title "Банк России сохранил ключевую ставку" --text "Ставка оставлена на уровне 14%." --llm
```

---

# Шаги 4–7: что сделано в твоей зоне (ветка `ai/agent-api`)

Твоего кода к этому моменту в `main` не было, поэтому участник 1 написал недостающие части сам,
чтобы сквозной сценарий заработал. Все файлы ниже можно свободно переписывать — главное, сохранить
интерфейсы из `docs/api.md` (их ждёт фронтенд) и прогнать тесты:
`cd backend` → `python -m unittest discover -s tests`.

## Новые файлы
| Файл | Что делает |
|---|---|
| `app/db/store.py` | SQLite-хранилище `backend/var/app.sqlite3` (путь — `APP_DB_PATH`): события, инсайты, журналы агента, отзывы, история чата. `ANALYSIS_VERSION` — поменяй при изменении логики анализа, чтобы старые инсайты не переиспользовались |
| `app/modules/news/service.py` | `ingest_text`, `ingest_url`, `collect_rss`, `load_events_file`: загрузка, классификация (`extract_event`) и сохранение событий |
| `app/modules/news/sources/article.py` | `fetch_article(url)` — загрузка статьи с защитой от SSRF (только http/https, только публичные IP, проверка каждого редиректа, лимит 3 МБ и 15 с) и извлечение текста из `<p>` |
| `app/api/deps.py` | хранилище как зависимость FastAPI, проверка `X-Company-Id` |
| `app/api/v1/events.py`, `feed.py`, `insights.py`, `research.py`, `system.py` | эндпоинты из `docs/api.md` |
| `scripts/load_events.py` | загрузка новостей из JSON или RSS в хранилище |
| `requirements.txt`, `requirements.lock` | зависимости backend; lock сделан `pip freeze` в чистом venv на Python 3.13 |
| `data/synthetic/*` | 6 синтетических компаний, платежи, 10 новостей, ручная разметка релевантности |

## Изменённые файлы
- `app/main.py` — подключены роутеры; CORS (`CORS_ORIGINS`, по умолчанию `http://localhost:5173`);
  обработчики ошибок: лимит LLM → 429, сбой модели → 502, нет ключа LLM или данных компаний → 503.
  `/health` не менялся.
- `app/api/router.py` — добавлены новые роутеры, `companies` как был.
- `app/modules/companies/repository.py`, `relationships.py` — путь к CSV можно переопределить
  переменными `COMPANIES_CSV` и `PAYMENTS_CSV` (по умолчанию прежний `data/raw/...`).
- `.gitignore` — `data/` → `data/*` + исключение `!data/synthetic/`: синтетические данные хранятся в Git
  (их требуют условия сдачи), данные организаторов по-прежнему не коммитятся.

## Как запустить на синтетических данных (без данных организаторов)
```powershell
$env:COMPANIES_CSV="data/synthetic/companies.csv"; $env:PAYMENTS_CSV="data/synthetic/payments.csv"
python backend/scripts/load_events.py --file data/synthetic/news.json
cd backend; uvicorn app.main:app --reload --port 8000
```
Открыть http://localhost:8000/docs.

## Что осталось за тобой (не делалось, нужны твои решения)
1. **Docker**: `backend/Dockerfile`, `frontend/Dockerfile`, `docker-compose.yml` (тома `data/` и `backend/var/`,
   `env_file: backend/.env`). Не делалось — в этом окружении нельзя проверить сборку.
2. **Скор релевантности 0–100** вместо `match_count` в ленте (`app/api/v1/feed.py` сортирует по `match_count`,
   функция `assess_relevance` — твоя). Сейчас precision@5 ленты на синтетике 0,4–1,0 (`run_eval.py --feed-only`).
3. **Связи через физлиц** (`df_Fid_Uid_link_hack.csv`, `SYNTHETIC_F`) — в инструменте агента
   `get_company_relations` пока только группа (`GROUP_ID`) и концентрация платежей.
4. **Фоновый сбор RSS** по расписанию — сейчас ручной `POST /api/v1/events/collect` или `load_events.py --rss`.
5. Проверить реальные имена и формат CSV организаторов (кодировка, разделитель `;`, формат чисел) —
   синтетические CSV повторяют то, что ожидает `repository.py`.

## Официальные источники новостей (ветка `ai/official-sources`)
- Новые источники: `app/modules/news/sources/cbr.py` (ключевая ставка — DailyInfoWebServ, курсы — XML_daily)
  и `sources/moex.py` (ISS API Мосбиржи). Включаются `NEWS_OFFICIAL_SOURCES=cbr,moex` (по умолчанию оба).
- `collect_rss(..., extra_sources=[...])` — необязательный параметр, старые вызовы работают.
- **Для `docker-compose.yml`:** из значения `NEWS_RSS_URLS` по умолчанию стоит убрать ленту Мосбиржи
  `https://www.moex.com/export/news.aspx?cat=101`: она отдаёт весь архив (6,5 МБ), обрезается при чтении и не
  разбирается; новости биржи теперь идут через ISS API. `government.ru` не подключаем — недоступен ни с VPN, ни без. Переменные `NEWS_OFFICIAL_SOURCES`, `CBR_FX_ALERT_PCT`,
  `CBR_DATA_ENABLED` пробрасывать не обязательно: значения по умолчанию подходят.

## Строгий режим и снимок демо (ветка `ai/labeling-search`)
- `API_REQUIRE_COMPANY_SCOPE` и `DEMO_COMPANY_IDS` уже проброшены в `docker-compose.yml` (по умолчанию 0 и
  SYN_001…SYN_006); для внешнего сервера достаточно `API_REQUIRE_COMPANY_SCOPE=1` в `.env` рядом с compose.
  Там же — `NEWS_OFFICIAL_SOURCES`, расписание сбора, `PREANALYZE_ACTIVE`, `DEMO_SNAPSHOT_FILE`, `DEMO_USERS`;
  RSS Мосбиржи в лентах по умолчанию заменён экономическими рубриками.
- `scripts/seed_demo.py` сначала ищет `data/demo/demo_snapshot.json` (готовые разборы), потом синтетические новости —
  в Docker менять ничего не нужно.

## Индекс аналитики и демо-снимок в репозитории (ветка `ai/bank-index-in-repo`)
- `data/processed/bank_index.json` и `data/processed/bank_pages/` теперь в git (исключения в `.gitignore`).
  Docker с `ALFA_SIGNAL_DATA_DIR=./data` подхватывает их без шагов сборки.
- `build_bank_index.py` без PDF собирает индекс из `bank_pages` (без модели).
- `export_demo.py --role-views` добавляет в снимок ролевые блоки. Эндпоинт `/insights/{id}/role-view`
  пересобирает блок, построенный по правилам, если есть ключ LLM. Фронтенд не меняется.

## Новость от пользователя (ветка `ai/user-news`)
- `NewsEvent.submitted_by` и `NewsEvent.content`. Данные хранятся в JSON, старые записи читаются без миграции.
- `ingest_text(..., submitted_by=, paywalled=)` и `ingest_url(..., submitted_by=)`. `POST /events` принимает
  необязательный `company_id`.
- Лента, предварительный анализ и `export_snapshot` пропускают новости, присланные другой компанией.
