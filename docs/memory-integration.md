# Shared gaContExt memory

Diavisuals and shared memory are separate MCP services. Updating the diagram
package updates its renderer, tools and agent guidance; it does not provision,
migrate or activate gaContExt's memory service.

When the client exposes gaContExt's memory tools, agents should:

1. Recall context for the technical factory name `diavisuals` at task start.
2. Review the factory backlog before development and read complete truncated notes.
3. Record reusable style preferences and future diagram ideas with concise source
   evidence. Tentative ideas stay candidate/open until requirements are supplied.
4. Use the selected original consumer's stable project binding for project-specific
   guidance. A W1 execution root such as `/work` is not that consumer project.

The same owner-wide memory service can provide context across factories. The
renderer itself does not read the memory database, and bundles contain only their
explicitly selected diagram sources/resources, never an export of memory notes or
transport grants. There is no secondary project-local memory store.

The instructions ship in `AGENTS.md` and are exposed by
`diavisuals://agent-guide` in both source and installed packages. The protocol
tests read this resource through modern MCP 2 and legacy MCP 1 clients.

If memory tools are absent, continue ordinary rendering and state that persistence
was unavailable. Enable the companion through the client's gaContExt registration
and start a normal new client session when registration/instruction changes require
it. Do not terminate another busy session to pick up an upgrade.
