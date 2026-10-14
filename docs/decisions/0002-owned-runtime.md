# ADR 0002: Owned disposable runtime

Status: planned; implementation is feature 1.

Use PostgreSQL 17 in Docker, a per-run network, explicit ownership labels, and a
resource manifest that contains no credentials. The host owns Docker; workers
have scoped database access and no Docker socket. Cleanup must match both the run
manifest and ownership labels before deleting anything.

Pending decisions include image digest pinning, interruption recovery, template
reuse, bounded readiness probing, and worker role grants. Validate these through
real Docker integration tests before calling the lifecycle complete.
