# Guía de Operación y Hardening en Producción SaaS

Esta guía detalla la arquitectura, configuración, despliegue continuo y blindaje operativo de la plataforma Respondé en entornos de producción, bajo la filosofía **Zero Out-of-Pocket** (costo base de infraestructura de \$0 USD/mes).

---

## 1. Arquitectura de Producción

La plataforma se despliega como una solución contenerizada y autónoma, optimizada para operar eficientemente incluso en instancias virtuales gratuitas (GCP Compute Engine `e2-micro` u Oracle Cloud Always Free con 1 GB de RAM).

```
                      Internet (HTTPS / 443)
                                │
                                ▼
        ┌──────────────────────────────────────────────────┐
        │  Caddy Web Server (Reverse Proxy & Let's Encrypt)│
        └───────────────────────┬──────────────────────────┘
                                │ HTTP / Red Interna Docker
                                ▼
        ┌──────────────────────────────────────────────────┐
        │  Contenedor Flask / Waitress (Python 3.12)        │
        │  - Cola asíncrona de webhooks (desacople <30 ms) │
        │  - Monitoreo en vivo con Sentry SDK              │
        │  - Aislamiento estricto multitenant              │
        └───────────────┬───────────────────┬──────────────┘
                        │                   │
                        ▼                   ▼
     ┌──────────────────────┐   ┌──────────────────────────────┐
     │ SQLite (Modo WAL)    │   │ APIs Externas Seguras:       │
     │ Volumen persistente  │   │ - Meta Cloud API (WhatsApp)  │
     │ /app/instance/*.db   │   │ - Google Gemini (IA)         │
     └──────────────────────┘   │ - Mercado Pago (Cobros)      │
                                └──────────────────────────────┘
```

### Componentes Clave:
* **Caddy 2:** Servidor web perimetral con renovación automática de certificados SSL/TLS (Let's Encrypt / ZeroSSL), compresión zstd/gzip y cabeceras de seguridad.
* **Waitress WSGI:** Servidor de aplicaciones multiproceso/multihilo en Python puro, insensible a bloqueos de DLLs de compilación nativa.
* **SQLite 3 con WAL (Write-Ahead Logging):** Permite lecturas y escrituras concurrentes sin bloqueos de contención entre el bot y el panel administrativo.
* **Cola de Tareas en Memoria:** Procesa eventos entrantes de WhatsApp en segundo plano, devolviendo HTTP 200 a Meta en menos de 30 ms para evitar reintentos y saturación de la máquina virtual.

---

## 2. Variables de Entorno Recomendadas (`.env`)

En un despliegue real, cree el archivo `.env` en la raíz del proyecto a partir de `.env.example` y configure las siguientes variables:

### Núcleo de Aplicación y Seguridad
```ini
# Generar con: python -c "import secrets; print(secrets.token_hex(32))"
SECRET_KEY=9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b9c8d7e6f5a4b3c2d1e0f9a8b
URL_PUBLICA=https://tudominio.com
CONFIAR_EN_PROXY=true
SQLITE_WAL=true
SIMULADOR_HABILITADO=false
COOKIES_SEGURAS=true
LIMITES_POR_IP=true
COLA_SINCRONICA=false
CONTACTO_PLATAFORMA=soporte@tudominio.com
RETENCION_DIAS=365
```

### WhatsApp Business Platform (Cloud API & Embedded Signup)
```ini
WHATSAPP_TOKEN=EAA...
WHATSAPP_PHONE_NUMBER_ID=109876543210
WHATSAPP_APP_SECRET=a1b2c3d4e5f6...
WHATSAPP_VERIFY_TOKEN=clave-secreta-personalizada-de-verificacion
WHATSAPP_NUMERO_PUBLICO=5493510000000
WHATSAPP_API_VERSION=v23.0
WHATSAPP_AR_QUITAR_9=true

# Onboarding oficial en 1-clic (Meta Embedded Signup)
META_APP_ID=123456789012345
META_CONFIG_ID=987654321098765
META_SYSTEM_USER_TOKEN=EAA...
```

### Inteligencia Artificial (Google Gemini)
```ini
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL_CHAT=gemini-3.5-flash-lite
GEMINI_MODEL_INTERNO=gemini-3.8-flash
```

### Monetización y Pagos (Mercado Pago)
```ini
MERCADOPAGO_ACCESS_TOKEN=APP_USR-...
MERCADOPAGO_PUBLIC_KEY=APP_USR-...
MERCADOPAGO_WEBHOOK_SECRET=...
PLAN_PRO_PRECIO_MENSUAL=14900
```

### SuperAdmin del SaaS
```ini
SUPERADMIN_EMAIL=superadmin@tudominio.com
SUPERADMIN_CLAVE=ContrasenaSuperSeguraDe64Caracteres...
```

### Monitoreo en Vivo (Sentry) y Respaldos
```ini
SENTRY_DSN=https://clave@o0.ingest.sentry.io/0
SENTRY_ENVIRONMENT=production
PING_URL=https://hc-ping.com/uuid-de-healthchecks-io
RCLONE_REMOTO=gdrive:responde-respaldos
```

---

## 3. Despliegue y Actualización en Caliente

La actualización del código en producción está 100% automatizada y cuenta con verificación previa y posterior para garantizar cero pérdida de datos.

### Ejecutar actualización:
```bash
bash deploy/actualizar.sh
```

### Pasos ejecutados internamente:
1. **Respaldo previo:** Si el contenedor `app` está activo, ejecuta `deploy/respaldar.sh` para crear una copia en caliente de `instance/plataforma.db`.
2. **Descarga de código:** Realiza un `git pull --ff-only` desde la rama `produccion`.
3. **Reconstrucción de imagen:** Ejecuta `docker compose up -d --build --remove-orphans`.
4. **Verificación de salud:** Consulta en bucle el endpoint `/salud` hasta confirmar que la base y la app están listas.
5. **Auditoría automática:** Ejecuta `flask admin verificar` dentro del contenedor para alertar sobre inconsistencias de configuración.

---

## 4. Monitoreo y Observabilidad

### 1. Monitoreo de Excepciones con Sentry
* La aplicación inicializa automáticamente `sentry_sdk` si `SENTRY_DSN` está presente en `.env`.
* Configurado con `FlaskIntegration()`, muestreo de trazas de rendimiento (`traces_sample_rate=0.2`) y estricta privacidad (`send_default_pii=False`).
* Un fallo de conectividad con Sentry nunca impide el arranque de la aplicación (captura defensiva de errores).

### 2. Monitoreo de Disponibilidad (Uptime)
* Endpoint `/salud`: responde `{"estado": "ok", "base": "ok"}` con código HTTP 200 si la base responde correctamente.
* Ante fallo de base de datos responde HTTP 503 `{"estado": "error", "base": "sin conexión"}`.
* Puede vincularse a monitores externos gratuitos como Uptime Kuma, Better Stack o Healthchecks.io.

### 3. Auditoría de Seguridad y Configuración
Ejecute en cualquier momento:
```bash
docker compose exec app flask --app app admin verificar
```
El sistema auditará la presencia de claves seguras, estado del webhook, configuración de correo y monitoreo.

---

## 5. Estrategia de Respaldos Offsite

### Automatización con Cron
Instale la tarea programada idempotente en el host Ubuntu:
```bash
bash deploy/instalar-cron.sh
```
Esto programará en `crontab` la ejecución diaria a las 03:30 AM:
`30 3 * * * /ruta/deploy/respaldar.sh >> /home/ubuntu/respaldos/respaldar.log 2>&1`

### Ciclo de Respaldo (`deploy/respaldar.sh`)
1. Genera una copia consistente en caliente mediante el comando seguro `flask admin respaldar`.
2. Valida la integridad del archivo resultante con `PRAGMA integrity_check;`.
3. Aplica rotación automática local conservando los últimos 14 días.
4. Si `RCLONE_REMOTO` está configurado, sincroniza la copia a un almacenamiento externo (Google Drive, Cloud Storage u OCI Object Storage).
5. Si `PING_URL` / `HEALTHCHECK_URL` está configurado, envía un ping exitoso (o `/fail` en caso de error) al monitor de respaldos.
