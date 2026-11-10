#!/usr/bin/env bash
# Instala o actualiza de manera idempotente la tarea programada (cron) para
# los respaldos diarios a las 03:30 AM en un host Ubuntu/Debian.
#
# Uso:
#   bash deploy/instalar-cron.sh

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_RESPALDO="${RAIZ}/deploy/respaldar.sh"
CARPETA_LOGS="${HOME}/respaldos"
ARCHIVO_LOG="${CARPETA_LOGS}/respaldar.log"

if [ ! -f "$SCRIPT_RESPALDO" ]; then
    echo "[error] No se encontró el script de respaldo en: $SCRIPT_RESPALDO" >&2
    exit 1
fi

chmod +x "$SCRIPT_RESPALDO"
mkdir -p "$CARPETA_LOGS"

# Línea de crontab para ejecutar diariamente a las 03:30 AM
CRON_JOB="30 3 * * * ${SCRIPT_RESPALDO} >> ${ARCHIVO_LOG} 2>&1"

# Leer crontab actual, filtrar ejecuciones previas del script de respaldo e incorporar la nueva
CRONTAB_ACTUAL="$(crontab -l 2>/dev/null || true)"
CRONTAB_LIMPIO="$(echo "$CRONTAB_ACTUAL" | grep -v "deploy/respaldar.sh" || true)"

if [ -n "$CRONTAB_LIMPIO" ]; then
    NUEVO_CRONTAB="${CRONTAB_LIMPIO}
${CRON_JOB}"
else
    NUEVO_CRONTAB="${CRON_JOB}"
fi

echo "$NUEVO_CRONTAB" | crontab -

echo "==> Tarea cron programada correctamente (03:30 AM todos los días):"
echo "    ${CRON_JOB}"
echo "==> Registro de respaldos:"
echo "    ${ARCHIVO_LOG}"
