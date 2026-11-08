#!/usr/bin/env bash
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

usage() {
    echo "Использование: sudo $0 [пользователь для группы docker]" >&2
    exit 2
}

[[ $# -le 1 ]] || usage
require_root "$@"

if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
    log "Docker уже установлен: $(docker --version)"
else
    . /etc/os-release
    case "$ID" in
        ubuntu | debian) ;;
        *) die "Поддерживаются Ubuntu и Debian, а здесь $ID" ;;
    esac

    log "Подключаю официальный репозиторий Docker"
    apt-get update -q
    apt_install ca-certificates curl
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID ${UBUNTU_CODENAME:-$VERSION_CODENAME} stable" \
        >/etc/apt/sources.list.d/docker.list

    log "Устанавливаю Docker Engine и Compose"
    apt-get update -q
    apt_install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
fi

systemctl enable --now docker

if [[ $# -eq 1 ]]; then
    id "$1" >/dev/null 2>&1 || die "Нет пользователя $1"
    usermod -aG docker "$1"
    log "$1 добавлен в группу docker (подействует после повторного входа)"
fi

docker compose version
