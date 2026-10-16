import re
from pathlib import Path

import yaml


def test_ci_limits_permissions_and_retains_only_selected_evidence() -> None:
    workflow = Path(__file__).resolve().parents[2] / ".github/workflows/ci.yml"
    data = yaml.load(workflow.read_text(), Loader=yaml.BaseLoader)
    assert set(data["on"]) == {"push", "pull_request"}
    assert data["permissions"] == {"contents": "read"}
    job = data["jobs"]["rehearsal"]
    assert set(job["strategy"]["matrix"]["python"]) == {"3.12", "3.14"}
    steps = job["steps"]
    for step in steps:
        if "uses" in step:
            assert re.fullmatch(r"actions/[\w-]+@[a-f0-9]{40}", step["uses"])
        assert "continue-on-error" not in step
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["persist-credentials"] == "false"
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["if"] == "always()" and upload["with"]["include-hidden-files"] == "true"
    paths = upload["with"]["path"].splitlines()
    tests = next(s for s in steps if s.get("name") == "Unit and real PostgreSQL regression")
    assert "--basetemp=.pg-rehearse/pytest" in tests["run"]
    assert paths == [
        ".pg-rehearse/test-results.xml",
        ".pg-rehearse/pytest/**/report.json",
        ".pg-rehearse/pytest/**/report.md",
        ".pg-rehearse/pytest/**/report.html",
        ".pg-rehearse/evaluation/summary.json",
        ".pg-rehearse/evaluation/summary.md",
        ".pg-rehearse/evaluation/*/*/report.json",
        ".pg-rehearse/evaluation/*/*/report.md",
        ".pg-rehearse/evaluation/*/*/report.html",
        ".pg-rehearse/package-check/summary.md",
        ".pg-rehearse/package-check/packaging.log",
        ".pg-rehearse/package-check/*/*/*/report.json",
        ".pg-rehearse/package-check/*/*/*/report.md",
        ".pg-rehearse/package-check/*/*/*/report.html",
        "dist/*.whl",
        "dist/*.tar.gz",
    ]
