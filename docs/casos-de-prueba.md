# Casos de prueba

Material de base para el apartado 7.2 (Proceso de V&V) de la Actividad 4. Cada caso se vincula con el caso de uso y
los requerimientos que verifica, y con la prueba automatizada que lo ejecuta.

## Estrategia

| Nivel | Qué verifica | Cómo |
|---|---|---|
| Unitario | Normalización, extracción del código postal, detección de intención, seguridad y motor de estados | `tests/test_normalizacion_e_intencion.py`, `tests/test_motor.py`, `tests/test_seguridad_bot.py` (sin base de datos) |
| Comprensión | Exactitud del bot sobre 379 mensajes y 34 diálogos reales | `tests/test_corpus.py` y `scripts/evaluar_bot.py` (ver `docs/evaluacion-del-bot.md`) |
| Integración | Servicio del bot con la base, webhook de WhatsApp, envío por la Graph API simulado, migraciones del esquema | `tests/test_servicio_bot.py`, `tests/test_webhook_y_simulador.py`, `tests/test_migraciones.py` |
| Sistema | Casos de uso del panel de punta a punta por HTTP, aislamiento y seguridad | `tests/test_panel.py`, `tests/test_respuestas.py`, `tests/test_auth.py`, `tests/test_aislamiento.py`, `tests/test_seguridad.py` |
| Aceptación | Recorrido completo con el usuario, en el navegador y en el simulador | Guion manual al final de este documento |

Entorno: base SQLite en memoria nueva para cada prueba y reloj fijo en el martes 27/10/2026 a las 22:30, fuera del
horario de atención del comercio de prueba (lunes a viernes de 9 a 18 y sábados de 9 a 13). Ejecución:

```bash
pip install -r requirements-dev.txt
python -m pytest                       # todas las pruebas, con las del corpus
python scripts/verificar.py            # análisis estático, formato, pruebas y cobertura (verificación local)
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
| CP04.5 | Plantilla | Descargar plantilla | CSV con las columnas esperadas, incluida la del costo | `test_cu04_plantilla_csv` |
| CP04.6 | Costo por zona | «$ 9.900», «0», vacío y «doce mil» | Guarda 9900, gratis y sin informar; rechaza el texto | `test_cu04_costo_del_envio_por_zona` |
| CP04.7 | Envío gratis | «120.000», «0» y vacío | Guarda el monto; rechaza 0 con una indicación; vacío lo quita | `test_cu04_envio_gratis_desde_un_monto` |
| CP04.8 | Planilla con costo | CSV con columna `costo` y un costo inválido | Vista previa con el costo; la fila inválida queda observada | `test_cu04_planilla_con_costo` |

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
| CP07.2 | Chat de prueba | Envío, código postal, pregunta de producto y un botón | Se presenta, responde como el bot real, avisa la derivación con una nota y sigue respondiendo; no registra consultas | `test_cu07_chat_de_prueba_responde_sin_registrar` |
| CP07.3 | Precondición | Activar sin completar el onboarding | Redirige al onboarding | `test_cu07_requiere_onboarding_completo` |

### CU08 Identificar intención (RF01, RF06, RF13)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP08.1 | Normalización | «¿Hacen ENVÍOS a Río Cuarto?», «holaaa» | «hacen envios a rio cuarto», «hola» | `test_normaliza_minusculas_tildes_y_signos`, `test_reduce_letras_repetidas` |
| CP08.2 | Abreviaturas | «q onda aceptan mp», «hasta q hs» | «que onda aceptan mercado pago», «hasta que horas» | `test_expande_abreviaturas` |
| CP08.3 | Errores de tipeo | «orario», «trasferencia», «targeta», «mendosa» | Se corrigen hacia el vocabulario; «tarde», «plazas» o «cesto» no se tocan | `test_corrige_errores_de_tipeo_hacia_el_vocabulario`, `test_no_corrige_palabras_comunes` |
| CP08.4 | Tema por palabras clave | Doce mensajes de los distintos temas | Tema correcto en cada caso | `test_detecta_el_tema_por_palabras_clave` |
| CP08.5 | Varias preguntas | «¿Envían a Rosario? ¿Y cómo se paga?» | Dos temas, en orden | `test_varias_preguntas_en_un_mensaje` |
| CP08.6 | Falsos positivos | «tarjeta de dedicatoria», «de qué modo», «el número de seguimiento» | No es medio de pago; es envío; es pedido | `test_frases_largas_evitan_falsos_positivos`, `test_mandar_informacion_no_es_un_envio` |
| CP08.7 | Temas que absorben a otros | «acabo de pagar por mercado pago», «todavía no me llegó el pedido» | Pago informado; reclamo | `test_un_tema_absorbe_a_otro_cuando_habla_de_lo_mismo` |
| CP08.8 | Primer contacto con código | Texto del enlace | Registra comprador y conversación; responde la bienvenida con botones | `test_cu08_primer_contacto_con_codigo_registra_comprador_y_conversacion`, `test_primer_contacto_responde_bienvenida_con_botones_sin_registrar_consulta` |
| CP08.9 | Enlace con una consulta | Texto del enlace más «¿aceptan mercado pago?» | Se presenta en una línea y responde | `test_primer_contacto_con_una_consulta_se_presenta_y_responde`, `test_limpia_el_texto_del_enlace_y_conserva_lo_agregado` |
| CP08.10 | Comercio no identificado | Mensaje sin código | Pide ingresar por el enlace; no crea conversación | `test_cu08_excepcion_sin_codigo_no_crea_conversacion` |
| CP08.11 | Bot pausado | Código de un comercio pausado | Informa que la atención automática no está disponible | `test_cu08_excepcion_comercio_pausado` |
| CP08.12 | Línea compartida | Mismo comprador escribe a dos comercios | Conversaciones y consultas separadas por comercio | `test_multicomercio_mismo_numero_cambia_de_comercio_con_otro_codigo` |
| CP08.13 | Botones y opciones | Botón «Medios de pago», «2», «opción 3», «4» | Pagos, pagos, horarios y derivación a una persona | `test_botones_y_opciones_numericas`, `test_boton_tocado_se_guarda_con_su_titulo` |
| CP08.14 | Mensajes sin sentido | «jajaja», «asdf», «jsjs» | Aclara, ofrece una persona y después no responde | `test_aclaracion_dos_veces_y_despues_silencio`, `test_si_despues_de_ofrecer_una_persona_deriva` |
| CP08.15 | Imagen, audio, ubicación | Mensajes que no son texto | Deriva la imagen avisando que no la ve; pide escribir el audio; pide el CP | `test_imagen_deriva_y_explica_que_no_puede_verla`, `test_audio_ubicacion_sticker_y_reaccion` |

### CU09 Consultar plazo de envío (RF02, RF03, RF06, RF12, RNF04)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP09.1 | Flujo principal | «¿Hacen envíos?» y luego «5800» | Pide el código postal; responde 2 a 4 días y $6.900, con el envío gratis; consulta resuelta | `test_cu09_flujo_principal_solicita_cp_y_responde_plazo_y_costo` |
| CP09.2 | Código postal en el primer mensaje | «cuánto tarda el envío al 5000?» | Responde 1 a 2 días sin repreguntar | `test_cu09_alternativo_cp_en_el_primer_mensaje` |
| CP09.3 | Ciudad | «¿Hacen envíos a Río Cuarto?»; «Villa Carlos Paz» mientras espera | Usa el CP 5800 y el 5152 | `test_cu09_ciudad_en_lugar_del_codigo_postal` |
| CP09.4 | Localidad repetida | «San Martín» | Pide el código postal sin contar un intento | `test_cu09_localidad_repetida_pide_el_cp_sin_contar_un_intento` |
| CP09.5 | Provincia | «¿envían a Chubut?» | Usa la capital como referencia y lo aclara | `test_cu09_provincia_toma_la_capital_como_referencia` |
| CP09.6 | Varios destinos | «¿envían a Córdoba y a Río Cuarto?» | Una respuesta con los dos plazos | `test_cu09_varios_destinos_en_un_mensaje` |
| CP09.7 | Dato inválido | «no sé» y «ni idea» | Sugiere escribir la ciudad; al segundo intento deriva | `test_cu09_excepcion_dato_invalido_dos_veces_deriva` |
| CP09.8 | Zona no configurada | «9410» | Informa que no tiene plazo y deriva con el CP | `test_cu09_excepcion_zona_no_configurada_deriva` |
| CP09.9 | Costo sin cargar | «¿cuánto sale el envío al 1425?» | Responde el plazo y deriva el costo | `test_cu09_costo_preguntado_y_no_cargado_responde_el_plazo_y_deriva` |
| CP09.10 | Pregunta encadenada | «¿Y cuánto sale?» después del plazo | Responde solo el costo para el mismo código postal | `test_cu09_el_costo_se_pregunta_despues_del_plazo` |
| CP09.11 | Envío gratis y zona única | Zona con costo 0; una zona 1000 a 9999 | «gratis»; responde sin pedir el CP | `test_cu09_envio_gratis_a_una_zona`, `test_cu09_zona_unica_nacional_no_pide_cp` |
| CP09.12 | Otra consulta o cancelar mientras espera | «¿y cómo se paga?», «dejalo» | Responde pagos o cancela; vuelve a ACTIVA | `test_cu09_otra_consulta_mientras_espera_el_cp`, `test_cu09_cancelar_la_espera` |
| CP09.13 | Extracción del código postal | 22 formatos (CPA, montos, teléfonos, tarjetas, pedidos, años) | Solo acepta códigos válidos | `test_extrae_codigos_postales` |
| CP09.14 | Estado entre mensajes | Conversación de tres mensajes | Estado ESPERANDO_CP y luego ACTIVA; seis mensajes guardados | `test_cu09_conversacion_en_varios_pasos_y_mensajes_guardados` |
| CP09.15 | Sin zonas | Comercio sin zonas | Deriva | `test_cu09_sin_zonas_cargadas_deriva` |

### CU10 y CU11 Consultar medios de pago y horarios (RF04, RF05, RF12)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP10.1 | Medios de pago | «formas de pago?» | Listado completo con detalles; consulta resuelta | `test_cu10_responde_medios_de_pago_con_detalle` |
| CP10.2 | Medio puntual | «¿Aceptan Mercado Pago?», «¿efectivo?», «¿cuotas sin interés?» | «Sí» con el detalle; «no está entre los medios»; «sí, hay cuotas» | `test_cu10_si_o_no_para_un_medio_en_particular` |
| CP10.3 | Marca de tarjeta | «¿aceptan Naranja?» con y sin marcas cargadas | Sin marcas: no tiene el dato; con «Visa y Mastercard»: no | `test_cu10_marca_de_tarjeta_sin_dato_no_se_niega` |
| CP10.4 | Sin medios activos | Comercio sin medios | Deriva | `test_cu10_excepcion_sin_medios_deriva` |
| CP11.1 | Horarios en horario de atención | Martes 11:00 | Días agrupados y «Ahora estamos atendiendo, hasta las 18:00» | `test_cu11_horarios_agrupados_y_abierto_ahora` |
| CP11.2 | Fuera de horario | Martes 22:30, sábado 15:00 y miércoles 7:00 | «mañana a las 9:00», «el lunes a las 9:00», «hoy a las 9:00» | `test_cu11_alternativo_cerrado_indica_reapertura` |
| CP11.3 | Día puntual | «¿abren los sábados?», «¿los domingos?», «¿mañana?», «¿feriados?» | Responde el día antes del horario completo | `test_cu11_dia_puntual` |
| CP11.4 | Sin horarios | Comercio sin horarios | Deriva | `test_cu11_excepcion_sin_horarios_deriva` |
| CP11.5 | Jornada partida | Lunes 9 a 13 y 16 a 20 | «Lunes: 9:00 a 13:00 y 16:00 a 20:00» | `test_horario_jornada_partida` |

### CU12 Derivar a atención humana (RF07, RF12)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP12.1 | Producto | «¿Tienen el mantel en otro color?» | Mensaje de productos con el catálogo, el WhatsApp del comercio y cuándo responden; consulta pendiente | `test_cu12_producto_deriva_con_el_catalogo_y_cuando_responden` |
| CP12.2 | Mensaje según el tema | Reclamo, pago informado, pedido, persona, pregunta ajena | Cada tema con su mensaje y su tema registrado | `test_cu12_cada_tema_tiene_su_mensaje` |
| CP12.3 | En horario | Pedido de una persona a las 11:00 | «Estamos en horario de atención» | `test_cu12_en_horario_avisa_que_responden_a_la_brevedad` |
| CP12.4 | Persona sobre un tema | «quiero hablar con alguien sobre los medios de pago» | Deriva con el tema, sin respuesta automática | `test_cu12_pedir_una_persona_sobre_un_tema_respeta_el_pedido` |
| CP12.5 | Derivada responde lo que sabe | Pregunta de envío con un producto pendiente | Responde el envío y sigue derivada | `test_cu12_derivada_sigue_respondiendo_lo_que_resuelve`, `test_cu12_con_la_consulta_derivada_el_bot_responde_lo_que_sabe` |
| CP12.6 | Mensajes durante la derivación | «hola?» dos veces | Un recordatorio y después silencio; los mensajes se registran | `test_cu12_derivada_recordatorio_una_vez_y_despues_silencio`, `test_cu12_derivacion_y_vuelta_a_la_atencion_automatica` |
| CP12.7 | Datos pedidos | Nombre de la compra después de derivar un pedido | Agradece y confirma que se sumó a la consulta | `test_cu12_derivada_agradece_los_datos_pedidos` |
| CP12.8 | Tema nuevo durante la derivación | Pago informado con un producto pendiente | Registra otra consulta; el mismo tema no se repite | `test_cu12_derivada_registra_un_tema_nuevo_y_no_repite_el_mismo` |
| CP12.9 | Atender una de dos | Dos consultas pendientes, se atiende una | Sigue derivada hasta atender la segunda | `test_marcar_una_consulta_no_reactiva_si_hay_otra_pendiente` |
| CP12.10 | Respuesta y derivación juntas | «¿envían al 5000? ¿tienen stock del mantel?» | Responde el envío y deriva el producto; dos consultas | `test_responde_lo_que_sabe_y_deriva_el_resto` |
| CP12.11 | Falla de envío del aviso | La API rechaza el envío | Se registra el error y la consulta sigue pendiente | `test_falla_de_envio_conserva_la_consulta_pendiente` |

### CU13 y CU14 Resumen, pendientes e historial (RF12, RF17)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP13.1 | Indicadores | 3 consultas en 7 días y 1 hace 20 días | 3 recibidas, 67 % resueltas, 2 fuera de horario, 1 pendiente; 4 en 30 días | `test_cu13_indicadores_del_periodo` |
| CP13.2 | Marcar como atendida | Consulta pendiente | Fecha de atención registrada; la conversación vuelve al bot | `test_cu13_marcar_atendida_devuelve_la_conversacion_al_bot` |
| CP13.3 | Sin consultas | Comercio recién activado | Mensaje sin consultas | `test_cu13_sin_consultas` |
| CP14.1 | Historial y filtros | Dos consultas | Orden descendente, filtros por resultado, tema y fecha, conversación completa | `test_cu14_historial_filtros_y_detalle` |
| CP14.2 | Sin registros | Comercio sin consultas | «Todavía no hay consultas registradas» | `test_cu14_sin_registros` |

### CU15 Administrar respuestas propias (hallazgo C5)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CP15.1 | Respuesta propia | «hacen factura A?» con la respuesta de factura | Envía el texto del comercio con el cierre; consulta resuelta con el tema «Respuestas del comercio» y el vínculo a la respuesta | `test_responde_el_texto_del_comercio_y_registra_la_respuesta` |
| CP15.2 | Prioridad sobre palabras genéricas | «precio mayorista?», «venden x mayor?», «hacen fatura?», «puedo pasar a buscar el pedido?» | Responde la respuesta propia, no deriva como producto o pedido | `test_prioridad_de_las_respuestas_propias` |
| CP15.3 | Lo que no es de la respuesta | «retirar en sucursal de Andreani», «cambié de dirección…», «cambiar el medio de pago» | Envío, pedido y medios de pago respectivamente | `test_prioridad_de_las_respuestas_propias` |
| CP15.4 | Pedido concreto | «me olvidé de pedir factura en mi compra» | Responde la factura y deriva el pedido | `test_un_pedido_concreto_se_deriva_aunque_haya_respuesta` |
| CP15.5 | Reclamo | «quiero devolverlo porque vino fallado» | Deriva el reclamo, sin la política de cambios | `test_un_reclamo_no_se_responde_con_la_politica_de_cambios` |
| CP15.6 | Con la consulta derivada | Factura después de una consulta de producto | Responde la factura y sigue derivada | `test_con_la_consulta_derivada_sigue_respondiendo_las_respuestas_propias` |
| CP15.7 | Sin respuesta propia | «¿hacen factura?», «Hola, ¿hacen factura A?» | Deriva la pregunta (el saludo no la tapa) | `test_sin_respuesta_propia_la_pregunta_se_deriva` |
| CP15.8 | Validaciones | Título vacío o repetido; palabras de envíos, pagos, reclamos, saludos, precio o localidades; respuesta vacía, larga o con enlaces a otros sitios | Mensaje que explica el motivo; no se guarda | `test_validaciones`, `test_titulo_y_palabras_no_se_repiten_entre_respuestas`, `test_enlaces_solo_al_catalogo_del_comercio` |
| CP15.9 | Alta, edición, desactivación y baja | Formulario del panel | Se guarda desde una plantilla, se edita, se desactiva (el bot no la usa) y se elimina (la consulta queda en el historial) | `test_alta_desde_plantilla_edicion_y_baja`, `test_el_bot_usa_la_respuesta_guardada_y_mide_su_uso` |
| CP15.10 | Probar antes de guardar | Mensaje de ejemplo con el formulario sin guardar | Indica si el bot usaría la respuesta o qué haría; no guarda nada | `test_probar_una_respuesta_sin_guardarla` |
| CP15.11 | Uso y sugerencias | Consultas derivadas con «por mayor» | Sugiere la plantilla de ventas por mayor; los reclamos no cuentan; cuenta los usos de cada respuesta | `test_sugerencias_a_partir_de_las_consultas_derivadas`, `test_el_bot_usa_la_respuesta_guardada_y_mide_su_uso` |
| CP15.12 | RF13 | Respuesta de otro comercio | 404 al editar, eliminar, cambiar el estado o probar | `test_no_se_accede_a_respuestas_de_otro_comercio` |

### Seguridad del canal, abuso y métricas (#6, #7, #11)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CPS.1 | Tarjetas | Números de prueba de Visa, Mastercard y Amex; teléfono con 54 9; CBU | Solo las tarjetas válidas se detectan | `test_tarjetas_por_luhn_y_largo` |
| CPS.2 | Datos ocultos | Tarjeta con vencimiento y CVV, claves, código de verificación; código postal y de pedido | Se ocultan los datos sensibles y nada más | `test_ocultar_datos_sensibles`, `test_los_datos_de_tarjeta_no_se_guardan` |
| CPS.3 | Tarjeta en el chat | «mi tarjeta es 4509…» | Advierte, no repite el número y deriva con la alerta | `test_tarjeta_advierte_deriva_con_alerta_y_no_repite_el_numero` |
| CPS.4 | Estafas | Pedido de código, suplantación, devolución a otra cuenta, datos de otros clientes, clave, alias y teléfono ajenos | Advertencia y alerta registrada según el caso | `test_advertencias_registran_la_alerta` |
| CPS.5 | Verificación | Alias y teléfono propios y ajenos | Confirma los propios; ante uno ajeno avisa y muestra los datos reales | `test_verificacion_positiva_de_alias_y_telefono`, `test_alias_ajeno_muestra_los_datos_reales_y_sigue_con_el_pago_informado` |
| CPS.6 | Aviso en las respuestas | Medios de pago y contacto | «Pagá solo a estos datos» y aviso de número único | `test_medios_de_pago_y_contacto_llevan_el_aviso_de_seguridad` |
| CPS.7 | Pagos | «¿te llegó el pago?» | Nunca lo confirma: lo deriva | `test_el_bot_nunca_confirma_un_pago` |
| CPS.8 | Spam | Phishing | Respuesta de alcance, sin consulta y 24 horas sin responder | `test_spam_responde_el_alcance_y_silencia_un_dia` |
| CPS.9 | Insultos | Dos insultos y después una consulta | Límite, silencio de 12 horas y la consulta levanta la pausa | `test_insultos_limite_y_despues_silencio`, `test_insulto_con_consulta_se_atiende` |
| CPS.10 | Ráfagas | 12 mensajes en medio minuto | Una advertencia y silencio; los mensajes se guardan | `test_rafaga_una_advertencia_y_pausa_breve`, `test_rafaga_de_mensajes_desde_whatsapp` |
| CPS.11 | Bloqueo | Bloquear y desbloquear desde el panel; otro comercio | Sin respuestas ni consultas; pendientes atendidos; 404 para otro comercio | `test_numero_bloqueado_no_recibe_respuesta_ni_genera_consultas`, `test_bloqueo_de_otro_comercio_no_es_accesible` |
| CPS.12 | Consultas repetidas | La misma pregunta dos veces en pocos minutos | Se registra una sola consulta | `test_la_misma_consulta_resuelta_no_se_cuenta_dos_veces` |
| CPS.13 | Fuera de horario | Se cambia el horario después de la consulta | El resumen no cambia | `test_fuera_de_horario_se_guarda_al_llegar` |
| CPS.14 | Resumen | Alerta, reclamo y producto pendientes | Alertas primero, bloque de alertas y sin datos de tarjeta a la vista | `test_resumen_muestra_las_alertas_y_las_prioriza` |

### Seguimiento de pendientes, cuenta e historial (#8, #9, #10)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CPP.1 | Prioridad | Producto, pago informado, dos reclamos y una tarjeta | Alerta, reclamos del más antiguo al más nuevo, pago y producto | `test_pendientes_por_prioridad_y_antiguedad` |
| CPP.2 | Mensaje sugerido | Reclamo de Lucía; alerta de tarjeta | `wa.me` con saludo, motivo y cita; ofrecimiento de link de pago | `test_responder_por_whatsapp_con_mensaje_sugerido` |
| CPP.3 | Aviso en vivo | Consulta nueva con el panel abierto | El estado informa la cantidad y la más reciente | `test_estado_de_pendientes_para_el_aviso_en_vivo` |
| CPP.4 | Aviso por correo | Tres derivaciones en 45 minutos con los avisos activados | Dos correos (uno por intervalo), con enlace al panel | `test_aviso_por_correo_con_maximo_por_intervalo`, `test_sin_avisos_activados_no_se_manda_correo` |
| CPP.5 | Falla del correo | El servidor no responde | El bot responde y la consulta queda pendiente igual | `test_una_falla_del_correo_no_afecta_al_bot` |
| CPP.6 | Envío de correos | Modo archivo, SMTP y sin servidor | `.eml` guardado, envío en segundo plano, error registrado | `test_modo_archivo_guarda_un_eml`, `test_modo_smtp_envia_en_segundo_plano`, `test_una_falla_de_smtp_queda_registrada` |
| CPP.7 | Cambio de contraseña | Actual incorrecta, corta, distintas, igual a la actual; válida | Mensaje según el caso; con la válida se ingresa con la nueva | `test_cambio_de_contrasena_con_errores`, `test_cambio_de_contrasena` |
| CPP.8 | Recuperación | Pedido, enlace, contraseña nueva, enlace reutilizado | Correo con enlace de 60 minutos, una sola vez, desbloquea el ingreso | `test_recuperacion_de_contrasena_por_correo` |
| CPP.9 | Recuperación segura | Correo inexistente, reenvíos, enlace alterado, correo sin configurar | Misma respuesta, un correo cada 5 minutos, enlace rechazado, aviso de no disponible | `test_recuperacion_no_revela_cuentas_y_limita_reenvios`, `test_enlace_de_recuperacion_alterado`, `test_recuperacion_sin_correo_configurado` |
| CPP.10 | Ayuda y vista previa | Página de ayuda; resumen del onboarding | Ayuda accesible; tres respuestas del bot con los datos cargados | `test_ayuda_y_enlace_de_recuperacion`, `test_vista_previa_del_bot_en_el_onboarding` |
| CPP.11 | Búsqueda | Nombre, teléfono, texto del mensaje, sin resultados | Las consultas que corresponden | `test_busqueda_en_el_historial` |
| CPP.12 | Exportación | CSV filtrado por tema; celdas con fórmulas | Archivo con encabezado y filas filtradas; fórmulas escapadas | `test_exportacion_csv_con_filtros`, `test_exportacion_no_permite_formulas` |

### Seguridad web y operación (#12, #13)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CPW.1 | Encabezados | Cualquier página; la misma por HTTPS | CSP sin scripts en línea, sin marcos, `nosniff`; HSTS solo por HTTPS | `test_encabezados_de_seguridad_en_paginas_publicas`, `test_hsts_solo_por_https` |
| CPW.2 | Sin código en línea | Las páginas públicas y las del panel | Ningún `<script>` sin archivo ni atributo `on…` | `test_paginas_publicas_sin_scripts_ni_manejadores_en_linea`, `test_paginas_del_panel_sin_scripts_ni_manejadores_en_linea` |
| CPW.3 | Caché del panel | Página del panel con sesión | `Cache-Control: no-store` | `test_el_panel_no_se_guarda_en_cache` |
| CPW.4 | Cookies y sesiones | Ingreso con HTTPS; cambio de contraseña con dos sesiones | Cookie `Secure`; la otra sesión se cierra | `test_cookie_de_sesion_segura_con_https`, `test_cambiar_la_contrasena_cierra_las_otras_sesiones` |
| CPW.5 | Límites por IP | 21 ingresos, 6 registros, 6 recuperaciones, 41 mensajes del simulador | 429 con `Retry-After`; otra IP sigue pudiendo | `test_limite_de_ingresos_por_ip`, `test_limite_de_registros_y_recuperaciones`, `test_limite_del_simulador_responde_json` |
| CPW.6 | Simulador y datos reales | Historial del simulador con un número real | Lista vacía | `test_el_historial_del_simulador_solo_admite_numeros_de_prueba` |
| CPO.1 | Leído y entrega | Mensaje entrante; estados «read» y luego «delivered» | Marcado como leído; la respuesta queda «Leído» | `test_el_webhook_marca_leido_y_guarda_el_id_de_cada_respuesta`, `test_estados_de_entrega_en_cualquier_orden` |
| CPO.2 | Falla de entrega | Estado «failed»; error al enviar | Advertencia en el registro con el número abreviado; «No entregado» en el detalle | `test_falla_de_entrega_queda_registrada_y_se_ve_en_el_panel`, `test_error_al_enviar_marca_la_respuesta_como_no_entregada` |
| CPO.3 | Firma obligatoria | Webhook sin `WHATSAPP_APP_SECRET` | 401, salvo permiso explícito para pruebas | `test_sin_clave_secreta_el_webhook_rechaza_salvo_permiso_explicito` |
| CPO.4 | Retención | Conversaciones de hace 400 días (resuelta y pendiente) y de hace 10 | Se borra la resuelta; se conservan la pendiente con sus mensajes y la reciente | `test_depurar_borra_lo_viejo_y_conserva_lo_pendiente`, `test_depuracion_automatica_una_vez_por_dia` |
| CPO.5 | Supresión | Pedido de borrar los datos de un comprador | Se borran sus conversaciones con un comercio o con todos | `test_borrar_datos_de_un_comprador_con_un_comercio_o_con_todos`, `test_admin_borrar_comprador` |
| CPO.6 | Administración | Restablecer, desbloquear, pausar, activar, respaldar | Cada comando cumple y valida los datos | `test_admin_restablecer_clave_generada`, `test_admin_desbloquear`, `test_admin_pausar_y_activar`, `test_admin_respaldar` |
| CPO.7 | Configuración | Línea configurada sin clave, simulador abierto, correo sin servidor | Errores y avisos al iniciar; `admin verificar` sale con código 1 | `test_configuracion_insegura_se_informa`, `test_se_informa_al_iniciar_fuera_de_las_pruebas` |

### Privacidad y datos personales (#14)

| ID | Caso | Entrada | Resultado esperado | Prueba |
|---|---|---|---|---|
| CPV.1 | Política y términos | `/privacidad`, `/terminos` y los pies de las páginas públicas | Leyendas de la Ley 25.326, plazo de retención, contacto configurado y enlaces cruzados | `test_politica_de_privacidad`, `test_terminos_de_uso`, `test_contacto_y_plazo_configurables`, `test_enlaces_legales_en_las_paginas_publicas` |
| CPV.2 | Consentimiento | Registro sin marcar la aceptación; con la aceptación | Error que conserva los datos; cuenta creada con la fecha de aceptación | `test_cu01_registro_exige_aceptar_los_terminos`, `test_registro_guarda_la_aceptacion` |
| CPV.3 | Pregunta por los datos | «¿qué hacen con mis datos?» | Respuesta con lo que se guarda, el plazo y cómo pedir el borrado; sin consulta | `test_el_bot_explica_que_se_hace_con_los_datos`, `test_la_respuesta_incluye_el_plazo_y_el_enlace_si_estan_configurados` |
| CPV.4 | Pedido de borrado | «borren mis datos», con otra consulta, durante una derivación y en pausa | Derivación con tema Datos personales, sin duplicar | `test_pedido_de_borrar_los_datos_se_deriva`, `test_pedido_de_borrado_durante_una_derivacion_no_se_duplica`, `test_pedido_de_borrado_se_atiende_aunque_el_bot_este_en_pausa` |
| CPV.5 | Frases parecidas | «te paso mis datos para el envío», «necesito tus datos para transferir» | Envío y medios de pago, sin respuesta de privacidad | `test_frases_parecidas_que_no_son_de_privacidad` |
| CPV.6 | Supresión desde el panel | Detalle de la consulta, confirmación y borrado | Se borran las conversaciones con ese comercio; las de otro comercio y el bloqueo se conservan | `test_el_comercio_borra_los_datos_del_comprador`, `test_borrar_conserva_el_bloqueo`, `test_no_se_borran_datos_de_otro_comercio` |
| CPV.7 | Baja de un comercio | `admin borrar-comercio` | Se borran el comercio, su usuario, sus conversaciones y los números que solo le escribieron a él | `test_admin_borrar_comercio` |

### Requerimientos transversales

| ID | Requerimiento | Resultado esperado | Prueba |
|---|---|---|---|
| CPT.1 | RF13 Aislamiento | Un comercio no puede ver ni modificar zonas, medios ni consultas de otro (404) | `test_un_comercio_no_accede_a_registros_de_otro`, `test_listados_muestran_solo_lo_propio` |
| CPT.2 | RNF03 CSRF | Formularios sin token rechazados; con token aceptados | `test_formularios_sin_token_se_rechazan`, `test_formulario_con_token_funciona` |
| CPT.3 | RNF01 Webhook | Verificación con token, firma obligatoria, respuesta por la Graph API, eventos repetidos descartados | `test_verificacion_del_webhook`, `test_firma_invalida_se_rechaza`, `test_mensaje_entrante_se_atiende_y_se_responde_por_la_api` |
| CPT.4 | Números argentinos | 549 se envía como 54 en modo de prueba | `test_numero_argentino_sin_el_9_para_enviar` |
| CPT.6 | Botones de WhatsApp | Mensaje interactivo con el formato de la Graph API; si lo rechaza, se envía como texto con la instrucción | `test_envio_con_botones_por_graph_api`, `test_si_whatsapp_rechaza_los_botones_se_envia_texto`, `test_boton_tocado_en_whatsapp_llega_al_bot` |
| CPT.7 | Migraciones | Una base de la versión 0.1 se actualiza sin perder datos; iniciar dos veces no duplica nada | `test_base_de_la_version_0_1_se_actualiza`, `test_los_pasos_son_idempotentes` |
| CPT.8 | Comprensión | Ningún mensaje de los temas implementados falla en los corpus | `test_corpus_de_desarrollo`, `test_corpus_de_validacion`, `test_informe_de_exactitud` |
| CPT.5 | RF06 Inactividad | Conversación cerrada a las 24 horas; el comprador retoma con el mismo comercio | `test_inactividad_cierra_la_conversacion_y_el_comprador_retoma_sin_codigo` |

## Guion de aceptación (demo)

Escenario base para la presentación, con los datos de demostración (`iniciar.bat` o `flask --app app demo --si`).
Conviene tener dos ventanas: el panel y el simulador.

1. **Comercio nuevo (CU01, CU03).** Crear la cuenta «Deco Norte». Cargar una zona a mano e importar una planilla con
   una fila errónea para mostrar la vista previa. Agregar dos medios de pago y un horario con jornada partida.
2. **Prueba y activación (CU07).** En el chat de prueba escribir «¿Hacen envíos a Salta?», «¿y cuánto sale?» y
   «¿Tienen almohadones?» (aparece el aviso de derivación). Activar el bot y mostrar código, enlace, QR y cartel.
   Probar «¿este alias es de ustedes? lucas.ventas.mp» para mostrar la verificación de datos de pago.
3. **Comprador (CU08 a CU12).** En el simulador, «Abrir su enlace» de Deco Norte y enviar. Tocar el botón «Envíos»,
   escribir una ciudad, preguntar «¿aceptan naranja?» y «¿abren el sábado?», y una consulta de producto. Mostrar que
   el bot sigue respondiendo envíos con la consulta derivada y que a otro mensaje le responde un solo recordatorio.
4. **Línea compartida.** Con el mismo comprador, abrir el enlace de Casa & Detalles: la conversación pasa al otro
   comercio con sus propios datos.
5. **Seguimiento (CU13, CU14).** Volver al panel de Deco Norte: la consulta aparece pendiente. «Marcar como atendida»
   y comprobar en el simulador que el bot vuelve a responder. Abrir el historial y la conversación completa.
6. **Respuestas propias (CU15).** En **Respuestas frecuentes**, usar la plantilla de factura, cambiar el texto y probar
   «¿hacen factura A?» antes de guardar. Intentar agregar la palabra «envío» para mostrar la validación. Guardar y
   repetir la pregunta en el simulador: ahora la responde el bot.
7. **Datos con historia.** Ingresar como Casa & Detalles para mostrar el resumen con tres semanas de actividad y el
   porcentaje de consultas fuera de horario. Ingresar como Mundo Textil para mostrar las sugerencias de respuestas
   propias a partir de sus consultas derivadas.
