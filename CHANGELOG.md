# Changelog

## 0.3.0 - 2026-08-26

- Stage only the selected diagram and style assets for Docker rendering.
- Run Mermaid and PlantUML without network access or consumer workspace mounts.
- Add read-only, non-root, capability, process, memory, CPU, file, and tmpfs limits.
- Validate staged artifacts and publish them atomically without replacing valid outputs on failure.
- Pin the Node 24/Puppeteer 25 browser image, Mermaid 11.16.0, PlantUML checksum, Python dependencies, and MCP 1.29.0.
- Add checkout and installed-package factory lifecycles, CI, and wheel/sdist verification.

## 0.2.0 - 2026-08-25

- Added Docker-backed Mermaid and PlantUML MCP rendering.
- Added the `benizar` style family, compatibility profiles, and rendered gallery.
