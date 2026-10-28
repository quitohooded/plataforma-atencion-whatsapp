# Casos de prueba

Material de base para el apartado 7.2 (Proceso de V&V) de la Actividad 4. Cada caso se vincula con el caso de uso y
los requerimientos que verifica, y con la prueba automatizada que lo ejecuta.

## Estrategia

| Nivel | Qué verifica | Cómo |
|---|---|---|
| Unitario | Normalización, extracción del código postal, detección de intención y motor de estados | `tests/test_normalizacion_e_intencion.py`, `tests/test_motor.py` (sin base de datos) |
| Integración | Servicio del bot con la base, webhook de WhatsApp, envío por la Graph API simulado | `tests/test_servicio_bot.py`, `tests/test_webhook_y_simulador.py` |
| Sistema | Casos de uso del panel de punta a punta por HTTP, aislamiento y seguridad | `tests/test_panel.py`, `tests/test_auth.py`, `tests/test_aislamiento.py`, `tests/test_seguridad.py` |
| Aceptación | Recorrido completo con el usuario, en el navegador y en el simulador | Guion manual al final de este documento |

Entorno: base SQLite en memoria nueva para cada prueba y reloj fijo en el martes 27/10/2026 a las 22:30, fuera del
horario de atención del comercio de prueba (lunes a viernes de 9 a 18 y sábados de 9 a 13). Ejecución:

```bash
pip install -r requirements-dev.txt
python -m pytest            # 105 pruebas
```

Criterio de aceptación: todas las pruebas automatizadas pasan y el guion de aceptación se completa sin desvíos.

## Casos por caso de uso

### CU01 Registrarse en la plataforma (RF14, RNF02, RNF06)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP01.1 | Registro válido | Datos completos y contraseña de 13 caracteres | Comercio «En onboarding», usuario con contraseña cifrada, sesión iniciada, paso 1 del onboarding | `test_cu01_registro_crea_comercio_en_onboarding_e_inicia_sesion` |
| CP01.2 | Campos incompletos | Rubro vacío | «Complete todos los campos obligatorios», no se crea el comercio | `test_cu01_excepcion_campos_incompletos` |
| CP01.3 | Contraseña débil | Contraseña de 7 caracteres | Pide al menos ocho caracteres | `test_cu01_excepcion_contrasena_debil` |
| CP01.4 | Correo ya registrado | Correo existente | Informa la cuenta existente y ofrece iniciar sesión | `test_cu01_alternativo_correo_ya_registrado_ofrece_iniciar_sesion` |

### CU02 Iniciar sesión (RF08, RF13, RNF03)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP02.1 | Destino según el estado | Comercio activo, en onboarding (paso 3) y sin activar | Resumen, paso 3 y activación respectivamente | `test_cu02_ingreso_dirige_segun_el_estado_del_comercio` |
| CP02.2 | Registro del ingreso | Credenciales válidas | Se guarda la fecha y hora del último ingreso | `test_cu02_registra_el_ultimo_ingreso` |
| CP02.3 | Credenciales inválidas | Contraseña errónea; correo inexistente | Mismo mensaje «Correo o contraseña incorrectos» en ambos casos | `test_cu02_excepcion_credenciales_invalidas_mensaje_generico` |
| CP02.4 | Bloqueo | Cinco intentos fallidos y luego la contraseña correcta | Ingreso bloqueado; a los 16 minutos vuelve a permitirse | `test_cu02_excepcion_bloqueo_tras_cinco_intentos` |
| CP02.5 | Cierre de sesión | «Cerrar sesión» | Vuelve a la pantalla de ingreso; el panel exige sesión | `test_cu02_alternativo_cierre_de_sesion` |
| CP02.6 | Precondición de sesión | Acceso directo a las secciones sin sesión | Redirige al ingreso | `test_paginas_del_panel_requieren_sesion` |
| CP02.7 | Redirección segura | Parámetro «siguiente» con un sitio externo | Se ignora y va al resumen | `test_siguiente_no_permite_redireccion_externa` |

### CU03 Completar onboarding (RF09 a RF11, RF15, RNF06)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP03.1 | Recorrido completo | Datos, una zona, un medio y un horario | Resumen con todo lo cargado; al confirmar habilita la activación sin activar el bot | `test_cu03_recorrido_completo_del_onboarding` |
| CP03.2 | Paso incompleto | «Continuar» sin zonas | Indica la información faltante y no avanza | `test_cu03_excepcion_paso_incompleto_no_avanza` |
| CP03.3 | Saltear pasos | Acceso directo al paso 4 desde el paso 1 | Vuelve al paso pendiente | `test_cu03_no_se_pueden_saltear_pasos` |
| CP03.4 | Interrupción | Salir en el paso 3 y volver a ingresar | Retoma en el paso 3 | `test_cu03_alternativo_interrupcion_retoma_en_el_paso_pendiente` |
| CP03.5 | Corrección de un paso | «Volver» al paso 2 | Muestra las zonas cargadas | `test_cu03_alternativo_volver_a_un_paso_anterior_muestra_lo_cargado` |
| CP03.6 | Secciones bloqueadas | Abrir «Zonas de envío» durante el onboarding | Redirige al onboarding | `test_secciones_del_panel_esperan_el_onboarding` |

### CU04 Administrar zonas de envío (RF09, RF15)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP04.1 | Alta, edición y eliminación | Zona 4400 a 4409; cambio de plazo; eliminación confirmada | Se guarda, se actualiza y se elimina | `test_cu04_alta_edicion_y_eliminacion_de_zona` |
| CP04.2 | Rango inválido | Inicial mayor que final; plazo mínimo mayor que máximo | Mensaje de error, no se guarda | `test_cu04_excepciones_rango_invalido_y_superpuesto` |
| CP04.3 | Rango superpuesto | 5050 a 5150 con «Córdoba Capital» cargada | Indica la zona en conflicto | `test_cu04_excepciones_rango_invalido_y_superpuesto` |
| CP04.4 | Importación de planilla | CSV en Windows-1252 con una fila válida y tres observadas | Vista previa con los motivos; incorpora solo la válida | `test_cu04_alternativo_importacion_de_planilla` |
| CP04.5 | Plantilla | Descargar plantilla | CSV con las columnas esperadas | `test_cu04_plantilla_csv` |

### CU05 Administrar medios de pago (RF10, RF15)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP05.1 | Alta, duplicado, desactivación y baja | Tarjeta de crédito dos veces; desactivar; eliminar | Alta, «ya está cargado», queda inactivo, se elimina | `test_cu05_alta_duplicado_desactivacion_y_eliminacion` |
| CP05.2 | Medio «Otro» | Sin nombre; luego «Cuenta DNI» | Pide el nombre; luego lo guarda | `test_cu05_opcion_otro_requiere_nombre` |
| CP05.3 | Medio desactivado | Consulta de pagos con «Efectivo» inactivo | El bot no lo informa | `test_medio_desactivado_no_se_informa` |

### CU06 Administrar horarios (RF11, RF15)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP06.1 | Jornada partida | Lunes 9 a 13 y 16 a 20 | Se guardan las dos franjas | `test_cu06_guarda_jornada_partida` |
| CP06.2 | Horario inválido | Cierre anterior a la apertura; franjas superpuestas | Señala el día con error, no guarda | `test_cu06_excepcion_horario_invalido_no_guarda` |
| CP06.3 | Copiar a días hábiles | Lunes 8:30 a 17:30, «Copiar» | Lunes a viernes con el mismo horario | `test_cu06_alternativo_copiar_a_dias_habiles` |

### CU07 Activar el bot (RF16, RNF01, RNF05)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP07.1 | Activación, pausa y reactivación | «Activar bot», «Pausar», «Reactivar» | Código de 6 caracteres, enlace wa.me y QR; estado Pausado; mismo código al reactivar | `test_cu07_activar_genera_codigo_y_pausar` |
| CP07.2 | Chat de prueba | Envío, código postal y pregunta fuera de tema | Responde como el bot real y no registra consultas | `test_cu07_chat_de_prueba_responde_sin_registrar` |
| CP07.3 | Precondición | Activar sin completar el onboarding | Redirige al onboarding | `test_cu07_requiere_onboarding_completo` |

### CU08 Identificar intención (RF01, RF06, RF13)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP08.1 | Normalización | «¿Hacen ENVÍOS a Río Cuarto?» | «hacen envios a rio cuarto» | `test_normaliza_minusculas_tildes_y_signos` |
| CP08.2 | Tema por palabras clave | Ocho mensajes de los tres temas y uno ajeno | Tema correcto en cada caso | `test_detecta_el_tema_por_palabras_clave` |
| CP08.3 | Empate | «¿A qué hora llega el envío?» | No reconocido (deriva) | `test_empate_entre_temas_es_no_reconocido` |
| CP08.4 | Primer contacto con código | Texto del enlace | Registra comprador y conversación; responde la bienvenida | `test_cu08_primer_contacto_con_codigo_registra_comprador_y_conversacion` |
| CP08.5 | Comercio no identificado | Mensaje sin código | Pide ingresar por el enlace; no crea conversación | `test_cu08_excepcion_sin_codigo_no_crea_conversacion` |
| CP08.6 | Bot pausado | Código de un comercio pausado | Informa que la atención automática no está disponible | `test_cu08_excepcion_comercio_pausado` |
| CP08.7 | Línea compartida | Mismo comprador escribe a dos comercios | Conversaciones y consultas separadas por comercio | `test_multicomercio_mismo_numero_cambia_de_comercio_con_otro_codigo` |

### CU09 Consultar plazo de envío (RF02, RF03, RF06, RF12, RNF04)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP09.1 | Flujo principal | «¿Hacen envíos a Río Cuarto?» y luego «5800» | Pide el código postal; responde 2 a 4 días; consulta resuelta | `test_cu09_flujo_principal_solicita_cp_y_responde_plazo` |
| CP09.2 | Código postal en el primer mensaje | «cuánto tarda el envío al 5000?» | Responde 1 a 2 días sin repreguntar | `test_cu09_alternativo_cp_en_el_primer_mensaje` |
| CP09.3 | Código inválido | «Río Cuarto» y «no sé» | Repregunta una vez; al segundo intento deriva | `test_cu09_excepcion_cp_invalido_dos_veces_deriva` |
| CP09.4 | Zona no configurada | «1405» | Informa que no tiene plazo y deriva | `test_cu09_excepcion_zona_no_configurada_deriva` |
| CP09.5 | Extracción del código postal | 10 formatos (CPA, montos, longitudes) | Solo acepta códigos válidos | `test_extrae_codigo_postal` |
| CP09.6 | Estado entre mensajes | Conversación de tres mensajes | Estado ESPERANDO_CP y luego ACTIVA; seis mensajes guardados | `test_cu09_conversacion_en_varios_pasos_y_mensajes_guardados` |

### CU10 y CU11 Consultar medios de pago y horarios (RF04, RF05, RF12)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP10.1 | Medios de pago | «¿Aceptan Mercado Pago?» | Listado completo con detalles; consulta resuelta | `test_cu10_responde_medios_de_pago_con_detalle` |
| CP10.2 | Sin medios activos | Comercio sin medios | Deriva | `test_cu10_excepcion_sin_medios_deriva` |
| CP11.1 | Horarios en horario de atención | Martes 11:00 | Días agrupados y «Ahora estamos atendiendo, hasta las 18:00» | `test_cu11_horarios_agrupados_y_abierto_ahora` |
| CP11.2 | Fuera de horario | Martes 22:30, sábado 15:00 y miércoles 7:00 | «mañana a las 9:00», «el lunes a las 9:00», «hoy a las 9:00» | `test_cu11_alternativo_cerrado_indica_reapertura` |
| CP11.3 | Sin horarios | Comercio sin horarios | Deriva | `test_cu11_excepcion_sin_horarios_deriva` |

### CU12 Derivar a atención humana (RF07, RF12)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP12.1 | Tema no reconocido | «¿Tienen el mantel en otro color?» | Avisa que responderá una persona, con teléfono y horario; consulta derivada pendiente | `test_cu12_tema_no_reconocido_deriva_e_informa_horario` |
| CP12.2 | Mensajes durante la derivación | Nuevos mensajes | Se registran sin respuesta automática | `test_cu12_derivacion_y_vuelta_a_la_atencion_automatica` |
| CP12.3 | Falla de envío del aviso | La API rechaza el envío | Se registra el error y la consulta sigue pendiente | `test_falla_de_envio_conserva_la_consulta_pendiente` |

### CU13 y CU14 Resumen, pendientes e historial (RF12, RF17)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP13.1 | Indicadores | 3 consultas en 7 días y 1 hace 20 días | 3 recibidas, 67 % resueltas, 2 fuera de horario, 1 pendiente; 4 en 30 días | `test_cu13_indicadores_del_periodo` |
| CP13.2 | Marcar como atendida | Consulta pendiente | Fecha de atención registrada; la conversación vuelve al bot | `test_cu13_marcar_atendida_devuelve_la_conversacion_al_bot` |
| CP13.3 | Sin consultas | Comercio recién activado | Mensaje sin consultas | `test_cu13_sin_consultas` |
| CP14.1 | Historial y filtros | Dos consultas | Orden descendente, filtros por resultado, tema y fecha, conversación completa | `test_cu14_historial_filtros_y_detalle` |
| CP14.2 | Sin registros | Comercio sin consultas | «Todavía no hay consultas registradas» | `test_cu14_sin_registros` |

### Requerimientos transversales

| ID | Requerimiento | Resultado esperado | Prueba |
|---|---|---|---|
| CPT.1 | RF13 Aislamiento | Un comercio no puede ver ni modificar zonas, medios ni consultas de otro (404) | `test_un_comercio_no_accede_a_registros_de_otro`, `test_listados_muestran_solo_lo_propio` |
| CPT.2 | RNF03 CSRF | Formularios sin token rechazados; con token aceptados | `test_formularios_sin_token_se_rechazan`, `test_formulario_con_token_funciona` |
| CPT.3 | RNF01 Webhook | Verificación con token, firma obligatoria, respuesta por la Graph API, eventos repetidos descartados | `test_verificacion_del_webhook`, `test_firma_invalida_se_rechaza`, `test_mensaje_entrante_se_atiende_y_se_responde_por_la_api` |
| CPT.4 | Números argentinos | 549 se envía como 54 en modo de prueba | `test_numero_argentino_sin_el_9_para_enviar` |
| CPT.5 | RF06 Inactividad | Conversación cerrada a las 24 horas; el comprador retoma con el mismo comercio | `test_inactividad_cierra_la_conversacion_y_el_comprador_retoma_sin_codigo` |

## Guion de aceptación (demo)

Escenario base para la presentación, con los datos de demostración (`iniciar.bat` o `flask --app app demo --si`).
Conviene tener dos ventanas: el panel y el simulador.

1. **Comercio nuevo (CU01, CU03).** Crear la cuenta «Deco Norte». Cargar una zona a mano e importar una planilla con
   una fila errónea para mostrar la vista previa. Agregar dos medios de pago y un horario con jornada partida.
2. **Prueba y activación (CU07).** En el chat de prueba escribir «¿Hacen envíos a Salta?», «4400» y «¿Tienen
   almohadones?» (aparece el aviso de derivación). Activar el bot y mostrar código, enlace, QR y cartel.
3. **Comprador (CU08 a CU12).** En el simulador, «Abrir su enlace» de Deco Norte y enviar. Preguntar por envíos,
   pagos y horarios, y una consulta fuera de tema. Mostrar que el bot deja de responder mientras está derivada.
4. **Línea compartida.** Con el mismo comprador, abrir el enlace de Casa & Detalles: la conversación pasa al otro
   comercio con sus propios datos.
5. **Seguimiento (CU13, CU14).** Volver al panel de Deco Norte: la consulta aparece pendiente. «Marcar como atendida»
   y comprobar en el simulador que el bot vuelve a responder. Abrir el historial y la conversación completa.
6. **Datos con historia.** Ingresar como Casa & Detalles para mostrar el resumen con tres semanas de actividad y el
   porcentaje de consultas fuera de horario.
