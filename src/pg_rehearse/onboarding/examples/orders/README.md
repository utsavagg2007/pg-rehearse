# Orders migration starter

Requires Docker, PostgreSQL 17 and the matching pg-rehearse worker image. Prepare
images using the source distribution instructions; no images are pulled or built
by a rehearsal.

From this directory:

```sh
pg-rehearse doctor
pg-rehearse validate --config rehearsal.yml
pg-rehearse run --config rehearsal.yml  # expected exit 1: deployed name query breaks
pg-rehearse run --config control.yml    # expected exit 0: additive index
```

Each run prints JSON, Markdown and self-contained HTML report paths.
`pg-rehearse report <report.json>` displays the stored outcome without Docker.
`pg-rehearse report <report.json> --format html` regenerates the HTML view.
Both retain the saved rehearsal exit code; viewing a failing demo returns 1.

`pg-rehearse clean --run-id <run-id> --state-dir .pg-rehearse/runs` recovers one
inactive owned run. Reports and inputs remain. Normal runs clean up automatically.
The rename is intentionally incompatible, not an example migration to deploy.
