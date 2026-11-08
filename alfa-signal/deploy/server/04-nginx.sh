#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

usage() {
    echo "Использование: sudo $0 <домен>" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
require_root "$@"
domain="${1,,}"
require_domain "$domain"

busy="$(ss -Hltnp 'sport = :80' | grep -v nginx || true)"
[[ -z $busy ]] || die "Порт 80 занят другой программой: $busy"

command -v nginx >/dev/null || { apt-get update -q; apt_install nginx; }
install -d -m 755 "$ACME_ROOT"
systemctl enable --now nginx

log "Включаю сайт $domain по HTTP (для получения сертификата)"
render_site alfa-signal.http.conf.template "$domain"

if curl -fsS -o /dev/null -H "Host: $domain" http://127.0.0.1/; then
    log "Nginx проксирует запросы в контейнер фронтенда"
else
    warn "Контейнер фронтенда не отвечает на 127.0.0.1:8080. Запустите: docker compose up -d"
fi
