import json
import os
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock

import pytest
from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.config import load_config
from pg_rehearse.errors import ConfigurationError
from pg_rehearse.models import Finding, OperationResult, RunResult, Severity
from pg_rehearse.onboarding.init import STARTER_FILES, initialize
from pg_rehearse.report.html import render_html, write_html
from pg_rehearse.report.json_report import read_report, write_json

runner = CliRunner()


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)


def result_for(code: int) -> RunResult:
    return RunResult(
        run_id="a" * 32,
        completion="complete" if code in {0, 1} else "partial",
        verdict={0: "pass", 1: "fail", 4: "inconclusive"}[code],
        cleanup="complete",
        coverage={"required": ["known"], "completed": ["known"] if code != 4 else []},
    )


def test_html_keeps_hostile_data_inert_and_statuses_separate(tmp_path: Path) -> None:
    hostile = (
        '</pre><script>window.pwned=1</script><img src="https://bad.invalid" onerror="alert(1)">'
    )
    result = result_for(1)
    result.findings = [
        Finding(
            rule_id=hostile,
            severity=Severity.ERROR,
            explanation=hostile,
            evidence={"sql": hostile, "sqlstate": "42703"},
        )
    ]
    result.operations = [
        OperationResult(
            operation_id=hostile,
            version=hostile,
            phase=hostile,
            success=False,
            error_kind="sql_error",
            sqlstate="42703",
        )
    ]
    result.plans = [{"operation_id": hostile, "status": "unavailable", "structure_changed": None}]
    path = tmp_path / "report.html"
    write_html(path, result)
    rendered = path.read_text()
    page = Page()
    page.feed(rendered)
    assert not {"script", "img", "iframe", "link", "form"} & set(page.tags)
    assert not any(name.lower().startswith("on") for name, _ in page.attributes)
    assert all(value.startswith("#") for name, value in page.attributes if name == "href")
    assert "&lt;script&gt;" in rendered and hostile not in rendered
    assert "default-src 'none'" in rendered
    assert "Compatibility failure observed" in rendered and "Cleanup" in rendered
    assert "SQLSTATE" in rendered and "42703" in rendered and "unavailable" in rendered
    assert path.stat().st_mode & 0o777 == 0o600
    assert rendered == render_html(result)


def test_missing_evidence_does_not_render_as_a_passing_run() -> None:
    rendered = render_html(result_for(4))
    assert "Required evidence is inconclusive" in rendered
    assert "Missing required checks" in rendered and "<li>known</li>" in rendered
    assert "0 / 1" in rendered and "Controlled contention was not evaluated" in rendered
    assert "Not evaluated in this run" in rendered


def test_starter_is_contained_validated_and_matches_reference_inputs(tmp_path: Path) -> None:
    directory = initialize(tmp_path / "project")
    assert {
        p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()
    } == set(STARTER_FILES)
    assert load_config(directory / "rehearsal.yml").candidate_contract
    assert load_config(directory / "control.yml").classifications
    reference = Path(__file__).resolve().parents[2] / "examples/orders"
    for name in STARTER_FILES:
        if name != "README.md":
            assert (directory / name).read_bytes() == (reference / name).read_bytes()


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_init_does_not_overwrite_existing_targets(tmp_path: Path, kind: str) -> None:
    target = tmp_path / "existing"
    if kind == "directory":
        target.mkdir()
        (target / "mine").write_text("keep")
    elif kind == "file":
        target.write_text("keep")
    else:
        original = tmp_path / "original"
        original.mkdir()
        (original / "mine").write_text("keep")
        target.symlink_to(original, target_is_directory=True)
    response = runner.invoke(app, ["init", str(target)])
    assert response.exit_code == 2 and "already exists" in response.output
    assert (
        (target / "mine").read_text() == "keep" if kind != "file" else target.read_text() == "keep"
    )


def test_init_validates_example_before_creating_directory(tmp_path: Path) -> None:
    destination = tmp_path / "new"
    assert runner.invoke(app, ["init", str(destination), "--example", "unknown"]).exit_code == 2
    assert not destination.exists()


@pytest.mark.parametrize("code", [0, 1, 4])
@pytest.mark.parametrize("format", ["terminal", "html", "markdown"])
def test_saved_report_commands_preserve_outcome_without_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, code: int, format: str
) -> None:
    factory = Mock(side_effect=AssertionError("must not connect to Docker"))
    monkeypatch.setattr("docker.from_env", factory)
    path = tmp_path / "report.json"
    write_json(path, result_for(code))
    before = path.read_bytes()
    response = runner.invoke(app, ["report", str(path), "--format", format])
    assert response.exit_code == code, response.output
    if format != "terminal":
        assert path.with_suffix(".html" if format == "html" else ".md").exists()
    assert path.read_bytes() == before
    factory.assert_not_called()


@pytest.mark.parametrize("kind", ["bad_json", "forged_pass", "symlink", "fifo", "oversized"])
def test_report_reader_rejects_unsafe_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / "source.json"
    if kind == "bad_json":
        path.write_text("sensitive-password")
    elif kind == "forged_pass":
        path.write_text(json.dumps({"run_id": "x", "verdict": "pass"}))
    elif kind == "symlink":
        original = tmp_path / "original"
        write_json(original, result_for(4))
        path.symlink_to(original)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        monkeypatch.setattr("pg_rehearse.report.json_report.MAX_REPORT_BYTES", 64)
        path.write_bytes(b" " * 65)
    with pytest.raises(ConfigurationError):
        read_report(path)
    response = runner.invoke(app, ["report", str(path)])
    assert response.exit_code == 2 and "sensitive-password" not in response.output


def test_report_cannot_replace_source_or_misuse_terminal_output(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_json(path, result_for(4))
    before = path.read_bytes()
    assert (
        runner.invoke(
            app, ["report", str(path), "--format", "html", "--output", str(path)]
        ).exit_code
        == 2
    )
    assert (
        runner.invoke(app, ["report", str(path), "--output", str(tmp_path / "out")]).exit_code == 2
    )
    assert path.read_bytes() == before


@pytest.mark.parametrize("run_id", ["../escape", "a" * 31, "A" * 32, "a" * 33])
def test_clean_rejects_invalid_identifiers_without_recovery(
    monkeypatch: pytest.MonkeyPatch, run_id: str
) -> None:
    recovery = Mock(side_effect=AssertionError("must not recover"))
    monkeypatch.setattr("pg_rehearse.onboarding.clean.recover_run", recovery)
    response = runner.invoke(app, ["clean", "--run-id", run_id])
    assert response.exit_code == 2
    recovery.assert_not_called()


def test_clean_rejects_symlinked_run_or_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recovery = Mock(side_effect=AssertionError("must not recover"))
    monkeypatch.setattr("pg_rehearse.onboarding.clean.recover_run", recovery)
    external = tmp_path / "outside"
    external.mkdir()
    (external / "manifest.json").write_text("{}")
    run_id = "a" * 32
    selected = tmp_path / run_id
    selected.symlink_to(external, target_is_directory=True)
    assert (
        runner.invoke(app, ["clean", "--run-id", run_id, "--state-dir", str(tmp_path)]).exit_code
        == 2
    )
    selected.unlink()
    selected.mkdir()
    (selected / "manifest.json").symlink_to(external / "manifest.json")
    assert (
        runner.invoke(app, ["clean", "--run-id", run_id, "--state-dir", str(tmp_path)]).exit_code
        == 2
    )
    recovery.assert_not_called()
