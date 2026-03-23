#!/usr/bin/env bash
# Сборка и (пере)запуск стека Docker для проекта agents.
# Использование:
#   ./build.sh              — собрать образы и поднять контейнеры (docker compose up -d)
#   ./build.sh --rebuild    — пересборка без кэша слоёв (--no-cache) + up -d
#   ./build.sh --no-start   — только сборка, без запуска
#   ./build.sh --down       — остановить и удалить контейнеры перед сборкой
#   ./build.sh --stop       — остановить стек (docker compose down), без сборки
#   ./build.sh --clean      — down + удалить локально собранные образы (--rmi local)
#   ./build.sh --purge      — down + все образы сервисов + тома (--rmi all -v), данные БД пропадут
#   ./build.sh --status     — показать статус контейнеров (compose ps -a), без сборки

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

NO_CACHE=false
NO_START=false
DOWN_FIRST=false
STOP_MODE="" # пусто | stop | clean | purge
SHOW_STATUS=false

usage() {
    cat <<'EOF'
Сборка и (пере)запуск стека Docker.

  ./build.sh              — собрать образы и поднять контейнеры (up -d)
  ./build.sh --rebuild    — пересборка без кэша (--no-cache) + up -d
  ./build.sh --no-start   — только сборка, без запуска
  ./build.sh --down       — сначала docker compose down, затем сборка и up

Остановка / образы:
  ./build.sh --stop       — остановить контейнеры и сеть проекта (compose down)
  ./build.sh --clean      — то же + удалить образы, собранные из Dockerfile (--rmi local)
  ./build.sh --purge      — down + удалить все образы сервисов и тома (--rmi all -v)
                            ВНИМАНИЕ: сотрёт данные PostgreSQL, Redis, ChromaDB и т.д.

Проверка:
  ./build.sh --status     — статус контейнеров (docker compose ps -a)
  ./build.sh -s | --ps    — то же самое
EOF
    exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -r|--rebuild|--no-cache)
            NO_CACHE=true
            shift
            ;;
        --no-start)
            NO_START=true
            shift
            ;;
        --down)
            DOWN_FIRST=true
            shift
            ;;
        --stop)
            STOP_MODE=stop
            shift
            ;;
        --clean)
            STOP_MODE=clean
            shift
            ;;
        --purge)
            STOP_MODE=purge
            shift
            ;;
        --status|--ps|-s)
            SHOW_STATUS=true
            shift
            ;;
        -h|--help)
            usage 0
            ;;
        *)
            echo "Неизвестный аргумент: $1" >&2
            usage 1
            ;;
    esac
done

if ! command -v docker &>/dev/null; then
    echo "Ошибка: не найден docker" >&2
    exit 1
fi

if ! docker compose version &>/dev/null 2>&1 && ! docker-compose version &>/dev/null 2>&1; then
    echo "Ошибка: нужен Docker Compose v2 (docker compose) или v1 (docker-compose)" >&2
    exit 1
fi

COMPOSE=(docker compose)
if ! docker compose version &>/dev/null 2>&1; then
    COMPOSE=(docker-compose)
fi

# Статус контейнеров — .env не обязателен
if $SHOW_STATUS; then
    echo "==> Статус стека (${COMPOSE[*]} ps -a):"
    echo ""
    "${COMPOSE[@]}" ps -a
    echo ""
    if [[ -f .env ]]; then
        _get_env() {
            local key="$1"
            local def="${2:-}"
            local line
            line=$(grep -E "^[[:space:]]*${key}=" .env 2>/dev/null | head -1) || true
            if [[ -z "$line" ]]; then
                echo "$def"
                return
            fi
            local v="${line#*=}"
            v="${v//\"/}"
            v="${v//\'/}"
            v="${v//[[:space:]]/}"
            echo "${v:-$def}"
        }
        echo "==> Точки входа (из .env, если заданы):"
        echo "    App:       http://localhost:$(_get_env APP_PORT 8000)"
        echo "    Langfuse:  http://localhost:$(_get_env LANGFUSE_PORT 3001)"
        echo "    Postgres:  localhost:$(_get_env POSTGRES_PORT 5432)"
        echo "    Redis:     localhost:$(_get_env REDIS_PORT 6379)"
        echo "    ChromaDB:  localhost:$(_get_env CHROMADB_HOST_PORT 8100)"
    else
        echo "(файла .env нет — порты по умолчанию см. в .env.example)"
    fi
    exit 0
fi

# Только остановка / снятие образов — .env не обязателен
if [[ -n "$STOP_MODE" ]]; then
    case "$STOP_MODE" in
        stop)
            echo "==> Остановка стека (${COMPOSE[*]} down)..."
            "${COMPOSE[@]}" down
            ;;
        clean)
            echo "==> Остановка и удаление локально собранных образов (down --rmi local)..."
            "${COMPOSE[@]}" down --rmi local
            ;;
        purge)
            echo "ВНИМАНИЕ: будут удалены тома (данные БД, Redis, ChromaDB и др.)."
            "${COMPOSE[@]}" down --rmi all -v
            echo "==> Стек остановлен, образы и тома проекта удалены."
            exit 0
            ;;
    esac
    echo "==> Готово."
    exit 0
fi

if [[ ! -f .env ]]; then
    if [[ -f .env.example ]]; then
        echo "Внимание: нет файла .env — копирую из .env.example"
        cp .env.example .env
        echo "Отредактируйте .env (API-ключи и при необходимости APP_PORT), затем перезапустите."
    else
        echo "Ошибка: создайте .env (например из .env.example)" >&2
        exit 1
    fi
fi

if $DOWN_FIRST; then
    echo "==> Остановка контейнеров..."
    "${COMPOSE[@]}" down
fi

BUILD_ARGS=()
if $NO_CACHE; then
    BUILD_ARGS+=(--no-cache)
    echo "==> Пересборка образов без кэша..."
else
    echo "==> Сборка образов..."
fi

"${COMPOSE[@]}" build "${BUILD_ARGS[@]}"

if $NO_START; then
    echo "==> Готово (контейнеры не запускались, указан --no-start)."
    exit 0
fi

echo "==> Запуск контейнеров..."
"${COMPOSE[@]}" up -d

echo "==> Статус:"
"${COMPOSE[@]}" ps

_http_port="8000"
if [[ -f .env ]] && _line=$(grep -E '^[[:space:]]*APP_PORT=' .env 2>/dev/null | head -1); then
    _http_port="${_line#*=}"
    _http_port="${_http_port//\"/}"
    _http_port="${_http_port//\'/}"
    _http_port="${_http_port//[[:space:]]/}"
fi
echo ""
echo "Веб-интерфейс: http://localhost:${_http_port:-8000}"
echo "Статус: ./build.sh --status  |  Остановка: ./build.sh --stop  |  снять образы: ./build.sh --clean  |  полная очистка: ./build.sh --purge"
