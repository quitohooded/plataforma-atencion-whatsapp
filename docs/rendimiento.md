# Rendimiento y calidad de la interfaz

Evidencia medida de los requerimientos no funcionales que dependen de la ejecución: el tiempo de respuesta del bot
(RNF04), el funcionamiento en los navegadores y en el celular (RNF02) y la accesibilidad del panel (RNF06).

## Tiempo de respuesta del bot (RNF04)

> RNF04: «El bot debe responder las consultas frecuentes en cuestión de segundos, independientemente del horario en
> que se reciban».

`scripts/rendimiento.py` mide tres capas, de adentro hacia afuera, con los 601 mensajes de los tres corpus:

1. **Motor**: interpretar el mensaje y armar la respuesta, sin base de datos.
2. **Servicio completo**: el recorrido de un mensaje entrante con SQLite en disco (identificar el comercio, guardar
   los mensajes y las consultas y confirmar la transacción), igual que el webhook.
3. **HTTP con carga**: 10 compradores escribiendo a la vez al simulador, servido por waitress con 8 hilos, el mismo
   servidor que usa el prototipo.

Resultado en el equipo de desarrollo (Linux, 2 núcleos, Python 3.13), 29/10/2026:

| Medición | Mensajes | Mediana | p95 | p99 | Máximo |
|---|---|---|---|---|---|
| Motor (sin base de datos) | 1803 | 0,7 ms | 1,5 ms | 1,7 ms | 2,9 ms |
| Servicio completo con SQLite en disco | 601 | 9,7 ms | 13,4 ms | 46,6 ms | 66,9 ms |
| HTTP con 10 compradores simultáneos | 200 | 46,5 ms | 223,2 ms | 865,3 ms | 1572,8 ms |

Con carga se atendieron 72 mensajes por segundo. En la prueba HTTP los compradores simulados corren en el mismo
equipo de dos núcleos que el servidor y compiten con él por el procesador, así que esos tiempos son un techo
pesimista.

**Conclusión.** El sistema responde en milisegundos: la mitad de los mensajes, en menos de 50 ms aun con diez
compradores escribiendo a la vez, y ninguno superó los dos segundos. A eso se suma la red de WhatsApp (de Meta al
servidor y del servidor al comprador), que no depende del sistema. El requisito se cumple con margen.

**Cómo se llegó.** La primera medición con carga dio una mediana de 58 ms, un p95 de 476 ms y 58 mensajes por segundo.
La base pasó a usar el registro anticipado de SQLite (WAL), con el que las lecturas del panel no esperan a las
escrituras del bot: 72 mensajes por segundo y un p95 de 223 ms. Se desactiva con `SQLITE_WAL=false` si la base está
en un disco de red que no lo admite (por ejemplo, en PythonAnywhere).

**Regresiones.** `tests/test_rendimiento.py` fija techos holgados (p95 del motor por debajo de 50 ms, del servicio por
debajo de 500 ms y un mensaje de más de 11.000 caracteres en menos de un segundo) para detectar un cambio que dispare los
tiempos.

```bash
python scripts/rendimiento.py                         # las tres mediciones
python scripts/rendimiento.py --compradores 20 --mensajes 30
```

## Pruebas de punta a punta (RNF02)

`tests/e2e` recorre la aplicación con Chromium (Playwright) sobre un servidor real, con la protección CSRF activa y
la demostración cargada. Cada prueba falla si la página registra un error de JavaScript.

| Recorrido | Qué comprueba |
|---|---|
| Comercio nuevo de punta a punta | Registro (con el error por no aceptar los términos), los cuatro pasos de la carga inicial, la vista previa, el chat de prueba, la activación, un comprador en el simulador que pregunta y es derivado, y la consulta atendida en el panel |
| Comprador y datos sensibles | Advertencia por datos de tarjeta, verificación de un alias ajeno y, al recargar el simulador, la tarjeta oculta |
| Respuesta frecuente nueva | Plantilla, prueba antes de guardar y respuesta del bot en el simulador |
| Panel en el celular | Ninguna pantalla se desborda a lo ancho y el menú se abre con su botón |
| Aviso en vivo | El contador del panel se actualiza solo cuando llega una consulta (se adelanta el reloj de la página) |

## Accesibilidad (WCAG 2.1 AA)

`tests/e2e/test_accesibilidad.py` audita con axe-core 4.12 (reglas WCAG 2.0 y 2.1 A y AA, más las buenas prácticas)
cada pantalla pública y del panel, la conversación del historial, el simulador con mensajes, el registro con errores y
los cuatro pasos de la carga inicial, en escritorio y en celular.

La primera auditoría encontró:

- **Contraste insuficiente** del texto secundario (gris `#6c7d75`): 4,3 a 1 sobre blanco y 3,4 a 1 sobre las burbujas
  del chat, cuando el mínimo es 4,5 a 1. Se oscureció a `#5a6a63`, que supera 4,5 a 1 sobre todos los fondos.
- **Orden de los títulos**: los formularios de alta de zonas y medios de pago saltaban de `h1` a `h3`.
- **Regiones**: la barra superior del celular quedaba fuera de una región (ahora es `header`) y la página de una
  respuesta frecuente tenía dos `aside` sin nombre (ahora tienen `aria-label`).

Después de las correcciones, ninguna pantalla tiene incumplimientos.

```bash
pip install -r requirements-e2e.txt
python -m playwright install chromium
python -m pytest tests/e2e                 # o: python scripts/verificar.py --e2e
```
