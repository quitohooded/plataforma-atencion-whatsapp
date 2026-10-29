# Configuración de WhatsApp Business Platform (Cloud API)

El prototipo funciona completo con el simulador (`/simulador`). Esta guía explica cómo conectarlo a WhatsApp real con
el **número de prueba que provee Meta**, tal como se previó en el apartado 6.1.2 del informe. Se hace una sola vez y
lleva unos 30 minutos. Meta cambia sus pantallas con frecuencia: los nombres de los menús pueden variar levemente.

## Qué se necesita

- Una cuenta de Facebook para ingresar a [Meta for Developers](https://developers.facebook.com/).
- El prototipo corriendo en la computadora (`iniciar.bat` o `python serve.py`).
- Un túnel HTTPS para que Meta llegue a la computadora: [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/)
  (gratuito, sin cuenta) o [ngrok](https://ngrok.com/download).
- Hasta cinco celulares con WhatsApp para probar como compradores (límite del número de prueba).

## 1. Crear la app en Meta

1. En Meta for Developers, **Mis apps > Crear app**.
2. Elegir el caso de uso para conectar con clientes por WhatsApp (o «Otro» y luego tipo **Negocio**).
3. Agregar el producto **WhatsApp** y entrar a **Configuración de la API** (API Setup).

En esa pantalla Meta muestra:

| Dato en Meta | Variable del `.env` |
|---|---|
| Token de acceso temporal (dura 24 horas) | `WHATSAPP_TOKEN` |
| Identificador del número de teléfono (Phone number ID) | `WHATSAPP_PHONE_NUMBER_ID` |
| Número de prueba (desde), por ejemplo +1 555 012 3456 | `WHATSAPP_NUMERO_PUBLICO` (solo dígitos: `15550123456`) |

4. En **Para** (To), elegir **Administrar lista de números** y agregar los celulares que van a probar. Cada uno recibe
   un código por WhatsApp para confirmarlo.
5. En **Configuración de la app > Básica**, copiar la **Clave secreta de la app** en `WHATSAPP_APP_SECRET`.

## 2. Completar el `.env`

```ini
WHATSAPP_TOKEN=EAAG...            # token temporal o permanente
WHATSAPP_PHONE_NUMBER_ID=1234567890
WHATSAPP_NUMERO_PUBLICO=15550123456
WHATSAPP_APP_SECRET=abcdef0123456789
WHATSAPP_VERIFY_TOKEN=un-texto-secreto-para-verificar-el-webhook
WHATSAPP_API_VERSION=v23.0
WHATSAPP_AR_QUITAR_9=true
CONFIAR_EN_PROXY=true
```

`WHATSAPP_VERIFY_TOKEN` es un texto libre que se repite en Meta en el paso 4. Reiniciar el servidor después de editar
el archivo.

## 3. Exponer el servidor con un túnel

Con el servidor corriendo en el puerto 5000, en otra ventana:

```bash
cloudflared tunnel --url http://localhost:5000
# o bien
ngrok http 5000
```

El comando muestra una dirección pública HTTPS, por ejemplo `https://palabras-al-azar.trycloudflare.com`. La URL del
webhook es esa dirección más `/webhook/whatsapp`. Con cloudflared gratuito la dirección cambia cada vez que se inicia
el túnel; en ese caso hay que actualizarla en Meta.

## 4. Registrar el webhook en Meta

1. En el producto WhatsApp, **Configuración > Webhook > Editar**.
2. **URL de devolución de llamada**: `https://<dirección-del-túnel>/webhook/whatsapp`.
3. **Token de verificación**: el mismo valor de `WHATSAPP_VERIFY_TOKEN`.
4. **Verificar y guardar**. En la consola del servidor aparece «Webhook de WhatsApp verificado».
5. En **Campos del webhook**, suscribirse a **messages** (trae los mensajes y también los estados de entrega de las
   respuestas: enviado, entregado, leído o no entregado).
6. En **Configuración de la app > Básica**, cargar la **URL de la política de privacidad**
   (`https://<dirección-pública>/privacidad`) y la de los **términos del servicio** (`…/terminos`). Meta las pide para
   pasar la app a modo activo.

## 5. Probar

1. Ingresar al panel con un comercio activo (por ejemplo `demo@casaydetalles.com.ar` / `demo1234`).
2. En **Activación del bot**, el enlace ya apunta a `wa.me/<número de prueba>` con el código del comercio.
3. Desde uno de los celulares registrados, abrir el enlace (o escanear el QR) y enviar el mensaje propuesto.
4. El bot responde con la bienvenida. Probar «¿Hacen envíos a Río Cuarto?», luego «5800», «¿Aceptan Mercado Pago?» y
   una pregunta fuera de tema para ver la derivación en el resumen del panel.

## Token permanente (opcional)

El token temporal vence a las 24 horas. Para una demo de varios días conviene uno permanente:
**Configuración del negocio > Usuarios del sistema > Agregar**, asignarle la app y el activo de WhatsApp, y generar un
token con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.

## Números de Argentina

WhatsApp informa los celulares argentinos con el 9 después del 54 (`549 351 ...`), pero el número de prueba solo envía
si el destino va sin ese 9 (`54 351 ...`). Con `WHATSAPP_AR_QUITAR_9=true` el sistema lo corrige al responder. Si con
un número real de producción los envíos fallan, probar con `false`.

## Problemas frecuentes

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| Meta no verifica el webhook | El token no coincide o el túnel no está activo | Revisar `WHATSAPP_VERIFY_TOKEN` y abrir la URL del túnel en el navegador |
| Llegan mensajes pero el bot no contesta y el log dice 131030 | El celular no está en la lista de destinatarios | Agregarlo en **Para > Administrar lista de números** |
| El log dice «firma inválida» (401) | `WHATSAPP_APP_SECRET` incorrecto | Copiar de nuevo la clave secreta de la app |
| El log dice que el token venció (código 190) | Token temporal de más de 24 horas | Generar uno nuevo o usar un token permanente |
| No llega ningún evento | Falta la suscripción al campo `messages` | Suscribirse en **Campos del webhook** |
| El comprador recibe «necesito saber con qué comercio…» | El primer mensaje no incluyó el código | Usar el enlace del panel, que lo agrega |

Sin `WHATSAPP_TOKEN` el sistema queda en «modo sin envío»: procesa los mensajes, los guarda y escribe las respuestas
en la consola en lugar de enviarlas. Es útil para verificar el webhook antes de tener el token.
