# Imagen del prototipo: Python 3.12, servidor waitress y la base SQLite en un volumen.
#
#   docker build -t responde .
#   docker run -d --name responde -p 8000:8000 --env-file .env -v responde-datos:/app/instance responde
#   docker exec -it responde flask --app app demo --si        (datos de demostración)
#   docker exec -it responde flask --app app admin verificar  (revisar la configuración)
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app
COPY serve.py wsgi.py ./

# Usuario sin privilegios; la base, la clave de sesiones, los correos y los respaldos quedan en instance/.
RUN useradd --create-home --uid 10001 responde \
    && mkdir -p /app/instance \
    && chown responde:responde /app/instance
USER responde
VOLUME ["/app/instance"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/salud' % os.environ.get('PORT', '8000'), timeout=4)"

CMD ["python", "serve.py", "--publico"]
