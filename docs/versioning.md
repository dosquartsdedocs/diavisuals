# Versioning And Compatibility

`diavisuals` uses normal short release tags for the repository and separate compatibility profiles for render-engine guarantees.

## Release Tags

Git tags should be SemVer names:

```text
v0.1.0
v0.2.0
v0.3.0
v1.0.0
```

Do not create Git tags such as `compat/mermaid-11.16.0-plantuml-1.2026.1` or `mermaid-11.16.0-plantuml-1.2026.1`. Those names are useful as compatibility profile identifiers, but they are too long and too implementation-specific for releases.

A release tag means: this repository version of tokens, style presets, per-diagram overrides, tools, examples, compatibility profiles, and rendered gallery manifests has been reviewed together.

## Compatibility Profiles

Files under `compat/` describe the render engines and diagram types covered by a release. The profile id can be descriptive because it is machine-readable metadata, not a Git tag.

Current default profile:

```text
compat/mermaid-11.16.0-plantuml-1.2026.1.env
```

It records:

- Mermaid CLI: 11.16.0
- PlantUML: 1.2026.1
- Family: `benizar`
- Gallery manifest: `docs/gallery/benizar/mermaid-11.16.0-plantuml-1.2026.1/manifest.csv`

The older `mermaid-10.9.1-plantuml-1.2020.02` and `mermaid-11.4.2-plantuml-1.2026.1` profiles remain as record-only compatibility history and cannot build renderers from the current checkout.

## Badges And Release Notes

Use README badges and release notes to show what a short tag contains. For example:

```markdown
![release](https://img.shields.io/badge/release-v0.3.0-blue)
![Mermaid CLI](https://img.shields.io/badge/Mermaid_CLI-11.16.0-ff3670)
![PlantUML](https://img.shields.io/badge/PlantUML-1.2026.1-2a5db0)
```

The badge text and `docs/releases.md` should be updated when a release changes engine versions, families, or guaranteed diagram types.

## Release Rule

- A purely visual change within the same compatibility contract can be a normal patch or minor `diavisuals` release.
- A change that adds or removes supported diagram types must update the relevant compatibility profile and gallery manifest.
- A Mermaid or PlantUML engine upgrade must create a new compatibility profile instead of overwriting an older one.
- Child projects should pin a short `diavisuals` release tag such as `v0.1.0` and state which compatibility profile they render in CI, Docker, or project documentation.

## Gallery

Versioned galleries live in:

```text
docs/gallery/<family>/<compat-id>/
```

Regenerate the default gallery with:

```bash
make render-gallery
```

The target uses a networkless, read-only Docker container so the result does not depend on locally installed tools. Only the selected examples, styles, profile, and gallery tools are staged; the result directory is the sole writable bind mount.
