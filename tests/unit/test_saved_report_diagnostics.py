from pathlib import Path

from typer.testing import CliRunner

from pg_rehearse.cli import app
from pg_rehearse.models import RunResult
from pg_rehearse.report.json_report import write_json


def test_saved_report_missing_diagnostic_fields_remains_inconclusive(tmp_path: Path) -> None:
    path = tmp_path / "report.json"
    write_json(path, RunResult(run_id="partial", performance=[{}], plans=[{}]))

    response = CliRunner().invoke(app, ["report", str(path)])

    assert response.exit_code == 4, response.output
    assert "Performance Not recorded: Not recorded (advisory)" in response.output
    assert "Plan Not recorded: Not recorded; structure changed Not recorded" in response.output
