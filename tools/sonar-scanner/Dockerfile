FROM python:3.11-slim-bookworm # base image for sonar client Job

ARG SONAR_SCANNER_VERSION=5.0.1.3006 # pin scanner CLI
ENV SONAR_SCANNER_VERSION=${SONAR_SCANNER_VERSION}

# Java required by sonar-scanner; nodejs helps some language analyses.
RUN useradd -m -u 1000 appuser && \ # non-root runtime user
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget unzip ca-certificates \ # download/unzip scanner
        openjdk-17-jre-headless \ # Java runtime for scanner
        nodejs && \ # optional language support
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 # where JRE lives

# Download and install official SonarScanner CLI zip.
RUN wget -q "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip" && \
    unzip -q "sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip" && \
    mv "sonar-scanner-${SONAR_SCANNER_VERSION}-linux" /opt/sonar-scanner && \ # install under /opt
    ln -s /opt/sonar-scanner/bin/sonar-scanner /usr/local/bin/sonar-scanner && \ # on PATH
    rm "sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip" # drop zip

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt # requests for API poll/POST
COPY entrypoint.py .
# sonar-scanner writes .sonar cache under $HOME; keep it writable for appuser
ENV SONAR_USER_HOME=/tmp/.sonar # avoid writing to non-writable $HOME
RUN chown -R appuser:appuser /app

USER appuser
ENTRYPOINT ["python", "entrypoint.py"] # Job entrypoint
