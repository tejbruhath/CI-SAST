# Sentriq backend: Django/DRF API + Celery worker.
# Needs git (clone repos) and the docker CLI (run scanner containers via the
# host daemon over the mounted /var/run/docker.sock). Runs as root because it
# talks to the docker socket; scanners themselves run isolated in their images.
# Small Debian-based Python 3.11 runtime image.
FROM python:3.11-slim-bookworm

# Live logs to stdout; skip writing .pyc bytecode into the image layers.
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# Install git/TLS tools, Postgres build deps, then docker CLI only (not daemon).
# Docker apt key + repo match bookworm so docker-ce-cli installs cleanly.
# Purge build-essential after install to shrink the final image size.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl gnupg build-essential libpq-dev \
    && install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/debian bookworm stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && apt-get purge -y build-essential && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Application working directory inside the container.
WORKDIR /app
# Copy deps first so Docker can cache the pip layer when code changes only.
COPY requirements.txt .
# Install Python packages without keeping pip's download cache in the image.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the full ci-utils project source into /app.
COPY . .

# Document the API listen port (gunicorn binds here at runtime).
EXPOSE 8080

RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
# Default command runs the API (migrations first). The worker service overrides
# this with a celery command (see docker-compose.yml).
# Migrate DB schema, then serve WSGI with three workers and 120s timeout.
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn ciutils.wsgi:application --bind 0.0.0.0:8080 --workers 3 --timeout 120 --access-logfile - --error-logfile -"]
