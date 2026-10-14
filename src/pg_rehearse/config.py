"""Validate local YAML inputs without starting Docker or executing SQL."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from yaml.nodes import MappingNode, Node

from pg_rehearse.errors import ConfigurationError
from pg_rehearse.models import ContractSpec, RunSpec


class UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects ambiguous duplicate mapping keys."""

    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Any, Any]:
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


def load_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as stream:
            data = yaml.load(stream, Loader=UniqueKeyLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ConfigurationError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(data, dict) or any(not isinstance(key, str) for key in data):
        raise ConfigurationError(f"{path}: expected a YAML object with string keys")
    return data


def resolve_input(root: Path, declared: Path) -> Path:
    """All input paths are relative to the configuration's directory."""
    if declared.is_absolute():
        raise ConfigurationError(f"Input paths must be relative: {declared}")
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


def _load_contract(path: Path) -> ContractSpec:
    try:
        return ContractSpec.model_validate(load_yaml(path))
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid contract {path}: {exc}") from exc


def load_config(path: Path) -> LoadedConfig:
    """Check declarations and referenced contracts; SQL preflight is a later feature."""
    path = path.resolve()
    try:
        spec = RunSpec.model_validate(load_yaml(path))
    except ValidationError as exc:
        raise ConfigurationError(f"Invalid configuration {path}: {exc}") from exc
    root = path.parent
    schema = resolve_input(root, spec.schema_path)
    fixtures = resolve_input(root, spec.fixtures_path) if spec.fixtures_path else None
    if fixtures:
        load_yaml(fixtures)
    migrations = tuple(resolve_input(root, step.path) for step in spec.migrations)
    deployed = _load_contract(resolve_input(root, spec.contracts.deployed))
    candidate = (
        _load_contract(resolve_input(root, spec.contracts.candidate))
        if spec.contracts.candidate
        else None
    )
    if candidate and candidate.version == deployed.version:
        raise ConfigurationError("Deployed and candidate contract versions must differ")
    return LoadedConfig(path, spec, schema, fixtures, migrations, deployed, candidate)
