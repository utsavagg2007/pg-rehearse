"""Disposable runtime milestone; the migration rehearsal pipeline remains pending."""

import signal
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from types import FrameType

from pg_rehearse.config import LoadedConfig, load_config
from pg_rehearse.errors import RunInterrupted
from pg_rehearse.runtime.docker import DockerRuntime, RunEnvironment, RuntimeOptions
from pg_rehearse.runtime.manifest import ManifestStore, RunManifest


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
