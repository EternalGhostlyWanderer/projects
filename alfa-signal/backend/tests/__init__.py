import os

# Тесты не ходят в сеть: официальные источники и данные ЦБ выключены (можно переопределить).
os.environ.setdefault("NEWS_OFFICIAL_SOURCES", "")
os.environ.setdefault("CBR_DATA_ENABLED", "0")
os.environ.setdefault("NEWS_COLLECT_INTERVAL_MIN", "0")
os.environ.setdefault("NEWS_REFRESH_ON_LOGIN_MIN", "0")
os.environ.setdefault("PREANALYZE_ACTIVE", "0")
os.environ.setdefault("NEWS_RSS_URLS", "-")
os.environ.setdefault("NEWS_RSS_URLS_FOREIGN", "-")
# Агент разбирает по анонсу, не загружая статьи из сети (get_full_article проверяется отдельно).
os.environ.setdefault("NEWS_FETCH_FULL_TEXT", "0")
