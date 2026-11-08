# Проверка локально: команды по порядку

Все команды — **PowerShell из корня репозитория**, если не сказано иное. Шаги 1–4 бесплатные,
дальше — платные запросы к LLM (сколько — указано). Если шаг не прошёл, дальше не идите:
пришлите вывод (без ключей).

## 0. Подготовка (один раз)
```powershell
git fetch
git checkout ai/agent-api
python -m venv .venv            # если окружения ещё нет
.venv\Scripts\Activate.ps1
pip install -r backend/requirements.lock
pip install -r backend/requirements-test.txt   # для скриптов проверки PDF/CSV
```
В `backend\.env` должен быть ключ (`LLM_API_KEY=sk-...`).

## 1. Тесты (бесплатно, без сети)
```powershell
cd backend
python -m unittest discover -s tests
cd ..
```
Ожидается: `Ran 80 tests ... OK`.

## 2. Синтетические данные и лента (бесплатно)
```powershell
$env:COMPANIES_CSV="data/synthetic/companies.csv"
$env:PAYMENTS_CSV="data/synthetic/payments.csv"
$env:PEOPLE_CSV="data/synthetic/people.csv"
python backend/scripts/load_events.py --file data/synthetic/news.json
python backend/scripts/run_eval.py --companies SYN_001 SYN_002 SYN_003 SYN_004 SYN_005 SYN_006 --labels data/synthetic/relevance_labels.json --feed-only
```
Ожидается: 10 загруженных новостей с каналами; футбольная новость без каналов; precision@5 по компаниям
(на ключевых словах сейчас 0,4–1,0).

## 3. Сервер (бесплатно)
В **отдельном окне** PowerShell (переменные из шага 2 задать заново):
```powershell
.venv\Scripts\Activate.ps1
$env:COMPANIES_CSV="data/synthetic/companies.csv"; $env:PAYMENTS_CSV="data/synthetic/payments.csv"; $env:PEOPLE_CSV="data/synthetic/people.csv"
cd backend
uvicorn app.main:app --reload --port 8000
```
Открыть http://localhost:8000/docs. В первом окне:
```powershell
Invoke-RestMethod "http://localhost:8000/api/v1/system/status" | ConvertTo-Json -Depth 5
Invoke-RestMethod "http://localhost:8000/api/v1/feed?company_id=SYN_001" | ConvertTo-Json -Depth 6
Invoke-RestMethod "http://localhost:8000/api/v1/feed?company_id=SYN_002" | ConvertTo-Json -Depth 6
```
Ожидается: `llm.configured = true`; ленты SYN_001 и SYN_002 разные.

## 4. Индекс аналитики банка (бесплатно — только проверка файлов)
PDF Альфа-Банка ищутся во всей папке `data\raw\` с подпапками (например, `data\raw\news\`) и в `data\bank\`;
документ узнаётся по имени файла. Другую папку можно задать: `$env:BANK_DIR="путь"`.
```powershell
python backend/scripts/build_bank_index.py
```
Ожидается: таблица документов; «Пропущено страниц без текста: N» (это сканы).

## 5. Подключение к LLM (1 короткий запрос)
```powershell
python backend/scripts/test_connection.py --think-style openrouter
```

## 6. Распознавание одной страницы (1 запрос к Qwen3-VL)
```powershell
python backend/scripts/build_bank_index.py --vision --max-pages 1 --doc policy_rate_2026_09_11
```
Открыть `data\processed\bank_pages\policy_rate_2026_09_11.json` и сверить текст со сканом.
Если ошибка про изображения — **прислать текст ошибки** и не повторять.

## 7. Распознавание всех сканов (~37 запросов, спросит подтверждение)
```powershell
python backend/scripts/build_bank_index.py --vision
python backend/scripts/search_bank.py "ЦБ сохранил ключевую ставку" --channels interest_rate
```
После этого **перезапустить сервер** (шаг 3), чтобы он увидел индекс.

## 8. Извлечение события через LLM (1 запрос)
```powershell
python backend/scripts/test_extraction.py --title "Банк России сохранил ключевую ставку на уровне 14%" --text "Совет директоров взял паузу, снижение ставки не рассматривалось." --llm --company SYN_001
```
Ожидается: `метод: llm`, каналы `interest_rate, deposit_yield, leasing_cost`, факты из текста.

## 9. Сквозной сценарий через API (~10–15 запросов, спросит подтверждение)
Сервер из шага 3 должен работать.
```powershell
python backend/scripts/demo_scenario.py --companies SYN_001 SYN_002 --event-match "ключевую ставку"
```
Ожидается: два инсайта с разными причинами релевантности; журнал агента (план → инструменты →
анализ → проверка); при собранном индексе — `позиция банка: found` со ссылкой на документ;
ответ на вопрос со сценарным расчётом (−5 000 000 руб./год).

## 10. Оценка качества агента (~20–40 запросов, спросит подтверждение)
```powershell
python backend/scripts/run_eval.py --companies SYN_001 SYN_002 SYN_003 --max-events 2
```
Отчёт: `backend\test_results\eval_*.json` — **прислать файл**: по нему доводим промпты.

## 11. На реальных данных организаторов
Положить CSV в `data\raw\`, убрать переменные `COMPANIES_CSV`/`PAYMENTS_CSV`/`PEOPLE_CSV` (или открыть новое окно):
```powershell
Remove-Item Env:COMPANIES_CSV, Env:PAYMENTS_CSV, Env:PEOPLE_CSV -ErrorAction SilentlyContinue
python backend/scripts/test_qwen_personalization.py
```

## 12. Фронтенд (бесплатно, пока не нажимать «Запустить анализ»)
Сервер из шага 3 должен работать. В новом окне:
```powershell
cd frontend
copy .env.example .env.local
npm ci
npm run dev
```
Открыть http://localhost:5173/insights: компании SYN_001…SYN_006, ленты разные. Клик по карточке
запускает анализ (платно, ~5 запросов). Для реальных компаний — `python backend/scripts/pick_demo_companies.py`
и вписать результат в `VITE_COMPANY_IDS` в `frontend/.env.local`.

## Что прислать после проверки
1. Вывод шагов 1, 2, 4 целиком.
2. Результат шага 6: ок / текст ошибки; при успехе — 1–2 абзаца из JSON для сравнения со сканом.
3. Вывод шага 9 и файл отчёта шага 10.
4. Сколько показал `today.cost` в `/api/v1/system/status` после шагов 9–10 и сколько это рублей
   по данным организаторов — чтобы выставить `LLM_DAILY_COST_LIMIT`.
