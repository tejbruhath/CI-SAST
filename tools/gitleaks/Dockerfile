FROM python:3.11-slim-bookworm

ARG GITLEAKS_VERSION=8.18.0
ENV GITLEAKS_VERSION=${GITLEAKS_VERSION}

RUN useradd -m -u 1000 appuser && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -L "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" | \
    tar xz -C /usr/local/bin gitleaks && \
    chmod +x /usr/local/bin/gitleaks && \
    apt-get purge -y curl && apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY entrypoint.py .
RUN chown -R appuser:appuser /app

USER appuser
ENTRYPOINT ["python", "entrypoint.py"]
