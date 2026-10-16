# End-to-end code review

Reviewed the connected implementation and tests for all roadmap steps on
2026-10-16. Review is evidence about the inspected code, not a claim that every
possible production failure has been excluded. Actual test/build outcomes are in
`../PROGRESS.md`; the labeled and fault matrix is in `../evaluation/README.md`.

| Steps | Code inspected | Preserved boundary / review result |
| --- | --- | --- |
| 1 | runtime/docker, manifest, cleanup; orchestrator | Exact ownership/intent cleanup retained; manifest reads bounded; first cleanup signal now finishes teardown |
| 2 | config, models, migration/preflight and classify | Parse/path/type limits retained; malformed UTF-8 paths now rejected before allocation |
| 3 | worker, worker_protocol, runtime/roles and worker, Dockerfile | Scoped roles, private network, no host mounts/socket, bounded receipts; nested timer ownership repaired |
| 4–5 | fixtures/seed and validate; workload/contracts, runner and assertions | Ordered deterministic fixtures, typed assertions, rollback recovery and result limits retained |
| 6 | migration/executor and catalog | Transaction/autocommit evidence retained; surviving index facts now checked across later DDL |
| 7 | analysis/compatibility and coverage; report renderers | Missing evidence stays inconclusive; completion/verdict/coverage/cleanup independent |
| 8 | fixtures/template and clone; host clone helpers | Sealed template/seed identity, fresh branches, marker-checked early deletion retained |
| 9 | rollout/phases, validation, runner, mixed_writes, rollback; workload/sessions | Persistent/fresh sessions, committed cross-version writes and separate rollback remain explicit |
| 10 | rollout/apps and orders_app; example HTTP entry points | Real application lifecycle and domain failures remain distinct from SQL-only results |
| 11 | migration grammar, executor, catalog; rollout tests | Supported index/CHECK boundaries retained; CHECK predicate equivalence remains a documented limit |
| 12 | observe/locks, runner, validation; analysis/locks | Actor barriers, required wait/release evidence and server/host deadlines retained |
| 13 | observe/timings, benchmarks/*, analysis/performance | Fresh trial arms, raw failed attempts, A/A controls and advisory quality retained |
| 14 | observe/plans, analysis/plans | Separate diagnostic clones, execution consent, private raw plans and sanitized structures retained |
| 15 | report/html, template, JSON/Markdown/terminal, orchestrator | Escaped static data and atomic final reports retained; incomplete saved diagnostics no longer crash terminal rendering |
| 16 | onboarding/* and CLI | Exclusive init, real demo, bounded saved reports and selected owned recovery retained |
| 17 | CI, pyproject, lock, Makefile, distribution script | Locked builds, external installs, expected-failure assertions and artifact allowlists retained |
| 18 | evaluation/cases, evaluation runner, unit/e2e/fault tests | Labels compare actual outcomes; no expected verdict is fed into product analysis |
| 19 | release/pilot docs, changelog, execution guide | Preparation complete; actual independent pilot and remote release gates remain pending |

Two small simplifications were justified: `experiment_id` now validates against
the existing WorkerTask type instead of duplicating its vocabulary, and catalog
verification uses one expected index map for new and surviving indexes. Other
lifecycle/evidence loops preserve distinct ordering, ownership or error behavior;
shortening them merely to reduce line count would obscure those requirements.

The audit repaired concrete failure paths rather than adding dependencies or
generalizing the architecture. Full SQL semantics depend on accepted inputs and
the trusted worker image. CHECK receipt definitions are retained, but catalog
verification does not independently prove predicate equivalence: PostgreSQL's
coercions and IN/ANY rewrites make naive text/AST equality unsound. Real declared
write assertions remain necessary. External pilot, remote CI and browser visual
acceptance cannot be inferred from automated local checks.
