FROM python:3.11-slim-bookworm

# git is required by the dispatcher to clone repos onto the shared PV.
RUN useradd -m -u 1000 appuser && \
    apt-get update && \
    apt-get install -y --no-install-recommends git ca-certificates && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# /repos and /data/artifacts are PV mount points; create + own them so the
# non-root user can write even before the volume is mounted.
RUN mkdir -p /repos /data/artifacts && \
    chown -R appuser:appuser /app /repos /data/artifacts

USER appuser
EXPOSE 8080

# Default: the DRF API. The dispatcher container overrides this command with:
#   ["python", "manage.py", "run_dispatcher"]
CMD ["gunicorn", "ciutils.wsgi:application", \
     "--bind", "0.0.0.0:8080", "--workers", "2", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-"]
