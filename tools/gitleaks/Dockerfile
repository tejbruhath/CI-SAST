FROM python:3.11-slim-bookworm # slim base for Job image size

ARG GITLEAKS_VERSION=8.18.0 # pin gitleaks release at build time
ENV GITLEAKS_VERSION=${GITLEAKS_VERSION} # expose version to entrypoint

# Install non-root user + gitleaks binary, then drop curl for smaller image.
RUN useradd -m -u 1000 appuser && \ # uid 1000 for non-root runtime
    apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates && \ # download tools
    curl -L "https://github.com/gitleaks/gitleaks/releases/download/v${GITLEAKS_VERSION}/gitleaks_${GITLEAKS_VERSION}_linux_x64.tar.gz" | \
    tar xz -C /usr/local/bin gitleaks && \ # extract only the binary
    chmod +x /usr/local/bin/gitleaks && \
    apt-get purge -y curl && apt-get autoremove -y && \ # remove build-only packages
    apt-get clean && rm -rf /var/lib/apt/lists/* # shrink layer

WORKDIR /app # app files live here
COPY requirements.txt . # Python deps first (cache-friendly)
RUN pip install --no-cache-dir -r requirements.txt # requests etc.
COPY entrypoint.py . # Job runner script
RUN chown -R appuser:appuser /app # non-root ownership

USER appuser # never run scanner as root
ENTRYPOINT ["python", "entrypoint.py"] # k8s Job entrypoint
