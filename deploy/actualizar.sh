#!/usr/bin/env bash
# Actualiza la plataforma en la VM con respaldo previo y verificación posterior.
#
#   bash deploy/actualizar.sh

set -euo pipefail

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
cd "$RAIZ"

if docker compose ps --status running --services 2>/dev/null | grep -qx "app"; then
    echo "==> 1/4 Respaldo previo de la base"
    bash deploy/respaldar.sh
else
    echo "==> 1/4 El contenedor app no está corriendo; se omite el respaldo previo"
fi

echo "==> 2/4 Descargando cambios del repositorio"
git pull --ff-only

echo "==> 3/4 Reconstruyendo y reiniciando los contenedores"
docker compose up -d --build --remove-orphans

echo "==> 4/4 Esperando a que /salud responda"
for _ in $(seq 1 30); do
    ESTADO="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}sin-salud{{end}}' responde-app 2>/dev/null || true)"
    if [ "$ESTADO" = "healthy" ]; then
        break
    fi
    sleep 2
done

if [ "${ESTADO:-}" != "healthy" ]; then
    echo "[error] El contenedor app no quedó saludable (estado: ${ESTADO:-desconocido})." >&2
    docker compose logs --tail=50 app
    exit 1
fi

docker compose exec -T app flask --app app admin verificar
echo "==> Actualización completada."
