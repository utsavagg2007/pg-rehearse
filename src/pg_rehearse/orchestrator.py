"""Validated migration rehearsal coordination and guaranteed runtime teardown."""

import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from pg_rehearse.analysis.compatibility import analyze
from pg_rehearse.config import LoadedConfig, load_config
from pg_rehearse.errors import RunInterrupted, RuntimeLifecycleError
from pg_rehearse.models import Completion, Finding, RunResult, Severity, Verdict
from pg_rehearse.report.html import write_html
from pg_rehearse.report.json_report import write_json
from pg_rehearse.report.markdown import write_markdown
from pg_rehearse.runtime.docker import DockerRuntime, RunEnvironment, RuntimeOptions
from pg_rehearse.runtime.manifest import ManifestStore, RunManifest
from pg_rehearse.worker_protocol import InputFile, RehearsalEvidence, WorkerEvidence, WorkerInputs


def worker_inputs(loaded: LoadedConfig) -> WorkerInputs:
    """Copy accepted bytes, never reread the supplied paths after validation."""
    paths = [Path(loaded.config_path.name), loaded.spec.schema_path]
    if loaded.spec.fixtures_path:
        paths.append(loaded.spec.fixtures_path)
    paths.append(loaded.spec.contracts.deployed)
    if loaded.spec.contracts.candidate:
        paths.append(loaded.spec.contracts.candidate)
    paths.extend(step.path for step in loaded.spec.migrations)
    return WorkerInputs(
        files=[
            InputFile(
                name=path.as_posix(),
                text=snapshot.text,
                sha256=snapshot.sha256,
            )
            for path, snapshot in zip(paths, loaded.input_snapshots, strict=True)
        ]
    )


def check_isolated_worker(
    config_path: Path, *, state_dir: Path = Path(".pg-rehearse/runs")
) -> tuple[RunManifest, WorkerEvidence]:
    loaded = load_config(config_path)
    inputs = worker_inputs(loaded)
    runtime = DockerRuntime(
        state_dir=state_dir,
        options=RuntimeOptions(
            image=loaded.spec.postgres_image, startup_seconds=loaded.spec.timeouts.startup_seconds
        ),
    )
    with runtime.provision() as environment:
        evidence = runtime.execute_worker(environment, inputs, loaded.spec.timeouts)
    return ManifestStore(environment.manifest_path).load(), evidence


def run_rehearsal(
    config_path: Path, *, state_dir: Path = Path(".pg-rehearse/runs")
) -> tuple[RunResult, Path]:
    loaded = load_config(config_path)
    inputs = worker_inputs(loaded)
    evidence = RehearsalEvidence()
    runtime = DockerRuntime(
        state_dir=state_dir,
        options=RuntimeOptions(
            image=loaded.spec.postgres_image,
            startup_seconds=loaded.spec.timeouts.startup_seconds,
        ),
    )
    failure: BaseException | None = None
    try:
        with runtime.provision() as environment:
            runtime.rehearse(environment, inputs, loaded.spec.timeouts, evidence)
    except (RuntimeLifecycleError, RunInterrupted) as exc:
        failure = exc
    if runtime.manifest_path is None:
        if failure:
            raise failure
        raise RuntimeLifecycleError("Run manifest was not created")
    store = ManifestStore(runtime.manifest_path)
    manifest = store.load()
    result = analyze(loaded, inputs, evidence, manifest, infrastructure_error=failure is not None)
    writers = (
        (write_json, "report.json"),
        (write_markdown, "report.md"),
        (write_html, "report.html"),
    )
    try:
        for writer, name in writers:
            writer(store.path.parent / name, result)
    except OSError:
        result.completion = Completion.INFRASTRUCTURE_ERROR
        if result.verdict != Verdict.FAIL:
            result.verdict = Verdict.INCONCLUSIVE
        result.findings.append(
            Finding(
                rule_id="REPORT_WRITE_FAILED",
                severity=Severity.ERROR,
                explanation="A final report could not be saved.",
            )
        )
        for writer, name in writers:
            try:
                writer(store.path.parent / name, result)
            except OSError:
                try:
                    (store.path.parent / name).unlink(missing_ok=True)
                except OSError:
                    pass  # Storage loss can prevent both replacing and removing a stale report.
        raise RuntimeLifecycleError(
            f"Cannot save final reports; manifest retained at {store.path}"
        ) from None
    if isinstance(failure, RunInterrupted):
        failure.add_note(f"Partial reports: {store.path.parent}")
        raise failure
    return result, store.path.parent


@contextmanager
def validated_environment(
    config_path: Path, *, state_dir: Path = Path(".pg-rehearse/runs")
) -> Iterator[tuple[LoadedConfig, RunEnvironment]]:
    """The rehearsal allocation boundary: fully preflight before touching Docker."""
    loaded = load_config(config_path)
    options = RuntimeOptions(
        image=loaded.spec.postgres_image, startup_seconds=loaded.spec.timeouts.startup_seconds
    )
    runtime = DockerRuntime(state_dir=state_dir, options=options)
    with runtime.provision() as environment:
        yield loaded, environment


@contextmanager
def termination_signals() -> Iterator[None]:
    """CLI-only signal scope; restore the caller's handlers afterward."""
    interrupted = False

    def interrupt(signum: int, frame: FrameType | None) -> None:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            raise RunInterrupted(signum)

    previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        for sig in previous:
            signal.signal(sig, interrupt)
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def check_disposable_postgres(
    *,
    state_dir: Path,
    options: RuntimeOptions,
    hold_seconds: float = 0,
    on_ready: Callable[[RunEnvironment], None] | None = None,
) -> RunManifest:
    """Provision, confirm TCP readiness, optionally hold, then destroy owned resources."""
    runtime = DockerRuntime(state_dir=state_dir, options=options)
    with runtime.provision() as environment:
        if on_ready is not None:
            on_ready(environment)
        if hold_seconds > 0:
            time.sleep(hold_seconds)
    return ManifestStore(environment.manifest_path).load()
