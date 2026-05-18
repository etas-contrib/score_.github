from __future__ import annotations

import fnmatch
import tomllib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from generate_repo_overview.models import TrackedDep, WorkflowSignal

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True, slots=True)
class OrgConfig:
    """Organization-specific settings loaded from a TOML config file."""

    org_name: str
    repo_include_patterns: tuple[str, ...] = ()
    tracked_deps: tuple[TrackedDep, ...] = ()
    workflow_signals: tuple[WorkflowSignal, ...] = ()
    reference_integration_repo: str = ""
    registry_repo: str = ""

    def repo_matches_filter(self, repo_name: str) -> bool:
        if not self.repo_include_patterns:
            return True
        return any(
            fnmatch.fnmatch(repo_name, pattern)
            for pattern in self.repo_include_patterns
        )


def load_org_config(path: Path) -> OrgConfig:
    """Load and validate an OrgConfig from a TOML file.

    Raises ``ValueError`` for missing/invalid required fields and malformed
    repo paths.  Silently drops tracked_deps and workflow_signals entries
    that have missing or non-string fields.
    """
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    signals = cast("dict[str, Any]", raw.get("signals", {}))

    org_name = raw.get("org_name")
    if not isinstance(org_name, str) or not org_name.strip():
        raise ValueError("org_name is required in the config file.")

    reference_integration_repo = _str_or(
        signals.get("reference_integration_repo"), ""
    )
    registry_repo = _str_or(signals.get("registry_repo"), "")
    for field_name, field_value in (
        ("reference_integration_repo", reference_integration_repo),
        ("registry_repo", registry_repo),
    ):
        if field_value and "/" not in field_value:
            raise ValueError(
                f"{field_name} must be in 'org/repo' format, got '{field_value}'."
            )

    return OrgConfig(
        org_name=org_name.strip(),
        repo_include_patterns=_parse_string_list(raw.get("repo_include_patterns")),
        tracked_deps=_parse_tracked_deps(signals.get("tracked_deps")),
        workflow_signals=_parse_workflow_signals(signals.get("workflow_signals")),
        reference_integration_repo=reference_integration_repo,
        registry_repo=registry_repo,
    )


def _str_or(value: object, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _parse_string_list(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(
            f"Expected a list of strings, got {type(value).__name__}."
        )
    return tuple(item.strip() for item in value if isinstance(item, str) and item.strip())


def _parse_tracked_deps(value: object) -> tuple[TrackedDep, ...]:
    if not isinstance(value, list):
        return ()
    result: list[TrackedDep] = []
    for item in cast("list[Any]", value):
        if not isinstance(item, dict):
            continue
        repo = item.get("repo")
        module_name = item.get("module_name")
        if (
            isinstance(repo, str)
            and repo.strip()
            and isinstance(module_name, str)
            and module_name.strip()
        ):
            result.append(TrackedDep(repo=repo.strip(), module_name=module_name.strip()))
    return tuple(result)


def _parse_workflow_signals(value: object) -> tuple[WorkflowSignal, ...]:
    if not isinstance(value, list):
        return ()
    result: list[WorkflowSignal] = []
    for item in cast("list[Any]", value):
        if not isinstance(item, dict):
            continue
        label = item.get("label")
        if not isinstance(label, str) or not label.strip():
            continue
        reference = item.get("reference")
        if isinstance(reference, str) and reference.strip():
            result.append(WorkflowSignal(label=label.strip(), reference=reference.strip()))
    return tuple(result)
