# Registro de cambios

Formato basado en [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/). Las versiones siguen
[versionado semántico](https://semver.org/lang/es/).

## [Sin publicar]

### Agregado

- Comprensión del bot (#1): oraciones, abreviaturas, corrección de errores de tipeo, frases largas antes que palabras
  sueltas, varias preguntas por mensaje, 187 localidades con su código postal y preguntas encadenadas («¿y cuánto
  sale?», «¿y a Mendoza?»).
- Temas nuevos de consulta: contacto, productos y precios, pedidos realizados, reclamos y pagos informados.
- Derivaciones con mensaje según el tema, el WhatsApp desde el que responde el comercio y cuándo (#2). El bot se
  presenta como asistente automático y lo confirma si le preguntan.
- Botones de respuesta rápida de WhatsApp, con alternativa de texto (#3).
- Costo del envío por zona, envío gratis desde un monto y enlace al catálogo (#4).
- Respuestas propias del comercio a preguntas frecuentes (#5, CU15): plantillas de cambios, factura, retiro, ventas
  por mayor, garantía y envoltorio para regalo; validación de palabras clave contra los temas del bot; prueba con un
  mensaje antes de guardar; usos de cada respuesta y sugerencias a partir de las consultas derivadas. Las de Casa &
  Detalles se cargan con la demostración.
- Respuestas puntuales: «sí» o «no» para un medio de pago, el horario de un día, el contacto oficial.
- Manejo de imágenes, audios, ubicaciones, stickers y reacciones.
- Migraciones del esquema (`app/migraciones.py`) con sincronización del catálogo de palabras clave.
- Corpus de validación de 139 mensajes, prueba por cada mensaje de los corpus e informe de exactitud
  (`scripts/evaluar_bot.py`, `docs/evaluacion-del-bot.md`).
- Revisión por perfiles de usuario con 16 hallazgos registrados como issues (`docs/revision-por-perfiles.md`).
- Corpus de desarrollo de 240 mensajes y 28 diálogos para medir la comprensión del bot (`tests/corpus/mensajes.py`).
- Integración continua: análisis estático, pruebas en Python 3.10 a 3.13 con cobertura y auditoría de dependencias.
- Guía de contribución, política de seguridad y plantillas de pull request e issues.

### Cambiado

- Con una consulta derivada, el bot sigue respondiendo lo que sabe resolver y a lo demás le responde un solo
  recordatorio (antes no respondía nada). La conversación vuelve a la atención automática cuando se atienden todas sus
  consultas pendientes.
- Ante un mensaje que no entiende, el bot pide una aclaración y ofrece una persona; al tercer mensaje seguido sin
  sentido deja de responder. Las preguntas con contenido que no son ningún tema se derivan.
- La ciudad se acepta en lugar del código postal; la localidad ambigua no cuenta como intento fallido.
- El resumen muestra solo los temas con consultas, de mayor a menor; los reclamos y los pagos informados se destacan.
- La conversación de ejemplo de la página de inicio se genera con el motor real.
- Un saludo con una pregunta que el bot no sabe responder («Hola, ¿hacen factura?») deriva la pregunta en lugar de
  responder solo la bienvenida, y una pregunta directa con una sola palabra de contenido («¿tienen showroom?») se
  deriva en lugar de pedir una aclaración.
- «Cambié de dirección» o «modificar el pedido» son consultas de pedidos y «retiro en sucursal» es una consulta de
  envío.
- Formato de código unificado con ruff.
- Flujo de trabajo directo sobre `main` con verificación local obligatoria antes de cada push
  (`scripts/verificar.py --versiones 3.10 3.11 3.12 3.13 --auditoria`). El workflow de GitHub Actions queda de
  ejecución manual para no consumir minutos facturables.

### Corregido

- Un código postal se confundía con parte de un número de tarjeta, un teléfono o un número de pedido.
- El texto del enlace de acceso no se reconocía si el comercio cambiaba de nombre después de compartirlo.

## [0.1.0] - 2026-10-28

Prototipo funcional de la Entrega 3: casos de uso CU01 a CU14, integración con WhatsApp Cloud API, simulador, datos
de demostración y 105 pruebas automatizadas.
