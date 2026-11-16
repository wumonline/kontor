# Kontor für Unraid: App + Datenablage + FinTS-Abruf
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    DATA_DIR=/data \
    DROP_DIR=/eingang \
    APP_DIR=/srv/app

WORKDIR /srv
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt

COPY VERSION VERSION
COPY server/ server/
COPY app/index.html app/index.html

# Unraid-Standard: nobody (99) / users (100), damit die Dateien in appdata normal bearbeitbar bleiben
RUN useradd -u 99 -g 100 -M -d /srv -s /usr/sbin/nologin finanz 2>/dev/null || true \
 && mkdir -p /data /eingang && chown 99:100 /data /eingang
USER 99:100

VOLUME ["/data", "/eingang"]
EXPOSE 8080
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4)" || exit 1
CMD ["python", "server/app.py"]
