FROM python:3.13-slim-bookworm@sha256:281d39ff02e3b389401586134ff9e6572954687822a58055ec07a60ded4e0b7f

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WATCHTRACKER_DATA_DIR=/var/lib/pmt/data \
    WATCHTRACKER_CONFIG_DIR=/var/lib/pmt/config \
    WATCHTRACKER_CACHE_DIR=/var/lib/pmt/cache \
    WATCHTRACKER_LOG_DIR=/var/lib/pmt/logs \
    WATCHTRACKER_BACKUPS_DIR=/var/lib/pmt/backups

# Keep dump/restore tools compatible with the PostgreSQL 15 Compose service.
RUN apt-get update && apt-get install --yes --no-install-recommends postgresql-client-15 && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system pmt && useradd --system --gid pmt --home-dir /var/lib/pmt pmt
WORKDIR /app
COPY pyproject.toml README.md LICENSE /app/
COPY src /app/src
RUN python -m pip install --no-cache-dir '.[server,notifications]' && \
    mkdir -p /var/lib/pmt/data /var/lib/pmt/config /var/lib/pmt/cache /var/lib/pmt/logs /var/lib/pmt/backups && \
    chown -R pmt:pmt /var/lib/pmt

USER pmt
VOLUME ["/var/lib/pmt"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["personal-media-tracker", "--no-open", "server"]
