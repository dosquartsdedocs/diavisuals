# W1 native diagram job storage

**Profile: `diavisuals-private-directory-v1`, control plane 0.7.0.** This is the
explicit native-private adapter for `docker-job-volumes-v1`, pinned to gaContExt
`83cb0d3e2f424759475ae70b423a0f8dca8520b2` (integrated in PR #23). The
[coordinator's marker clarification](https://github.com/dosquartsdedocs/gacontext/issues/22#issuecomment-6055298853)
permits a locator fixed by the authenticated native manager/worker profile.
Source and wheel/sdist ship the separate `mcp-job-storage.json`; its exact bytes
are returned by `diavisuals://job-storage`. The factory schema version and legacy
consumer/Git path policies are independent of this companion.

## Selection and native mapping

The host controller owns a private, bounded external registry. Explicit
preparation of the already selected renderer is required. Initialization and job
admission inspect only; workers use the resulting immutable image ID and
`--pull=never`. No image build, pull, load or alias change occurs in a job.

```bash
# REGISTRY is a new private directory outside the consumer and package roots.
diavisuals --project "$CONSUMER" job init --registry "$REGISTRY"
# Retain the returned admin_grant privately. Allocate returns a separate job grant.
diavisuals --project "$CONSUMER" job --grant "$ADMIN_GRANT" allocate
export DIAVISUALS_JOB_STORAGE_GRANT="$JOB_GRANT"
diavisuals --project "$CONSUMER" job status
MCP_CONSUMER_WORKSPACE="$CONSUMER" diavisuals mcp serve
```

Admin and client grants are private local capabilities, excluded from bundles,
logs and wire states. Registry/job UUIDs and binding JSON alone confer no access.
The selected consumer's path and device/inode are checked independently of
`/work`; neither the environment binding nor D0 native process identity is
rewritten to pretend that the host controller runs in the volume.

| Native operation | Mapping |
| --- | --- |
| `job_storage(request)` / `job control --request JSON` | Exact W1 status, quiesce and seal envelopes; mutations require revision/epoch CAS. |
| `render_job_diagram` / `job render` | Explicit source/variants, expected revision/epoch; snapshot and real render in volumes. No final project publication. |
| `job receiver --root ROOT --prefix PATH` | Admin registers the receiver's explicit durable directory policy and observed filesystem/binding. |
| `job deliver` | Exact product, receiver, destination and CAS; retained-only read lease; complete tree/domain checks and durable no-replace publication. |
| `job plan-release` / `job release` | Manager-native plan digest plus revision/epoch, 30-second freshness and live revalidation. Never execute a self-authored reference plan. |
| `release_session` / stdio EOF | Drop only this process's client interest; last eligible interest drains and retires safe storage. D0 still requires close/wait/reap. |
| `job toggle --jobs ID …` | Per-job outcomes; drop only caller-owned interests and preserve other clients/transfers. |
| `job recover` | Independently observe dead native owners, remove only their exact correlated workers, then release their leases. No TTL-only death inference. |
| `job reopen` | Closed/unleased job only; fresh epoch and a new scratch incarnation if the former was retired. |
| `job discard` | Explicit user decision with current protected-tree hash, CAS, reason and `--confirm-discard`. No inference from toggle/failure/age. |

Administrative commands select `job --grant "$ADMIN_GRANT" --job-id "$JOB"`.
`job list` reports bounded registered job IDs, phases and allocation completion
for recovery. Mutating domain commands use `--expected-revision` and
`--expected-epoch`; inspect current status before retrying a conflict. Sealing
unchanged completed products and quiescing an already closed job are no-ops.

When a W1 grant is selected, legacy rendering/export/project staging and broad
`down` are refused. Consumers without a grant continue to use the existing native
profile. This is an explicit profile selection, not automatic adoption of old
unmanaged staging, old registries or another manager's volumes.

## Physical and source boundary

Each job receives two distinct local, non-bind named volumes. Names are
`gacontext-job-<volume-id>`, with the exact W1 correlation labels, daemon ID,
creation time and immutable marker digest recorded externally. The native marker
is `.diavisuals-w1-marker.json`: canonical ASCII JSON with contract, registry,
job, binding, provider, descriptor hash, daemon, volume ID/name and role.
Neither caller-selected marker paths nor fallback marker discovery are supported.

Workers have no network or Docker socket, a read-only image root, bounded
CPU/memory/PIDs/files, and no host checkout/input/output staging mount. The only
host bind is a bounded, manager-owned read-only metadata file at
`/run/gacontext/job-storage.json`, identified by `MCP_JOB_STORAGE_BINDING`.
Manager inspection/bootstrap tasks are separately leased and use fixed native
control messages. The registry is fenced across their observations.

`inputs/<operation>/` retains the exact UTF-8 file/inline source, effective
request, profile, styles/tools, selected original/edited SVGs, and the trusted
checker/controller snapshot (including pure Python PyYAML). The worker verifies
controller bytes against manager-held hashes before importing them. `/work/results`
holds fresh SVG/PNG/PDF output, `/work/exports` complete native artifact-v1 trees,
and `/work/recovery` bounded execution evidence. Browser and Java HOME/cache/TMPDIR
use the separately mounted scratch volume. A failed/interrupted operation remains
protected even when no complete export can be produced.

The native leaf dependency profile is unchanged: explicit local diagram source
and shipped effective resources, without unbounded includes, URLs or composite
upstream inputs. A new operation/variant creates a new immutable product identity.
The manager covers every protected file by its exact sealed-product hash or an
explicit tree-bound discard; remaining files and unexpected directories become
holds. Physical retained inspection runs without the nested scratch mount, so
hidden material beneath that mountpoint cannot disappear from the inventory.

## Delivery and release

The receiver chooses the product and a destination beneath its registered prefix.
The complete retained tree uses the existing leaf layout; selected generated or
edited SVGs can be referenced at their bundle-relative paths. The producer does
not select Git/LFS policy or the receiver's final directory name.

The receiver profile requires observed local ext4, XFS, Btrfs or ZFS, no symlinks,
and an explicit durable path outside temporary/cache/job roots. Partial delivery
stays in a receiver-owned `delivery-<transaction>` directory, never acknowledged
or overwritten. Sender and receiver domain checks run before acknowledgement;
the manager independently rereads the final tree and records the separate W1
retention envelope and hash. Directory `content_sha256` is the exact `bundle.json`
digest. Every removal revalidates current destination/bundle/domain bytes. Missing,
edited, replaced or unavailable destinations preserve retained storage.

Status performs bounded read-only ledger/Docker/receiver observations. It never
starts an inspection container or refreshes the ledger. Volume observation times
identify the last marker/byte measurement; stale measurements become unknown.
Explicit admission/quiesce/plan operations refresh through leased native probes.

After fencing and verified absence of all clients/writers/readers/transfers and
attachments (including stopped containers), pending jobs can retire scratch alone.
Retained removal also requires complete current inventory and a verified current
decision for every product. Plans are journalled and reapplied under the registry
lock; exact-name `docker volume rm` never uses force. Docker rejects a racing
attachment. Absence is independently inspected before a tombstone is committed.
Interrupted removal resumes from the journal and fresh observations. A released
tombstone preserves historical decisions rather than promising perpetual receiver
retention. Prepared images/packages and unrelated containers/volumes remain outside
the job policy.

## Capacity and explicit limits

- Native Linux, local Unix Docker, `overlay2`, default local volumes on the same
  observed filesystem as image storage. Host mount topology is metadata only;
  actual capacity is measured inside the Docker runtime. Docker's private volume
  `Mountpoint` is never used as an application filesystem.
- 512 MiB scratch and 512 MiB retained per job, 5,000 combined entries, two live
  jobs per registry, 1 GiB minimum free space, 2-second monitoring. Whole ceilings
  remain conservatively reserved for pending jobs; unknown capacity refuses work.
- `job init --min-free-bytes … --max-jobs …` can tighten policy. Hard quotas are
  explicitly refused. Monitoring/cancellation cannot promise zero transient
  overshoot or stop unrelated software filling the disk.
- 32 MiB bounded input stream, at most 16 diagram operations per job, 64 MiB
  files and the existing 256 MiB leaf-product ceiling. Ledger JSON is at most
  1 MiB, 64 registered jobs/tombstones, 16 receivers, 128 concurrent leases and
  128 release journal records. A full ledger refuses further mutation/admission.
- This release profile supports **directory retention**. ZIP/tar-gzip receipt
  formats, cross-registry adoption, shared-hub marker execution, shared global
  reservations and remote Docker require separately selected/tested adapters.
  Its private registry does not account for reservations owned by another manager.
- Native process absence and disk retirement are separate outcomes. SDK termination
  during EOF cleanup can require `job recover` followed by an exact job toggle.
  Unknown owner namespaces or replaced volume identities remain blocked.

## Verification

```bash
make check
make lint tests tests-mcp
make docker-test
DIAVISUALS_W1_DOCKER=1 make tests-install
DIAVISUALS_STORAGE_REFERENCE=/absolute/read-only/gacontext-reference \
  DIAVISUALS_W1_DOCKER=1 .venv/bin/python -m unittest \
  tests.test_job_storage tests.test_job_storage_docker
```

The independent validator reads Git objects at the pin above, not the reference
checkout's mutable HEAD. Real tests exercise both renderers, source/variant closure,
closed-job delivery after scratch removal, receiver relocation, changed final bytes,
actual two-process interests, busy quiesce/controller SIGKILL and exact recovery,
foreign stopped attachment, stale CAS/plan, changed daemon, group toggle,
reactivation and interrupted physical removal. Pressure tests raise the threshold
after real input admission and observe real worker cancellation; they do not fill
the operator's disk. Synthetic durable receiver selections live under ignored
`.w1-receivers/`; failure preserves the external registry and reports its location.
Only exact synthetic fixtures with an explicit test-author discard are retired.

Owner implementation/review/publication evidence is coordinated in
[Diavisuals #16](https://github.com/dosquartsdedocs/diavisuals/issues/16) and
[gaContExt #22](https://github.com/dosquartsdedocs/gacontext/issues/22). A source
declaration or passing reference plan alone is not installed W1 acceptance.
