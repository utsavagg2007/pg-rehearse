# Outside-developer pilot

**Status: not started. No participants or external feedback are recorded.**
The project owner confirmed that no feedback is available and requested leaving
the pilot pending on 2026-10-16.
Step 19's release documents are prepared, but its acceptance criterion requires
independent developers to run the project and provide real feedback. Maintainer
tests and automated evaluation do not satisfy that criterion.

## Session protocol

Ask developers outside the implementation work to use the same candidate source
and lockfile. Give them [RUNNING.md](../RUNNING.md), the supported-input matrix in
[preflight.md](preflight.md), and the expected results below. Record initial
questions and assistance rather than silently coaching past unclear instructions.
Use the synthetic orders starter; no production credentials or personal data are
needed. Keep reports private unless participants explicitly agree to share them.

Each participant should independently:

1. Prepare the locked environment, Docker, PostgreSQL 17 and matching worker using
   the execution guide; record OS/architecture, Python/uv/Docker versions and exact
   source, lockfile and image identities.
2. Initialize a new orders starter and validate it without allocation. Repeat init
   at the same destination and confirm exit 2 leaves their files unchanged.
3. Run the control and obtain exit 0, complete required evidence and cleanup.
4. Run the rename or `demo` and obtain exit 1 with committed rename, deployed
   SQLSTATE 42703 and passing candidate assertions over preserved Ada data.
5. Open the final HTML, navigate with a keyboard and inspect print output. Explain
   completion, verdict, missing coverage and cleanup in their own words. Regenerate
   HTML from saved JSON and confirm that the stored exit code is retained.
6. Try a documented unsupported input. With the checkout available, validate
   `examples/orders/unsupported.yml`: expect exit 4 before allocation. Try a missing
   config: expect exit 2 before allocation. Confirm neither is a passing rehearsal.
7. Exercise documented recovery: interrupt a held `sandbox` normally and inspect
   cleanup; run `clean --run-id <id> --state-dir <state-directory>` for that inactive
   run. Repeating clean must retain reports and leave unrelated resources alone.
   Use a selected run's manifest for `recover` after a hard crash, if encountered;
   do not crash or prune unrelated Docker resources.
8. Record where they hesitated, commands that failed, expected versus actual
   behavior, how recovery worked, and one concrete improvement or explicit
   confirmation that the instructions were sufficient.

Capture the actual command exit statuses, run IDs, report paths and final cleanup
states. A successful command or a screenshot by itself is insufficient evidence.
An infrastructure limitation remains unresolved until reproduced or explained;
do not relabel it as a successful pilot. Re-run any affected checks after fixes.

## Feedback record

Copy the following for each consenting participant. Do not replace pending fields
with inferred or simulated responses.

| Field | Recorded value |
| --- | --- |
| Participant identifier and independent role | Pending |
| Session date and candidate commit | Pending |
| Lockfile hash and image identities | Pending |
| OS/architecture; Python, uv and Docker versions | Pending |
| Setup and first useful report time | Pending |
| Control: exit, run ID, coverage, cleanup | Pending |
| Rename: exit, SQLSTATE, candidate result, cleanup | Pending |
| Unsupported/missing input: exit and zero allocation | Pending |
| Init preservation and saved-report behavior | Pending |
| Interruption/recovery and retained evidence | Pending |
| Browser, keyboard and print observations | Pending |
| Confusing instructions and assistance required | Pending |
| Participant feedback, in their words | Pending |
| Defect/fix reference and independent retest | Pending |
| Permission to share feedback/artifacts | Pending |
| Session accepted, blocked or follow-up needed | Pending |

## Acceptance record

Current independent sessions: **0**. External pilot acceptance: **pending**.
Record actual feedback and follow-up results here before marking this criterion
complete. The project cannot generate external feedback on participants' behalf;
no invitations or reports have been sent as part of preparing this protocol.
