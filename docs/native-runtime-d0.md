# Native runtime / live identity — D0

Diavisuals **0.6.0** implements the native Python **stdio** profile against
[gaContExt D0 at `5634ea2e3e42122bb365992dfca9f248feb89dec`](https://github.com/dosquartsdedocs/gacontext/blob/5634ea2e3e42122bb365992dfca9f248feb89dec/src/bash/mcp_factories/NATIVE_RUNTIME_REQUIREMENTS.md).
Owner tracking: [Diavisuals #14](https://github.com/dosquartsdedocs/diavisuals/issues/14);
coordination: [gaContExt #15](https://github.com/dosquartsdedocs/gacontext/issues/15).
This maps existing native interfaces and adds process/lifecycle observation; it
does not introduce a central manifest schema or change coordinator helper pins.

## Preparation and launch

Prepare the package with its pinned direct dependencies (`PyYAML==6.0.3`, optional
`mcp==1.29.0` and that package's declared dependency closure), a supported Python
environment and a reachable Docker CLI/daemon. Source preparation uses `uv.lock`;
installed acceptance records the actual prepared package/dependency inventory.
The wheel includes the CLI/MCP, styles, profiles, tools and teaching/gallery assets.
Rendering needs the separately verified Docker image; normal use needs no engine
checkout. The supported tested host profile is Linux with `/proc` PID/start/boot
observations. See [published artifacts](releases.md#published-artifacts).

Preparation is explicit (`make mcp-build` or installed-package acquisition followed
by the verified renderer bootstrap). The Make stdio transport and factory
serve/status launchers require the prepared CLI and never call `uv sync` on normal
launch/inspection. Generated client snippets bind the interpreter and the owned
`diavisuals/stdio.py` entry point, avoiding a consumer cwd as a Python module search
root. The installed `diavisuals mcp serve` entry point is also supported.

Use the existing [runtime selector](runtime-selection.md):

- `--runtime-image` / `DIAVISUALS_RUNTIME_IMAGE`;
- `--runtime-expected-id` / `DIAVISUALS_RUNTIME_EXPECTED_ID`.

Full IDs identify themselves; an alias requires an expected ID; a repository
digest must be recorded locally. The MCP freezes that selection at startup.
Normal MCP rendering inspects prepared images even in default-profile mode; it
never builds a missing image. Standalone legacy CLI preparation/default rendering
retains its documented behavior. A managed adapter must use an explicit verified
selection, not treat the unpinned default alias as a managed release selection.

## Observation from the actual serving connection

| Native surface | Meaning |
| --- | --- |
| MCP `server_identity()` | Bounded, read-only observation of this serving process. |
| Resource `diavisuals://server/identity` | Same observation and stable instance as the tool. |
| Existing `renderer_status()` / CLI `renderer-status` | Selected-renderer observation only; not a replacement for live server identity. |

The live packet contains:

- `instance`: process-lifetime UUID, native PID, startup parent PID, UID, server
  startup UTC time, Linux process start ticks, boot ID and PID namespace.
- `loaded`: version captured from imported code, installed/development mode,
  package root, loaded Python code-object revision, startup source fingerprint
  and startup installed-metadata observation. A checkout HEAD is labelled as a
  startup metadata observation, not used as the loaded-code revision.
- `current_disk`: current source/metadata hashes and version, drift or unavailable
  observation. Changing METADATA or source files does not relabel the loaded
  version/revision. Work refuses drift until restart; identity remains available.
- `interpreter`: effective executable, resolved executable and Python version.
- `binding`: startup-fixed canonical consumer path in the native server, and the
  private worker input/output paths. The renderer never mounts the consumer.
- `resources`, `renderer`: startup/current profile hash, resource-root observation,
  selected ref/expected ID versus observed actual image ID and explicit diagnostics.
- `docker_daemon`: observed daemon ID and first-observation comparison. A changed
  or unavailable daemon cannot authorize cleanup on another endpoint.
- `lifecycle`, `bounds`: connection/job state and limits. `pinned_runtime_ready`
  describes local observed prerequisites, **not verification of an external
  preparation receipt or completion of hub adapter acceptance**.

Identity reads process and package/profile metadata only: no consumer enumeration,
prose, authored source, CV/student data, secrets, registration edits or preparation.
Responses contain hashes/counts rather than source/metadata contents. Package
source inspection is capped at 32 Python files / 4 MiB and directory enumeration
at 128 entries; installed metadata is capped at 1 MiB. Unknown observations stay
unknown. The code-object digest is interpreter/install-path specific; the portable
release identity remains the verified distribution and source fingerprint.

This is explicitly an observation, not permanent process attestation. A new stdio
process receives a new UUID; multiple observations of the same process retain it.
There is one backend per stdio connection. Shared HTTP, a multi-client stdio proxy
and an outer Docker MCP launcher are **not claimed profiles**. A wrapper PID is not
the reported Python PID; a renderer's container PID is never compared with it.
Namespace/boot/start information must agree before a native PID comparison is used.

## Busy, drain, exit and crash recovery

`release_session(expected_instance_id)` is a **live MCP tool**, scoped to that
stdio instance. It refuses a wrong ID, busy work or unverified worker cleanup.
When idle it changes state to `draining`, rejects new work, and tells the caller
to close that stdio connection and wait for that exact process to exit. Its reply
does not claim process/RAM release while the process is still serving the reply.

Mutating operations run off the protocol loop, so identity and release remain
responsive while a job runs. One mutating operation is permitted per instance;
concurrent submissions receive busy errors rather than an unbounded queue. EOF
allows bounded work/cleanup to finish; adapters should drain first. There is no
shared backend or timer-based idle service: the stdio connection owns the process.
Abrupt client termination/SIGKILL can leave a worker or private staging directory.

Workers retain the existing factory/workspace labels plus exact instance, job,
owner PID/start/boot/namespace/UID, actual image ID and daemon ID. The Docker CID
file supplies the full container ID; live job observations and render/export
responses expose the correlation. An observed CID is labelled `identified`, not
misrepresented as a separately inspected running state. Cleanup checks ownership
and removes **by exact ID**, then inspects absence. Name collisions, wrong labels,
unknown ownership and changed daemons fail without removing the foreign object.

The recovery CLI uses identity retained from the live connection:

```bash
diavisuals --project /absolute/consumer inspect-session \
  --instance-id INSTANCE --pid PID --start-ticks TICKS \
  --boot-id BOOT --pid-namespace 'pid:[NAMESPACE]' --daemon-id DAEMON

diavisuals --project /absolute/consumer release-session \
  --instance-id INSTANCE --pid PID --start-ticks TICKS \
  --boot-id BOOT --pid-namespace 'pid:[NAMESPACE]' --daemon-id DAEMON \
  --container-id EXACT_64_HEX_ID
```

`inspect-session` is read-only. CLI `release-session` is orphan recovery, distinct
from the live drain tool: it requires an observed **dead** owner in the same
boot/PID namespace and UID, the same daemon, exact requested container IDs and
matching consumer/instance/job/image labels. Alive or unknown owners are never
stopped. Inventory is bounded to 16 containers and preflighted before removal;
foreign IDs are refused. Absence is rechecked before release is reported. The
caller still owns reaping its child process; this API never signals arbitrary PIDs.

Legacy `down` / `make mcp-down` remains an explicitly **workspace-wide force
operation affecting all instances of that workspace**. It is not the D0 adapter's
ordinary per-client off action. Preserve other clients by using live drain/EOF,
and exact orphan recovery only when needed. Images, packages, persistent volumes,
author files and retained bundles are preserved. Disk cleanup (including orphaned
private staging) is a separate explicit reference-aware operation.

Workers remain network-none, pull-never, read-only, non-root, 1 GiB memory/swap,
2 CPUs, 256 PIDs, bounded descriptors/files and 300 seconds execution timeout.
Docker inspection/removal and diagnostic draining have their additional bounded
timeouts; 300 seconds is not a total process-shutdown SLA. Bounds are per worker
and per stdio instance, not a global cap across independent clients.

## Acceptance and remaining gate

Acceptance uses synthetic consumers and the real Docker executable, without an
alias wrapper. It covers tool/resource agreement, same-version reconnect, stable
loaded identity under on-disk metadata mutation, offline useful rendering, missing
and wrong explicit images, busy refusal, independent-client detach, last-client
termination, an actual crashed controller with a paused owned worker, exact orphan
cleanup, unknown namespace/foreign refusal and reactivation. The audit guard denies
internet/DNS, implicit preparation and (in installed tests) mutable checkout reads.
Prepared package/source/metadata and author/foreign-registration bytes are rechecked.

Actual version A/B/A uses the checksum-verified published **0.5.0** wheel and the
real **0.6.0** distribution, not a renamed copy. 0.5.0 can render/coexist/rollback
but has no complete live instance/loaded-package identity endpoint. That observation
is explicitly partial. **Two complete D0 live-identity release points are not yet
available**; a second real supporting delivery is required before that full gate
can be claimed. No continuous version interval or coordinator helper upgrade is
inferred. Hub adapter intake and older coordinator acceptance remain separate.
