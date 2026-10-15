# Input validation and PostgreSQL 17 preflight

Step 2 is implemented. `validate` and the rehearsal allocation boundary fully
validate and snapshot inputs without contacting Docker or executing SQL.

```sh
uv run --locked pg-rehearse validate --config examples/orders/rehearsal.yml
uv run --locked pg-rehearse validate --config examples/orders/control.yml
```

The output lists migration families, file/line/column locations, and input snapshot
counts. Success means the inputs fit the documented envelope. It does not prove
that migrations execute, CHECK predicates accept existing data, contract results
are correct, or applications remain compatible. Those require subsequent worker,
fixture, execution, and analysis features. `run` still returns 4 for a valid
configuration until the full pipeline is implemented.

## Allocation boundary

`load_config(path)` reads every declaration and referenced input, builds a baseline
catalog, validates fixture rows, parses every contract operation, and classifies
every migration step. `validated_environment(path)` calls it before constructing
`DockerRuntime`, connecting to Docker, writing a run manifest, or allocating any
resources. Standalone `sandbox` accepts no rehearsal SQL and remains an independent
infrastructure diagnostic.

The accepted SQL strings and input files are retained in snapshots with SHA-256
hashes. The future worker must consume these accepted snapshots rather than reopen
paths after validation. PostgreSQL AST parsing preserves original migration SQL
and statement spans; it does not split on semicolons or rewrite executable SQL.

## Strict declarations and file reads

- Unknown YAML fields and duplicate keys are errors. Aliases, merge keys, and
  nesting deeper than 40 levels are rejected.
- Input booleans and integers must have their declared types; string numbers and
  booleans are not silently converted. Schema versions must be integer 1.
- Seeds are unsigned 32-bit integers. Positive deadline limits are enforced and
  lock timeout cannot exceed statement timeout. Only the existing official PG17
  image-reference pattern is accepted.
- All referenced paths are relative to the configuration's directory. Absolute,
  Windows drive/UNC, parent traversal, backslash, and control-character paths are
  rejected. Symlinks must resolve inside that root.
- Reads use directory descriptors and no-follow opens after resolution, preventing
  a symlink substitution from escaping the root. Special files are rejected using
  file metadata; opening a FIFO does not block. Each input is at most 1 MiB and
  must contain valid UTF-8 without NUL characters.
- At most 100 migration steps, 1000 operations per contract, and 10000 explicit
  fixture rows are accepted. Expression traversal has a 100000-node budget.

## SQL parser and migration support

The locked `pglast` 7.20 dependency reports PostgreSQL 17.7 grammar. Preflight
checks the parser major version and uses its PostgreSQL AST rather than keyword
substring matching. See the [pglast parser API](https://pglast.readthedocs.io/en/v7/parser.html).

| Accepted migration family | Boundary |
| --- | --- |
| Direct column rename | `ALTER TABLE ... RENAME COLUMN`; known baseline table, existing source, new destination |
| Index creation | Named, non-unique B-tree index over existing plain columns; optional ASC/DESC and NULL ordering |
| Concurrent index creation | Same index subset, declared as one autocommit statement |
| Named CHECK addition | `ADD CONSTRAINT ... CHECK (...)`, optionally `NOT VALID` |
| CHECK validation/removal/replacement | The CHECK must be explicitly named in the baseline or an earlier accepted step; no CASCADE or IF EXISTS |

Ordered migration declarations update an in-memory projection so a subsequent
index can reference a renamed column, and CHECK validation can reference an earlier
addition. This projection is support checking, not a replacement for PostgreSQL's
catalog analysis or the future executor's catalog snapshots.

Transaction steps may contain multiple supported statements. Autocommit steps
must contain exactly one. Concurrent index creation is rejected in transaction
mode, matching [PostgreSQL 17's transaction restriction](https://www.postgresql.org/docs/17/sql-createindex.html).
Explicit `BEGIN`, `COMMIT`, savepoints, session identity changes, COPY, DO, function
or extension creation, arbitrary DDL, and unknown AST shapes are rejected.

Unique, expression, partial, covering, non-B-tree and anonymous indexes are outside
this initial subset. ADD COLUMN, type changes, table renames, partitioning, RLS,
extensions, and other schemas are also outside it. The original nullable-column
control was moved to `examples/orders/unsupported/add_order_note.sql` as a rejected
counterexample. The active control now creates an ordinary B-tree index.

## Baseline and fixture validation

Baseline setup accepts plain persistent `CREATE TABLE` declarations in `public`.
It supports inline/table primary and unique keys, simple immediate fixture foreign
keys, CHECKs, NULL/NOT NULL, and scalar-literal defaults. Table inheritance,
partitioning, ON COMMIT behavior, generated/identity/serial columns, executable defaults, and arbitrary
setup scripts are not accepted by this initial loader.

Supported column types: smallint/integer/bigint, text, varchar (optionally a positive
length), boolean, unbounded numeric, double precision, UUID, date, timestamp, and
timestamptz. Arrays, custom types, and other type modifiers are rejected. Identifiers
are limited to 63 UTF-8 bytes and cannot start with `pg_` in this initial subset.

Explicit fixture rows are checked for unknown tables/columns, missing required
values, NULLability, integer ranges, varchar length, scalar type, numeric finiteness,
valid UUID/ISO date/time strings, duplicate primary/unique keys, and missing foreign
key parent rows. Boolean values cannot stand in for integer IDs. Numeric values
use integers or quoted decimal strings; dates/timestamps must be quoted strings,
and timestamptz strings must include an offset. Fixture data is not coerced or
inserted into PostgreSQL during preflight.

General CHECK evaluation, PostgreSQL coercion/collation rules, automatic constraint
naming, and all server catalog semantics are deliberately not emulated. Database
setup verification remains required before interpreting a migration result.

## Contract SQL and parameters

Each operation contains one SELECT, INSERT, UPDATE, or DELETE statement. The
accepted expression subset includes ordinary columns, literals, bound parameters,
comparisons/arithmetic, boolean/null tests, basic joins/subqueries, sorting, limits,
approved casts, and a small built-in function set. `lower`, `upper`, `length`, and
`abs` are supported in scalar expressions; `count`, `sum`, `min`, `max`, and `avg`
are additionally accepted in queries. CHECK expressions cannot use aggregates.

CTEs, SELECT INTO, explicit locking clauses, window functions, arbitrary functions
and operators, system relations, utility commands, and unknown AST nodes/options
are rejected. Expected columns/rows/counts are validated structurally; their actual
database results remain unevaluated until the runner exists.

`parameters` accepts a positional scalar list for `%s` or a scalar mapping for
`%(name)s`. The parser uses temporary `$n` representations only for validation;
original operation SQL and parameters remain unchanged. Missing/unused parameters,
mixed styles, native `$n`, and binding markers inside literals, quoted identifiers,
or comments are rejected. With nonempty bindings, literal percent signs must use
`%%`, following Psycopg formatting. With empty bindings the future worker must
execute using `parameters=None`, preserving literal percent signs as written.

## Exit codes and evidence

- Invalid YAML, paths, types, syntax, fixtures, or transaction declarations: **2**.
- Parseable SQL outside the supported envelope: **4 (inconclusive)**.
- Supported preflight: **0** for `validate`, with no compatibility verdict.
- Valid input passed to the unfinished full `run` pipeline: **4**.

Unit tests assert that invalid SQL, YAML, paths, and fixtures never reach the
allocator and create no state directory. Real integration tests exercise the
accepted rename, ordinary/concurrent index, and CHECK shapes against PostgreSQL
17 after the validation gate, retaining the existing runtime teardown tests.
