FROM debian:bookworm-slim

ARG MERMAID_CLI_VERSION=11.4.2
ARG PLANTUML_VERSION=1.2026.1

ENV DEBIAN_FRONTEND=noninteractive
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        bash \
        chromium \
        curl \
        default-jre-headless \
        graphviz \
        libbatik-java \
        libfop-java \
        make \
        nodejs \
        npm \
        python3 \
    && npm install -g "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}" \
    && mkdir -p /opt/plantuml \
    && curl -fL "https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar" -o /opt/plantuml/plantuml.jar \
    && printf '#!/bin/sh\nexec java -Duser.home="${HOME:-/tmp}" -cp "/opt/plantuml/plantuml.jar:/usr/share/java/*" net.sourceforge.plantuml.Run "$@"\n' > /usr/local/bin/plantuml \
    && chmod +x /usr/local/bin/plantuml \
    && npm cache clean --force \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /workspace
