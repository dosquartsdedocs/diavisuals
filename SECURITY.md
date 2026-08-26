# Security Policy

## Supported Version

Security fixes are applied to the latest release.

## Reporting

Report vulnerabilities through GitHub private vulnerability reporting for
`dosquartsdedocs/diavisuals`. Do not include private consumer diagrams or
workspace content in a public issue.

## Runtime Boundary

The MCP fixes the consumer root at startup. Diagram inputs and outputs must stay
inside that root, and symlinked path components are rejected. Rendering stages
only the selected source and style assets in a private directory; the consumer
workspace and package root are never mounted into the renderer container.

Renderer containers run without networking, with a read-only root filesystem,
all Linux capabilities dropped, `no-new-privileges`, a non-root user, private
tmpfs storage, and CPU, memory, process, descriptor, and output-size limits.
Only the private result directory is writable. Validated artifacts are copied
to a same-filesystem temporary file and atomically replace the requested output.

Docker daemon access remains a privileged host capability. Only trusted users
should install or configure renderer images, compatibility profiles, or the
Docker daemon used by this package.
