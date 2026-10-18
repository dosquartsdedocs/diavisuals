# Fresh audit in an explicit preparation build; renderer executions stay offline.
FROM ghcr.io/puppeteer/puppeteer:25.14.0@sha256:ced0f7e1b416fafb4166f9f9d26109ea7bbd7cb04b8a38ae8c14b61f364c3d6f AS audit
USER root
WORKDIR /locked
COPY package.json package-lock.json ./
RUN npm audit --omit=dev --json > npm-audit.json

FROM scratch AS audit-export
COPY --from=audit /locked/npm-audit.json /npm-audit.json
