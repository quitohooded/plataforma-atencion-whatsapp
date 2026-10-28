# Plataforma de atención automatizada de consultas frecuentes mediante WhatsApp

Prototipo funcional del proyecto del **Seminario de Práctica de Analista en Software** (Ingeniería en Software,
Universidad Siglo 21, cátedra C, 2026). Autores: Román Cuberli (SOF01923) y Esteban Aguilar (SOF02122).
Docente: Leonardo Gabriel Gamboa.

La plataforma combina un **bot de WhatsApp** y un **panel web de administración** para que comercios minoristas que
venden por mensajería, como Casa & Detalles (caso de estudio), respondan al instante las consultas sobre **envíos,
medios de pago y horarios**. Varios comercios comparten una misma línea de WhatsApp provista por la plataforma; el
código incluido en el primer mensaje del comprador identifica a qué comercio corresponde cada conversación.

![Resumen del panel](docs/capturas/13-resumen-y-pendientes.png)

## Qué incluye

| Caso de uso | Dónde está |
|---|---|
| CU01 Registrarse en la plataforma | `/registro` |
| CU02 Iniciar sesión (con bloqueo tras 5 intentos fallidos durante 15 minutos) | `/ingresar` |
| CU03 Completar onboarding (4 pasos y resumen, retoma el paso pendiente) | `/onboarding` |
| CU04 Administrar zonas de envío (incluye importación de planilla CSV con vista previa) | `/zonas` |
| CU05 Administrar medios de pago (activar, desactivar, editar, eliminar) | `/medios-de-pago` |
| CU06 Administrar horarios (jornada partida y copia a días hábiles) | `/horarios` |
| CU07 Activar el bot (chat de prueba, código, enlace wa.me, QR, cartel imprimible, pausa) | `/activacion` |
| CU08 a CU12 Atención por WhatsApp (intención, envíos con código postal, pagos, horarios, derivación) | `/webhook/whatsapp` y `/simulador` |
| CU13 Consultar resumen y pendientes (indicadores por período, «Responder por WhatsApp») | `/panel` |
| CU14 Consultar historial de consultas (filtros y conversación completa) | `/historial` |

Además: simulador de WhatsApp para demos sin Meta, datos de demostración con dos comercios y tres semanas de
actividad, y 105 pruebas automatizadas organizadas por caso de uso.

## Inicio rápido en Windows

1. Instalar [Python 3.10 o superior](https://www.python.org/downloads/) marcando **«Add python.exe to PATH»**.
2. Hacer doble clic en **`iniciar.bat`**.

El script crea el entorno virtual, instala las dependencias, carga los datos de demostración la primera vez y abre
el navegador en `http://localhost:5000`.

| Usuario de prueba | Contraseña | Comercio |
|---|---|---|
| `demo@casaydetalles.com.ar` | `demo1234` | Casa & Detalles (código `CASA26`) |
| `demo@mundotextil.com.ar` | `demo1234` | Mundo Textil (código `TEXT42`) |

El simulador de WhatsApp está en `http://localhost:5000/simulador`.

## Inicio manual (cualquier sistema)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env               # macOS/Linux: cp .env.example .env
flask --app app demo --si            # borra la base y carga la demostración
python serve.py                      # http://localhost:5000
```

Para desarrollo con recarga automática: `flask --app app run --debug`.

### Comandos útiles

| Comando | Para qué |
|---|---|
| `flask --app app crear-tablas` | Crea la base vacía con el catálogo de palabras clave |
| `flask --app app demo --si` | Reinicia la base con los comercios de ejemplo |
| `flask --app app palabras listar --tema ENVIO` | Lista las palabras clave de un tema |
| `flask --app app palabras agregar "retiro" ENVIO` | Agrega una palabra clave al catálogo |
| `python -m pytest` | Corre las pruebas (instalar antes `requirements-dev.txt`) |
| `python scripts/capturas.py` | Regenera las capturas de `docs/capturas` (requiere Playwright) |

## Conectar WhatsApp

El prototipo funciona completo con el simulador. Para atender mensajes reales con el número de prueba de Meta, seguir
[docs/configuracion-whatsapp.md](docs/configuracion-whatsapp.md): se completan cinco variables en `.env`, se expone el
servidor con un túnel HTTPS y se registra la URL del webhook en Meta.

## Tecnología

Python 3.10+, Flask 3, SQLite (SQLAlchemy 2), WhatsApp Business Platform (Cloud API), Jinja, CSS y JavaScript sin
dependencias externas (funciona sin conexión a internet salvo la integración con WhatsApp), Waitress como servidor
compatible con Windows y pytest para las pruebas.

## Estructura

```
app/
  modelos.py            Clases del dominio (diagrama de clases) mapeadas a las tablas del DER
  bot/                  Motor del bot: normalización, intención, estados, respuestas, servicio
  mensajeria/           Cliente de WhatsApp Cloud API y lectura del webhook
  servicios/            Reglas del panel: cuentas, zonas, medios de pago, horarios, métricas
  web/                  Rutas (una por caso de uso), webhook y simulador
  templates/, static/   Interfaz del panel
  datos/                Catálogo de palabras clave y datos de demostración
tests/                  Pruebas por caso de uso
docs/                   Arquitectura, manual de uso, configuración de WhatsApp, casos de prueba y capturas
```

## Documentación

- [Arquitectura y decisiones de implementación](docs/arquitectura.md)
- [Manual de uso del panel](docs/manual-de-uso.md)
- [Configuración de WhatsApp Business Platform](docs/configuracion-whatsapp.md)
- [Casos de prueba](docs/casos-de-prueba.md)
- [Capturas de la interfaz](docs/capturas)

## Publicar en GitHub

El repositorio ya tiene su historial de Git. Para subirlo, crear un repositorio vacío en GitHub y ejecutar:

```bash
git remote add origin https://github.com/<usuario>/plataforma-atencion-whatsapp.git
git push -u origin main
```

## Alcance del prototipo

Respeta lo delimitado en el informe: clasificación por palabras clave (sin procesamiento de lenguaje natural), un único
usuario por comercio, sin consulta de stock, sin cobros, sin seguimiento de envíos, un solo canal (WhatsApp) y línea
provista por la plataforma. Esas funciones quedan como requerimientos candidatos (RC01 a RC04).
