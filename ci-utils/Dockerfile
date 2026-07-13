# Sentriq backend: Django/DRF API + Celery worker.
# Needs git (clone repos) and the docker CLI (run scanner containers via the
# host daemon over the mounted /var/run/docker.sock). Runs as root because it
# talks to the docker socket; scanners themselves run isolated in their images.
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

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

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080
# Default command runs the API (migrations first). The worker service overrides
# this with a celery command (see docker-compose.yml).
CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn ciutils.wsgi:application --bind 0.0.0.0:8080 --workers 3 --timeout 120 --access-logfile - --error-logfile -"]
