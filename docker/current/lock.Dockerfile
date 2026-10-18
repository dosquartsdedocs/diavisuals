# Explicit preparation only: generate the reviewed lock without executing scripts.
FROM ghcr.io/puppeteer/puppeteer:25.14.0@sha256:ced0f7e1b416fafb4166f9f9d26109ea7bbd7cb04b8a38ae8c14b61f364c3d6f AS lock
USER root
WORKDIR /locked
COPY package.json .
ENV PUPPETEER_SKIP_DOWNLOAD=true
RUN npm install --package-lock-only --ignore-scripts --no-fund

FROM scratch AS lock-export
COPY --from=lock /locked/package-lock.json /package-lock.json
