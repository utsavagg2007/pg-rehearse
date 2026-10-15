"""Validate local YAML inputs without starting Docker or executing SQL."""

import copy
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.events import AliasEvent
from yaml.nodes import MappingNode, Node

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.fixtures.validate import validate_fixtures
from pg_rehearse.migration.classify import (
    MigrationClassification,
    baseline_catalog,
    classify_migration,
    validate_contract,
)
from pg_rehearse.migration.preflight import (
    MAX_INPUT_BYTES,
    SQLDocument,
    bound_sql_for_parse,
    parse_document,
)
from pg_rehearse.models import ContractSpec, FixtureSpec, RunSpec


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""

    _depth = 0

    def compose_node(self, parent: Node | None, index: Any) -> Node | None:
        if self.check_event(AliasEvent):
            raise ConfigurationError("YAML aliases are not supported")
        if self._depth >= 40:
            raise ConfigurationError("YAML nesting exceeds 40 levels")
        self._depth += 1
        try:
            return super().compose_node(parent, index)
        finally:
            self._depth -= 1

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
        if any(key.tag == "tag:yaml.org,2002:merge" for key, _ in node.value):
            raise ConfigurationError("YAML merge keys are not supported")
        self.flatten_mapping(node)
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise ConfigurationError(f"Duplicate YAML key: {key!r}")
                seen.add(key)
            except TypeError as exc:
                raise ConfigurationError("YAML mapping keys must be scalar values") from exc
        return super().construct_mapping(node, deep=deep)


def _construct_mapping(loader: UniqueKeyLoader, node: Node) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise ConfigurationError("Expected a YAML mapping")
    return loader.construct_mapping(node)


UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


@dataclass(frozen=True)
class LoadedConfig:
    """Validated declarations and resolved, existing input files."""

    config_path: Path
    spec: RunSpec
    schema_path: Path
    fixtures_path: Path | None
    migration_paths: tuple[Path, ...]
    deployed_contract: ContractSpec
    candidate_contract: ContractSpec | None
    fixtures: FixtureSpec | None
    schema_sql: SQLDocument
    migration_sql: tuple[SQLDocument, ...]
    classifications: tuple[MigrationClassification, ...]
    input_snapshots: tuple["InputSnapshot", ...]


@dataclass(frozen=True)
class InputSnapshot:
    path: Path
    text: str
    sha256: str


def read_snapshot(path: Path, *, root: Path | None = None) -> InputSnapshot:
    """Bound reads, reject special files, and do not follow symlinks during open."""
    descriptors: list[int] = []
    try:
        if root is not None:
            descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            descriptors.append(descriptor)
            parts = path.relative_to(root).parts
            for part in parts[:-1]:
                descriptor = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
                )
                descriptors.append(descriptor)
            descriptor = os.open(
                parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
            )
        else:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ConfigurationError(f"{path}: input must be a regular file")
            data = stream.read(MAX_INPUT_BYTES + 1)
        if len(data) > MAX_INPUT_BYTES:
            raise ConfigurationError(f"{path}: input exceeds 1 MiB")
        text = data.decode("utf-8")
        if "\x00" in text:
            raise ConfigurationError(f"{path}: NUL characters are not supported")
        return InputSnapshot(path, text, hashlib.sha256(data).hexdigest())
    except (OSError, UnicodeError, ValueError) as exc:
        if isinstance(exc, ConfigurationError):
            raise
        raise ConfigurationError(f"Cannot read {path}: {type(exc).__name__}") from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def load_yaml(path: Path) -> dict[str, Any]:
    return parse_yaml(read_snapshot(path).text, path)


def parse_yaml(text: str, path: Path) -> dict[str, Any]:
    try:
        data = yaml.load(text, Loader=UniqueKeyLoader)
    except (RecursionError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or any(not isinstance(key, str) for key in data):
        raise ConfigurationError(f"{path}: expected a YAML object with string keys")
    return data


def resolve_input(root: Path, declared: Path) -> Path:
    """All input paths are relative to the configuration's directory."""
    if declared.is_absolute() or PureWindowsPath(str(declared)).drive:
        raise ConfigurationError(f"Input paths must be relative: {declared}")
    if ".." in declared.parts or "\\" in str(declared) or any(ord(c) < 32 for c in str(declared)):
        raise ConfigurationError(
            f"Input paths cannot contain traversal, backslashes, or control characters: {declared}"
        )
    root = root.resolve()
    try:
        resolved = (root / declared).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigurationError(f"Input does not exist or cannot be resolved: {declared}") from exc
    if not resolved.is_relative_to(root):
        raise ConfigurationError(f"Input escapes the project directory: {declared}")
    if not resolved.is_file():
        raise ConfigurationError(f"Input must be a regular file: {declared}")
    return resolved


def validation_message(source: Path | str, exc: ValidationError) -> str:
    errors = exc.errors(include_input=False, include_url=False)
    details = "; ".join(
        f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in errors[:10]
    )
    return f"Invalid input {source}: {details}"


def load_config(path: Path) -> LoadedConfig:
    """Snapshot and preflight every accepted input before any runtime allocation."""
    try:
        path = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ConfigurationError(f"Cannot resolve configuration: {path}") from exc
    config_snapshot = read_snapshot(path)
    try:
        spec = RunSpec.model_validate(parse_yaml(config_snapshot.text, path))
    except ValidationError as exc:
        raise ConfigurationError(validation_message(path, exc)) from exc
    root = path.parent
    snapshots = [config_snapshot]

    def read(declared: Path) -> InputSnapshot:
        snapshot = read_snapshot(resolve_input(root, declared), root=root)
        snapshots.append(snapshot)
        return snapshot

    schema = read(spec.schema_path)
    schema_sql = parse_document(schema.text, str(schema.path))
    catalog = baseline_catalog(schema_sql)
    fixture = read(spec.fixtures_path) if spec.fixtures_path else None
    try:
        fixture_spec = (
            FixtureSpec.model_validate(parse_yaml(fixture.text, fixture.path)) if fixture else None
        )
    except ValidationError as exc:
        raise ConfigurationError(validation_message("fixtures", exc)) from exc
    validate_fixtures(fixture_spec, catalog, str(fixture.path) if fixture else "fixtures")

    def contract(declared: Path) -> ContractSpec:
        snapshot = read(declared)
        try:
            model = ContractSpec.model_validate(parse_yaml(snapshot.text, snapshot.path))
        except ValidationError as exc:
            raise ConfigurationError(validation_message(snapshot.path, exc)) from exc
        for operation in model.operations:
            source = f"{snapshot.path} (operation {operation.id})"
            sql = bound_sql_for_parse(operation.sql, operation.parameters, source)
            validate_contract(parse_document(sql, source))
        return model

    deployed = contract(spec.contracts.deployed)
    candidate = contract(spec.contracts.candidate) if spec.contracts.candidate else None
    if candidate and candidate.version == deployed.version:
        raise ConfigurationError("Deployed and candidate contract versions must differ")
    documents = []
    classifications: list[MigrationClassification] = []
    projected = copy.deepcopy(catalog)
    for step in spec.migrations:
        snapshot = read(step.path)
        document = parse_document(snapshot.text, str(snapshot.path))
        classifications.extend(classify_migration(document, step.transaction, projected))
        documents.append(document)
    return LoadedConfig(
        path,
        spec,
        schema.path,
        fixture.path if fixture else None,
        tuple(Path(document.source) for document in documents),
        deployed,
        candidate,
        fixture_spec,
        schema_sql,
        tuple(documents),
        tuple(classifications),
        tuple(snapshots),
    )
