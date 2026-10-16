"""Install wheel and rebuilt sdist outside the checkout, then run real CLI rehearsals."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory


def check_distributions(dist: Path, output: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    dist, output = dist.resolve(strict=True), output.absolute()
    wheels, sources = list(dist.glob("*.whl")), list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sources) != 1:
        raise ValueError("Use a distribution directory containing exactly one wheel and one sdist")
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        raise ValueError(
            "Run this check with uv run --locked python scripts/check_distributions.py"
        )
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    environment = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
    with (output / "packaging.log").open("x", encoding="utf-8") as log:

        def run(args: list[str], cwd: Path, expected: int = 0) -> str:
            completed = subprocess.run(
                args,
                cwd=cwd,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=300,
            )
            log.write(f"Command: {args!r}\n{completed.stdout}\n")
            log.flush()
            if completed.returncode != expected:
                raise RuntimeError(
                    f"{Path(args[0]).name} returned {completed.returncode}; expected {expected}. "
                    f"See {output / 'packaging.log'}"
                )
            return completed.stdout

        with TemporaryDirectory(prefix="pg-rehearse-installed-") as temporary:
            outside = Path(temporary)
            requirements = outside / "runtime.txt"
            run(
                [
                    uv,
                    "export",
                    "--locked",
                    "--no-dev",
                    "--no-emit-project",
                    "--output-file",
                    str(requirements),
                ],
                repository,
            )
            extracted = outside / "source"
            extracted.mkdir()
            with tarfile.open(sources[0]) as archive:
                archive.extractall(extracted, filter="data")
            projects = list(extracted.glob("*/pyproject.toml"))
            if len(projects) != 1:
                raise ValueError("Malformed source distribution")
            rebuilt = outside / "rebuilt"
            run(
                [
                    sys.executable,
                    "-I",
                    "-m",
                    "build",
                    "--no-isolation",
                    "--wheel",
                    "--outdir",
                    str(rebuilt),
                    str(projects[0].parent),
                ],
                outside,
            )
            (rebuilt_wheel,) = rebuilt.glob("*.whl")
            if (
                hashlib.sha256(wheels[0].read_bytes()).digest()
                != hashlib.sha256(rebuilt_wheel.read_bytes()).digest()
            ):
                raise ValueError("Wheel rebuilt from sdist differs; packaging is not reproducible")
            summaries = []
            for label, wheel in (("wheel", wheels[0]), ("sdist", rebuilt_wheel)):
                package_cwd = outside / label
                package_cwd.mkdir()
                venv = package_cwd / "venv"
                run([uv, "venv", "--python", sys.executable, str(venv)], package_cwd)
                python, cli = venv / "bin/python", venv / "bin/pg-rehearse"
                run(
                    [
                        uv,
                        "pip",
                        "sync",
                        "--python",
                        str(python),
                        "--require-hashes",
                        str(requirements),
                    ],
                    package_cwd,
                )
                run(
                    [uv, "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
                    package_cwd,
                )
                run(
                    [
                        str(python),
                        "-I",
                        "-c",
                        "import pathlib,pg_rehearse,sys; "
                        "assert pathlib.Path(pg_rehearse.__file__).is_relative_to("
                        "pathlib.Path(sys.prefix)); "
                        "print(pg_rehearse.__file__)",
                    ],
                    package_cwd,
                )
                run([str(cli), "--version"], package_cwd)
                run([str(cli), "doctor", "--skip-docker"], package_cwd)
                project = package_cwd / "orders"
                run([str(cli), "init", str(project)], package_cwd)
                for name, expected in (("rehearsal", 1), ("control", 0)):
                    config = project / f"{name}.yml"
                    state = output / label / name
                    run([str(cli), "validate", "--config", str(config)], package_cwd)
                    run(
                        [str(cli), "run", "--config", str(config), "--state-dir", str(state)],
                        package_cwd,
                        expected,
                    )
                    (report,) = state.glob("*/report.json")
                    data = json.loads(report.read_text())
                    assert data["completion"] == "complete" and data["cleanup"] == "complete"
                    assert data["verdict"] == ("fail" if expected else "pass")
                    assert not set(data["coverage"]["required"]) - set(
                        data["coverage"]["completed"]
                    )
                    assert (
                        report.with_suffix(".html").is_file()
                        and report.with_suffix(".md").is_file()
                    )
                    if expected:
                        assert any(
                            o["phase"] == "post_deployed" and o["sqlstate"] == "42703"
                            for o in data["operations"]
                        )
                        assert any(
                            o["phase"] == "post_candidate" and o["success"]
                            for o in data["operations"]
                        )
                    run(
                        [str(cli), "report", str(report), "--format", "html"], package_cwd, expected
                    )
                    run(
                        [str(cli), "clean", "--run-id", data["run_id"], "--state-dir", str(state)],
                        package_cwd,
                    )
                    summaries.append(
                        f"| {label} | {name} | {expected} | {data['verdict']} | {data['cleanup']} |"
                    )
            (output / "summary.md").write_text(
                "# Installed distribution checks\n\nWheel and sdist rebuilt identically. "
                "Both installed outside the checkout.\n\n"
                "| Package | Case | Exit | Verdict | Cleanup |\n| --- | --- | --- | --- | --- |\n"
                + "\n".join(summaries)
                + "\n",
                encoding="utf-8",
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--output", type=Path, default=Path(".pg-rehearse/package-check"))
    args = parser.parse_args()
    try:
        check_distributions(args.dist, args.output)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Installed wheel/sdist checks passed; reports: {args.output}")


if __name__ == "__main__":
    main()
