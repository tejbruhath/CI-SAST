FROM python:3.11-slim-bookworm

ARG SONAR_SCANNER_VERSION=5.0.1.3006
ENV SONAR_SCANNER_VERSION=${SONAR_SCANNER_VERSION}

RUN useradd -m -u 1000 appuser && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        wget unzip ca-certificates \
        openjdk-17-jre-headless \
        nodejs && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

RUN wget -q "https://binaries.sonarsource.com/Distribution/sonar-scanner-cli/sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip" && \
    unzip -q "sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip" && \
    mv "sonar-scanner-${SONAR_SCANNER_VERSION}-linux" /opt/sonar-scanner && \
    ln -s /opt/sonar-scanner/bin/sonar-scanner /usr/local/bin/sonar-scanner && \
    rm "sonar-scanner-cli-${SONAR_SCANNER_VERSION}-linux.zip"

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY entrypoint.py .
# sonar-scanner writes .sonar cache under $HOME; keep it writable for appuser
ENV SONAR_USER_HOME=/tmp/.sonar
RUN chown -R appuser:appuser /app

USER appuser
ENTRYPOINT ["python", "entrypoint.py"]
