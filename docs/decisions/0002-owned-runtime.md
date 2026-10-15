# ADR 0002: Owned disposable runtime

Status: implemented and verified locally, 2026-10-15 (feature 1).

Use PostgreSQL 17 in Docker, a per-run network, explicit ownership labels, and a
resource manifest that contains no credentials. The host owns Docker; workers
have scoped database access and no Docker socket. Cleanup must match both the run
manifest and ownership labels before deleting anything.

Resolve official PostgreSQL 17 images before allocation, launch their immutable
content ID, and record their repository digest and platform. Image downloads are
explicit so they do not consume the readiness deadline. CI uses the verified
registry digest.

Use a private internal network with no published database port, tmpfs storage,
resource limits, and an ephemeral bootstrap password. Persist allocation intents
before creation and IDs immediately afterward. Atomic replacement and fsync
provide recoverable records; an advisory OS lock protects live runs. Recovery
checks IDs and ownership labels, falling back to an exact intent name only when
an ID was never saved. Never disconnect foreign endpoints or prune Docker.

The established `.pg-rehearse/runs` directory convention is retained. SIGINT and
SIGTERM cause teardown; SIGKILL requires explicit `recover`. Cleanup failures stay
visible and may be retried. Thirteen real integration cases verify the lifecycle.

Worker role grants (feature 3), template reuse (feature 8), and the full migration
pipeline remain pending. See `docs/runtime.md` for commands and supported limits.
