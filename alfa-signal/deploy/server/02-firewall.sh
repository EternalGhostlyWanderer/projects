#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

require_root "$@"

command -v ufw >/dev/null || { apt-get update -q; apt_install ufw; }

log "Правила по умолчанию: входящие запрещены, исходящие разрешены"
ufw default deny incoming
ufw default allow outgoing

log "Открываю SSH (с ограничением частоты), HTTP и HTTPS"
ufw limit OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp

ufw --force enable
ufw status verbose

if command -v docker >/dev/null && docker ps --format '{{.Ports}}' 2>/dev/null | grep -q '0\.0\.0\.0:\(8000\|8080\)->'; then
    warn "Docker публикует 8000/8080 на все адреса в обход ufw. В .env должны быть FRONTEND_BIND=127.0.0.1 и BACKEND_BIND=127.0.0.1"
fi
