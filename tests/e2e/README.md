# End-to-end test plan

After the real pipeline exists, exercise the installed CLI, its exit codes,
coverage, report artifacts, and cleanup. The rename example must return 1 and the
control 0. Invalid input returns 2 before allocation. Infrastructure failure
returns 3. Missing evidence returns 4. Currently only foundation CLI unit tests run.
