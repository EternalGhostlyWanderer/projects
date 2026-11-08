# Отчёт 17. Демо-данные и индекс аналитики банка в репозитории

## Зачем
Команда и организаторы: в чистом клоне `bank_chunks=0`. Индекс аналитики был только локально, и позиция банка
не находилась. Готового демо с разборами тоже не было («лучше, чтобы были сохранены новости для демо»).
Проверяющий не должен вручную распознавать PDF.

## Что сделано
- **Индекс в репозитории.** Добавлены `data/processed/bank_index.json` (251 фрагмент, 40 прогнозов из таблиц)
  и `data/processed/bank_pages/*.json` (9 документов). Страницы хранятся как распознанный текст, PDF не коммитятся.
  Исключения прописаны в `.gitignore`. Репозиторий приватный; если он станет публичным, эти файлы нужно убрать.
- **Сборка без PDF.** `build_bank_index` берёт сохранённые страницы, если PDF документа нет (`source: pages`).
  Скрипт `build_bank_index.py` больше не завершается с ошибкой без `data/raw`. Модель не нужна.
- **Демо-снимок с ролевыми блоками.** У `export_demo.py` появился флаг `--role-views`: перед выгрузкой он строит
  недостающие ролевые блоки для каждого разбора и каждой роли. При наличии ключа их пишет LLM, без ключа они
  строятся по правилам. Снимок `data/demo/demo_snapshot.json` содержит 20 событий, 7 разборов, 7 журналов агента
  и 21 ролевой блок.
- **Старые блоки обновляются сами.** Если сохранённый ролевой блок построен по правилам, а ключ LLM есть, эндпоинт
  ролевого блока пересобирает его моделью. Без ключа отдаётся сохранённый.
- **Старое и новое вместе.** Снимок подгружается при `SEED_SYNTHETIC_DATA=1`. Новые разборы (предварительный
  анализ, нажатие «Разобрать») добавляются поверх него.

## Проверка
- Чистая база + `seed_demo.py`: `{'events': 20, 'insights': 7, 'role_views': 21}`, `bank_chunks 251, forecasts 40`.
- `eval_bank_search.py`: первое попадание 100%, в пятёрке 100%.
- Тесты бэкенда: 233 OK.

## Ограничения
В 5 из 7 сохранённых разборов позиция банка `not_found`: они делались до того, как индекс попал в репозиторий.
Снимок стоит перегенерировать с ключом LLM и VPN на 2–3 разных событиях для SYN_001 и SYN_002. Команды для этого
есть в сообщении к PR.

## Как перегенерировать снимок с LLM (PowerShell, из корня, с VPN и `LLM_API_KEY` в `.env`)
Терминал 1 — сервер на временной базе:
```powershell
$env:COMPANIES_CSV="data/synthetic/companies.csv"
$env:PAYMENTS_CSV="data/synthetic/payments.csv"
$env:PEOPLE_CSV="data/synthetic/people.csv"
$env:APP_DB_PATH="$PWD\backend\var\demo_regen.sqlite3"
$env:PREANALYZE_ACTIVE="0"
Remove-Item $env:APP_DB_PATH -ErrorAction SilentlyContinue
python backend/scripts/load_events.py --file data/synthetic/news.json
cd backend; uvicorn app.main:app --port 8000
```
Терминал 2 — три разных события для двух компаний (платно, по 2–6 запросов на разбор), затем выгрузка:
```powershell
python backend/scripts/demo_scenario.py --companies SYN_001 SYN_002 --event-match "ключевую ставку" --yes
python backend/scripts/demo_scenario.py --companies SYN_001 SYN_002 --event-match "юаню" --yes
python backend/scripts/demo_scenario.py --companies SYN_001 SYN_002 --event-match "пошлины на металлопрокат" --yes
$env:COMPANIES_CSV="data/synthetic/companies.csv"
$env:APP_DB_PATH="$PWD\backend\var\demo_regen.sqlite3"
python backend/scripts/export_demo.py --companies SYN_001 SYN_002 --role-views
git add data/demo/demo_snapshot.json; git commit -m "Демо-снимок: разборы с LLM и позицией банка"
```

## Поправка по прогону перегенерации
Разбор «пошлины на металлопрокат» для SYN_002 получил ошибку «Числа без источника: 24, 25». Это были коды ОКВЭД
из текста самого разбора. Проверка чисел теперь пропускает коды ОКВЭД («ОКВЭД 24, 25», «ОКВЭД 47.11»). Суммы и
проценты рядом с кодом по-прежнему проверяются. Тесты: `test_agent.py` (+2).
