FROM python:3.11-slim-bookworm

ARG TRIVY_VERSION=0.72.0
ENV TRIVY_VERSION=${TRIVY_VERSION}

# Direct release tarball (more reliable than the install.sh pipe). Keep
# ca-certificates for the runtime vuln-DB fetch over HTTPS.
RUN useradd -m -u 1000 appuser && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \
    curl -sfL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" -o /tmp/trivy.tgz && \
    tar xzf /tmp/trivy.tgz -C /usr/local/bin trivy && rm /tmp/trivy.tgz && \
    apt-get purge -y curl && apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY entrypoint.py .
RUN mkdir -p /home/appuser/.cache/trivy && \
    chown -R appuser:appuser /app /home/appuser

USER appuser
ENTRYPOINT ["python", "entrypoint.py"]
