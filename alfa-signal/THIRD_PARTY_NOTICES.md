# Сторонние компоненты, модели, данные и смоделированные интеграции

Версии runtime-зависимостей зафиксированы в `backend/requirements.lock` и `frontend/package-lock.json`.

## Языковые модели (доступ через шлюз организаторов, OpenAI-совместимый API)
| Модель | Где используется |
|---|---|
| `qwen/qwen3.6-35b-a3b` | анализ события, планирование и пересмотр в агенте, чат уточнений, извлечение событий (по умолчанию) |
| `qwen/qwen3-vl-30b-a3b-instruct` | распознавание сканированных страниц аналитики Альфа-Банка |
| `google/gemma-4-26b-a4b-it`, `z-ai/glm-5.3-flash`, `deepseek/deepseek-v4.1-flash`, `moonshotai/kimi-k2.6` | сравнение моделей (`scripts/compare_models.py`); могут назначаться ролям через `.env` |

После хакатона провайдер выбирается переменной `LLM_PROVIDER` (OpenRouter, Groq, Google Gemini, Mistral,
локальная Ollama — `docs/free-llm-providers.md`). Модели и условия использования — у выбранного провайдера.

На время хакатона использовались только модели из списка кейса. Внешние AI-сервисы, готовые агенты и агентные
фреймворки не используются; логика агента, поиска и ранжирования написана командой.

## Данные
| Источник | Использование |
|---|---|
| Обезличенные данные организаторов (компании, физлица, платежи) | профиль и персонализация; в репозиторий не входят |
| Аналитические материалы Центра макроэкономического анализа Альфа-Банка | позиция банка в инсайтах; исходные PDF не коммитятся, производный текстовый индекс и распознанные страницы находятся в `data/processed/` |
| Новости из RSS-лент и по ссылкам пользователя | события; готовый демо-снимок содержит публичные материалы ЦБ РФ, остальные новости хранятся локально |
| Иностранные RSS-ленты: BBC Business, The Guardian Business, CNBC Economy, пресс-релизы ФРС и ЕЦБ, OilPrice, Mining.com | события ленты (`app/modules/news/foreign.py`): заголовок, анонс в переводе и ссылка на оригинал; полный текст статьи загружается только для разбора |
| GDELT DOC 2.0 API | опциональный источник новостей (`app/modules/news/sources/api.py`) |
| Банк России: веб-сервис DailyInfoWebServ (ключевая ставка), XML_daily.asp (официальные курсы), RSS пресс-релизов и событий | события ленты и факты для агента (`app/modules/news/sources/cbr.py`); открытые сервисы без ключа |
| Московская биржа: ISS API (`iss.moex.com/iss/sitenews.json`) | новости биржи (`app/modules/news/sources/moex.py`); открытый API без ключа |
| `data/synthetic/` | синтетические компании, платежи, новости и разметка, созданы командой для тестов и демо |

## Backend (Python)
| Пакет | Лицензия |
|---|---|
| FastAPI | MIT |
| Starlette | BSD-3-Clause |
| Uvicorn | BSD-3-Clause |
| Pydantic | MIT |
| openai (Python SDK) | Apache-2.0 |
| python-dotenv | BSD-3-Clause |
| httpx | BSD-3-Clause |
| PyMuPDF | AGPL-3.0 или коммерческая лицензия Artifex — см. примечание ниже |
| pypdf, pandas, jsonschema (скрипты проверки) | BSD-3-Clause, BSD-3-Clause, MIT |

## Frontend
| Пакет | Лицензия |
|---|---|
| React, React DOM, React Router | MIT |
| Vite, @vitejs/plugin-react | MIT |
| Tailwind CSS, tw-animate-css | MIT |
| shadcn/ui, @base-ui/react | MIT |
| @tanstack/react-query | MIT |
| lucide-react | ISC |
| class-variance-authority | Apache-2.0 |
| Geist (шрифт, @fontsource-variable/geist) | SIL Open Font License 1.1 |

## Смоделированные интеграции
- Интерфейс интернет-банка «Альфа-Бизнес» (главная, меню, платёжные блоки) — макет для демонстрации точки входа.
- Авторизация и права доступа — подписанная demo-сессия и контекст `X-Company-Id` вместо банковского SSO.
- Компании в демо — синтетические (`data/synthetic/`), новости в офлайн-снимке — публичные материалы ЦБ РФ.

## Примечание о лицензии PyMuPDF
PyMuPDF распространяется под AGPL-3.0; условия кейса ограничений на лицензии сторонних библиотек
не содержат, поэтому библиотека оставлена. Для промышленного внедрения потребуется коммерческая
лицензия Artifex либо замена на `pypdfium2` (Apache-2.0 / BSD-3-Clause) — затронут только
`backend/app/research/pages.py`.

## Развёртывание на внешнем сервере
| Компонент | Лицензия |
|---|---|
| Nginx (`nginxinc/nginx-unprivileged` в контейнере фронтенда; пакет дистрибутива как reverse proxy на хосте) | BSD-2-Clause |
| Certbot (сертификаты Let's Encrypt, `deploy/server/05-tls.sh`) | Apache-2.0 |
| Docker Engine и Docker Compose (`deploy/server/03-docker.sh`) | Apache-2.0 |
