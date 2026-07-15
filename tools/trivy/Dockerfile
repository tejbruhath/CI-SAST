FROM python:3.11-slim-bookworm # slim base for Job image

ARG TRIVY_VERSION=0.72.0 # pin Trivy release
ENV TRIVY_VERSION=${TRIVY_VERSION} # available at runtime

# Direct release tarball (more reliable than the install.sh pipe). Keep
# ca-certificates for the runtime vuln-DB fetch over HTTPS.
RUN useradd -m -u 1000 appuser && \ # non-root user
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \ # fetch + TLS
    curl -sfL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-64bit.tar.gz" -o /tmp/trivy.tgz && \
    tar xzf /tmp/trivy.tgz -C /usr/local/bin trivy && rm /tmp/trivy.tgz && \ # install binary
    apt-get purge -y curl && apt-get autoremove -y && \ # drop curl after install
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt # HTTP client for POST
COPY entrypoint.py .
RUN mkdir -p /home/appuser/.cache/trivy && \ # writable DB cache dir
    chown -R appuser:appuser /app /home/appuser

USER appuser # non-root
ENTRYPOINT ["python", "entrypoint.py"] # run Job
