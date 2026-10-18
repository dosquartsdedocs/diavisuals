# Immutable W1 test reference

`reference.tar` is a Git archive of exactly these three normative files from
gaContExt revision `83cb0d3e2f424759475ae70b423a0f8dca8520b2`:

- `src/bash/mcp_factories/job-storage-v1.schema.json`
- `src/bash/mcp_factories/mcp_job_storage/contract.py`
- `src/bash/mcp_factories/mcp_job_storage/planner.py`

It contains no consumer data, credentials, checkout or unrelated hub code.
The upstream checker/planner/schema bytes are unchanged. This fixture makes
the independent conformance gate executable on runners that cannot authenticate
to the private reference repository. `tests/job_storage_reference.py` checks
the archive digest before bounded extraction and supplies only JSON/error/file
primitives needed by the unmodified reference imports. With
`DIAVISUALS_STORAGE_REFERENCE` selected it additionally compares these exact
files with the pinned Git objects and uses the original dependency modules.

This test-data archive is unrelated to receiver retention-format support.
