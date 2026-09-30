# Exact renderer audit exception — 2026-09-30

The owner explicitly accepted this bounded exception during the 0.5.0 closeout
after the initial PR CI run failed. This is a retained risk/applicability decision,
not a claim that the dependency has been patched or that `npm audit` found nothing.

## Finding and scope

- Advisory: [GHSA-p98j-92pf-mc4p](https://github.com/advisories/GHSA-p98j-92pf-mc4p),
  published 2026-09-30 at 15:37:57Z; severity **low**, CVSS v4 **2.3**.
- Package: DOMPurify **3.4.14**, fixed upstream in **3.4.16**.
- Exact reused image:
  `sha256:5a6887b372a0e1c386a7b54981d11ae1910215baeb6a12dfd0706b3e85ef0846`.
- Exact `docker/package-lock.json` SHA-256:
  `48e4128ecfebd45fd751aef50d96b10b01e9768ee0797a441735c4eb5de2b438`.
- Renderer archive SHA-256:
  `de5d98d6bcff2f427e2ce83db6e7a14edaf6963d199483cb68674ab43d3d75e4`.

The first CI failure is retained at
[run 36769117412](https://github.com/dosquartsdedocs/diavisuals/actions/runs/36769117412).
The owner chose to preserve the published renderer and accept this one finding,
with all other findings still blocking. Replacing the renderer with patched
dependency bytes requires a separate reviewed runtime identity and acceptance.

## Applicability review

The advisory requires **all** of: sanitizing a caller-owned live DOM node with
`IN_PLACE`, a node-removing `afterSanitizeElements` or `afterSanitizeAttributes`
hook, and a detached descendant retaining its event handlers.

The exact image was inspected in a mount-free, network-disabled, read-only,
non-root container. Its Mermaid library is **11.17.2** (the separately versioned
Mermaid CLI remains **11.16.0**). The inspected Mermaid call sites sanitize
strings (`txt`, serialized SVG `code`, title/text). Its `afterSanitizeAttributes`
hook restores anchor `target`, removes a temporary **attribute**, and adds
`rel=noopener`; it does not remove a DOM node. These inspected call paths do not
satisfy the advisory's live-node plus node-removing-hook preconditions.

Image-local reviewed files:

| Path below `/opt/mermaid/node_modules/mermaid/dist/` | SHA-256 |
| --- | --- |
| `mermaid.core.mjs` | `19f24f8cd5bf77ef366f63698b45377ffe6b346e78e6ed0ee5ba121f7b42ed7c` |
| `chunks/mermaid.core/chunk-DU6HZSFF.mjs` | `3e097dc503ef753116bb327d93a8592e3dbbcaa9cc2a3696e552a982c6a41bb6` |

The sandbox remains required, but network isolation alone is not the rationale
for dismissing a DOM-XSS advisory. This decision is scoped to the inspected
renderer usage and exact bytes, not general use of DOMPurify or arbitrary custom
images, hooks, resource trees or browser applications.

## Enforcement

CI still obtains the complete `npm audit --omit=dev --json` report, including the
original audit exit code. `tools/check-renderer-audit.py`:

- Checks the actual inspected image ID and exact lock hash/version.
- Accepts a clean report, or exactly this single low-severity DOMPurify advisory
  at `node_modules/dompurify`, with the reviewed advisory URL/title.
- Rejects all other packages/advisories, changed severity/title/scope, additional
  findings, inconsistent totals, incomplete/error reports and audit command errors.

It is not a severity-wide threshold or a `continue-on-error` gate. Regression
tests cover the accepted finding and each rejected variation. The publication
receipt records the exception so downstream owners can make their own adoption
decision. Existing consumer pins and renderer aliases are not changed by it.
