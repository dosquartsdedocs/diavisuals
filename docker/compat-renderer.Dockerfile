ARG BASE_IMAGE=ghcr.io/puppeteer/puppeteer:25.9.0@sha256:5c341215d78353c3416b6c92aae9fac66e8f11c146c3753234980443d6792f8f
FROM ${BASE_IMAGE} AS builder

USER root

ARG MERMAID_CLI_VERSION=11.16.0
ARG PUPPETEER_VERSION=25.9.0
ARG PLANTUML_VERSION=1.2026.1
ARG PLANTUML_SHA256=89c116168a2a0f7cf5292e11617ba22abd743f891914f1fec5bc9c7d257b3092

ENV DEBIAN_FRONTEND=noninteractive

COPY package.json package-lock.json /opt/mermaid/

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
    && test "$(node -p "require('/opt/mermaid/package.json').dependencies['@mermaid-js/mermaid-cli']")" = "${MERMAID_CLI_VERSION}" \
    && test "$(node -p "require('/opt/mermaid/package.json').dependencies.puppeteer")" = "${PUPPETEER_VERSION}" \
    && PUPPETEER_SKIP_DOWNLOAD=true npm ci --prefix /opt/mermaid --omit=dev \
    && mkdir -p /opt/plantuml \
    && curl -fL "https://github.com/plantuml/plantuml/releases/download/v${PLANTUML_VERSION}/plantuml-${PLANTUML_VERSION}.jar" -o /opt/plantuml/plantuml.jar \
    && printf '%s  %s\n' "${PLANTUML_SHA256}" /opt/plantuml/plantuml.jar | sha256sum -c - \
    && rm -rf /var/lib/apt/lists/* /root/.npm /tmp/* /var/tmp/*

FROM ${BASE_IMAGE}

USER root

LABEL org.opencontainers.image.title="diavisuals renderer" \
      org.opencontainers.image.description="Offline Mermaid and PlantUML renderer" \
      org.opencontainers.image.source="https://github.com/dosquartsdedocs/diavisuals" \
      io.context.mcp-factory="diavisuals"

ENV DEBIAN_FRONTEND=noninteractive \
    HOME=/tmp \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PLANTUML_SECURITY_PROFILE=SANDBOX \
    PUPPETEER_EXECUTABLE_PATH=/home/pptruser/.cache/puppeteer/chrome/linux-152.0.7977.54/chrome-linux64/chrome \
    XDG_CACHE_HOME=/tmp/cache

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        bash \
        default-jre-headless \
        graphviz \
        libbatik-java \
        libfop-java \
        python3 \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY --from=builder /opt/mermaid /opt/mermaid
COPY --from=builder /opt/plantuml/plantuml.jar /opt/plantuml/plantuml.jar

RUN ln -s /opt/mermaid/node_modules/.bin/mmdc /usr/local/bin/mmdc \
    && printf '#!/bin/sh\nexec java -Duser.home="${HOME:-/tmp}" -cp "/opt/plantuml/plantuml.jar:/usr/share/java/*" net.sourceforge.plantuml.Run "$@"\n' > /usr/local/bin/plantuml \
    && chmod 0755 /usr/local/bin/plantuml

WORKDIR /tmp
USER 65532:65532
