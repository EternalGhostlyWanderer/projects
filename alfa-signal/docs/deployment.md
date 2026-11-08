# Развёртывание через Docker Compose

Compose поднимает два сервиса:

- `backend` — FastAPI на порту `8000`, SQLite хранится в постоянном Docker volume;
- `frontend` — production-сборка React под Nginx на порту `8080`, запросы `/api` проксируются
  во внутреннюю сеть к backend.

Оба контейнера запускаются не от `root`, имеют healthcheck и политику перезапуска. Секреты и
локальные данные не копируются в образы.

## Быстрый запуск

Нужны Docker Engine или Docker Desktop с поддержкой Compose v2.

```bash
cp .env.example .env
```

Ключ `LLM_API_KEY` в `.env` нужен только для AI-анализа. Без него работают список компаний,
персональная лента, RSS-сбор и классификация по ключевым словам.

```bash
docker compose up --build -d
docker compose ps
```

После успешных healthchecks:

- интерфейс: http://localhost:8080;
- Swagger: http://localhost:8000/docs;
- healthcheck backend: http://localhost:8000/health.

При первом запуске пустая база автоматически получает 10 синтетических новостей. При следующих
перезапусках seed пропускается.

## Управление

```bash
# Логи всех сервисов
docker compose logs -f

# Пересобрать после изменения кода или frontend-переменных
docker compose up --build -d

# Остановить, сохранив SQLite
docker compose down

# Полностью удалить локальное состояние SQLite
docker compose down -v
```

## Реальные данные

Положите файлы организаторов в `data/raw/`. Папка `data/` подключается к backend только для
чтения и не попадает в Docker-образ.

В `.env` задайте:

```dotenv
COMPANIES_CSV=data/raw/df_Uid_data_hack.csv
PAYMENTS_CSV=data/raw/df_Uid_payment_hack.csv
PEOPLE_CSV=data/raw/df_Fid_Uid_link_hack.csv
SEED_SYNTHETIC_DATA=0
VITE_COMPANY_IDS=U_9250,U_57706,U_177581
```

После изменения `VITE_COMPANY_IDS` frontend нужно пересобрать командой
`docker compose up --build -d` — переменные Vite встраиваются на этапе сборки.

## Аналитика банка

Backend читает готовый индекс `data/processed/bank_index.json` из подключённой папки `data/`.
Индекс собирается до запуска Compose:

```bash
python backend/scripts/build_bank_index.py
docker compose restart backend
```

PDF и OCR JSON не отправляются в Docker registry и не включаются в образ благодаря
`.dockerignore`.

## Проверка после запуска

```bash
curl --fail http://localhost:8000/health
curl --fail "http://localhost:8080/api/v1/feed?company_id=SYN_001"
```

Второй запрос одновременно проверяет Nginx, внутреннюю сеть Compose, backend, SQLite и загрузку
синтетических данных.

## Настройки

Основные параметры находятся в корневом `.env`:

- `FRONTEND_PORT`, `BACKEND_PORT` — внешние порты;
- `LLM_*` — шлюз, модели и лимиты;
- `COMPANIES_CSV`, `PAYMENTS_CSV`, `PEOPLE_CSV` — пути внутри подключённой папки проекта;
- `SEED_SYNTHETIC_DATA` — автоматическая загрузка демо-новостей в пустую базу;
- `NEWS_RSS_URLS` — источники для разового `POST /api/v1/events/collect`;
- `VITE_COMPANY_IDS` — компании в интерфейсе.

Корневой `.env` и `backend/.env` не коммитятся. Для Compose используется корневой `.env`, для
обычного локального запуска — `backend/.env`.

## Внешний сервер (VPS)

Схема: Nginx на хосте (HTTPS, порты 80/443) → контейнер фронтенда (Nginx, `127.0.0.1:8080`) → контейнер
backend (`127.0.0.1:8000`). Наружу открыты только 22, 80 и 443. Скрипты настройки лежат в
`deploy/server/`, шаблоны Nginx — в `deploy/nginx/`.

| Шаг | Скрипт | Что делает |
|---|---|---|
| 1 | `01-ssh.sh <пользователь>` | Пользователь с sudo, вход только по ключу, root и пароли по SSH запрещены |
| 2 | `02-firewall.sh` | ufw: всё входящее закрыто, кроме SSH (с ограничением частоты), 80 и 443 |
| 3 | `03-docker.sh [пользователь]` | Docker Engine и Compose из официального репозитория |
| 4 | `04-nginx.sh <домен>` | Nginx как reverse proxy к контейнеру фронтенда |
| 5 | `05-tls.sh <домен> <email>` | Сертификат Let's Encrypt, HTTPS, автоматическое продление |

### Подготовка

- VPS: Ubuntu 22.04/24.04 или Debian 12, 2 ГБ памяти, 20 ГБ диска.
- Домен: A-запись → IP сервера. Проверка: `getent hosts <домен>` показывает IP сервера.
- SSH-ключ на своём компьютере (если его нет — `ssh-keygen -t ed25519`) и ключ на сервере:

```bash
ssh-copy-id root@<IP-сервера>
```

### 1. SSH по ключам

```bash
git clone https://github.com/EternalGhostlyWanderer/alfa-signal.git
cd alfa-signal
sudo deploy/server/01-ssh.sh <пользователь>
```

Скрипт копирует ключ root новому пользователю, спрашивает пароль для sudo и запрещает вход по паролю
и под root (`/etc/ssh/sshd_config.d/10-hardening.conf`). Не закрывая текущую сессию, откройте новое окно
и проверьте вход `ssh <пользователь>@<IP-сервера>`. Дальше работайте под этим пользователем.

### 2. Файрвол

```bash
sudo deploy/server/02-firewall.sh
```

Docker публикует порты в обход ufw, поэтому порты 8000 и 8080 закрыты иначе: в `.env` стоят
`FRONTEND_BIND=127.0.0.1` и `BACKEND_BIND=127.0.0.1`.

### 3. Docker и сервис

```bash
sudo deploy/server/03-docker.sh "$USER"
cp .env.production.example .env
```

После `03-docker.sh` войдите по SSH заново, чтобы группа docker подействовала. Заполните `.env`
(раздел «Вход на сервере» ниже) и запустите сервис:

```bash
docker compose up --build -d
docker compose ps
```

Сразу проверьте, что с сервера открываются российские источники новостей (из-за рубежа сайт ЦБ и
часть СМИ иногда закрывают доступ):

```bash
curl -sI https://www.cbr.ru/rss/RssPress | head -1
curl -sI https://www.interfax.ru/rss.asp | head -1
```

Недоступный источник просто не попадёт в ленту; список задаётся в `NEWS_RSS_URLS`.

### 4. Nginx как reverse proxy

```bash
sudo deploy/server/04-nginx.sh <домен>
```

Nginx принимает запросы на 80 и передаёт их контейнеру фронтенда на `127.0.0.1:8080` с заголовками
`X-Real-IP`, `X-Forwarded-For` и `X-Forwarded-Proto`: по ним backend видит настоящий адрес клиента.
Каталог `/var/www/certbot` отдаётся напрямую — через него Let's Encrypt проверяет домен.

### 5. HTTPS через Let's Encrypt

```bash
sudo deploy/server/05-tls.sh <домен> <email>
```

Certbot получает сертификат (проверка webroot через Nginx), конфигурация переключается на
`deploy/nginx/alfa-signal.conf.template`:
- HTTP → HTTPS (301), HTTP/2, TLS 1.2/1.3, HSTS;
- ограничение частоты для `/api/v1/auth/login` и `/api/v1/auth/register` (20 запросов в минуту с адреса);
- таймаут 180 с для долгих разборов, сжатие gzip.

Сертификат продлевает таймер `certbot.timer`, после продления хук
`/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh` перезагружает Nginx. Скрипт сразу проверяет
продление: `certbot renew --dry-run`.

Проверка извне:

```bash
curl -sI https://<домен> | head -5
```

### Переход с Caddy

На сервере, где HTTPS раньше давал Caddy (`docker-compose.prod.yml`), до `git pull` освободите порты
80 и 443:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml rm -sf caddy
docker volume rm alfa-signal_caddy-data alfa-signal_caddy-config
```

Затем `git pull`, `docker compose up -d` и шаги 4–5.

### Вход на сервере

С `AUTH_STRICT=1`:
- без входа API отвечает 401 на всё, кроме `/api/v1/auth/login`;
- демо-учётки (`demo` / `alfa-signal`) не действуют;
- пароли хранятся только как хеш pbkdf2-sha256;
- после 5 неверных паролей для логина (или 20 с одного адреса) вход блокируется на 1 минуту;
- Swagger выключен (`API_DOCS=1` — включить);
- сессия скользящая. Токен действует `AUTH_SESSION_HOURS` (24 ч) и сам продлевается, пока сайт
  открыт: лента перезапрашивается раз в 5 минут, и после половины срока фронт получает новый токен.
  Не заходили дольше срока — снова вход. Независимо от активности вход нужен не реже, чем раз в
  `AUTH_SESSION_MAX_DAYS` (7) дней. Пользователь, удалённый из `AUTH_USERS`, не сможет продлить
  сессию: доступ закроется не позже чем через половину срока токена.

Секрет подписи сессий:

```bash
openssl rand -hex 32
```

**Регистрация.** По умолчанию (`AUTH_REGISTRATION=1`) на экране входа есть вкладка «Регистрация»: человек сам
заводит учётную запись (логин, имя, роль, пароль), администратор не нужен, и `AUTH_USERS` можно оставить
пустым. Учётные записи хранятся в базе (таблица `accounts`), пароли — хешем. С одного адреса — не больше
5 регистраций в час. Чтобы зарегистрироваться могли только свои, задайте `AUTH_REGISTRATION_CODE` —
код приглашения; `AUTH_REGISTRATION=0` — только пользователи из `AUTH_USERS`.

**Профиль.** Кнопка аккаунта в правом верхнем углу открывает меню: «Профиль и пароль» (имя, роль, смена
пароля), «Данные компании» (сведения о компании, которые уточняют ленту) и «Выйти». Пользователи из
`AUTH_USERS` тоже могут менять имя, роль и пароль; удаление из `AUTH_USERS` по-прежнему закрывает доступ.

Строка пользователя для `AUTH_USERS` (пароль спрашивается без отображения, не короче 10 символов):

```bash
python3 backend/scripts/hash_password.py ivan --role cfo --name "Иван Петров"
```

Результат вида `ivan:pbkdf2_sha256.390000.…::cfo:Иван Петров` вставьте в `AUTH_USERS`. Несколько
пользователей разделяются `;`. Чтобы ограничить пользователя компаниями, добавьте
`--companies SYN_001,SYN_002`. Роли: `owner`, `ceo`, `cfo`, `accountant`, `treasury`, `other`.

Заполните в `.env`: `CORS_ORIGINS=https://<домен>`, `DEMO_AUTH_SECRET`, `AUTH_USERS`,
`LLM_PROVIDER`, `LLM_API_KEY`.

### Обновление и пользователи

```bash
git pull
docker compose up --build -d
```

После изменения `AUTH_USERS` достаточно перезапустить backend:
`docker compose up -d backend`. Смена
`DEMO_AUTH_SECRET` разлогинивает всех.

### Как обновляются данные

- **При входе** и **при открытии ленты** новости собираются заново, если с прошлого сбора прошло
  больше 30 минут (`NEWS_REFRESH_ON_LOGIN_MIN`, `NEWS_REFRESH_ON_OPEN_MIN`). Сбор идёт в фоне,
  лента открывается сразу.
- **Пока страница открыта,** лента перезапрашивается раз в 5 минут, а пока идёт фоновый разбор, —
  каждые 10 секунд. Каждый такой запрос тоже проверяет возраст новостей, поэтому данные на открытой
  странице не старше примерно 30 минут.
- **Если вкладка свёрнута,** перезапросов нет. При возврате на вкладку лента обновляется сразу.
- **Плановый сбор** (`NEWS_COLLECT_INTERVAL_MIN=30`) работает, пока кто-то пользуется сервисом.

### Сколько новостей разбирается

| Переменная | По умолчанию | Что делает |
|---|---|---|
| `PREANALYZE_PER_COMPANY` | 10 | сколько верхних событий ленты разбирать заранее при открытии ленты |
| `PREANALYZE_DAILY_LIMIT` | 150 | предварительных разборов в сутки |
| `PREANALYZE_WORKERS` | 2 | разборов одновременно (1–4) |
| `LLM_DAILY_REQUEST_LIMIT` | 300 | запросов к LLM в сутки, считая повторы и чат |
| `AGENT_LLM_PLAN` | 1 | 0 — план агента по правилам, на один запрос меньше на разбор |
| `ROLE_VIEW_LLM` | 1 | 0 — ролевой блок по правилам, без отдельного запроса |

Один разбор — 1–3 запроса к LLM. При `AGENT_LLM_PLAN=0` в среднем около 1,5. На ответ 429 по
минутному лимиту клиент делает паузу и повторяет запрос; дневной лимит провайдера останавливает
предварительный разбор до следующих суток.

### Место на диске и память

**База** (SQLite в томе `backend-state`) хранит новости, разборы, журналы агента и кеш ответов нейросети
бессрочно. Объёмы: новость — 1,5–7 КБ, разбор вместе с журналом и ролевым блоком — около 27 КБ, кеш —
около 5 КБ на запрос к нейросети. Даже на максимальных лимитах (150 разборов в сутки) это меньше 10 МБ
в день, то есть около 3 ГБ в год. На бесплатных лимитах нейросети выходит в разы меньше.

**Логи контейнеров** ограничены: 3 файла по 10 МБ на сервис (`x-logging` в `docker-compose.yml`).

**Больше всего места занимают старые образы Docker:** каждая пересборка (`up --build`) оставляет
прежние, по 0,5–1 ГБ. Освободить место после обновления:

```bash
docker image prune -f && docker builder prune -f
```

Посмотреть, что занимает диск:

```bash
df -h / && docker system df
```

Размер базы:

```bash
docker compose exec backend du -h var/
```

**Оперативная память:** в работе сервис занимает около 300–500 МБ (backend, два Nginx). Сборка
фронтенда (`up --build`) кратковременно требует ещё около 1 ГБ. Если на сервере 1 ГБ памяти и сборка
падает, добавьте файл подкачки:

```bash
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```
