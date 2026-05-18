from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Mapping

DEFAULT_CATEGORY = "Uncategorized"
DEFAULT_SUBCATEGORY = "General"
SNAPSHOT_SCHEMA_VERSION = 17


@dataclass(frozen=True, slots=True)
class TrackedDep:
    """A Bazel dependency tracked across all repositories."""

    repo: str
    module_name: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TrackedDep:
        return cls(
            repo=cast("str", data.get("repo", "")),
            module_name=cast("str", data.get("module_name", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {"repo": self.repo, "module_name": self.module_name}


@dataclass(frozen=True, slots=True)
class WorkflowSignal:
    """A named workflow signal with a reference string to match."""

    label: str
    reference: str

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> WorkflowSignal:
        return cls(
            label=cast("str", data.get("label", "")),
            reference=cast("str", data.get("reference", "")),
        )

    def to_dict(self) -> dict[str, str]:
        return {"label": self.label, "reference": self.reference}


@dataclass(frozen=True, slots=True)
class DeepContentSignals:
    """Deep, slow-to-collect content signals from default-branch tree inspection."""

    is_bazel_repo: bool = False
    bazel_version: str | None = None
    codeowners: tuple[str, ...] = ()
    referenced_by_reference_integration: bool = False
    has_lint_config: bool = False
    has_gitlint_config: bool = False
    has_pyproject_toml: bool = False
    has_pre_commit_config: bool = False
    has_ci: bool = False
    matched_workflow_signals: tuple[str, ...] = ()
    has_coverage_config: bool = False
    top_languages: tuple[str, ...] = ()
    bazel_deps: tuple[tuple[str, str], ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DeepContentSignals:
        return cls(
            is_bazel_repo=bool(data.get("is_bazel_repo", False)),
            bazel_version=cast("str | None", data.get("bazel_version")),
            codeowners=normalize_string_tuple(data.get("codeowners")),
            referenced_by_reference_integration=bool(
                data.get("referenced_by_reference_integration", False)
            ),
            has_lint_config=bool(data.get("has_lint_config", False)),
            has_gitlint_config=bool(data.get("has_gitlint_config", False)),
            has_pyproject_toml=bool(data.get("has_pyproject_toml", False)),
            has_pre_commit_config=bool(data.get("has_pre_commit_config", False)),
            has_ci=bool(data.get("has_ci", False)),
            matched_workflow_signals=normalize_string_tuple(
                data.get("matched_workflow_signals")
            ),
            has_coverage_config=bool(data.get("has_coverage_config", False)),
            top_languages=normalize_string_tuple(data.get("top_languages")),
            bazel_deps=normalize_string_pairs(data.get("bazel_deps")),
        )


@dataclass(frozen=True, slots=True)
class RegistrySignals:
    """Registry-sourced signals collected from shared bazel registry metadata."""

    maintainers_in_bazel_registry: tuple[str, ...] = ()
    latest_bazel_registry_version: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RegistrySignals:
        return cls(
            maintainers_in_bazel_registry=normalize_string_tuple(
                data.get("maintainers_in_bazel_registry")
            ),
            latest_bazel_registry_version=cast(
                "str | None",
                data.get("latest_bazel_registry_version"),
            ),
        )


@dataclass(frozen=True, slots=True)
class VolatileMetricsSnapshot:
    """Fast-refresh volatile activity metrics with optional fetch timestamp."""

    last_push_date: str | None = None
    merged_prs_30_days: int = 0
    open_issues: int = 0
    open_prs: int = 0
    open_ready_prs: int = 0
    open_draft_prs: int = 0
    latest_release_version: str | None = None
    latest_release_date: str | None = None
    commits_since_latest_release: int | None = None
    release_bazel_version: str | None = None
    release_bazel_deps: tuple[tuple[str, str], ...] = ()
    volatile_metrics_fetched_at: str | None = None

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> VolatileMetricsSnapshot:
        return cls(
            last_push_date=cast("str | None", data.get("last_push_date")),
            merged_prs_30_days=cast("int", data.get("merged_prs_30_days", 0)),
            open_issues=cast("int", data.get("open_issues", 0)),
            open_prs=cast("int", data.get("open_prs", 0)),
            open_ready_prs=cast("int", data.get("open_ready_prs", 0)),
            open_draft_prs=cast("int", data.get("open_draft_prs", 0)),
            latest_release_version=cast(
                "str | None", data.get("latest_release_version")
            ),
            latest_release_date=cast("str | None", data.get("latest_release_date")),
            commits_since_latest_release=cast(
                "int | None",
                data.get("commits_since_latest_release"),
            ),
            release_bazel_version=cast(
                "str | None",
                data.get("release_bazel_version"),
            ),
            release_bazel_deps=normalize_string_pairs(data.get("release_bazel_deps")),
            volatile_metrics_fetched_at=cast(
                "str | None",
                data.get("volatile_metrics_fetched_at"),
            ),
        )


@dataclass(frozen=True, slots=True)
class TraceabilityTypeMetrics:
    """Parsed traceability metrics for one requirement type within a repository."""

    type_name: str
    req_total: int = 0
    req_with_code_link: int = 0
    req_with_test_link: int = 0
    req_fully_linked: int = 0
    tests_total: int = 0
    tests_linked: int = 0

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> TraceabilityTypeMetrics:
        return cls(
            type_name=cast("str", data.get("type_name", "")),
            req_total=cast("int", data.get("req_total", 0)),
            req_with_code_link=cast("int", data.get("req_with_code_link", 0)),
            req_with_test_link=cast("int", data.get("req_with_test_link", 0)),
            req_fully_linked=cast("int", data.get("req_fully_linked", 0)),
            tests_total=cast("int", data.get("tests_total", 0)),
            tests_linked=cast("int", data.get("tests_linked", 0)),
        )


@dataclass(frozen=True, slots=True)
class RepoEntry:
    """Normalized repository record grouped by collection cadence and source."""

    name: str
    description: str
    category: str
    subcategory: str
    default_branch: str | None = None
    default_branch_sha: str | None = None
    content: DeepContentSignals = field(default_factory=DeepContentSignals)
    registry: RegistrySignals = field(default_factory=RegistrySignals)
    volatile: VolatileMetricsSnapshot = field(default_factory=VolatileMetricsSnapshot)
    stars: int = 0
    forks: int = 0
    traceability: tuple[TraceabilityTypeMetrics, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepoEntry:
        content_payload = cast("Mapping[str, Any]", data.get("content", {}))
        registry_payload = cast("Mapping[str, Any]", data.get("registry", {}))
        volatile_payload = cast("Mapping[str, Any]", data.get("volatile", {}))
        traceability_payload = data.get("traceability", ())

        return cls(
            name=cast("str", data.get("name", "")),
            description=cast("str", data.get("description", "(no description)")),
            category=cast("str", data.get("category", DEFAULT_CATEGORY)),
            subcategory=cast("str", data.get("subcategory", DEFAULT_SUBCATEGORY)),
            default_branch=cast("str | None", data.get("default_branch")),
            default_branch_sha=cast("str | None", data.get("default_branch_sha")),
            content=DeepContentSignals.from_dict(content_payload),
            registry=RegistrySignals.from_dict(registry_payload),
            volatile=VolatileMetricsSnapshot.from_dict(volatile_payload),
            stars=cast("int", data.get("stars", 0)),
            forks=cast("int", data.get("forks", 0)),
            traceability=tuple(
                TraceabilityTypeMetrics.from_dict(cast("Mapping[str, Any]", item))
                for item in traceability_payload
            )
            if isinstance(traceability_payload, (list, tuple))
            else (),
        )

    def to_dict(self) -> dict[str, Any]:
        return cast("dict[str, Any]", asdict(self))


@dataclass(frozen=True, slots=True)
class SubcategoryConfig:
    """Rendering configuration for a subcategory section in the profile README."""

    name: str
    description: str


@dataclass(frozen=True, slots=True)
class CategoryConfig:
    """Rendering configuration for a category and its subcategory ordering."""

    name: str
    description: str
    subcategories: tuple[SubcategoryConfig, ...] = ()


@dataclass(frozen=True, slots=True)
class ReadmeConfig:
    """Top-level rendering configuration for grouping repositories in README output."""

    categories: tuple[CategoryConfig, ...]


@dataclass(frozen=True, slots=True)
class RepoSnapshot:
    """Versioned snapshot payload containing all normalized repository entries."""

    schema_version: int
    org_name: str
    generated_at: str
    repos: tuple[RepoEntry, ...]
    tracked_deps: tuple[TrackedDep, ...] = ()
    workflow_signal_labels: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> RepoSnapshot:
        repos_data = data.get("repos")
        if not isinstance(repos_data, list):
            raise ValueError("Snapshot payload must contain a 'repos' list.")

        schema_version = data.get("schema_version", SNAPSHOT_SCHEMA_VERSION)
        if schema_version != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(
                "Unsupported snapshot schema version "
                f"{schema_version}; expected {SNAPSHOT_SCHEMA_VERSION}."
            )

        org_name = data.get("org_name")
        generated_at = data.get("generated_at")
        if not isinstance(org_name, str) or not org_name:
            raise ValueError("Snapshot payload must contain a non-empty 'org_name'.")
        if not isinstance(generated_at, str) or not generated_at:
            raise ValueError(
                "Snapshot payload must contain a non-empty 'generated_at'."
            )

        typed_repos_data = cast("list[Mapping[str, Any]]", repos_data)

        return cls(
            schema_version=cast("int", schema_version),
            org_name=org_name,
            generated_at=generated_at,
            repos=tuple(RepoEntry.from_dict(repo) for repo in typed_repos_data),
            tracked_deps=tuple(
                dep
                for item in (data.get("tracked_deps") or ())
                if isinstance(item, dict)
                and (dep := TrackedDep.from_dict(cast("Mapping[str, Any]", item)))
                and dep.repo
                and dep.module_name
            ),
            workflow_signal_labels=normalize_string_tuple(
                data.get("workflow_signal_labels")
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "org_name": self.org_name,
            "generated_at": self.generated_at,
            "repos": [repo.to_dict() for repo in self.repos],
            "tracked_deps": [dep.to_dict() for dep in self.tracked_deps],
            "workflow_signal_labels": list(self.workflow_signal_labels),
        }


CustomPropertyValue = str | list[str] | None


def normalize_string_pairs(value: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    items = cast("list[object]", list(value))
    result: list[tuple[str, str]] = []
    for raw in items:
        pair = cast("list[object]", list(raw)) if isinstance(raw, (list, tuple)) else None
        if pair is None or len(pair) != 2:
            continue
        name, ver = pair[0], pair[1]
        if isinstance(name, str) and isinstance(ver, str):
            result.append((name, ver))
    return tuple(result)


def normalize_string_tuple(value: object) -> tuple[str, ...]:
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, list):
        sequence_items = cast("list[object]", value)
        return tuple(item for item in sequence_items if isinstance(item, str))
    return ()


def lookup_bazel_dep_version(
    bazel_deps: tuple[tuple[str, str], ...],
    dep_name: str,
) -> str | None:
    for name, version in bazel_deps:
        if name == dep_name:
            return version
    return None
