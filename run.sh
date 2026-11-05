#!/usr/bin/env bash
# Запуск проекта одной командой: база → зависимости → данные → API с HTML-дашбордом → HTTPS-туннель → Telegram-бот.
# Повторный запуск безопасен: .env не перезаписывается, данные не дублируются.
# Дашборд один и тот же в браузере и в Telegram (/app): туннель cloudflared даёт API HTTPS-адрес,
# который передаётся боту как WEBAPP_URL (адрес быстрого туннеля меняется при каждом запуске, в .env не пишется).
#   ./run.sh               всё
#   ./run.sh --no-bot      без бота
#   ./run.sh --no-tunnel   без туннеля (/app в Telegram работать не будет, если WEBAPP_URL не задан в .env)
#   API_PORT=8010 ./run.sh
# Остановка: Ctrl+C (база в Docker продолжает работать; остановить её: docker-compose stop).
set -euo pipefail
cd "$(dirname "$0")"

RUN_BOT=1
RUN_TUNNEL=1
for arg in "$@"; do
    case "$arg" in
        --no-bot)    RUN_BOT=0 ;;
        --no-tunnel) RUN_TUNNEL=0 ;;
        *) echo "Неизвестный параметр: $arg (есть --no-bot, --no-tunnel)" >&2; exit 2 ;;
    esac
done

say()  { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- 1. .env ----------
if [[ ! -f .env ]]; then
    cp .env.example .env
    die "Создан .env из шаблона. Впишите POSTGRES_PASSWORD и TELEGRAM_BOT_TOKEN (DASHBOARD_KEY — по желанию) и запустите снова."
fi
set -a; source .env; set +a
[[ -n "${POSTGRES_PASSWORD:-}" && -n "${POSTGRES_USER:-}" && -n "${POSTGRES_DB:-}" ]] \
    || die "В .env не заданы POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB"
[[ -z "${DASHBOARD_KEY:-}" ]] && say "Дашборд и API открыты без ключа (DASHBOARD_KEY пуст)"

# ---------- 2. база ----------
if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
say "PostgreSQL"
$COMPOSE up -d >/dev/null
for _ in $(seq 1 30); do
    [[ "$(docker inspect -f '{{.State.Health.Status}}' faq-postgres 2>/dev/null)" == "healthy" ]] && break
    sleep 1
done

# ---------- 3. зависимости ----------
if [[ ! -x .venv/bin/python ]]; then
    say "Виртуальное окружение"
    python3 -m venv .venv
fi
REQ_HASH=$(sha256sum requirements.txt | cut -d' ' -f1)
if [[ "$(cat .venv/.requirements.sha 2>/dev/null)" != "$REQ_HASH" ]]; then
    say "Установка зависимостей (requirements.txt изменился)"
    .venv/bin/pip install -q -r requirements.txt
    echo "$REQ_HASH" > .venv/.requirements.sha
fi
PY=.venv/bin/python

# ---------- 4. подключение и данные ----------
DB_ERROR=$($PY - <<'EOF' 2>&1
from sqlalchemy import text
from db import get_engine
with get_engine().connect() as conn:
    conn.execute(text("SELECT 1"))
EOF
) || {
    if grep -q "password authentication failed" <<<"$DB_ERROR"; then
        die "Пароль в .env не совпадает с паролем базы. Верните прежний POSTGRES_PASSWORD или задайте базе новый:
  docker exec -it faq-postgres psql -U $POSTGRES_USER -d $POSTGRES_DB -c \"ALTER USER $POSTGRES_USER PASSWORD '<пароль из .env>';\""
    fi
    die "Нет подключения к PostgreSQL:
$(tail -n 3 <<<"$DB_ERROR")"
}
say "Данные FAQ и оценка методов (выполняется только то, чего ещё нет)"
$PY init_project.py

# ---------- 5. API + дашборд ----------
PORT="${API_PORT:-8000}"
port_busy() { $PY -c "import socket,sys; s=socket.socket(); sys.exit(s.connect_ex(('127.0.0.1', $1)) != 0)"; }
while port_busy "$PORT"; do
    warn "Порт $PORT занят, пробую $((PORT + 1))"
    PORT=$((PORT + 1))
done

PIDS=()
cleanup() {
    trap - INT TERM EXIT
    echo; say "Остановка"
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
    wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

say "API и дашборд на порту $PORT"
.venv/bin/uvicorn api.app:app --host 0.0.0.0 --port "$PORT" --log-level warning &
PIDS+=($!)

# ---------- 6. HTTPS-туннель для Telegram ----------
# Telegram открывает мини-приложения только по HTTPS. Если постоянный адрес уже задан в .env — используем его.
CLOUDFLARED=$(command -v cloudflared || echo "$HOME/.local/bin/cloudflared")
if [[ $RUN_TUNNEL == 1 && $RUN_BOT == 1 && -z "${WEBAPP_URL:-}" ]]; then
    if [[ -x "$CLOUDFLARED" ]]; then
        say "HTTPS-туннель для /app в Telegram"
        TUNNEL_LOG=$(mktemp)
        "$CLOUDFLARED" tunnel --no-autoupdate --url "http://localhost:$PORT" >"$TUNNEL_LOG" 2>&1 &
        PIDS+=($!)
        for _ in $(seq 1 30); do
            WEBAPP_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$TUNNEL_LOG" | head -n 1 || true)
            [[ -n "$WEBAPP_URL" ]] && break
            sleep 1
        done
        if [[ -n "$WEBAPP_URL" ]]; then
            export WEBAPP_URL
        else
            warn "Туннель не поднялся за 30 с — /app в Telegram работать не будет (лог: $TUNNEL_LOG)"
        fi
    else
        warn "cloudflared не найден — /app в Telegram работать не будет (установка: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)"
    fi
fi

# ---------- 7. бот ----------
if [[ $RUN_BOT == 1 ]]; then
    if [[ -n "${TELEGRAM_BOT_TOKEN:-}" ]]; then
        say "Telegram-бот"
        $PY bot.py &
        PIDS+=($!)
    else
        warn "TELEGRAM_BOT_TOKEN пуст — бот не запущен (токен выдаёт @BotFather)"
    fi
fi

URL="http://localhost:$PORT/"
[[ -n "${DASHBOARD_KEY:-}" ]] && URL+="?key=$DASHBOARD_KEY"
cat <<EOF

  Дашборд:   $URL
  API:       http://localhost:$PORT/api/docs
  Telegram:  ${WEBAPP_URL:-не подключён} (команда /app в боте открывает тот же дашборд)

  Ctrl+C — остановить
EOF

# если один из процессов упал — останавливаем и остальные
wait -n "${PIDS[@]}" || true
