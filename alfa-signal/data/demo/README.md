# Демо-данные

- `demo_snapshot.json` — готовый снимок: новости (официальные источники и деловые издания), разборы агента,
  журналы и ролевые блоки по **синтетическим** компаниям (`SYN_*`). С ним демо работает без ключа LLM.
- `extra_news.json` — пул заготовленных демонстрационных новостей под отрасли шести синтетических компаний.
  Новости помечены как демонстрационные.

Оба файла загружает в чистую базу `backend/scripts/seed_demo.py` (в Docker — при первом запуске).

Пересобрать снимок с живой моделью (нужны ключ LLM и VPN, из корня):
```powershell
$env:COMPANIES_CSV="data/synthetic/companies.csv"
$env:PAYMENTS_CSV="data/synthetic/payments.csv"
$env:PEOPLE_CSV="data/synthetic/people.csv"
$env:APP_DB_PATH="$PWD\backend\var\demo_regen.sqlite3"
python backend/scripts/seed_demo.py
python backend/scripts/export_demo.py --companies SYN_001 SYN_002 SYN_003 SYN_004 SYN_005 SYN_006 --analyze-top 5 --role-views
```

Снимки с данными реальных компаний организаторов сюда не кладём: в доказательствах разборов могут быть их
выручка и банковские продукты. Для локальной проверки используйте `--out backend/var/demo_snapshot.json`
(папка `var` в git не попадает) и `DEMO_SNAPSHOT_FILE`.
