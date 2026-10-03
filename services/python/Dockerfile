# syntax=docker/dockerfile:1
FROM python:3.12.9-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN --mount=type=secret,id=proxy_ca if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; pip install --no-cache-dir -r requirements.txt
RUN python --version > /build-info.txt && pip freeze >> /build-info.txt
COPY server.py .
CMD ["python", "server.py"]
