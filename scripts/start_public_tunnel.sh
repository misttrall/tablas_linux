#!/usr/bin/env bash
# Script para iniciar o consultar el túnel público HTTPS de demostración.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/scripts/bin/cloudflared"
LOG="/tmp/cloudflared.log"

if [[ ! -x "$BIN" ]]; then
  echo "[info] Descargando binario cloudflared..."
  mkdir -p "$ROOT/scripts/bin"
  curl -L --fail -o "$BIN" https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64
  chmod +x "$BIN"
fi

if ! pgrep -f "cloudflared tunnel" > /dev/null; then
  echo "[info] Iniciando túnel hacia http://localhost:8001..."
  nohup "$BIN" tunnel --url http://localhost:8001 > "$LOG" 2>&1 &
  sleep 4
fi

URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$LOG" 2>/dev/null | tail -n 1 || true)
if [[ -z "$URL" ]]; then
  # Fallback a buscar en logs de background task si existe
  for f in "$LOG" /tmp/cloudflared*.log /home/mist/.gemini/antigravity-ide/brain/*/.system_generated/tasks/*.log; do
    if [[ -f "$f" ]]; then
      FOUND=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' "$f" 2>/dev/null | tail -n 1 || true)
      if [[ -n "$FOUND" ]]; then
        URL="$FOUND"
        break
      fi
    fi
  done
fi

echo "==============================================================="
echo "🚀 DEMO WEB ACTIVA Y ACCESIBLE GLOBALMENTE EN:"
echo "   $URL"
echo "==============================================================="
echo "Credenciales:"
echo "  - Administrador: admin / admin"
echo "  - Analista:     analista / demo1234"
echo "==============================================================="
