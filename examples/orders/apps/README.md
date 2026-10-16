# Reference HTTP applications

`deployed.py` and `candidate.py` are independent entry points for maintained old/new
orders applications. They use the installed pg-rehearse package and Psycopg. Each
reads scoped connection settings as one JSON line on stdin, prints its readiness
port/process/backend/revision, then serves GET /users/id, GET /orders/id and POST
/orders on loopback. The old version reads name; the candidate reads full_name and
accepts processing status. Both validate and serialize domain values.

For normal rehearsal use:

```sh
make worker-image
pg-rehearse run --config examples/orders/applications.yml
pg-rehearse run --config examples/orders/applications-rename.yml
pg-rehearse run --config examples/orders/applications-status-failure.yml
```

For independent service execution in a prepared scoped database environment:

```sh
python examples/orders/apps/deployed.py < scoped-settings.json
python examples/orders/apps/candidate.py < scoped-settings.json
```

Settings keys are host, port, dbname, user (rehearse_workload), password, options
and connect_timeout. Keep that file private. The rehearsal adapter sends credentials
through pipes instead of writing settings to disk; it grants no Docker authority.
Services are separate processes in the worker image with independent connections.
The reference compatible fixture has both name columns; it makes no dual-write or
production deployment claim. See docs/rollout.md for covered probes and limits.
