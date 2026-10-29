# Despliegue y operación

Cómo publicar la plataforma sin costo, cómo administrarla desde la consola y qué tareas de mantenimiento tiene. La
conexión con Meta se explica en [configuracion-whatsapp.md](configuracion-whatsapp.md).

## Dónde publicarla sin costo

| Opción | Costo | A favor | En contra |
|---|---|---|---|
| Computadora propia con túnel de Cloudflare | Gratis, sin cuenta | Lo más simple para una demostración; la base queda en la computadora | La computadora tiene que estar encendida; la dirección del túnel rápido cambia cada vez que se inicia y hay que actualizarla en Meta |
| PythonAnywhere (cuenta gratuita) | Gratis | Dirección fija con HTTPS (`usuario.pythonanywhere.com`), disco persistente para SQLite, permite llamar a la API de Meta y usar el SMTP de Gmail | Una sola aplicación web, que hay que renovar cada mes desde el panel; sin tareas programadas en las cuentas nuevas (no hacen falta: la depuración corre dentro de la aplicación) |
| Docker en un equipo o servidor propio | Gratis | Misma imagen en cualquier sistema | Hace falta Docker y, para Meta, una dirección HTTPS (túnel o proxy) |

No conviene un servicio con disco efímero (por ejemplo, el plan gratuito de Render): la base SQLite se pierde cada vez
que el servicio se reinicia o se duerme por inactividad, y además bloquea los puertos de correo.

Condiciones consultadas en octubre de 2026: [Render, plan gratuito](https://render.com/docs/free),
[PythonAnywhere, sitios permitidos](https://www.pythonanywhere.com/whitelist/) y
[SMTP para cuentas gratuitas](https://www.pythonanywhere.com/wiki/SMTPForFreeUsers),
[Cloudflare, túneles rápidos](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/trycloudflare/).
Pueden cambiar: revisarlas antes de elegir.

### Opción 1: computadora propia con túnel

1. Instalar y cargar la demostración como indica el README (`iniciar.bat` en Windows).
2. En `.env`: `SECRET_KEY` con un texto aleatorio largo, `CONFIAR_EN_PROXY=true` (el túnel es un proxy) y, si se van a
   enviar correos, la sección de correo.
3. `python serve.py` y, en otra consola, `cloudflared tunnel --url http://localhost:5000`.
4. Con la dirección que muestra el túnel: `URL_PUBLICA=https://…trycloudflare.com` en `.env`, reiniciar el servidor y
   registrar el webhook en Meta (`…/webhook/whatsapp`).

### Opción 2: PythonAnywhere

1. Crear una cuenta gratuita y abrir una consola Bash.
2. Clonar el repositorio y crear el entorno:

   ```bash
   git clone https://github.com/quitohooded/plataforma-atencion-whatsapp.git
   cd plataforma-atencion-whatsapp
   python3.12 -m venv ~/.virtualenvs/responde
   ~/.virtualenvs/responde/bin/pip install -r requirements.txt
   cp .env.example .env
   ```

3. Completar `.env`: `SECRET_KEY`, `URL_PUBLICA=https://USUARIO.pythonanywhere.com`, `CONFIAR_EN_PROXY=true`,
   `CONTACTO_PLATAFORMA`, las variables de WhatsApp y el correo (`MAIL_MODO=smtp` con `smtp.gmail.com` y una
   contraseña de aplicación). Para mostrar la demostración: `~/.virtualenvs/responde/bin/flask --app app demo --si`.
4. En la pestaña **Web**: *Add a new web app*, *Manual configuration*, Python 3.12. En *Virtualenv*, la ruta
   `~/.virtualenvs/responde`. En *Static files*, la URL `/static/` apunta a
   `/home/USUARIO/plataforma-atencion-whatsapp/app/static`. Activar *Force HTTPS*.
5. Editar el archivo WSGI que ofrece la pestaña y dejar solo:

   ```python
   import sys

   RUTA = "/home/USUARIO/plataforma-atencion-whatsapp"
   if RUTA not in sys.path:
       sys.path.insert(0, RUTA)

   from wsgi import app as application  # noqa: E402
   ```

6. *Reload* y abrir `https://USUARIO.pythonanywhere.com/salud`: debe responder `{"base": "ok", "estado": "ok"}`.
7. Revisar la configuración en la consola: `~/.virtualenvs/responde/bin/flask --app app admin verificar`.
8. Una vez por mes, en la pestaña **Web**, el botón para extender la aplicación otro mes.

### Opción 3: Docker

```bash
docker build -t responde .
docker run -d --name responde -p 8000:8000 --env-file .env -v responde-datos:/app/instance responde
docker exec -it responde flask --app app demo --si        # datos de demostración (opcional)
docker exec -it responde flask --app app admin verificar
```

La imagen usa Python 3.12, corre con un usuario sin privilegios, guarda la base, la clave de sesiones, los correos y
los respaldos en el volumen `/app/instance` y se revisa sola con `/salud`.

## Antes de abrirla al público

`flask --app app admin verificar` lista lo que falta o es inseguro. La aplicación también lo escribe en el registro al
iniciar. En un despliegue real:

- `SECRET_KEY` propia, de al menos 32 caracteres.
- `WHATSAPP_APP_SECRET` configurada: sin ella el webhook rechaza todos los eventos, porque no puede comprobar que
  vienen de Meta (`WHATSAPP_PERMITIR_SIN_FIRMA` existe solo para pruebas locales).
- `SIMULADOR_HABILITADO=false`, salvo que se lo use para demostraciones.
- `URL_PUBLICA` con https: activa las cookies seguras y arma bien los enlaces de los correos.
- `CONTACTO_PLATAFORMA`: el correo que muestra la política de privacidad para ejercer los derechos sobre los datos.
- Correo por SMTP, para que lleguen la recuperación de contraseña y los avisos.

## Administración por consola

| Comando | Para qué |
|---|---|
| `flask --app app admin comercios` | Comercios con su estado, código, consultas pendientes y correo (y si el ingreso está bloqueado) |
| `flask --app app admin restablecer-clave CORREO` | Contraseña nueva para un responsable sin acceso a su correo (`--generar` crea una temporal). Levanta el bloqueo y cierra sus sesiones |
| `flask --app app admin desbloquear CORREO` | Levanta el bloqueo de ingreso por intentos fallidos |
| `flask --app app admin pausar CORREO` | Pausa el bot de un comercio (por ejemplo, ante un uso indebido); `admin activar` lo reactiva |
| `flask --app app admin borrar-comprador TELEFONO` | Borra las conversaciones de un comprador que lo pidió, con todos los comercios o con uno (`--comercio`) |
| `flask --app app admin depurar` | Borra ya los datos más antiguos que `RETENCION_DIAS` (o `--dias N`) |
| `flask --app app admin respaldar [DESTINO]` | Copia la base en caliente a `instance/respaldos/` |
| `flask --app app admin verificar` | Revisa la configuración; sale con código 1 si hay errores |

Donde se pide un comercio, sirve su número (la primera columna de `admin comercios`) o el correo de su usuario.

## Mantenimiento

- **Esquema de la base.** Las migraciones se aplican solas al iniciar (`app/migraciones.py`); no hay que correr nada
  después de actualizar el código.
- **Retención de datos.** Una vez por día la aplicación borra los mensajes y las consultas con más de
  `RETENCION_DIAS` días (365 por defecto), las conversaciones que quedan vacías y los números sin conversaciones. Se
  conservan las consultas pendientes con sus mensajes y los números bloqueados. `RETENCION_DIAS=0` lo desactiva.
- **Respaldos.** `admin respaldar` antes de cada actualización y, con un servidor propio, una vez por día con el
  programador de tareas del sistema. El archivo se restaura reemplazando `instance/plataforma.db` con el servidor
  detenido.
- **Monitoreo.** `/salud` responde 200 si la base contesta y 503 si no; sirve para un monitor externo gratuito.
- **Registro.** Las fallas de entrega que informa WhatsApp quedan como advertencias en el registro (con el número
  abreviado) y en el detalle de la conversación del panel. El nivel se cambia con `LOG_LEVEL`.
- **Límites por IP.** Se cuentan en la memoria del proceso: con un solo proceso (waitress o la cuenta gratuita de
  PythonAnywhere) son exactos; con varios, cada uno cuenta por separado.
