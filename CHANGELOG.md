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
- Seguridad del canal (#6): los datos de tarjeta, claves y códigos se ocultan antes de guardar; advertencias ante
  pedidos de códigos, suplantación del comercio, devoluciones a otra cuenta y pedidos de datos de otros clientes;
  verificación de alias, CBU y teléfonos contra los del comercio; alertas de seguridad en el resumen y en el detalle
  de la consulta, con qué conviene hacer (`docs/seguridad.md`).
- Abuso del canal (#7): el spam recibe una respuesta de alcance y 24 horas sin respuesta; los insultos, un límite y
  después silencio; las ráfagas, una advertencia y una pausa breve. Bloqueo de números desde el panel.
- Seguimiento de pendientes (#8): contador en vivo, avisos del navegador, aviso por correo opcional (como máximo uno
  cada 30 minutos) y «Responder por WhatsApp» con un mensaje inicial que cita la consulta.
- Cuenta y ayuda (#9): cambio de contraseña, recuperación por correo con enlace firmado de un solo uso, página de
  ayuda y vista previa de las respuestas del bot en el resumen del onboarding.
- Historial (#10): búsqueda por nombre, teléfono o texto y descarga en CSV con los filtros aplicados.
- Correo sin costo (`app/correo.py`): guarda los correos en `instance/correos` o los envía por SMTP.
- Privacidad (#14): política de privacidad y términos de uso con las leyendas de la Ley 25.326, aceptación obligatoria
  y registrada al crear la cuenta, respuesta del bot a «¿qué hacen con mis datos?», derivación de los pedidos de
  borrado con el tema «Datos personales», borrado de los datos de un comprador desde el panel y baja de un comercio por
  consola.
- Operación (#13): comandos de administración (`flask --app app admin …`), depuración automática de datos con más de
  `RETENCION_DIAS` días, respaldo de la base en caliente, verificación de la configuración al iniciar, estados de
  entrega de WhatsApp en el detalle de la conversación, mensajes marcados como leídos, `/salud` con control de la
  base, `Dockerfile` y guía de despliegue sin costo (`docs/operacion.md`).
- Seguridad web (#12): política de contenido sin scripts en línea, encabezados de seguridad, HSTS y cookies seguras
  con HTTPS, panel sin caché, límites de intentos por IP en ingreso, registro, recuperación y simulador, y cierre de
  las demás sesiones al cambiar la contraseña.
- Respuestas puntuales: «sí» o «no» para un medio de pago, el horario de un día, el contacto oficial.
- Manejo de imágenes, audios, ubicaciones, stickers y reacciones.
- Migraciones del esquema (`app/migraciones.py`) con sincronización del catálogo de palabras clave.
- Corpus de validación de 139 mensajes, prueba por cada mensaje de los corpus e informe de exactitud
  (`scripts/evaluar_bot.py`, `docs/evaluacion-del-bot.md`).
- Revisión por perfiles de usuario con 16 hallazgos registrados como issues (`docs/revision-por-perfiles.md`).
- Corpus de desarrollo de 252 mensajes y 30 diálogos para medir la comprensión del bot (`tests/corpus/mensajes.py`).
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
- «Necesito tus datos» o «pasame tus datos» (para transferir) son consultas de medios de pago.
- «Cambié de dirección» o «modificar el pedido» son consultas de pedidos y «retiro en sucursal» es una consulta de
  envío.
- La respuesta de medios de pago termina con «Pagá solo a estos datos» y la de contacto aclara que es el único número
  del comercio. El bot nunca confirma un pago: «¿te llegó el pago?» se deriva para que lo verifique el comercio.
- Los pendientes se ordenan por prioridad (alertas de seguridad, reclamos, pagos informados, pedidos) y antigüedad.
- La misma consulta resuelta en la misma conversación dentro de 30 minutos se registra una sola vez, y cada consulta
  guarda si llegó fuera de horario según el horario de ese momento (#11).
- Formato de código unificado con ruff.
- Flujo de trabajo directo sobre `main` con verificación local obligatoria antes de cada push
  (`scripts/verificar.py --versiones 3.10 3.11 3.12 3.13 --auditoria`). El workflow de GitHub Actions queda de
  ejecución manual para no consumir minutos facturables.

### Corregido

- Un código postal se confundía con parte de un número de tarjeta, un teléfono o un número de pedido.
- El texto del enlace de acceso no se reconocía si el comercio cambiaba de nombre después de compartirlo.
- El historial del simulador podía mostrar la conversación de cualquier número; ahora solo la de números de prueba.
- El archivo `.env` no se leía al iniciar con `python serve.py` ni con el archivo WSGI (solo con el comando `flask`).
- Sin `WHATSAPP_APP_SECRET` el webhook aceptaba eventos sin firma; ahora los rechaza.

## [0.1.0] - 2026-10-28

Prototipo funcional de la Entrega 3: casos de uso CU01 a CU14, integración con WhatsApp Cloud API, simulador, datos
de demostración y 105 pruebas automatizadas.
