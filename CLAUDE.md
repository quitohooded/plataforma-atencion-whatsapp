# Contexto para Claude Code

Prototipo del Seminario de Práctica de Analista en Software (UES21, 2026): bot de WhatsApp multi-comercio para
consultas frecuentes (envíos, medios de pago, horarios) más panel web de administración. El diseño de referencia es
el informe técnico (Entrega 3): casos de uso CU01 a CU14, diagrama de clases y DER. El código debe seguir siendo
trazable a ese diseño.

## Comandos

- `python -m pytest`: pruebas (deben pasar todas antes de cada commit).
- `flask --app app demo --si`: reinicia la base con los datos de demostración.
- `python serve.py` o `flask --app app run --debug`: servidor local en el puerto 5000.
- `python scripts/capturas.py --url http://127.0.0.1:5000`: regenera `docs/capturas` (requiere Playwright).

## Convenciones

- Código, nombres de dominio, mensajes y documentación en español (Argentina). Nombres de clases y tablas iguales al
  diagrama de clases y al DER; métodos en snake_case.
- La interfaz del panel trata de «usted» (coincide con los mensajes citados en los casos de uso). El bot le habla al
  comprador de «vos», como el comercio en WhatsApp.
- Sin rayas largas (—) en textos ni documentación.
- El motor (`app/bot/motor.py`) no accede a la base: recibe `DatosComercio` y devuelve el resultado.
- Toda lectura del panel se filtra por el comercio de la sesión (RF13): usar `del_comercio()` o los servicios.
- Todo cambio de comportamiento del bot o del modelo se documenta en `docs/arquitectura.md` (sección de decisiones),
  porque luego se refleja en el informe.
- Alcance acotado: sin NLP, sin stock, un usuario por comercio, línea de WhatsApp provista por la plataforma.
