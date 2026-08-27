FROM python:3.13-slim@sha256:ffb752e139c0a19692a43af8d8523b274222dd68eebad5d583b45c2201c6e30a

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WATCHTRACKER_DATA_DIR=/var/lib/pmt/data \
    WATCHTRACKER_CONFIG_DIR=/var/lib/pmt/config \
    WATCHTRACKER_CACHE_DIR=/var/lib/pmt/cache \
    WATCHTRACKER_LOG_DIR=/var/lib/pmt/logs \
    WATCHTRACKER_BACKUPS_DIR=/var/lib/pmt/backups

RUN apt-get update && apt-get install --yes --no-install-recommends postgresql-client && \
    rm -rf /var/lib/apt/lists/* && \
    groupadd --system pmt && useradd --system --gid pmt --home-dir /var/lib/pmt pmt
WORKDIR /app
COPY . /app
RUN python -m pip install --no-cache-dir '.[server]' && \
    mkdir -p /var/lib/pmt/data /var/lib/pmt/config /var/lib/pmt/cache /var/lib/pmt/logs /var/lib/pmt/backups && \
    chown -R pmt:pmt /var/lib/pmt

USER pmt
VOLUME ["/var/lib/pmt"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3)"
CMD ["personal-media-tracker", "--no-open", "server"]
