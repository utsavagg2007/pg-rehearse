# Release preparation

Version **0.1.0** is prepared in source; no publication or external pilot acceptance
is claimed. [Release notes](../CHANGELOG.md) describe this version, and
[RUNNING.md](../RUNNING.md) gives the execution instructions.

## Reproduce and record the candidate

Use a dedicated checkout of the exact candidate with Python 3.12 or 3.14, uv
0.12.7, Docker and enough free Docker memory. Run the following from its root:

```sh
uv sync --locked
uv lock --check
docker pull postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3
docker tag postgres:17@sha256:2d2b8998d31037bf721cfdf764d76ba74171b4fab3431b7f72c27c56ddbdf9e3 postgres:17
make worker-image
make lint typecheck
uv run --locked pytest --run-docker --junitxml=.pg-rehearse/release-tests.xml
uv run --locked python scripts/evaluate.py --output .pg-rehearse/release-evaluation-0.1.0
uv run --locked python -m build --no-isolation --outdir .pg-rehearse/release-0.1.0/dist
uv run --locked python scripts/check_distributions.py --dist .pg-rehearse/release-0.1.0/dist --output .pg-rehearse/release-0.1.0/install-check
```

Evaluation and installation output directories must be new. Finish image building
before running measured rehearsals; run the checks sequentially. A successful
test suite must include real PostgreSQL cases. A suite that skipped Docker cases
does not satisfy this checklist. The distribution check rebuilds the sdist outside
the checkout, requires byte-identical wheel output, installs each independently
with hash-locked runtime dependencies, and asserts rename exit 1/control exit 0.

Record `git rev-parse HEAD`, `git status --porcelain`, `uv --version`, the Python
version, platform, `shasum -a 256 uv.lock`, artifact hashes, and the resolved image
identities alongside the results:

```sh
docker image inspect postgres:17 pg-rehearse-worker:0.1.0 --format '{{.Id}} {{json .RepoDigests}} {{.Architecture}}'
shasum -a 256 .pg-rehearse/release-0.1.0/dist/*
```

Require a clean candidate checkout before assigning a release commit. The worker
Dockerfile uses versioned base tags, so rebuilding later can select different base
image bytes. Record and retain the tested image content ID; the reproducible wheel
check does not establish bit-identical Docker builds. A rehearsal pins the resolved
worker image content ID for that run.

## Release gate

- Confirm package metadata, `pg-rehearse --version`, notes and worker image tag all
  use the candidate version; rebuild the worker whenever source or lockfiles change.
- Retain the passing test XML, evaluation summary and individual reports, package
  check summary, wheel/sdist hashes, exact source and lockfile identities.
- Run the configured Python 3.12/3.14 GitHub Actions matrix and retain its actual
  result URLs. Local verification does not count as a remote workflow result.
- Complete the [outside-developer pilot](pilot.md) and fix/retest reported defects.
  Record real feedback; an empty record leaves Step 19 acceptance pending.
- Review HTML independently in a browser, including keyboard navigation and print
  output. Static escaping tests alone do not establish visual usability.
- Check each tested run's final cleanup and ownership records. Retry only selected
  inactive runs when necessary. Do not use global Docker pruning for verification.
- Review artifact sharing: reports contain SQL and fixture values; private raw
  plans, input snapshots, manifests and worker receipts are not default CI artifacts.

Publication, release tags and messages to pilot participants are separate actions.
This checklist does not publish artifacts or represent an accepted release.

## Upgrade guidance

This is the first prepared version. There is no earlier stable-version upgrade
contract. Finish active rehearsals and recover interrupted runs with their existing
installation before replacing it. Keep old reports and their source/lockfile
identities; do not edit historical evidence to match a newer result schema.

For another checkout of this version, run `uv sync --locked`, rebuild the matching
worker, run `doctor`, and validate inputs again before rehearsing. A standalone
wheel install also needs the separately prepared matching worker and PostgreSQL
image. Images are never downloaded or built implicitly by `run` or `demo`.
`report.json` currently uses schema version 1; saved-report rendering validates the
model and retains the stored exit status. Recovery updates the manifest, while
historical reports retain the original cleanup outcome.
