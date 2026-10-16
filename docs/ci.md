# CI and installed distributions

The workflow runs on push and pull requests with read-only contents permissions.
Checkout does not persist credentials; Actions use pinned commit IDs. There is no
privileged `pull_request_target` workflow. Python 3.12 and 3.14 each install the
locked environment, run lint/format/types, prepare the pinned PostgreSQL digest,
build the matching worker, and run the full real PostgreSQL suite.
It then executes the seven-case labeled matrix, preserving expected incompatible,
unsupported and inconclusive outcomes, before checking both installed distributions.

```sh
uv sync --locked
make worker-image
make check
make integration
make evaluate
make package-check
```

`make build` uses `python -m build --no-isolation` inside the locked development
environment. Hatchling 1.32.4 and its build dependencies are locked alongside the
runtime/test tools. Runtime dependencies are unchanged. The distributions include
the static HTML template, starter inputs, docs and verification script. `uv.lock`
fixes this repository's environment; normal package consumers may resolve within
the declared supported dependency ranges.

`scripts/check_distributions.py` requires exactly one wheel and sdist in `dist/`.
It exports hash-locked runtime requirements, safely extracts the sdist into a
temporary directory outside the checkout and rebuilds its wheel with the locked
backend. Wheel bytes must match. Each wheel is then installed without editable
source into its own fresh environment with hash-verified runtime dependencies.
An isolated import check confirms the module lives inside that environment.

Both installations run version/diagnostics, initialize bundled inputs, validate,
run the rename and control, render saved HTML, and clean the selected owned runs.
The rename must return exactly 1 with actual deployed SQLSTATE 42703 and passing
candidate probes; the control must return 0. Both require complete evidence and
cleanup. Reports and the package-check log stay in `.pg-rehearse/package-check`.
Use `--output <new-directory>` for another run; the default refuses overwriting
previous verification output.

The artifact step uses `always()` and includes only the test XML, package summary
and log, known synthetic report JSON/Markdown/HTML files, wheel and sdist. Pytest uses
an explicit retained temporary root, so test reports survive even when package
checks are skipped after an earlier test failure. Hidden
file inclusion is explicitly enabled for `.pg-rehearse`. Raw worker receipts,
plan trees, input snapshots and manifests are excluded. Retention is seven days.
The evaluation summary JSON/Markdown and its synthetic report files are explicitly
allowlisted alongside test/package evidence. Evaluation exit 0 means the expected
labels matched, including failures; it does not change any rehearsal verdict.
Reports from a partially failed installation check are retained when available;
an unavailable filesystem cannot guarantee evidence persistence. Real user SQL
and fixture values require a separate artifact-sharing decision.

This workflow tests the tool using maintained synthetic examples. It does not
implement a trusted production migration policy, Git-ref baseline or external
pilot certification. Local checks are recorded in `../PROGRESS.md`; GitHub-hosted
execution and the remote Python matrix remain unverified until the workflow runs.
