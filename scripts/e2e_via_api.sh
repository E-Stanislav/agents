#!/usr/bin/env bash
# Повторяемый E2E: только HTTP API (как в README) + WebSocket через Python из контейнера app.
# На хосте нужны: curl, python3 (stdlib), docker compose.
# Зависимости приложения (websockets, httpx) не ставятся на хост — используется образ app.
#
# Использование:
#   export APP_PORT=8000   # как в .env
#   ./scripts/e2e_via_api.sh
# Опционально:
#   E2E_BASE_URL=http://localhost:8000   # если не задан — см. ниже
#   E2E_TASK_FILE=tasks/e2e_minimal_task.md
#   COMPOSE="docker compose"  или  COMPOSE="docker-compose"
#
set -euo pipefail

# По умолчанию HTTP к первому адресу из hostname -I (не только localhost), иначе 127.0.0.1
_e2e_default_host() {
  local h
  h="$(hostname -I 2>/dev/null | awk '{print $1}')"
  [[ -n "$h" ]] && echo "$h" || echo "127.0.0.1"
}

if [[ -n "${E2E_BASE_URL:-}" ]]; then
  BASE_URL="$E2E_BASE_URL"
else
  BASE_URL="http://$(_e2e_default_host):${APP_PORT:-8005}"
fi
TASK_FILE="${E2E_TASK_FILE:-tasks/e2e_minimal_task.md}"
COMPOSE="${COMPOSE:-docker compose}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [[ ! -f "$REPO_ROOT/$TASK_FILE" ]] && [[ ! -f "$TASK_FILE" ]]; then
  echo "Файл задачи не найден: $TASK_FILE (относительно $REPO_ROOT)" >&2
  exit 1
fi
TASK_PATH="$TASK_FILE"
if [[ -f "$REPO_ROOT/$TASK_FILE" ]]; then
  TASK_PATH="$REPO_ROOT/$TASK_FILE"
fi

echo "==> Health: $BASE_URL/health"
curl -fsS "$BASE_URL/health" | python3 -m json.tool

echo "==> POST /api/tasks (md_content из файла, как в README)"
# POST /api/tasks/upload есть не во всех сборках; /api/tasks + JSON — базовый контракт.
PAYLOAD="$(python3 -c "
import json, sys
with open(sys.argv[1], encoding='utf-8') as f:
    print(json.dumps({'md_content': f.read()}))
" "$TASK_PATH")"
RESP="$(curl -fsS -X POST "$BASE_URL/api/tasks" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d "$PAYLOAD")"
echo "$RESP" | python3 -m json.tool
TASK_ID="$(printf '%s' "$RESP" | python3 -c "import json,sys; print(json.load(sys.stdin)['task_id'])")"
echo "task_id=$TASK_ID"

if ! command -v docker >/dev/null 2>&1; then
  echo >&2
  echo "Дальше нужен WebSocket ws://.../ws/$TASK_ID — в контейнере app есть клиент." >&2
  echo "Установите Docker и выполните из каталога репозитория:" >&2
  echo "  $COMPOSE exec -T app python3 /app/scripts/e2e_ws_runner.py $TASK_ID" >&2
  exit 2
fi

if ! $COMPOSE -f "$REPO_ROOT/docker-compose.yml" exec -T app test -r /app/scripts/e2e_ws_runner.py 2>/dev/null; then
  echo >&2 "Контейнер app недоступен или нет /app/scripts/e2e_ws_runner.py."
  echo >&2 "Запустите стек и при необходимости пересоберите образ: cd $REPO_ROOT && $COMPOSE build app && $COMPOSE up -d"
  exit 3
fi

echo "==> WebSocket (внутри контейнера app) → завершение генерации"
# Внутри контейнера подключаемся к uvicorn на localhost
export TASK_ID
$COMPOSE -f "$REPO_ROOT/docker-compose.yml" exec -T \
  -e TASK_ID="$TASK_ID" \
  app python3 /app/scripts/e2e_ws_runner.py

echo "==> GET /api/tasks/$TASK_ID"
STATUS_RESP="$(curl -sS "$BASE_URL/api/tasks/$TASK_ID" 2>&1)" || true
echo "$STATUS_RESP" | python3 -m json.tool 2>/dev/null || echo "$STATUS_RESP"

# Архив доступен на хосте через volume ./output
ARCHIVE="$(ls "$REPO_ROOT/output/${TASK_ID}"_*.tar.gz 2>/dev/null | head -1)"

if [[ -n "$ARCHIVE" && -f "$ARCHIVE" ]]; then
  echo "==> Архив найден локально: $ARCHIVE"
  ls -la "$ARCHIVE"
else
  # Попробуем скачать через API
  OUT="${E2E_DOWNLOAD_PATH:-$REPO_ROOT/output/e2e_${TASK_ID}_project.tar.gz}"
  mkdir -p "$(dirname "$OUT")"
  echo "==> GET /api/tasks/$TASK_ID/download → $OUT"
  if curl -fsS -o "$OUT" "$BASE_URL/api/tasks/$TASK_ID/download"; then
    ARCHIVE="$OUT"
    ls -la "$ARCHIVE"
  else
    echo "Не удалось скачать архив через API (возможен reload сервера)." >&2
    echo "Проверьте output/ вручную: ls $REPO_ROOT/output/${TASK_ID}*" >&2
    exit 4
  fi
fi

if [[ -n "$ARCHIVE" && -f "$ARCHIVE" ]]; then
  echo ""
  echo "Содержимое (без каталога .git):"
  tar tzf "$ARCHIVE" | grep -v '/\.git/' || true
fi

echo ""
echo "Готово. task_id=$TASK_ID"
echo "Повтор: тот же $TASK_FILE, те же переменные, при необходимости снимок llm_config.yaml."
