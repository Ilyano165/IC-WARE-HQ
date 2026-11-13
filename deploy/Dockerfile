# IC WARE HQ — Produktions-Image. Bauen aus dem Projektordner:
#   docker build -f deploy/Dockerfile -t ic-ware-hq:local .   (Betrieb: deploy/hq build)
FROM python:3.12-slim AS build
WORKDIR /src
COPY requirements.lock pyproject.toml ./
COPY src ./src
# Abhängigkeiten nur mit geprüften Hashes, das eigene Paket ohne Nachladen.
# Optional: zusätzliche Wurzel-CA für Netze mit TLS-prüfendem Proxy (Build-Secret „extra_ca", landet NICHT im Image):
#   docker build --secret id=extra_ca,src=/pfad/ca.pem …
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi \
 && pip install --no-cache-dir --prefix=/install --require-hashes -r requirements.lock \
 && pip install --no-cache-dir --prefix=/install --no-deps .

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin ichq \
 && mkdir -p /var/lib/ichq/storage && chown -R 10001:10001 /var/lib/ichq
COPY --from=build /install /usr/local
USER 10001
WORKDIR /var/lib/ichq
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/readiness', timeout=4).status == 200 else 1)"
# Kein Entwicklungsserver: uvicorn mit mehreren Prozessen, ohne Zugriffslog (wir loggen selbst)
CMD ["ichq", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
