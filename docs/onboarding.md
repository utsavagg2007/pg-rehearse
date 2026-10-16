# Starter and saved evidence

Use Python 3.12+, Docker, the installed official PostgreSQL 17 image and the matching
`pg-rehearse-worker:0.1.0` image. From a checkout, run `uv sync --locked`,
`docker pull postgres:17` and `make worker-image` first. Commands never implicitly
download images or build a worker. Rebuild the worker after source/lockfile changes.

```sh
pg-rehearse init my-rehearsal --example orders
pg-rehearse validate --config my-rehearsal/rehearsal.yml
pg-rehearse run --config my-rehearsal/rehearsal.yml  # expected 1
pg-rehearse run --config my-rehearsal/control.yml    # expected 0
pg-rehearse demo                                   # expected 1
```

Init defaults to `pg-rehearse-demo`, accepts only the orders example and refuses
any existing target, including an empty directory or symlink. It creates private
files exclusively, then preflights both configurations without Docker. A partial
creation failure leaves files for inspection. Bundled resources work from installed
distributions; the editable checkout is not required.

Demo copies those inputs to a temporary directory and runs the existing real
pipeline. Its retained state defaults to `.pg-rehearse/runs/<run-id>`. The deployed
query fails with SQLSTATE 42703 after the rename commits; candidate assertions see
the preserved Ada row. Exit 1 is the intended demonstration, never converted to 0.
The temporary starter is removed; accepted snapshots and reports remain in state.

```sh
pg-rehearse report .pg-rehearse/runs/<run-id>/report.json
pg-rehearse report .pg-rehearse/runs/<run-id>/report.json --format html
pg-rehearse report .pg-rehearse/runs/<run-id>/report.json --format markdown --output review.md
pg-rehearse clean --run-id <run-id>
```

Replace the run ID with the value printed by run/demo. Report defaults to the
terminal. HTML/Markdown default to adjacent files and replace them atomically with
mode 0600. Output cannot replace the source JSON. The bounded reader accepts only
a regular, non-symlink JSON file up to 64 MiB, validates the result model and never
connects to Docker. A pass, confirmed failure or inconclusive report retains exit
0, 1 or 4 respectively; saved infrastructure failures retain 3. Invalid input is 2
and a rendering write failure is 3. Viewing a report does not verify its provenance.

HTML opens independently with no scripts, remote fonts or other network assets.
It escapes SQL, identifiers, errors and evidence. Headings and status text separate
the verdict from execution, required coverage and cleanup. Keyboard navigation,
native disclosure controls and print styles are included. Raw private query plans
are excluded; normalized structures and measurements are available. Fixture/SQL
values remain intentional evidence: keep files private when inputs are sensitive.

Clean selects one inactive run using a 32-character lowercase hexadecimal ID and
an optional `--state-dir`. It checks the real directory/manifest and delegates
recovery to the host runtime's exact IDs/intents and ownership labels. It refuses
active runs and never prunes globally or removes foreign endpoints. Success is 0,
invalid selection is 2, and refused/failed cleanup is 3. Repeating successful cleanup
is safe. It does not delete reports or rewrite the original rehearsal outcome;
the manifest records the later cleanup result.
