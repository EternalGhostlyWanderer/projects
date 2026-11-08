#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
NGINX_SITE="/etc/nginx/sites-available/alfa-signal.conf"
export ACME_ROOT="/var/www/certbot"

log() {
    printf '\033[1;32m==>\033[0m %s\n' "$*"
}

warn() {
    printf '\033[1;33m!!\033[0m %s\n' "$*" >&2
}

die() {
    printf '\033[1;31mxx\033[0m %s\n' "$*" >&2
    exit 1
}

require_root() {
    [[ $EUID -eq 0 ]] || die "Запустите через sudo: sudo $0 $*"
}

require_domain() {
    local domain="$1"
    [[ $domain =~ ^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$ ]] || die "Некорректный домен: $domain"
}

apt_install() {
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends "$@"
}

render_site() {
    local template="$1" domain="$2" backup
    backup="$(mktemp)"
    [[ -f $NGINX_SITE ]] && cp "$NGINX_SITE" "$backup"
    sed "s/__DOMAIN__/$domain/g" "$REPO_DIR/deploy/nginx/$template" >"$NGINX_SITE"
    ln -sf "$NGINX_SITE" /etc/nginx/sites-enabled/alfa-signal.conf
    rm -f /etc/nginx/sites-enabled/default
    if ! nginx -t; then
        if [[ -s $backup ]]; then cp "$backup" "$NGINX_SITE"; else rm -f "$NGINX_SITE" /etc/nginx/sites-enabled/alfa-signal.conf; fi
        rm -f "$backup"
        die "Конфигурация Nginx не прошла проверку, восстановлена прежняя"
    fi
    rm -f "$backup"
    systemctl reload nginx
}
