# Cómo trabajar en el proyecto

## Flujo

1. Cada cambio parte de un issue (error, mejora o hallazgo de revisión) asignado al hito vigente.
2. Se trabaja en una rama con prefijo según el tipo: `bot/`, `panel/`, `seguridad/`, `operacion/`, `qa/`,
   `docs/`, `proceso/`.
3. Se abre un pull request contra `main` con la plantilla completa y la referencia al issue (`Closes #N`).
4. La integración continua debe pasar: análisis estático, pruebas en Python 3.10 a 3.13 con cobertura mínima de
   85 % y auditoría de dependencias.
5. Se integra con merge (se conserva el historial de la rama) y la rama se elimina.
6. Las versiones se publican con una etiqueta `vX.Y.Z` y una release con las notas del `CHANGELOG.md`.

## Entorno de desarrollo

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
flask --app app demo --si
flask --app app run --debug
```

## Antes de abrir el pull request

```bash
ruff check .
ruff format .
python -m pytest --cov=app
```

## Convenciones

- Código, mensajes y documentación en español (Argentina).
- Las clases y tablas respetan el diagrama de clases y el DER del informe; los métodos van en snake_case.
- El panel trata de «usted»; el bot le habla al comprador de «vos».
- Toda lectura del panel se filtra por el comercio de la sesión (RF13).
- Todo cambio de comportamiento del bot o del modelo se documenta en `docs/arquitectura.md`.
- Cada cambio del bot se valida contra el corpus de `tests/corpus/mensajes.py`.
- Mensajes de commit en imperativo y en español: «Agrega…», «Corrige…».
