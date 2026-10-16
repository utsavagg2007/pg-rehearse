# Labeled evaluation and fault audit

Prepare the locked environment, PostgreSQL 17 and matching worker, then run:

```sh
uv run --locked python scripts/evaluate.py --output .pg-rehearse/evaluation
uv run --locked pytest --run-docker
```

Evaluation output must be a new directory. `src/pg_rehearse/evaluation/cases.py`
is the fixed expectation catalog. It never supplies verdicts to analysis. The
runner calls the same real pipeline used by `run`, compares each outcome and
retains private JSON/Markdown/HTML reports with incremental summaries. Exit 0 means
every expectation matched, including expected failures; it is not a migration pass.
Any unexpected exit, missing evidence, mismatched coverage or incomplete cleanup
makes the evaluation fail. Interrupted evaluation cannot claim a complete matrix.

| Case | Label | Exit | Completion / verdict | Required evidence |
| --- | --- | --- | --- | --- |
| index-create | compatible | 0 | complete / pass | Complete contracts/catalog, cleanup |
| index-drop | compatible | 0 | complete / pass | Complete contracts/catalog, cleanup |
| check-add | compatible | 0 | complete / pass | Existing reads pass; CHECK remains NOT VALID |
| rename | incompatible | 1 | complete / fail | DEPLOYED_SQL_ERROR, 42703 |
| check-write | incompatible | 1 | complete / fail | DEPLOYED_SQL_ERROR, 23514 |
| unsupported-add-column | unsupported | 4 | no run result | No run directory/allocation |
| lock-deadline | inconclusive | 4 | complete / inconclusive | 55P03, observed wait/release and attempted checks, cleanup |

False passes mean an expected non-passing case received pass; false failures mean
an expected pass received fail. Other unexpected outcomes remain mismatches rather
than being silently assigned either label. Synthetic examples establish bounded
behavior, not production representativeness or a statistical accuracy estimate.
An experiment may complete and cover every declared observation while its verdict
stays inconclusive because SQL timed out. Coverage describes observed checks;
successful migration execution is a separate fact.

## Failure-path audit

The full suite covers these connected boundaries against real PostgreSQL, with
unit checks for pure trust-boundary and evidence decisions:

| Boundary | Checks |
| --- | --- |
| Input before allocation | Invalid YAML/paths/Unicode/SQL/bindings, unsupported variants; unit strict inputs and preflight |
| Allocation and bookkeeping | Readiness/partial allocation, lost create responses, failed manifest writes; integration runtime/faults |
| Worker | Scope/permissions, malformed/missing/oversized receipts, crashes, authentication, deadlines; integration worker |
| Baseline and SQL | Invalid fixtures, semantic mismatch, transaction recovery, failed migrations, independent branches; baseline/rehearsal |
| Evidence | Tampered actors, commits, coverage, schedules, plans, surviving index facts; unit protocol/catalog and real rollout/observations |
| Cleanup | Foreign IDs/labels/endpoints, active locks, failed removals, original failure precedence; runtime/rehearsal/onboarding |
| Reports | JSON/Markdown/HTML write faults, stale-pass prevention, hostile HTML, bounded saved files, incomplete diagnostics |
| Interruptions | Real SIGINT/SIGTERM/SIGKILL lifecycle recovery; first signal during teardown; full-rehearsal report/exit preservation |
| Measurement | Lost connection retains samples, missing waits stay inconclusive, A/A controls and sample sufficiency; observations |

Run-result completion, verdict, coverage and cleanup stay independent. A confirmed
failure can coexist with failed cleanup; missing required observations cannot pass.
Ownership is checked for every removal. No global prune is part of this audit.

CHECK receipts retain the PostgreSQL definition and verify constraint identity and
validation state; predicate equivalence is not independently proven by catalog
comparison. The trusted worker executes the accepted SQL snapshot, and declared
write contracts test semantics. PostgreSQL coercions and IN/ANY rewrites make raw
text or raw AST equality unsafe as a replacement proof. A compromised worker image
is outside this local trusted-code model. Record this boundary when interpreting
evidence rather than claiming broader database attestation.

Actual local results and unresolved external checks are recorded in `../PROGRESS.md`.
