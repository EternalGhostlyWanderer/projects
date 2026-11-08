#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

usage() {
    echo "Использование: sudo $0 <пользователь>" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
require_root "$@"

user="$1"
[[ $user =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || die "Некорректное имя пользователя: $user"
[[ $user != root ]] || die "Нужен отдельный пользователь, вход под root будет закрыт"

if ! id "$user" >/dev/null 2>&1; then
    log "Создаю пользователя $user"
    adduser --disabled-password --gecos "" "$user"
fi
usermod -aG sudo "$user"

home="$(getent passwd "$user" | cut -d: -f6)"
keys="$home/.ssh/authorized_keys"
install -d -m 700 -o "$user" -g "$user" "$home/.ssh"

if [[ ! -s $keys && -s /root/.ssh/authorized_keys ]]; then
    log "Копирую ключи из /root/.ssh/authorized_keys"
    install -m 600 -o "$user" -g "$user" /root/.ssh/authorized_keys "$keys"
fi
[[ -s $keys ]] || die "В $keys нет ключей. Сначала добавьте ключ: ssh-copy-id root@<IP-сервера>"
chown "$user:$user" "$keys"
chmod 600 "$keys"
grep -Eq '^(ssh-(ed25519|rsa)|ecdsa-sha2-|sk-)' "$keys" || die "В $keys не найдено ни одного публичного ключа"

if passwd -S "$user" | awk '{exit ($2 == "P") ? 0 : 1}'; then
    log "Пароль для sudo у $user уже задан"
else
    log "Задайте пароль $user для команд sudo (по SSH вход будет только по ключу)"
    passwd "$user"
fi

log "Настраиваю sshd: вход только по ключу, без root"
cat >/etc/ssh/sshd_config.d/10-hardening.conf <<CONF
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthenticationMethods publickey
MaxAuthTries 3
LoginGraceTime 30
X11Forwarding no
AllowUsers $user
CONF
chmod 644 /etc/ssh/sshd_config.d/10-hardening.conf

sshd -t || die "Ошибка в настройках sshd, изменения не применены"
systemctl reload ssh 2>/dev/null || systemctl reload sshd

log "Готово. НЕ закрывайте эту сессию, пока в новом окне не сработает вход:"
echo "    ssh $user@$(hostname -I | awk '{print $1}')"
