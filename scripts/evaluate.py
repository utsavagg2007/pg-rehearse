"""Run the fixed labeled matrix; success means expectations matched, including failures."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from pg_rehearse.errors import ConfigurationError, RunInterrupted, RuntimeLifecycleError
from pg_rehearse.evaluation.cases import CASES, case_errors
from pg_rehearse.orchestrator import run_rehearsal, termination_signals
from pg_rehearse.report.json_report import atomic_text, read_report
from pg_rehearse.runtime.manifest import ManifestStore


def evaluate(output: Path) -> bool:
    output = output.absolute()
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    examples = Path(__file__).resolve().parents[1] / "examples/orders"
    records = []
    for case in CASES:
        state = output / case.id
        result, directory = None, None
        try:
            result, directory = run_rehearsal(examples / case.config, state_dir=state)
            code = int(result.exit_code)
        except ConfigurationError as exc:
            code = int(exc.exit_code)
        except RuntimeLifecycleError:
            code = 3
            reports = list(state.glob("*/report.json"))
            if len(reports) == 1:
                directory = reports[0].parent
                result = read_report(reports[0])
        errors = case_errors(case, result, code)
        if case.label == "unsupported" and state.exists():
            errors.append("unsupported input allocated a run directory")
        if directory:
            manifest = ManifestStore(directory / "manifest.json").load()
            if manifest.cleanup != "complete" or not all(r.removed for r in manifest.resources):
                errors.append("resource cleanup is incomplete")
            for name in ("report.json", "report.md", "report.html"):
                if not (directory / name).is_file():
                    errors.append(f"missing saved {name}")
        records.append(
            {
                "case": asdict(case),
                "exit": code,
                "completion": result.completion.value if result else None,
                "verdict": result.verdict.value if result else None,
                "cleanup": result.cleanup.value if result else None,
                "missing_coverage": result.coverage.missing if result else None,
                "report": str(directory / "report.json") if directory else None,
                "errors": errors,
            }
        )
        summary = {
            "schema_version": 1,
            "complete": len(records) == len(CASES),
            "matched": sum(not r["errors"] for r in records),
            "total": len(CASES),
            "false_passes": sum(
                r["verdict"] == "pass" and r["case"]["verdict"] != "pass" for r in records
            ),
            "false_failures": sum(
                r["verdict"] == "fail" and r["case"]["verdict"] == "pass" for r in records
            ),
            "cases": records,
        }
        atomic_text(output / "summary.json", json.dumps(summary, indent=2) + "\n")
        atomic_text(
            output / "summary.md",
            "# Labeled evaluation\n\nMatching an expected failure is an evaluation success, "
            "not a passing migration.\n\n"
            "| Case | Label | Exit | Verdict | Completion | Cleanup | Matches |\n"
            "| --- | --- | --- | --- | --- | --- | --- |\n"
            + "\n".join(
                f"| {r['case']['id']} | {r['case']['label']} | {r['exit']} | {r['verdict']} | "
                f"{r['completion']} | {r['cleanup']} | {not r['errors']} |"
                for r in records
            )
            + "\n",
        )
    return all(not r["errors"] for r in records)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".pg-rehearse/evaluation"))
    args = parser.parse_args()
    try:
        with termination_signals():
            matched = evaluate(args.output)
    except RunInterrupted as exc:
        raise SystemExit(128 + exc.signum) from exc
    except (OSError, ConfigurationError, RuntimeLifecycleError) as exc:
        raise SystemExit(f"Evaluation could not finish: {exc}") from exc
    print(f"Evaluation {'matched' if matched else 'mismatched'}; evidence: {args.output}")
    raise SystemExit(0 if matched else 1)


if __name__ == "__main__":
    main()
