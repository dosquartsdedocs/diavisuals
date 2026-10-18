ARG BASE_IMAGE=ghcr.io/puppeteer/puppeteer:25.14.0@sha256:ced0f7e1b416fafb4166f9f9d26109ea7bbd7cb04b8a38ae8c14b61f364c3d6f
ARG JAVA_IMAGE=eclipse-temurin:25-jre-jammy@sha256:e0d8c47eccd7ec82d635542dfcd1f2b1293add6bdd7ffbeb650f8ec1b1335425
FROM ${JAVA_IMAGE} AS java
FROM ${BASE_IMAGE} AS builder
USER root
ARG MERMAID_CLI_VERSION=12.0.0
ARG PUPPETEER_VERSION=25.14.0
ARG PLANTUML_VERSION=1.2026.9
ARG PLANTUML_SHA256=aa4a1d06f8911c4b842beff4828dd955be431692b631a312d04c0e9fab9581de
ENV DEBIAN_FRONTEND=noninteractive
COPY package.json package-lock.json /opt/mermaid/
COPY rebundle.mjs /opt/mermaid/rebundle.mjs
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && test "$(node -p "require('/opt/mermaid/package.json').dependencies['@mermaid-js/mermaid-cli']")" = "${MERMAID_CLI_VERSION}" \
    && test "$(node -p "require('/opt/mermaid/package.json').dependencies.puppeteer")" = "${PUPPETEER_VERSION}" \
    && PUPPETEER_SKIP_DOWNLOAD=true npm ci --prefix /opt/mermaid --include=dev \
    && node /opt/mermaid/rebundle.mjs \
    && npm prune --prefix /opt/mermaid --omit=dev --ignore-scripts \
    && npm audit --prefix /opt/mermaid --omit=dev \
    && mkdir -p /opt/plantuml \
    && curl -fL "https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar" -o /opt/plantuml/plantuml.jar \
    && printf '%s  %s\n' "${PLANTUML_SHA256}" /opt/plantuml/plantuml.jar | sha256sum -c - \
    && rm -rf /var/lib/apt/lists/* /root/.npm /tmp/* /var/tmp/*

FROM ${BASE_IMAGE}
USER root
LABEL org.opencontainers.image.title="diavisuals renderer" \
      org.opencontainers.image.version="0.7.0" \
      org.opencontainers.image.description="Offline Mermaid 12 and PlantUML renderer" \
      org.opencontainers.image.source="https://github.com/dosquartsdedocs/diavisuals" \
      io.context.mcp-factory="diavisuals"
ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PLANTUML_SECURITY_PROFILE=SANDBOX \
    PUPPETEER_EXECUTABLE_PATH=/usr/local/bin/diavisuals-chromium \
    XDG_CACHE_HOME=/tmp/cache \
    JAVA_HOME=/opt/java/openjdk \
    PATH=/opt/java/openjdk/bin:${PATH}
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash graphviz libbatik-java libfop-java python3 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*
COPY --from=java /opt/java/openjdk /opt/java/openjdk
COPY --from=builder /opt/mermaid /opt/mermaid
COPY --from=builder /opt/plantuml/plantuml.jar /opt/plantuml/plantuml.jar
RUN env -u PUPPETEER_EXECUTABLE_PATH PUPPETEER_CACHE_DIR=/home/pptruser/.cache/puppeteer node -e \
    "(async()=>{const fs=require('node:fs'); const browser=await require('/opt/mermaid/node_modules/puppeteer').executablePath(); if(!fs.existsSync(browser)) throw new Error('prepared Chromium missing: '+browser); fs.symlinkSync(browser, '/usr/local/bin/diavisuals-chromium');})().catch(error=>{console.error(error);process.exitCode=1;});" \
    && ln -s /opt/mermaid/node_modules/.bin/mmdc /usr/local/bin/mmdc \
    && printf '#!/bin/sh\nexec java -Duser.home="${HOME:-/tmp}" -cp "/opt/plantuml/plantuml.jar:/usr/share/java/*" net.sourceforge.plantuml.Run "$@"\n' > /usr/local/bin/plantuml \
    && chmod 0755 /usr/local/bin/plantuml
WORKDIR /tmp
USER 65532:65532
