# Integration test plan

No real-database tests are implemented at the foundation stage. Add them with
features 1–7 and mark them `integration`. Provision only labeled disposable
resources. Verify readiness deadlines, cleanup after errors and interruptions,
baseline success, baseline failure classification, SQLSTATE `42703` after the
rename, the additive control, and recovery without deleting unrelated resources.

Do not add a permanently skipped fake database test to make this directory look
implemented. Document daemon requirements and retain evidence for actual runs.
