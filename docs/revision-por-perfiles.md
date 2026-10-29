# Revisión por perfiles de usuario

Revisión del prototipo 0.1 (Entrega 3) antes de cerrar la versión 1.0.0. Se recorrió el producto con la mirada de
cada perfil que lo usa (comprador, responsable del comercio y operador de la plataforma), se midió el bot contra un
corpus de mensajes reales y se registró cada hallazgo como issue en GitHub, dentro del hito «v1.0.0». La columna
«Resolución», al final, indica el commit que cierra cada issue.

## Método

1. **Corpus de mensajes.** 215 mensajes de compradores escritos como llegan por WhatsApp (errores de tipeo,
   abreviaturas, jerga rioplatense, varias preguntas juntas, intentos de estafa, spam e insultos) y 14 diálogos de
   varios pasos, cada uno con el resultado esperado. Está en `tests/corpus/mensajes.py`.
2. **Recorrido por perfil.** Uso guiado del panel como responsable sin conocimientos técnicos, de la línea como
   comprador (simulador) y de la operación como administrador de la plataforma.
3. **Consistencia de datos.** Contraste entre lo que se carga en el panel, lo que responde el bot y lo que muestran
   el resumen y el historial.
4. **Seguridad.** Modelo de amenazas para un canal de mensajería comercial: estafas contra el comercio, estafas
   contra el comprador que usan el nombre del comercio, abuso del canal y filtración de datos.

## Línea de base del bot (versión 0.1)

Exactitud sobre el corpus: **36,3 %** (78 de 215 mensajes).

| Categoría | Aciertos | Categoría | Aciertos |
|---|---|---|---|
| Medios de pago | 88,9 % | Respuestas del comercio | 0 % |
| Horarios | 86,7 % | Productos y precios | 5 % |
| Pedido de una persona | 85,7 % | Pedidos y reclamos | 0 % |
| Cortesía | 80 % | Seguridad y estafas | 0 % |
| Envíos | 61,9 % | Spam e insultos | 0 % |
| Saludos | 50 % | Varias preguntas juntas | 0 % |

Lo que mejor funcionaba eran las preguntas directas sobre los tres temas del alcance. Fallaba ante ciudades sin
código postal, abreviaturas («mp», «hs», «q»), errores de tipeo («trasferencia», «orario») y todo lo que no fueran
esos tres temas, que terminaba derivado sin distinción.

### Evidencia de riesgos graves

| Mensaje del comprador | Respuesta del bot 0.1 | Riesgo |
|---|---|---|
| «mi tarjeta es 4509 9535 6623 3704 vence 11/27 cvv 123» | Lista de medios de pago; el número queda guardado completo | Datos de tarjeta en texto plano |
| «¿Este alias es de ustedes? lucas.ventas.mp» | Lista de medios de pago, sin aclarar | El comprador puede pagarle a un estafador |
| «Te transferí de más, devolveme la diferencia a este alias: juan.perez.mp» | Lista de medios de pago | Estafa de la devolución sin alerta al comercio |
| «Soy de Mercado Pago, tu cuenta será suspendida, verificá en bit.ly/abc» | Lista de medios de pago | El bot interactúa con phishing |
| «Felicitaciones! Ganaste un premio…», «sos un pelotudo» | Derivación a una persona | Pendientes falsos que hacen perder tiempo al comercio |
| «te mandé un código por error, me lo pasás?» | Derivación a una persona | Intento de robo de cuenta sin advertencia |

## Hallazgos por perfil

Severidad: **alta** (riesgo de fraude o bloqueo de uso), **media** (consulta mal resuelta o trabajo extra para el
comercio), **baja** (mejora de comprensión o comodidad).

### Comprador

| ID | Hallazgo | Severidad | Issue |
|---|---|---|---|
| B1 | Si escribe la ciudad («¿llegan a Río Cuarto?») el bot siempre pide el código postal | Media | #1 |
| B2 | Abreviaturas y errores de tipeo frecuentes terminan derivados | Media | #1 |
| B3 | Con dos preguntas en un mensaje («¿envían a Rosario y cómo se paga?») responde solo una | Media | #1 |
| B4 | Si mientras se le pide el CP pregunta otra cosa, el bot insiste con el CP | Media | #1 |
| B5 | El bot nunca dice que se puede pedir hablar con una persona | Baja | #2 |
| B6 | Al derivar no dice cuándo le van a responder (por ejemplo, «mañana desde las 9») | Media | #2 |
| B7 | Tiene que escribir todo: no hay botones para elegir el tema | Baja | #3 |
| B8 | «¿Sos un bot?» se deriva en lugar de responder con honestidad que es automático | Baja | #2 |
| B9 | «Una consulta» se deriva antes de que escriba la consulta | Baja | #1 |
| B10 | Ante preguntas de productos, precios o stock el mensaje es genérico | Media | #2 |
| B11 | Un reclamo recibe el mismo mensaje que cualquier consulta | Media | #2 |
| B12 | Si avisa que pagó, nadie le explica que el pago se verifica antes de confirmar | Media | #2, #6 |
| B13 | No puede verificar si un alias o un teléfono son del comercio | Alta | #6 |
| B14 | Si envía datos de su tarjeta no recibe advertencia y quedan guardados | Alta | #6 |
| B15 | Si pregunta por el contacto oficial o las redes, se deriva | Baja | #1 |
| B16 | No hay respuesta para el costo del envío, la pregunta más común después del plazo | Media | #4 |

### Responsable del comercio

| ID | Hallazgo | Severidad | Issue |
|---|---|---|---|
| C1 | Si olvida la contraseña no tiene forma de recuperarla | Alta | #9 |
| C2 | No puede cambiar la contraseña | Media | #9 |
| C3 | Durante el onboarding no ve cómo va a responder el bot con sus datos | Baja | #9 |
| C4 | No puede cargar el costo del envío ni un mínimo para envío gratis | Media | #4 |
| C5 | No puede cargar respuestas propias (cambios, factura, retiro, ventas por mayor) | Media | #5 |
| C6 | Los pendientes no tienen prioridad: un reclamo o un pago informado se ven como cualquier otro | Media | #8 |
| C7 | No se entera de una consulta pendiente si no tiene el panel abierto | Media | #8 |
| C8 | «Responder por WhatsApp» abre un chat vacío y hay que reescribir el contexto | Baja | #8 |
| C9 | El spam y los insultos aparecen como consultas pendientes | Media | #7 |
| C10 | No puede bloquear un número que molesta | Media | #7 |
| C11 | El historial no permite buscar por teléfono, nombre o texto, ni exportar | Baja | #10 |
| C12 | No hay ayuda dentro del panel | Baja | #9 |
| C13 | Si el comprador repite la misma pregunta, cuenta como varias consultas | Media | #11 |
| C14 | «Fuera de horario» se recalcula con el horario actual y cambia el historial si se modifican los horarios | Media | #11 |
| C15 | Si cambia el nombre del comercio, los enlaces viejos siguen llegando con el nombre anterior | Baja | #1 |
| C16 | No puede compartir un enlace a su catálogo | Baja | #4 |
| C17 | Si un comprador pregunta por un medio que no acepta («¿aceptan Naranja?») recibe la lista sin un «no» claro | Baja | #1 |

### Operador de la plataforma

| ID | Hallazgo | Severidad | Issue |
|---|---|---|---|
| O1 | No hay herramientas para restablecer contraseñas, desbloquear usuarios o pausar un comercio | Media | #13 |
| O2 | Faltan encabezados de seguridad, política de contenido (CSP) y cookies seguras con HTTPS | Alta | #12 |
| O3 | No hay límite de intentos por IP en ingreso, registro y simulador | Media | #12 |
| O4 | No hay política de privacidad ni términos (Meta los exige para publicar la app; Ley 25.326) | Media | #14 |
| O5 | Agregar columnas rompe una base existente: no hay migraciones | Alta | #13 |
| O6 | Los mensajes se guardan para siempre: no hay depuración | Media | #13 |
| O7 | El webhook no registra fallas de entrega ni marca los mensajes como leídos | Baja | #13 |
| O8 | Un número que envía cientos de mensajes recibe cientos de respuestas | Alta | #7 |
| O9 | Solo se puede correr en una computadora con túnel: no hay guía de despliegue | Media | #13 |
| O10 | No se advierte una configuración insegura al iniciar (simulador público, firma sin clave) | Media | #13 |

### Calidad y proceso

| ID | Hallazgo | Severidad | Issue |
|---|---|---|---|
| Q1 | No hay integración continua, análisis estático ni medición de cobertura | Media | #15 |
| Q2 | No hay pruebas de punta a punta con navegador ni auditoría de accesibilidad | Media | #16 |
| Q3 | No hay evidencia medida del tiempo de respuesta (RNF04) | Baja | #16 |
| Q4 | La comprensión del bot no se mide contra un corpus | Media | #16 |
| Q5 | Faltan CHANGELOG, guía de contribución y plantillas de PR e issues | Baja | #15 |

## Resolución

Los 48 hallazgos quedaron resueltos en la versión 1.0.0. Cada commit cierra sus issues desde el mensaje
(`Closes #N`); el detalle de cada cambio está en `CHANGELOG.md` y en las decisiones de `docs/arquitectura.md`.

| Issue | Hallazgos | Commit | Qué se hizo |
|---|---|---|---|
| #1 | B1, B2, B3, B4, B9, B15, C15, C17 | `183160a` | Oraciones, abreviaturas, corrección de tipeo, 187 localidades, varias preguntas por mensaje, contacto oficial, «no» claro para un medio de pago |
| #2 | B5, B6, B8, B10, B11, B12 | `183160a` | Derivación con el tema, el WhatsApp desde el que responde el comercio y cuándo; el bot dice que es automático |
| #3 | B7 | `183160a` | Botones de respuesta rápida, con alternativa de texto |
| #4 | B16, C4, C16 | `183160a` | Costo por zona, envío gratis desde un monto y enlace al catálogo |
| #5 | C5 | `c306670` | Respuestas propias del comercio (CU15) con plantillas, validación y prueba antes de guardar |
| #6 | B12, B13, B14 | `b45aa3a` | Datos sensibles ocultos, advertencias, verificación de alias, CBU y teléfonos, alertas para el comercio |
| #7 | C9, C10, O8 | `b45aa3a` | Spam, insultos y ráfagas sin pendientes falsos; bloqueo de números |
| #8 | C6, C7, C8 | `35aedd8` | Pendientes por prioridad, contador en vivo, avisos del navegador y por correo, mensaje sugerido |
| #9 | C1, C2, C3, C12 | `35aedd8` | Cambio y recuperación de contraseña, ayuda del panel y vista previa del bot en el onboarding |
| #10 | C11 | `35aedd8` | Búsqueda en el historial y exportación a CSV |
| #11 | C13, C14 | `b45aa3a` | Consultas repetidas no se cuentan dos veces; «fuera de horario» se guarda al momento |
| #12 | O2, O3 | `c17cfaf` | Encabezados de seguridad, CSP sin scripts en línea, cookies seguras, límites por IP |
| #13 | O1, O5, O6, O7, O9, O10 | `46070ec` | Administración por consola, migraciones, retención, estados de entrega, despliegue sin costo, verificación de la configuración |
| #14 | O4 | `510df5f` | Política de privacidad, términos, consentimiento registrado y borrado de datos de un comprador |
| #15 | Q1, Q5 | `acb2c5d` (PR #17) | Análisis estático, pruebas en Python 3.10 a 3.13, cobertura, auditoría, guía de contribución y plantillas |
| #16 | Q2, Q3, Q4 | `53a0239` | Pruebas con navegador, accesibilidad WCAG 2.1 AA, tiempo de respuesta medido y tercer corpus a ciegas |

### Resultado final

| Medición | Versión 0.1 | Versión 1.0.0 |
|---|---|---|
| Los 215 mensajes de la línea de base | 36,3 % | 100 % |
| Corpus de desarrollo (252 mensajes, 30 diálogos) | sin medir | 100 % |
| Corpus de validación (139 mensajes, 6 diálogos) | sin medir | 88,5 % en su primera corrida, 100 % después |
| Corpus a ciegas (120 mensajes, 6 diálogos) | sin medir | 83,3 % en su primera corrida, 100 % después |
| Pruebas automatizadas | 105 | 985, más 13 con navegador; cobertura de 94 % |
| Accesibilidad (axe-core, WCAG 2.1 AA) | sin medir | ningún incumplimiento en escritorio y celular |
| Tiempo de respuesta (RNF04) | sin medir | 9,7 ms de mediana por mensaje con la base; 46,5 ms con 10 compradores a la vez |

Las primeras corridas de los corpus de validación y a ciegas son la medida honesta de cómo generaliza el bot ante
mensajes nuevos; los 100 % posteriores indican que esos casos quedaron como pruebas de regresión.
