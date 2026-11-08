#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

usage() {
    echo "Использование: sudo $0 <домен> <email для уведомлений Let's Encrypt>" >&2
    exit 2
}

[[ $# -eq 2 ]] || usage
require_root "$@"
domain="${1,,}"
email="$2"
require_domain "$domain"
[[ $email == *@*.* ]] || die "Некорректный email: $email"
[[ -L /etc/nginx/sites-enabled/alfa-signal.conf ]] || die "Сначала выполните 04-nginx.sh"

server_ip="$(curl -4fsS https://api.ipify.org || true)"
domain_ip="$(getent ahostsv4 "$domain" | awk 'NR == 1 {print $1}')"
[[ -n $domain_ip ]] || die "Домен $domain не найден в DNS"
[[ -z $server_ip || $server_ip == "$domain_ip" ]] || die "Домен $domain указывает на $domain_ip, а IP сервера $server_ip"

command -v certbot >/dev/null || { apt-get update -q; apt_install certbot; }

log "Получаю сертификат Let's Encrypt для $domain"
certbot certonly --webroot -w "$ACME_ROOT" -d "$domain" \
    --email "$email" --agree-tos --no-eff-email --non-interactive --keep-until-expiring

install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
cat >/etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh <<'HOOK'
#!/bin/sh
nginx -t && systemctl reload nginx
HOOK
chmod 755 /etc/letsencrypt/renewal-hooks/deploy/reload-nginx.sh

log "Включаю HTTPS"
render_site alfa-signal.conf.template "$domain"

log "Проверяю автоматическое продление"
certbot renew --dry-run --cert-name "$domain"
systemctl list-timers --all | grep -E 'certbot|NEXT' || warn "Таймер certbot не найден: продление настройте через cron"

if curl -fsS -o /dev/null "https://$domain/"; then
    log "Сайт отвечает по https://$domain"
else
    warn "Сайт пока не отвечает по https://$domain, проверьте: sudo nginx -t && docker compose ps"
fi
