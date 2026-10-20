# Implementation progress

Updated: 2026-10-17 (Asia/Kolkata).

## Current checkpoint

**Steps 1–18 and all six reported audit fixes are implemented and locally verified.**
The frozen-source suite passed **513 tests in 430.66s**: 405 unit cases and 108
Docker-enabled cases (107 real PostgreSQL cases and one unsupported preflight
refusal). All seven labeled cases passed within that suite; the previous standalone
matrix also matched 7/7. Completion, verdict, coverage and cleanup remain separate.
Lint, formatting, strict typing and the offline 45-package lock check pass.

Step 19 release/pilot preparation and the execution guide remain complete.
Independent pilot acceptance stays pending at the user's request because no external
feedback is available. Remote CI/Python matrix and browser visual QA remain
unverified. Wheel/sdist rebuild and isolated installed CLI checks pass. Final
managed Docker inventory is zero containers and zero networks.

## Audit fixes and verification — 2026-10-17

- Anchor catalog column inventories to accepted schema and prior committed renames;
  reject duplicate identities, missing object references and disappearing index/CHECK
  facts between adjacent migration snapshots. Missing evidence cannot pass.
- Propagate closed/broken EXPLAIN connections to worker infrastructure failure while
  retaining ordinary SQL plan errors as unavailable diagnostics.
- Normalize positive-exponent and signed-zero numeric fixtures exactly, preserving
  precision, scale and existing negative-exponent representations.
- Interpret native numeric defaults using the declared column type, retaining bounds
  and rejection of unsupported casts or fixture coercions.
- Convert YAML integer-construction ValueError into a bounded input error before
  allocation, preserving existing custom error types and explanations.
- Remove the unused FeatureNotImplementedError definition after checking all callers.

Added 65 unit and four real PostgreSQL cases. Updated PROJECT_LAYOUT.md and the
integration guide. No dependency or execution boundary changed. Independent code
review found no remaining blocking issue in this fix scope; this is not a guarantee
that every possible bug has been excluded.

| Check | Actual outcome |
| --- | --- |
| Locked unit suite | 405 passed in 2.79s |
| Focused PostgreSQL regressions | 7 passed in 48.09s; `.pg-rehearse/audit-fixes-focused.xml` |
| Complete frozen-source suite | 513 passed in 430.66s; `.pg-rehearse/audit-fixes-test-results.xml` |
| Lint / formatting / strict typing | Pass; 135 formatted Python files and 66 typed source files |
| Offline lock check | Pass; 45 packages, no dependency change |
| Worker rebuild | Pass; `sha256:6b902e3410792ee558630b4a770fb74f68664e7368b8dc8e532f88affd8e9755` |
| Wheel/sdist and isolated installed CLI | Pass; identical rebuilt wheels, both installed outside the checkout; rename exits 1 and control exits 0 with complete evidence/cleanup |
| Final managed Docker inventory | Zero managed containers and zero managed networks; read-only ownership-label filter |

Installed distribution evidence:
`.pg-rehearse/audit-fixes-package-check/{summary.md,packaging.log}`. Verified wheel:
`ee1a07827b822f7ec3d5da18d99b5859e7fd0afda92c315449565ee1dde92a6c`.
All six audit fixes are complete. Next: obtain independent pilot feedback when the
user is ready and observe remote CI; neither result is inferred from local tests.

## Steps 18–19 implementation and verification log

Earlier pending statements below are chronological history, superseded by the
current checkpoint and final verification table.

**Steps 18–19 work in progress:** Steps 15–17 recheck passed 36 focused cases in
40.60s, including real onboarding and report faults. Independent installed-package
recheck is running. Added a fixed seven-case evaluation catalog, pure expectation
comparison and real end-to-end tests; not yet verified. The full code audit found
manifest special-file reads, nested deadline ownership and saved diagnostic gaps;
focused fixes are in progress. Release/pilot materials are prepared, with
external feedback explicitly pending. No outside participants or messages invented.

Added `scripts/evaluate.py` and `make evaluate`: the fixed labeled matrix uses the
real pipeline, retains per-case evidence and incrementally writes private summary
JSON/Markdown with mismatches/false-pass/false-failure counts. Existing output is
never overwritten. Unsupported input must have no result or run allocation. The
runner and all code-audit fixes still await verification.

Steps 15–17 installed wheel/sdist recheck passed all real rename/control/report/
clean commands. The expanded initial unit suite passed **340 cases in 3.09s**;
lint, formatting and strict typing pass. Audit fixes cover bounded manifest reads,
UTF-8 paths, deadline ownership, first interruption during teardown, surviving index
facts and incomplete saved diagnostics. Added real full-rehearsal interruption,
JSON-report failure and confirmed-failure/cleanup precedence checks; still unrun.

CI now runs the labeled matrix and retains only its known synthetic summaries and
reports. Added the fault-audit map and explicit CHECK receipt boundary: definitions
are retained, identity/validation state are verified, while predicate equivalence
is not independently proven. The trusted worker runs accepted SQL; a fragile text
comparison was deliberately avoided. Final real checks and build remain pending.

Wheel and sdist built successfully with the locked backend. Created `RUNNING.md`
after that build, covering setup, real demo/control, custom input files, validation,
report interpretation, recovery, exits and verification. Added the step-by-step
code audit, release checklist/changelog and truthful blank external-pilot record.
New real focused checks are running; final source tests/build/install verification
will follow before recording acceptance. No runtime dependency was added.

The first real seven-case matrix run passed six and rejected the lock-deadline
label's incorrect assumption that an observed SQL timeout must mean partial/missing
coverage. Actual evidence had complete observation attempts and cleanup, with an
inconclusive verdict and 55P03. Corrected the expected completion/coverage, preserving
their independence. Evidence: `.pg-rehearse/step18-19-focused.xml` (failed attempt).
No product timeout outcome was changed to satisfy the label.

The corrected **16-case real focused suite passed in 55.75s**, including all seven
labels, actual teardown signals, all three report writers and confirmed failure
with failed cleanup. The locked wheel/sdist build passed; resources include the
evaluation module, execution guide, changelog, release/pilot/audit docs and runner.
The seven-case evaluation command and frozen-source 444-case full regression are
next. External pilot acceptance and remote CI remain pending.

The standalone evaluation command completed with **7/7 matched**, zero false
passes/failures in the fixed matrix, all six actual rehearsals cleaned, and the
unsupported case rejected before run allocation. Evidence:
`.pg-rehearse/step18-evaluation/{summary.json,summary.md}`. The full frozen 444-case
regression is running. Final read-only harness/CI/guide review found no blocking
logic issue; corrected the documented Mac environment fallback to persist for
later commands. This prose change does not alter the running tests.

The user confirmed on 2026-10-16: no external feedback is available; leave the pilot
pending. Step 19 therefore records completed release/pilot preparation and pending
independent acceptance. Updated CI/test documentation to match the evaluation and
new interruption/failure checks. No messages or invitations were sent.

**Steps 1–17 are implemented.** Local verification passed all **91 real PostgreSQL
cases** and a fresh **312-case unit suite**, plus real wheel/sdist installation
checks outside the checkout. Lint, formatting, strict typing and the offline lock
check pass. All 13 example configurations pass preflight. The tested worker image is
`sha256:9ecc6c9ba5c3fa2e0991abd180ebc43c391267296fac2fe53f4a7874a33433ca`.
Final Docker inventory: **zero managed containers and zero managed networks**.

Step 15 adds private escaped static HTML. Step 16 adds init/demo/report/clean using
the existing real pipeline and ownership guards. Step 17 adds pinned, read-only CI,
retained synthetic reports and reproducible installed-distribution checks. The
lock contains 45 packages: runtime dependencies are unchanged; Hatchling and its
build-only dependency chain are now pinned in the development environment.

GitHub-hosted CI/Python matrix execution and browser visual QA are unverified.
Steps 18–19 remain pending. The detailed earlier checkpoint and chronological
implementation log below are retained as history; the final verification table
at the end records the current state.

## Previous Steps 12–14 checkpoint

Existing Steps 9–11
and earlier behavior passed a pre-change **334-case regression in 460.77s**, including
75 real PostgreSQL cases. The final source has optional controlled contention,
sequential advisory benchmarks and isolated query-plan diagnostics. No dependency
was added; the locked environment still resolves 42 packages.

The complete **372-case suite (284 unit + 88 real PostgreSQL)** passed in **540.80s**.
After the final actor-barrier receipt tightening, all **13 real observation cases
passed in 172.63s** against the rebuilt final worker, and all **284 unit cases passed
in 4.83s**. Lint, formatting, strict typing and the offline lock check pass. All 13
example configurations passed complete preflight.

The host retains Docker and fixed bootstrap/clone administration; all application
SQL and observation collection run inside scoped workers. Analysis uses accepted
inputs and retained receipts only. Completion, verdict, required coverage and cleanup
remain separate. Missing required observations cannot pass. Optional performance
quality and plan availability are explicit fields; advisory warnings and informational
plan changes do not invalidate complete compatibility evidence.

## Steps 9–11 reverified

The pre-change suite passed all 334 cases, including persistent/fresh SQL and HTTP
sessions, committed cross-version writes, independent application rollback, real
application domain failure despite passing SQL, receipt tampering, index validity,
failed concurrent builds, CHECK validation/drop/re-add and existing lifecycle faults.
Docker was initially stopped; that first attempt failed before integration setup.
Docker Desktop was started before the passing recheck.

Evidence: `.pg-rehearse/step9-11-recheck.xml`.

Existing rename/control behavior remains part of the full suite: committed rename
breaks deployed SQL with 42703 while the candidate sees preserved data; additive
index control passes. Immutable seed digests, independent clones, rollback-only
contracts, semantic assertions, worker permissions, signals/recovery, ownership
refusal, post-cleanup reports and separate failure/coverage/cleanup fields remain
covered. Earlier Step 6–8 and Step 9–11 receipts remain under `.pg-rehearse/`.

## Step 12: controlled contention and lock observation

- Optional declarations preflight bounded UPDATE blocker/probe SQL and require
  poll_ms <= observe_ms < lock_ms. Existing migration SQL is reused on a fresh clone.
- A scoped writer holds a real transaction after a successful UPDATE. The migrator
  starts afterward; a separate read-only observer records activity, wait events,
  pg_blocking_pids, lock types/modes/grants and wait-start values for known actors.
- Only an observed migration wait starts the declared application probe. The probe
  may be observed waiting behind the migration. Release follows an observed barrier
  or bounded fallback. An explicit timeout variant holds through the migration's
  server deadline and retains 55P03/inconclusive evidence.
- The blocker rolls back on exit, including observer and SQL failures. Connections
  close before owned worker teardown. Server statement/lock deadlines apply to SQL
  actor threads; the main worker and host enforce the total wall budget.
- Receipts retain actor PIDs, UTC snapshots, monotonic events, actual hold duration,
  observer overhead, missed polls and at most 1000 samples. Pure validation checks
  identities/barriers and derives required wait/release coverage from actual facts.
- Observed snapshots without a conflicting wait differ from unavailable observations;
  neither can satisfy this expected-wait scenario. No lock-free or production-outage
  claim is inferred from missing samples. The passing release case treats an observed
  controlled wait as informational; failed deadlines remain visible.

## Step 13: repeatable advisory performance

- Optional operation IDs select the same deployed SQL, bound parameters and semantic
  expectations for all arms. The fixed schedule is hashed and retained.
- Each of up to five trials creates four fresh verified clones: baseline, migrated
  candidate, and unchanged A/A controls. Trial order alternates and all arms execute
  sequentially. Statistics preparation is consistent. Defaults: 50 warmups and 200
  measured attempts per selected operation, one connection and concurrency 1.
- Writes commit in both warmup and measurement schedules. Fresh clones reset state
  between arms/trials. Repeated primary keys and failed assertions/errors stay in
  the attempted schedule; failed requests are not silently replaced or filtered.
- Finished benchmark databases are released early by fixed host SQL to keep the
  bounded tmpfs from accumulating twenty copies. Exact run/owner/template/branch
  marker and administrator ownership are required; a changed marker is refused.
  Worker roles remain unable to create/drop databases.
- Raw warmups and attempted samples retain monotonic durations, SQLSTATE/error kinds,
  counts, timeout/error rates, median, p95, MAD, extrema and successful throughput over
  attempted client time. Successful latency excludes errors; timeout attempts remain.
- The advisory-v1 heuristic needs five pairs, >=200 successful measured samples per
  arm/bucket/trial, successful warmups and consistent environment. Both absolute and
  relative thresholds must recur in four of five pairs. Zero baselines and missing
  or erroneous samples are insufficient. Bidirectional A/A drift and excessive trial
  spread are noisy. No strict performance gate, improvement badge or confidence
  interval is claimed.
- Timings include the existing validation/assertion harness, binding, full bounded
  consumption and commit. Reports preserve image IDs/digest, architecture, configured
  Docker limits, seed, PostgreSQL settings, timer resolution and preparation policy.
- A lost measurement connection retains its partial sample prefix and yields an
  infrastructure outcome, rather than discarding observations or claiming completion.

## Step 14: query-plan capture and comparison

- Optional selected operations get independent baseline and migrated plan clones,
  separate from compatibility, rollout and benchmark branches.
- Default EXPLAIN FORMAT JSON does not execute SQL. Explicit analyze: true enables
  ANALYZE/BUFFERS/TIMING OFF. Execution-capable write plans commit on their own clone;
  commit state and consent are checked against accepted input.
- Original JSON, including unknown fields and predicates, is retained only in private
  mode-0600 worker receipts. Shared reports contain sanitized structural summaries
  and references to those files. Limits: 256 KiB per plan, 2000 nodes, depth 64.
- Version-1 normalization retains operators, relation/index identity, child order,
  scan direction/options and parsed expression shapes with literal values removed.
  Timing/cost/row/buffer/spill metrics stay outside the structural fingerprint.
- Missing/failed/malformed plans remain explicitly unavailable. Plan differences are
  informational; costs are not milliseconds and an index scan is not automatically
  better. Fresh unprepared diagnostics do not certify a production pooled plan.
- The deterministic 6002-order selectivity fixture demonstrates a natural before/after
  index plan change without disabling sequential scans or changing planner costs.

## Verification actually performed

| Check | Result |
| --- | --- |
| Pre-change full regression | **334 passed in 460.77s**, including 75 real PG cases |
| Initial new observation cases | Seven passed; repeated-trial coverage collision found and fixed |
| New real observation regression | **10 passed in 136.59s** |
| Focused final index-drop, combined HTTP/observations, connection-loss cases | **3 passed in 39.38s** |
| Final standalone unit suite | **284 passed in 4.83s** |
| Complete regression | **372 passed in 540.80s**, including 88 real PostgreSQL cases |
| Final-source observation regression | **13 passed in 172.63s**, including actor-barrier tampering |
| Ruff lint / formatting / strict mypy | Passed; 66 source files type-checked |
| Locked dependency check | Passed offline; 42 packages, no new dependency |
| Example preflight | All 13 configurations passed |
| Worker image | Final source rebuilt; all 13 observation cases and 284 unit cases passed after final receipt tightening |
| Final public CLI demos | Contention 0, five-pair benchmark 0, query plans 0; cleanup complete |
| Distribution build | Wheel and source distribution built offline; wheel includes all new modules |
| Final managed Docker inventory | **Zero managed containers and zero managed networks** |

The first new combined run exposed duplicate compatibility coverage labels for
repeated benchmark arms. Advisory experiments now retain their own sample/plan
status and every branch includes trial/arm identity. A later 370-case checkpoint
stopped after 48 passes on a baseline-clone infrastructure error in the existing
index-drop example, before migration. Its report remained inconclusive/infra and
cleanup completed. The focused final-image index-drop case passed afterward. These
failed attempts are not counted as complete passing regressions. The clean 372-case
suite passed with image building finished. The subsequent final receipt tightening
was verified by the complete thirteen-case observation regression and unit suite.

Evidence:
- `.pg-rehearse/step9-11-recheck.xml`: existing behavior before implementation.
- `.pg-rehearse/step12-14-initial.xml`: first run and discovered coverage collision.
- `.pg-rehearse/step12-14-new.xml`: ten passing real new cases.
- `.pg-rehearse/step12-14-final-faults.xml`: three passing final targeted cases.
- `.pg-rehearse/step12-14-test-results.xml`: complete 372-case regression.
- `.pg-rehearse/step12-14-final-observations.xml`: final-source thirteen-case real regression.
- `.pg-rehearse/step12-14-final-unit.xml`: final-source 284 unit cases.
- `.pg-rehearse/runs/4d47059c8eb24aa785892d8700bcce68/`: final passing contention CLI report.
- `.pg-rehearse/runs/9797c2b13cac4443b955037cf5fee93a/`: final advisory CLI benchmark, 20 arms and 5000 retained warmup/measured samples; no regression observed by the declared heuristic.
- `.pg-rehearse/runs/52ef2c13dd444e5188cae005aad1eed1/`: final passing plan CLI report; Sort/Seq Scan became Sort/Index Scan naturally.

Local environment: Docker Desktop 29.7.2, Linux arm64 PostgreSQL 17, host Python
3.14.6, worker Python 3.14.8. Official image:
`postgres@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3`.
Final worker content ID:
`sha256:79d2df36cfd49c4d2ad2458926dbab2dd7538fe994aad203dac98b8b8bb1d60b`.
GitHub CI is configured for Python 3.12/3.14 but has not run in this chat.

## Code inventory

There are 66 source files: 52 working modules, two version/module entry points,
eleven namespace files and one remaining placeholder (`evaluation/cases.py`). Unit tests occupy fifteen
files (312 cases); integration tests occupy nine (91 cases). Two independently
runnable reference HTTP application entry points remain outside src. See
PROJECT_LAYOUT.md and docs/observations.md for responsibilities and supported input.

## Boundaries and next task

**Step 18: labeled evaluation and failure-path audit** is next. Requested local
implementation and verification for Steps 12–17 is complete. Step 17's workflow is
configured and its commands verified locally; no remote CI execution is claimed.
Steps 18–19 (broader evaluation and external pilot) remain pending; no external
feedback is invented.

The implemented rollout remains schema-first. Application rollback keeps S1 and
candidate-written data; app-first and database down-migrations are unsupported.
Reference HTTP probes are maintained demos, not production release certification.

Contention is a deliberate bounded actor scenario, not arbitrary traffic replay.
Performance is advisory, sequential, synthetic and closed-loop. Static parameter
schedules must be appropriate for repeated committed writes. Plan diagnostics use
fresh unprepared connections; unknown raw facts remain private. These measurements
do not establish production capacity, outage duration or equivalence.

DML RETURNING still buffers in libpq. Receipts keep the 8 MiB cap. An entire worker
crash before receipt finalization loses that task's unfinished observations; earlier
receipts and missing coverage remain. Filesystem loss can prevent reports. Recovery
updates the manifest; existing reports retain the original cleanup attempt. The
provided architecture PDF is unchanged.

## Steps 15–17 chronological implementation log

These notes preserve intermediate states and failed attempts; later entries
supersede earlier pending-check statements.

Pre-change verification passed **297 tests in 191.55s**: all 284 unit cases and
13 real PostgreSQL observation cases. Evidence: `.pg-rehearse/step12-14-recheck.xml`.
Implemented a self-contained escaped HTML renderer/template and post-cleanup HTML
output, plus bounded saved-result reading. Failed report writes now retry all
formats with the updated infrastructure outcome and try to remove stale files.
New checks, onboarding commands, distribution installation and CI updates are pending.

Added packaged minimal starter assets and init/demo/report/clean commands. Init
refuses any existing target directory and creates files exclusively; demo uses
bundled inputs and the real pipeline; saved reports preserve the original exit
code without Docker; clean selects one validated run and delegates ownership/active
checks to recovery. The worker/SQL experiment flow is unchanged. Verification and
CI/package installation work remain pending.

Added installed-distribution verification: export hash-locked runtime dependencies,
rebuild the sdist outside the checkout, compare wheel bytes, install both into fresh
environments and execute real rename/control/report/clean commands while retaining
reports. CI now pins Action commits, uses read-only permissions, asserts expected
failure exit 1, and uploads only explicit report/build/test artifacts with always().
Pinned the existing Hatchling backend (1.32.4) and locked its build-only dependency
chain; runtime dependencies are unchanged. The lock now contains 45 packages. CI
execution, local distribution smoke checks and all new feature tests are pending.

Initial new unit checks passed: **27 cases**, including hostile HTML, bounded report
reads, source preservation, starter parity and refusal to overwrite files. Lint,
formatting and strict typing passed. Added real onboarding/demo/clean tests, HTML
failure fallback coverage and CI artifact/permission checks; these are not yet run.

The expanded **312-case unit suite passed in 4.77s**, including the CI checks.
Ruff formatting/lint and strict mypy (66 source files) passed. Wheel and sdist build
with the pinned backend succeeded offline. Real new integration and independent
installed-distribution checks remain pending.

Real onboarding cases passed: fresh init/validate/control, actual demo SQLSTATE
42703/candidate Ada data, saved HTML and idempotent clean with reports retained;
active clean refusal and unrelated network preservation. The first HTML-failure
test assertion incorrectly expected an unescaped Markdown rule ID; saved JSON
already showed infrastructure_error/inconclusive with complete cleanup. Corrected
the assertion to check the readable explanation and outcome. Added onboarding/CI
documentation and updated module layout. A browser preview could not be obtained:
loopback timed out and the browser rejects local file URLs. Static HTML structural,
escaping and accessibility-markup checks passed; visual QA is unverified.

Both real report-failure cases now pass (**2 cases in 11.02s**), with all surviving
formats updated to infrastructure_error and no stale failed-format file. Full
403-case regression is running against the rebuilt worker. CI now places pytest
temporary evidence under an explicit retained root and allowlists only report
files there, preserving failed-test reports even before package checks execute.

All **91 real PostgreSQL cases passed** in the full-suite attempt. That process
then failed its first unit case: CI artifact rules were updated after collection,
so the already-loaded old assertion expected the earlier allowlist. This was a
verification-process error, not a product or database failure. A fresh 312-case unit
run and installed wheel/sdist checks are now running. The interrupted full attempt
is retained as `.pg-rehearse/step15-17-test-results.xml`; it is not claimed as a
complete passing suite.

## Steps 15–17 completed behavior

- HTML is rendered from the same final post-cleanup RunResult as JSON/Markdown.
  Every data value is escaped; the bundled template embeds static CSS only, a
  restrictive CSP, keyboard focus/skip navigation, table captions, native details
  and print styles. Findings lead, followed by coverage, phases, SQL/HTTP probes,
  migrations, controlled waits, advisory measurements, sanitized plans and
  environment/clone identities. No raw plan trees or credential sources are read.
- Report-write failures update the infrastructure outcome and retry every format;
  an unavailable format is removed when possible so it cannot retain a stale pass.
  Mode-0600 atomic writers and private run directories remain in use.
- Init creates one new directory exclusively from nine bundled starter files,
  validates both configurations and refuses all existing destinations. Demo runs
  the actual rename pipeline and preserves expected exit 1/SQLSTATE 42703 with
  candidate Ada data. Accepted snapshots/reports outlive the temporary starter.
- Report validates a bounded regular JSON file without Docker, renders terminal,
  HTML or Markdown, protects the source JSON and retains the stored exit code.
  Clean validates a single run ID, refuses symlinks and active runs, delegates
  ownership checks to existing recovery and retains all evidence files.
- CI pins Action commits, uses read-only permissions and does not persist checkout
  credentials. It builds the matching worker, runs real tests on Python 3.12/3.14,
  builds distributions with the locked backend and verifies both outside source.
  Expected rename exit 1 and control exit 0 are asserted. An always-run artifact
  step allowlists only known synthetic reports, test/build artifacts and a package
  log; manifests, snapshots, raw plans and worker receipts are excluded.
- Package verification rebuilds the sdist outside the checkout, requires identical
  wheel bytes, installs both into independent environments with hash-locked runtime
  dependencies, verifies isolated import paths, and executes real init/validate/
  rename/control/report/clean commands. All four real rehearsals completed cleanup.

## Final Steps 15–17 verification actually performed

| Check | Result |
| --- | --- |
| Steps 12–14 pre-change recheck | **297 passed in 191.55s**: 284 unit + 13 real observation cases |
| Final real PostgreSQL regression | **91 passed** in the full-suite attempt; no database test failed |
| Fresh final unit regression | **312 passed in 3.91s**, including updated CI artifact rules |
| Report failure fallback | **2 real cases passed in 11.02s**, also passed in the final PostgreSQL regression |
| Lint / formatting / strict mypy | Passed; 120 Python files formatted, 66 source files type-checked |
| Locked environment | Offline lock check passed, 45 packages; runtime requirements unchanged |
| Example validation | All 13 configurations passed complete preflight |
| Wheel/sdist resources | HTML template and all nine starter files included |
| Installed distributions | Byte-identical sdist rebuild; both fresh external installs passed real rename 1/control 0, HTML rendering and clean |
| Final managed Docker inventory | **Zero containers and zero networks** |
| GitHub-hosted CI / remote Python matrix | Configured, not executed in this chat |
| Browser visual QA | Unverified: loopback timed out and browser policy rejected file URLs; static HTML safety/markup checks passed |

The 403 current cases were verified in two groups: 91 real PostgreSQL cases in
the full attempt, then all 312 unit cases in a fresh process. The full attempt
exited nonzero because its old, collected CI assertion encountered an updated
artifact allowlist; it is not represented as a single passing 403-case invocation.
No product code changed between the passing database cases and fresh unit run.

Current evidence:
- `.pg-rehearse/step12-14-recheck.xml`: pre-change re-verification.
- `.pg-rehearse/step15-17-test-results.xml`: 91 passing PostgreSQL cases and the stale CI assertion failure.
- `.pg-rehearse/step15-17-final-unit.xml`: 312 passing final unit cases.
- `.pg-rehearse/step15-17-report-faults.xml`: passing real report-write failures.
- `.pg-rehearse/package-check/summary.md`: both installed distributions and four actual rehearsal outcomes.
- `.pg-rehearse/package-check/packaging.log`: isolated builds/imports/CLI commands.
- `.pg-rehearse/package-check/{wheel,sdist}/{rehearsal,control}/<run-id>/`: retained final JSON/Markdown/HTML.

This CI is a synthetic tool self-test, not a trusted production policy or Git-ref
baseline gate. Performance remains advisory. Reports intentionally contain SQL
and fixture values and require private handling for sensitive inputs. The provided
architecture PDF is unchanged. No external pilot or release publication occurred.

## Final Steps 18–19 verification and handoff

| Check | Actual result |
| --- | --- |
| Steps 15–17 recheck | 36 focused cases passed in 40.60s; both installed distributions passed four actual rename/control runs |
| Initial expanded unit suite | 340 passed in 3.09s |
| New focused real checks | 16 passed in 55.75s: seven labels, report faults, cleanup precedence and actual signals |
| Final complete regression | **444 passed in 418.72s, zero errors/failures/skips** |
| Standalone evaluation | **7/7 matched; zero false passes/failures** in the fixed matrix; six real rehearsals cleaned, unsupported input unallocated |
| Final Ruff lint / formatting / mypy | Passed; 131 Python files formatted, 66 source files checked |
| Lock and dependencies | Offline check passed; 45 packages, no new runtime dependency |
| Example preflight | 14 accepted; the one intentional unsupported configuration rejected before allocation |
| Final build/install | Wheel/sdist built; identical sdist wheel rebuild; both external fresh installs passed real rename 1/control 0, saved HTML and clean |
| Package contents | Evaluation module, HTML/starter assets, runner, RUNNING.md and audit/release/pilot/changelog resources present |
| Final managed Docker inventory | **Zero containers and zero networks** |
| External pilot | **Pending at the user's request; zero outside sessions/feedback** |
| Remote CI and browser visual QA | Unverified; no remote success or visual acceptance claimed |

Audited and repaired bounded manifest loading, malformed UTF-8 paths, nested deadline
ownership, first interruption during teardown, surviving index catalog integrity,
and incomplete saved terminal diagnostics. Removed the repeated WorkerTask whitelist
and merged duplicate index expectation bookkeeping. The remaining lifecycle and
evidence loops have distinct safety responsibilities and were retained. No broad
refactor or dependency addition was needed. See `docs/audit.md` for the reviewed
step/module map and explicit CHECK predicate-equivalence boundary.

Final evidence:
- `.pg-rehearse/step15-17-recheck.xml` and `.pg-rehearse/step15-17-package-recheck/`.
- `.pg-rehearse/step18-19-unit-initial.xml`: 340 passing unit checks.
- `.pg-rehearse/step18-19-focused.xml`: retained incorrect-label attempt, not counted as passing.
- `.pg-rehearse/step18-19-focused-final.xml`: 16 passing focused cases.
- `.pg-rehearse/step18-19-test-results.xml`: complete passing 444-case run.
- `.pg-rehearse/step18-evaluation/{summary.json,summary.md}` and per-case reports.
- `.pg-rehearse/step18-19-package-check/{summary.md,packaging.log}` and four installed-run report sets.
- `.pg-rehearse/step18-19-build.json`: final source/wheel/lock hashes and tested image identity.

The tested executable worker image is
`sha256:9aded118260932e27e96ad209ff6e3170080d36925eb1086a4095336bf031480`.
The final installed/tested wheel SHA256 is
`c8806248be82f8aa24d57045349ddc50d9c995758eac30266ebd78aef758ec1e`.
Documentation-only rebuilds must preserve those wheel bytes; source-archive hashes
are recorded separately after the final progress update. The working tree remains
uncommitted; this is verified source preparation, not an assigned release commit.

Use `RUNNING.md` for execution. Next external actions are the recorded independent
pilot protocol and actual remote CI/browser checks, followed by the release gate
in `docs/release.md`. The user explicitly requested leaving the pilot pending.
No participant messages, release tags, publication or simulated feedback occurred.
