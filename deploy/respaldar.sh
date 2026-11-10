#!/usr/bin/env bash
# Respalda la base SQLite en caliente desde el contenedor, la copia a ~/respaldos/,
# borra los respaldos locales antiguos y, si está configurado rclone, los sube a un
# almacenamiento externo (Oracle Object Storage, Google Drive, etc.).
#
# Variables opcionales (en el entorno o en .env):
#   CARPETA_RESPALDOS       carpeta local donde guardar las copias (por defecto: $HOME/respaldos)
#   DIAS_RESPALDOS          días que se conservan las copias locales (por defecto: 14)
#   RCLONE_REMOTO           destino de rclone, por ejemplo "gdrive:responde-respaldos" u "oci:responde-respaldos"
#   PING_URL / HEALTHCHECK_URL  URL de monitoreo de éxito (ej. Healthchecks.io gratuito o Cronitor)
#
# Ejemplo en crontab (todos los días a las 03:30):
#   30 3 * * * /home/ubuntu/plataforma-atencion-whatsapp/deploy/respaldar.sh >> $HOME/respaldos/respaldar.log 2>&1

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

CHECK_URL="${PING_URL:-${HEALTHCHECK_URL:-}}"

notificar_error() {
    local codigo=$?
    if [ -n "${CHECK_URL:-}" ] && command -v curl >/dev/null 2>&1; then
        curl -fsS -m 10 --retry 2 "${CHECK_URL%/}/fail" >/dev/null 2>&1 || true
    fi
    exit "$codigo"
}
trap notificar_error ERR

CARPETA="${CARPETA_RESPALDOS:-$HOME/respaldos}"
DIAS="${DIAS_RESPALDOS:-14}"
REMOTO="${RCLONE_REMOTO:-}"
FECHA="$(date +%Y%m%d-%H%M%S)"
ARCHIVO="plataforma-${FECHA}.db"
RUTA_CONTENEDOR="/app/instance/respaldos/${ARCHIVO}"
RUTA_LOCAL="${CARPETA}/${ARCHIVO}"

mkdir -p "$CARPETA"

echo "[$(date -Iseconds)] Creando respaldo en caliente: ${ARCHIVO}"
docker compose exec -T app flask --app app admin respaldar "$RUTA_CONTENEDOR"
docker compose cp "app:${RUTA_CONTENEDOR}" "$RUTA_LOCAL"
docker compose exec -T app rm -f "$RUTA_CONTENEDOR"
chmod 600 "$RUTA_LOCAL"

# Comprobar que la copia es una base SQLite íntegra antes de darla por buena.
if command -v sqlite3 >/dev/null 2>&1; then
    INTEGRIDAD="$(sqlite3 "$RUTA_LOCAL" "PRAGMA integrity_check;" | head -n 1)"
    if [ "$INTEGRIDAD" != "ok" ]; then
        echo "[error] La verificación de integridad falló: ${INTEGRIDAD}" >&2
        exit 1
    fi
fi

find "$CARPETA" -maxdepth 1 -type f -name 'plataforma-*.db' -mtime "+${DIAS}" -delete

if [ -n "$REMOTO" ]; then
    if command -v rclone >/dev/null 2>&1; then
        echo "[$(date -Iseconds)] Copiando a ${REMOTO}"
        rclone copy "$RUTA_LOCAL" "$REMOTO"
        rclone delete "$REMOTO" --min-age "${DIAS}d" --include 'plataforma-*.db' || true
    else
        echo "[aviso] RCLONE_REMOTO está definido pero rclone no está instalado." >&2
    fi
fi

echo "[$(date -Iseconds)] Respaldo listo: ${RUTA_LOCAL}"

if [ -n "$CHECK_URL" ]; then
    if command -v curl >/dev/null 2>&1; then
        echo "[$(date -Iseconds)] Enviando ping de éxito a ${CHECK_URL}"
        curl -fsS -m 10 --retry 3 "$CHECK_URL" >/dev/null 2>&1 || echo "[aviso] No se pudo enviar el ping a ${CHECK_URL}" >&2
    else
        echo "[aviso] PING_URL/HEALTHCHECK_URL está definido pero curl no está instalado." >&2
    fi
fi
