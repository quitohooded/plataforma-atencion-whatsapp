# Cómo trabajar en el proyecto

## Flujo

El equipo es de dos personas y el proyecto no usa servicios pagos, así que se trabaja directamente sobre `main` con
verificación local obligatoria antes de cada push:

1. Cada cambio parte de un error, una mejora o un hallazgo de revisión. Los hallazgos de la revisión por perfiles se
   identifican con su número (#1 a #16) en `docs/revision-por-perfiles.md` y en el `CHANGELOG.md`.
2. Se hace el cambio con sus pruebas y su documentación (`docs/arquitectura.md` si cambia el comportamiento del bot
   o del modelo, `CHANGELOG.md` siempre).
3. Antes del push se corre la verificación completa, equivalente a la integración continua:

   ```bash
   python scripts/verificar.py --versiones 3.10 3.11 3.12 3.13 --auditoria --e2e
   ```

   Debe pasar: análisis estático, formato, pruebas en Python 3.10 a 3.13 con cobertura mínima de 85 %, pruebas con
   navegador y de accesibilidad, y auditoría de dependencias. Requiere [uv](https://docs.astral.sh/uv/) para crear los
   entornos de cada versión y, para `--e2e`, `requirements-e2e.txt` y Chromium (`python -m playwright install
   chromium`). Si el cambio toca la interfaz, también conviene `python scripts/rendimiento.py` cuando afecta al bot.
4. El mensaje del commit menciona el hallazgo que resuelve, si corresponde.
5. Las versiones se publican con una etiqueta `vX.Y.Z` y una release con las notas del `CHANGELOG.md`.

El workflow de GitHub Actions (`.github/workflows/ci.yml`) hace lo mismo y se puede ejecutar a mano. No corre en cada
push: la verificación de referencia es la local. Los cambios de terceros llegan por pull request con la plantilla del
repositorio.

## Entorno de desarrollo

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
flask --app app demo --si
flask --app app run --debug
```

## Verificación rápida mientras se trabaja

```bash
ruff check .
ruff format .
python -m pytest --cov=app
python scripts/evaluar_bot.py      # exactitud del bot sobre los corpus, si se tocó el bot
```

## Convenciones

- Código, mensajes y documentación en español (Argentina).
- Las clases y tablas respetan el diagrama de clases y el DER del informe; los métodos van en snake_case.
- El panel trata de «usted»; el bot le habla al comprador de «vos».
- Toda lectura del panel se filtra por el comercio de la sesión (RF13).
- Todo cambio de comportamiento del bot o del modelo se documenta en `docs/arquitectura.md`.
- Cada cambio del bot se valida contra los corpus de `tests/corpus` (desarrollo y validación). Un mensaje nuevo que el
  bot no entendía se agrega al corpus junto con la corrección.
- Mensajes de commit en imperativo y en español: «Agrega…», «Corrige…».
