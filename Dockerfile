# Single image, many roles.  Each service in docker-compose.yml runs the same
# image with a different module and port - the same shape as deploying several
# Mule applications from one build pipeline.
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/services

WORKDIR /app

COPY services/requirements.txt /app/services/requirements.txt
RUN pip install --no-cache-dir -r /app/services/requirements.txt

COPY . /app

# Never run as root.
RUN useradd --create-home --uid 10001 acme && chown -R acme:acme /app
USER acme

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://localhost:{os.getenv(\"PORT\",\"8080\")}/health').read()"

CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080"]
