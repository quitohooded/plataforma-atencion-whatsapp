# Despliegue en Oracle Cloud (Always Free) con Docker y Caddy

Guía paso a paso para pasar la plataforma desde PythonAnywhere (o desde un entorno local) a una máquina virtual propia
en **Oracle Cloud Infrastructure (OCI)** dentro del nivel **Always Free**, con **Docker Compose**, **Caddy** (certificado
HTTPS de Let's Encrypt renovado solo), respaldos diarios fuera del servidor y monitoreo externo.

Costo: **USD 0**. No requiere cambios en el código de la aplicación.

```
Comprador (WhatsApp) ──► Meta Cloud API ──► HTTPS :443 ──► [ Caddy ] ──► red interna :8000 ──► [ app: Flask + waitress ]
Comercio (navegador) ─────────────────────► HTTPS :443 ──┘                                              │
                                                                                                        ▼
UptimeRobot ──────────────────────────────► /salud                                         volumen responde-datos
                                                                                           (SQLite WAL, clave, respaldos)
                                                                                                        │
                                                                                           cron diario (deploy/respaldar.sh)
                                                                                                        │
                                                                                                        ▼
                                                                                           Google Drive / Object Storage
```

---

## 1. Crear la cuenta de Oracle Cloud

1. Entrar en <https://www.oracle.com/cloud/free/> y crear una cuenta.
2. **Elegir bien la región de origen (*Home Region*):** no se puede cambiar después y los recursos Always Free solo se
   crean ahí. Para Argentina, **Brazil East (São Paulo)** es la de menor latencia; si no hay capacidad de procesadores
   ARM en el nivel gratuito, **Brazil Southeast (Vinhedo)** o **Chile Central (Santiago)** suelen estar menos saturadas.
3. Oracle pide una tarjeta de crédito o débito para verificar la identidad (hace una retención chica y la devuelve).
4. **Recomendado — pasar la cuenta a *Pay As You Go*:** dentro del nivel gratuito puro, Oracle puede apagar las máquinas
   que tengan menos del 20 % de uso durante 7 días seguidos, y además suele faltar capacidad para crear instancias ARM.
   Al pasar a *Pay As You Go* (*Billing → Upgrade and Manage Payment*), los recursos **Always Free siguen siendo
   gratuitos** siempre que no se superen sus límites (4 OCPU, 24 GB de RAM y 200 GB de disco en total).
5. **Obligatorio si se activa *Pay As You Go* — crear una alerta de presupuesto de USD 1:**
   - Ir a **Billing & Cost Management → Cost Management → Budgets → Create Budget**.
   - *Target*: todo el compartimento raíz. *Amount*: `1`.
   - Agregar una regla de alerta (*Budget Alert Rule*) al **1 % del monto real** y otra al **100 % del monto
     proyectado**, con tu correo. Así recibís un aviso inmediato si alguna vez se crea algo fuera del nivel gratuito.

---

## 2. Crear la máquina virtual y abrir los puertos

### 2.1. Crear la instancia

1. Ir a **Compute → Instances → Create instance**.
2. **Name:** `responde`.
3. **Image and shape:**
   - *Image*: **Canonical Ubuntu 24.04** (arquitectura **aarch64 / ARM**).
   - *Shape*: **Ampere** → **`VM.Standard.A1.Flex`** (*Always Free-eligible*). Elegir **2 OCPU y 12 GB de RAM** (o
     **1 OCPU y 6 GB** si aparece el cartel *Out of capacity in availability domain*; cualquiera de las dos sobra para
     la plataforma).
4. **Networking:** dejar que cree una red virtual (*VCN*) nueva con subred pública y marcar **Assign a public IPv4
   address**.
5. **Add SSH keys:** elegir *Generate a key pair for me* y descargar la clave privada (`ssh-key-*.key`), o subir tu
   propia clave pública (`~/.ssh/id_ed25519.pub`).
6. **Boot volume:** dejar el tamaño por defecto (47–50 GB; el nivel gratuito incluye hasta 200 GB).
7. Pulsar **Create** y esperar a que pase a estado **Running**.

### 2.2. Dejar fija la IP pública (IP reservada)

Para que la dirección no cambie si algún día se detiene y se vuelve a encender la máquina:

1. En el detalle de la instancia, bajar a **Attached VNICs**, entrar en la VNIC primaria y abrir la pestaña **IPv4
   Addresses**.
2. En el menú `⋮` de la IP asignada, elegir **Edit**, cambiar *Public IP Type* a **Reserved Public IP** → **Create new
   reserved IP address** y guardar. Anotar esa IP (`IP_PUBLICA`).

### 2.3. Abrir los puertos 80 y 443 en la red de Oracle

La máquina tiene **dos** firewalls: el de la red de Oracle (*Security List*) y el del propio Ubuntu (`iptables`). Si
falta cualquiera de los dos, Caddy no puede obtener el certificado HTTPS. El de Ubuntu lo abre el script del paso 4;
el de Oracle se abre desde la consola web:

1. En el detalle de la instancia, hacer clic en el nombre de la **Subnet** → hacer clic en **`Default Security List for
   …`** → **Add Ingress Rules**.
2. Cargar dos reglas con **Source CIDR** `0.0.0.0/0`:
   - *IP Protocol*: **TCP**, *Destination Port Range*: `80,443`.
   - *IP Protocol*: **UDP**, *Destination Port Range*: `443` (HTTP/3, opcional).
3. El puerto `22` (SSH) ya viene abierto. Si tenés IP fija en tu casa, conviene cambiar su *Source CIDR* de `0.0.0.0/0`
   a `TU_IP/32`.

---

## 3. Apuntar un dominio a la IP de la máquina

Meta exige HTTPS con un certificado válido, y Let's Encrypt no emite certificados para una IP suelta: hace falta un
nombre de dominio. Dos opciones:

### Opción A: DuckDNS (gratis, en dos minutos)

1. Entrar en <https://www.duckdns.org/> e iniciar sesión (con GitHub o Google).
2. Escribir un subdominio (por ejemplo, `responde-catedra`), poner la `IP_PUBLICA` de la VM en **current ip** y pulsar
   **add domain**. Queda creado `responde-catedra.duckdns.org`.

### Opción B: dominio propio (por ejemplo, `.com.ar` en NIC Argentina)

1. En el proveedor de DNS del dominio (Cloudflare gratuito, por ejemplo), crear un registro **A** con el nombre `@` (o
   un subdominio como `app`) apuntando a `IP_PUBLICA`, **sin proxy** (nube gris en Cloudflare) al menos hasta que Caddy
   emita el certificado.

### Comprobar que el DNS ya responde

Antes de levantar Caddy, verificar desde tu computadora que el nombre ya resuelve a la IP de la VM:

```bash
nslookup responde-catedra.duckdns.org
```

---

## 4. Preparar el servidor (una sola vez)

Conectarse por SSH con el usuario `ubuntu` y la clave privada del paso 2.1:

```bash
# En Windows (PowerShell) o Linux/macOS:
ssh -i ruta/a/ssh-key.key ubuntu@IP_PUBLICA
```

Clonar el repositorio y ejecutar el script de preparación:

```bash
git clone https://github.com/quitohooded/plataforma-atencion-whatsapp.git
cd plataforma-atencion-whatsapp
sudo bash deploy/preparar-vm.sh
```

`deploy/preparar-vm.sh` hace todo lo necesario en una pasada:

- activa las actualizaciones automáticas de seguridad (`unattended-upgrades`);
- fija la zona horaria en `America/Argentina/Cordoba`;
- crea un archivo *swap* de 2 GB;
- instala Docker Engine, el plugin `docker compose`, `sqlite3` y `rclone` desde los repositorios oficiales;
- abre los puertos `80/tcp`, `443/tcp` y `443/udp` en el `iptables` de la imagen de Oracle y guarda las reglas;
- deshabilita el inicio de sesión por SSH con contraseña (solo clave pública).

Al terminar, **cerrar la sesión SSH y volver a entrar** (`exit` y de nuevo `ssh …`) para que el usuario `ubuntu` tome
el grupo `docker`.

---

## 5. Configurar `.env` y levantar los contenedores

Dentro de `~/plataforma-atencion-whatsapp`:

```bash
cp .env.example .env
nano .env
```

Generar una clave aleatoria para `SECRET_KEY` con `openssl rand -hex 32` y dejar al menos estos valores:

```dotenv
# Dominio y certificado HTTPS (Caddy)
DOMINIO=responde-catedra.duckdns.org
ACME_EMAIL=tu-correo@ejemplo.com

# Aplicación
SECRET_KEY=pegar_aqui_los_64_caracteres_de_openssl_rand_hex_32
PLATAFORMA_NOMBRE=Respondé
SQLITE_WAL=true
ZONA_HORARIA=America/Argentina/Cordoba
CONFIAR_EN_PROXY=true
LIMITES_POR_IP=true
URL_PUBLICA=https://responde-catedra.duckdns.org
CONTACTO_PLATAFORMA=tu-correo@ejemplo.com

# Dejar en true durante la defensa o demostración; pasar a false cuando quede solo para uso real.
SIMULADOR_HABILITADO=true

# WhatsApp Business Platform (los mismos valores que tenías en PythonAnywhere)
WHATSAPP_TOKEN=...
WHATSAPP_PHONE_NUMBER_ID=...
WHATSAPP_VERIFY_TOKEN=...
WHATSAPP_APP_SECRET=...
WHATSAPP_NUMERO_PUBLICO=...
WHATSAPP_AR_QUITAR_9=true

# Correo por SMTP (Gmail con contraseña de aplicación de 16 letras)
MAIL_MODO=smtp
MAIL_SERVIDOR=smtp.gmail.com
MAIL_PUERTO=587
MAIL_USUARIO=tu-cuenta@gmail.com
MAIL_CONTRASENA=xxxx xxxx xxxx xxxx
MAIL_REMITENTE=Respondé <tu-cuenta@gmail.com>
MAIL_TLS=true
```

Proteger el archivo y levantar todo:

```bash
chmod 600 .env
docker compose up -d --build
```

La primera vez tarda uno o dos minutos mientras construye la imagen y Caddy obtiene el certificado de Let's Encrypt.
Revisar la configuración y el estado:

```bash
docker compose ps
docker compose exec app flask --app app admin verificar
curl -fsS https://responde-catedra.duckdns.org/salud
```

Debe responder `{"base":"ok","estado":"ok"}` con código 200 y sin errores en `admin verificar` (si `SIMULADOR_HABILITADO`
está en `true` para la cátedra, aparece como `[aviso]`, no como `[error]`).

---

## 6. Traer los datos desde PythonAnywhere (o cargar la demo)

### Opción A: migrar la base existente desde PythonAnywhere

1. En la consola Bash de PythonAnywhere, hacer un respaldo en caliente:

   ```bash
   cd ~/plataforma-atencion-whatsapp
   ~/.virtualenvs/responde/bin/flask --app app admin respaldar ~/plataforma-migracion.db
   ```

2. Desde la pestaña **Files** de PythonAnywhere, descargar `plataforma-migracion.db` a tu computadora.
3. Subirlo a la VM de Oracle y reemplazar la base del contenedor:

   ```bash
   # Desde tu computadora:
   scp -i ruta/a/ssh-key.key plataforma-migracion.db ubuntu@IP_PUBLICA:~/

   # En la VM:
   cd ~/plataforma-atencion-whatsapp
   docker compose stop app
   docker compose cp ~/plataforma-migracion.db app:/app/instance/plataforma.db
   docker compose exec -u root app chown responde:responde /app/instance/plataforma.db
   docker compose start app
   rm ~/plataforma-migracion.db
   ```

   Al arrancar, `app/migraciones.py` aplica sola cualquier migración pendiente.

### Opción B: empezar con los datos de demostración

```bash
docker compose exec app flask --app app demo --si
```

---

## 7. Actualizar la dirección del webhook en Meta

1. Entrar en <https://developers.facebook.com/apps/> → tu aplicación → **WhatsApp → Configuración**.
2. En **Webhook**, pulsar **Editar**:
   - **URL de devolución de llamada:** `https://responde-catedra.duckdns.org/webhook/whatsapp`
   - **Token de verificación:** el valor de `WHATSAPP_VERIFY_TOKEN` de tu `.env`.
3. Pulsar **Verificar y guardar** y confirmar que el campo **`messages`** sigue suscripto.
4. Enviar un mensaje desde WhatsApp al número de prueba y verificar que el bot responde y que la consulta aparece en el
   panel (`https://responde-catedra.duckdns.org/panel`).

---

## 8. Respaldos diarios fuera del servidor y monitoreo

### 8.1. Probar el script de respaldo local

```bash
bash deploy/respaldar.sh
ls -lh ~/respaldos/
```

El script usa `flask admin respaldar` (copia en caliente de SQLite, sin detener la app), verifica la integridad del
archivo con `PRAGMA integrity_check` y borra las copias de más de 14 días.

### 8.2. Subir los respaldos a la nube con `rclone` (opcional pero muy recomendado)

Si algún día se borra la VM o se cierra la cuenta gratuita, los respaldos locales se pierden con ella. Para guardarlos
en **Google Drive** o en **Oracle Object Storage** (20 GB gratis):

1. Configurar un remoto interactivo:

   ```bash
   rclone config
   ```

   - Elegir `n` (*New remote*), ponerle de nombre `remoto` y elegir `drive` (Google Drive, siguiendo el enlace de
     autorización en tu navegador) u `oracleobjectstorage`.
2. Agregar en `.env`:

   ```dotenv
   RCLONE_REMOTO=remoto:responde-respaldos
   ```

3. Volver a correr `bash deploy/respaldar.sh` y comprobar que el archivo aparece en la carpeta remota.

### 8.3. Programar el respaldo diario con `cron`

```bash
crontab -e
```

Agregar al final (corre todos los días a las 03:30 de Argentina):

```cron
30 3 * * * /bin/bash /home/ubuntu/plataforma-atencion-whatsapp/deploy/respaldar.sh >> /home/ubuntu/respaldos/respaldar.log 2>&1
```

### 8.4. Cómo restaurar un respaldo

```bash
cd ~/plataforma-atencion-whatsapp
docker compose stop app
docker compose cp ~/respaldos/plataforma-AAAAMMDD-HHMMSS.db app:/app/instance/plataforma.db
docker compose start app
```

Conviene probar este procedimiento al menos una vez antes de dar por terminado el despliegue.

### 8.5. Monitoreo externo gratuito con UptimeRobot

1. Crear una cuenta gratuita en <https://uptimerobot.com/>.
2. **Add New Monitor**:
   - *Monitor Type*: **HTTP(s) — Keyword**.
   - *URL*: `https://responde-catedra.duckdns.org/salud`.
   - *Keyword*: `"estado":"ok"` (*Alert when keyword is not present*).
   - *Monitoring Interval*: 5 minutos.
3. Además de avisarte por correo si la aplicación o la base se caen, las consultas cada 5 minutos generan tráfico
   constante en la VM.

---

## 9. Operación cotidiana y actualizaciones

| Tarea | Comando en la VM (`~/plataforma-atencion-whatsapp`) |
|---|---|
| Actualizar a la última versión del repositorio (hace respaldo antes) | `bash deploy/actualizar.sh` |
| Ver el registro de la aplicación en vivo | `docker compose logs -f app` |
| Ver el registro de Caddy (certificados y accesos) | `docker compose logs -f caddy` |
| Listar comercios registrados | `docker compose exec app flask --app app admin comercios` |
| Restablecer la contraseña de un comercio | `docker compose exec -it app flask --app app admin restablecer-clave CORREO` |
| Hacer un respaldo manual ahora | `bash deploy/respaldar.sh` |
| Reiniciar los contenedores | `docker compose restart` |

---

## 10. Lista de verificación antes de apagar PythonAnywhere

- [ ] `https://DOMINIO/salud` responde `{"base":"ok","estado":"ok"}` con certificado válido (candado en el navegador).
- [ ] `http://DOMINIO` redirige automáticamente a `https://DOMINIO`.
- [ ] `http://IP_PUBLICA:8000` **no** responde desde afuera (el puerto 8000 solo es accesible dentro de la red de Docker).
- [ ] `docker compose exec app flask --app app admin verificar` termina sin `[error]`.
- [ ] Ingreso al panel, onboarding y simulador funcionan; la cookie `session` tiene los atributos `Secure` y `HttpOnly`.
- [ ] El webhook verificado en Meta recibe un mensaje real de WhatsApp y el bot responde.
- [ ] El correo de recuperación de contraseña (`/recuperar`) llega a la bandeja de entrada.
- [ ] `bash deploy/respaldar.sh` genera el archivo en `~/respaldos/` (y en el remoto de `rclone`, si se configuró).
- [ ] Después de reiniciar la máquina (`sudo reboot`), `app` y `caddy` vuelven a levantarse solos.
- [ ] UptimeRobot muestra el monitor en verde.
- [ ] En Oracle Cloud está creada la alerta de presupuesto de USD 1.
