# Evaluación del bot

Cómo se mide si el bot entiende y responde bien, y qué resultados da. Es material para el apartado de verificación y
validación (V&V) del informe.

## Método

El bot no usa procesamiento de lenguaje natural (alcance del informe): identifica la intención con reglas
deterministas sobre palabras clave (ver `docs/arquitectura.md`, «Cómo entiende el bot un mensaje»). Para saber si esas
reglas alcanzan en el mundo real se mide contra mensajes escritos como los escriben los compradores por WhatsApp.

1. **Corpus de desarrollo** (`tests/corpus/mensajes.py`). 240 mensajes y 28 diálogos de varios pasos, armados con el
   vocabulario relevado en la elicitación y con casos difíciles: errores de tipeo, abreviaturas, jerga rioplatense,
   varias preguntas juntas, mensajes ambiguos, estafas, spam e insultos. Con este corpus se construyó y ajustó el
   vocabulario.
2. **Corpus de validación** (`tests/corpus/validacion.py`). 139 mensajes y 6 diálogos redactados después y por
   separado, con otras formas de preguntar lo mismo. Mide si el bot generaliza o si solo aprendió los ejemplos.
3. **Comercio de evaluación.** Los mensajes se responden con los datos de Casa & Detalles, los mismos de la
   demostración (`app/datos/casa_y_detalles.py`), un martes a las 22:30 (fuera del horario de atención).
4. **Resultado esperado.** Cada mensaje tiene la acción que el bot debe tomar: responder un tema (`ENVIO`, `PAGO`,
   `HORARIO`, `CONTACTO`, `CATALOGO`), pedir el código postal (`ENVIO?`), derivar con un tema (`D:RECLAMOS`), saludar,
   pedir una aclaración, etc. El motor devuelve la lista de acciones que tomó y se compara con la esperada; varias
   acciones deben coincidir todas (`ENVIO+PAGO`).

Cada mensaje es una prueba automatizada (`tests/test_corpus.py`): si un cambio hace que el bot deje de entender algo
que entendía, la verificación (`scripts/verificar.py`) falla. Los temas que todavía no se implementaron están marcados como fallas
esperadas estrictas, que avisan cuando el bot empieza a resolverlos.

Para ver el informe actualizado:

```bash
python scripts/evaluar_bot.py            # exactitud por categoría de ambos corpus
python scripts/evaluar_bot.py --fallos   # además, cada mensaje que no se resolvió como se esperaba
```

## Línea de base (versión 0.1)

Con el bot de la Entrega 3 (tres temas, coincidencia exacta de palabras), la exactitud sobre los 215 mensajes
originales del corpus fue **36,3 %**. Detalle en `docs/revision-por-perfiles.md`.

## Versión 1.0, comprensión (issues #1 a #4)

| Medición | Resultado |
|---|---|
| Corpus de desarrollo, mensajes de los temas implementados | 100 % (205 de 205) |
| Corpus de desarrollo, diálogos de los temas implementados | 100 % (26 de 26) |
| Los 215 mensajes de la línea de base | 83,7 % (36,3 % en la versión 0.1) |
| Corpus de validación, **primera corrida, antes de cualquier ajuste** | **88,5 % (123 de 139); diálogos 5 de 6** |
| Corpus de validación después de los ajustes | 100 % (139 de 139); diálogos 6 de 6 |

Los mensajes que todavía no se resuelven son los de temas que llegan en issues siguientes: respuestas propias del
comercio (cambios, factura, retiro, ventas por mayor, #5), seguridad y estafas (#6), y spam e insultos (#7). Por eso
el total del corpus de desarrollo es 85,4 % (205 de 240).

### Qué falló en la validación y cómo se corrigió

La primera corrida del corpus de validación es la medida honesta de cómo el bot enfrenta mensajes que nunca vio. Los
16 mensajes que falló mostraron problemas generales, no casos aislados, y cada corrección se hizo sobre la regla, no
sobre el mensaje:

| Problema | Ejemplo | Corrección |
|---|---|---|
| El precio en otra oración no se asociaba al envío | «¿Mandan a Ushuaia? ¿Cuánto sale?» derivaba como pregunta de precio | Una oración que solo pregunta un precio, en un mensaje sobre envíos o justo después de una respuesta de envío, pregunta el costo del envío |
| «Un pedido» genérico se leía como un pedido ya hecho | «cuánto tarda en llegar un pedido a Bahía Blanca» | «Un pedido» pesa poco; «mi pedido» o «hice un pedido» siguen siendo pedidos realizados |
| La búsqueda de frases de izquierda a derecha perdía frases largas | «el número de seguimiento» se leía como contacto | Se elige la combinación de frases que más palabras cubre (programación dinámica) |
| Daños que no estaban en el vocabulario | «me llegó el mantel manchado», «vino astillada», «llegó incompleto» | Se sumaron los adjetivos de daño y faltantes como reclamo |
| Formas de pedir una persona | «que me atienda una persona real», «me podés pasar con un vendedor» | Se sumaron las construcciones con «atender» y «pasar con» |
| Un reclamo y un pedido del mismo mensaje se registraban como dos consultas | «hice una compra el viernes y no me llegó el mail» | Reclamo, pago informado y pedido de un mismo mensaje hablan de lo mismo: queda el más importante |
| «No sé mi código postal» no contaba como intento | La conversación nunca derivaba | En la espera del código postal, «no sé» cuenta como intento aunque nombre el código postal |
| Verbos y colores sin cubrir | «estan atendiendo?», «lo tenés en blanco?», «a qué número los puedo llamar?» | Se sumaron al vocabulario |

## Revisión con los datos de la demostración

Además del corpus, se leyeron las conversaciones que genera la demostración (tres semanas de actividad simulada)
desde el punto de vista del comprador. Eso encontró problemas que el corpus no mide porque la acción era correcta pero
el texto no:

- «¿Se puede pagar con tarjeta en cuotas?» respondía que las cuotas no estaban entre los medios de pago aunque el
  detalle decía «hasta 3 cuotas sin interés».
- «¿Y cuánto sale?» repetía el plazo completo en lugar de responder el costo.
- «¿Aceptan Naranja?» respondía que no había dato aunque el comercio había cargado «Visa y Mastercard»: si el
  comercio nombra las marcas, la que falta no se acepta.
- Después de pedir el número de pedido, la respuesta del comprador recibía un recordatorio genérico; ahora se le
  agradece y se le confirma que se sumó a su consulta.

## Próximas mediciones

- Al cerrar los issues #5 a #7, el corpus de desarrollo completo debe llegar al 100 %.
- Antes de la versión 1.0.0 se escribe un tercer corpus a ciegas y se informa su primera corrida sin ajustes.
- Con la línea real, los mensajes que el bot no entendió quedan en el historial del comercio: son la fuente para
  ampliar el vocabulario con `flask palabras agregar`.
