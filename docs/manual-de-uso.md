# Manual de uso del panel de administración

Este manual está dirigido al responsable del comercio. Explica cómo registrarse, cargar la información con la que
responde el bot, activarlo y hacer el seguimiento de las consultas. No requiere conocimientos técnicos.

## 1. Crear la cuenta

1. Ingrese a la página de la plataforma y elija **Crear cuenta**.
2. Complete el nombre del comercio, el rubro, un teléfono de contacto, su correo electrónico y una contraseña de al
   menos ocho caracteres.
3. Elija **Crear cuenta**. La sesión queda iniciada y el sistema lo lleva al primer paso de la configuración.

El teléfono de contacto es el número desde el que su equipo responde las consultas que el bot no puede resolver. El
bot se lo indica al comprador en esos casos.

![Registro](capturas/02-registro.png)

## 2. Configurar el comercio (cuatro pasos)

La configuración se hace una sola vez, en cuatro pasos. Si la interrumpe, la próxima vez que ingrese el sistema
retoma desde el paso pendiente. Puede volver a un paso anterior con **Volver** o con el nombre del paso en la parte
superior.

**Paso 1. Datos del negocio.** Revise los datos del registro y elija **Confirmar y continuar**.

**Paso 2. Zonas de envío.** Cargue cada rango de códigos postales al que despacha, con el plazo mínimo y máximo de
entrega en días hábiles. Por ejemplo: «Córdoba Capital», del 5000 al 5099, de 1 a 2 días. Dos zonas no pueden
compartir códigos postales.

Si ya tiene las zonas en una planilla:
1. Elija **Descargar plantilla** y complétela en Excel, una zona por fila.
2. Guárdela como CSV y elíjala con **Importar planilla**.
3. El sistema muestra las filas válidas y las observadas, con el motivo. Elija **Incorporar** para sumar las válidas.

![Zonas de envío](capturas/05-onboarding-2-zonas.png)

**Paso 3. Medios de pago.** Elija cada medio de la lista y, si quiere, agregue un detalle: el alias para
transferencias, las cuotas disponibles o las billeteras que acepta. Con **Otro** puede nombrar un medio que no está en
la lista.

**Paso 4. Horarios de atención.** Marque los días que atiende e indique el horario. Si hace jornada partida, use
**Agregar franja** para sumar el horario de la tarde. **Copiar a los días hábiles** repite el horario de un día de
lunes a viernes.

**Revisar y confirmar.** El sistema muestra todo lo cargado. Elija **Confirmar e ir a la activación**.

## 3. Probar y activar el bot

En **Activación del bot** hay un chat de prueba que responde con la información de su comercio. Escriba como si fuera
un comprador, por ejemplo «¿Hacen envíos a Río Cuarto?». Lo que escriba en este chat no se registra.

Si una respuesta tiene un dato incorrecto, corríjalo en la sección correspondiente y vuelva a probar.

Cuando las respuestas sean correctas, elija **Activar bot**. El sistema genera:

- el **código de su comercio**, por ejemplo `CASA26`;
- el **enlace de acceso** a la línea de WhatsApp de la plataforma, que ya incluye el código;
- un **código QR** y un **cartel para imprimir**.

![Activación](capturas/11-activacion-enlace-y-qr.png)

## 4. Compartir el enlace

Publique el enlace en la biografía de Instagram, en su catálogo o en sus estados de WhatsApp. Cuando un comprador lo
abre, WhatsApp le propone un primer mensaje con el código: así la línea compartida sabe que la consulta es para su
comercio. El cartel imprimible sirve para pegar en el depósito o en los paquetes.

## 5. Seguimiento diario

**Resumen.** Es la pantalla inicial. Muestra, para el período elegido, cuántas consultas recibió el bot, cuántas
resolvió sin intervención, cuántas llegaron con el comercio cerrado y cómo se reparten por tema.

**Consultas pendientes.** Son las que el bot no pudo resolver: una pregunta fuera de los tres temas, un código postal
sin zona cargada o un dato que falta. Para cada una:

1. Elija **Responder por WhatsApp**: se abre la conversación con el comprador en su WhatsApp habitual.
2. Cuando la haya respondido, elija **Marcar como atendida**. La consulta sale del listado y el bot vuelve a atender
   a ese comprador.

Mientras una consulta está pendiente, el bot no responde los mensajes de ese comprador para no interferir con su
respuesta.

![Resumen](capturas/13-resumen-y-pendientes.png)

**Historial de consultas.** Lista todas las consultas, de la más reciente a la más antigua. Puede filtrar por fechas,
tema y resultado, y abrir cada una para ver la conversación completa.

## 6. Mantener la información actualizada

Las secciones **Zonas de envío**, **Medios de pago**, **Horarios** y **Datos del negocio** permiten modificar la
información en cualquier momento. El bot usa los cambios desde la siguiente consulta.

Un medio de pago **desactivado** se conserva en el listado, pero el bot deja de informarlo. Sirve, por ejemplo, para
suspender el pago en efectivo durante las vacaciones.

## 7. Pausar el bot

En **Activación del bot**, **Pausar** detiene la atención automática. Quienes escriban reciben un aviso con el
teléfono de contacto del comercio. **Reactivar bot** vuelve a encenderlo con el mismo código y el mismo enlace.

## Preguntas frecuentes

**¿Qué consultas responde el bot?** Envíos y plazos según el código postal, medios de pago y horarios de atención.

**¿Qué pasa con las demás preguntas?** El bot avisa al comprador que una persona del comercio le va a responder y la
consulta queda pendiente en el resumen.

**¿Tengo que tramitar algo con WhatsApp?** No. La línea la provee la plataforma.

**¿Otro comercio puede ver mis datos?** No. Cada comercio ve solamente su información y sus consultas.

**Olvidé la contraseña.** En esta versión del prototipo no hay recuperación automática; la restablece el administrador
de la plataforma.
