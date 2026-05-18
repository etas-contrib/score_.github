from __future__ import annotations

import os
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, TypedDict, cast

from generate_repo_overview.models import (
    DEFAULT_CATEGORY,
    DEFAULT_SUBCATEGORY,
    CustomPropertyValue,
    DeepContentSignals,
    RegistrySignals,
    RepoEntry,
    VolatileMetricsSnapshot,
    WorkflowSignal,
)

from .signal_detection import (
    DeepContentPayload,
    detect_all_bazel_deps,
    detect_bazel_version,
    fetch_repository_tree_paths,
    inspect_repository_content_slow,
)

if TYPE_CHECKING:
    from .registry_metadata import RegistrySignalsPayload


class PullRequestCounts(TypedDict):
    ready: int
    draft: int
    total: int


class LatestReleaseDetails(TypedDict):
    version: str | None
    date: str | None
    commits_since_release: int | None
    release_bazel_version: str | None
    release_bazel_deps: tuple[tuple[str, str], ...]


class VolatileMetricsPayload(TypedDict):
    last_push_date: str | None
    merged_prs_30_days: int
    open_issues: int
    open_prs: int
    open_ready_prs: int
    open_draft_prs: int
    latest_release_version: str | None
    latest_release_date: str | None
    commits_since_latest_release: int | None
    release_bazel_version: str | None
    release_bazel_deps: tuple[tuple[str, str], ...]


MERGED_PULL_REQUEST_WINDOW_DAYS = 30
DEFAULT_VOLATILE_METRICS_TTL_MINUTES = 60
VOLATILE_METRICS_TTL_ENV = "REPO_OVERVIEW_VOLATILE_TTL_MINUTES"


def collect_repository_entry(
    *,
    repository_name: str,
    repository: Any,
    custom_properties: dict[str, CustomPropertyValue],
    bazel_registry_metadata: RegistrySignalsPayload | None,
    cached_entry: RepoEntry | None,
    referenced_by_reference_integration: bool = False,
    reuse_cached_entry_when_unchanged: bool = False,
    workflow_signals: tuple[WorkflowSignal, ...] = (),
) -> RepoEntry:
    fast_entry = maybe_collect_repository_entry_fast_path(
        repository_name=repository_name,
        repository=repository,
        custom_properties=custom_properties,
        bazel_registry_metadata=bazel_registry_metadata,
        referenced_by_reference_integration=referenced_by_reference_integration,
        cached_entry=cached_entry,
        reuse_cached_entry_when_unchanged=reuse_cached_entry_when_unchanged,
    )
    if fast_entry is not None:
        return fast_entry

    return collect_repository_entry_slow_path(
        repository_name=repository_name,
        repository=repository,
        custom_properties=custom_properties,
        bazel_registry_metadata=bazel_registry_metadata,
        referenced_by_reference_integration=referenced_by_reference_integration,
        cached_entry=cached_entry,
        workflow_signals=workflow_signals,
    )


def maybe_collect_repository_entry_fast_path(
    *,
    repository_name: str,
    repository: Any,
    custom_properties: dict[str, CustomPropertyValue],
    bazel_registry_metadata: RegistrySignalsPayload | None,
    referenced_by_reference_integration: bool,
    cached_entry: RepoEntry | None,
    reuse_cached_entry_when_unchanged: bool,
) -> RepoEntry | None:
    """Attempt a fast collection path that avoids deep content inspection.

    Returns ``None`` when the fast path is not applicable.
    """
    default_branch = cast("str | None", getattr(repository, "default_branch", None))
    default_branch_sha = get_default_branch_sha(repository, default_branch)
    cache_matches_default_branch = cached_entry_matches_default_branch(
        cached_entry,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )

    if not (reuse_cached_entry_when_unchanged and cache_matches_default_branch):
        return None

    assert cached_entry is not None
    if should_reuse_cached_volatile_metrics(cached_entry):
        return build_repo_entry_from_cached(
            cached_entry=cached_entry,
            repository_name=repository_name,
            description=cast("str | None", getattr(repository, "description", None)),
            custom_properties=custom_properties,
            default_branch=default_branch,
            default_branch_sha=default_branch_sha,
            bazel_registry_metadata=bazel_registry_metadata,
            referenced_by_reference_integration=referenced_by_reference_integration,
            stars=getattr(repository, "stargazers_count", 0) or 0,
            forks=getattr(repository, "forks_count", 0) or 0,
        )

    # Medium-fast variant: keep cached content indicators but refresh volatile API metrics.
    content_signals = cached_signals_for_repository(
        cached_entry,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )
    assert content_signals is not None
    content_signals["referenced_by_reference_integration"] = (
        referenced_by_reference_integration
    )
    volatile_metrics = collect_volatile_metrics(
        repository,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )
    registry_signals = build_registry_signals(bazel_registry_metadata)
    return build_repo_entry(
        repository_name=repository_name,
        description=cast("str | None", getattr(repository, "description", None)),
        custom_properties=custom_properties,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
        content_signals=content_signals,
        registry_signals=registry_signals,
        volatile_metrics=volatile_metrics,
        volatile_metrics_fetched_at=datetime.now(UTC).isoformat(),
        stars=getattr(repository, "stargazers_count", 0) or 0,
        forks=getattr(repository, "forks_count", 0) or 0,
    )


def collect_repository_entry_slow_path(
    *,
    repository_name: str,
    repository: Any,
    custom_properties: dict[str, CustomPropertyValue],
    bazel_registry_metadata: RegistrySignalsPayload | None,
    referenced_by_reference_integration: bool,
    cached_entry: RepoEntry | None,
    workflow_signals: tuple[WorkflowSignal, ...] = (),
) -> RepoEntry:
    """Collect a repository entry with deep content inspection.

    Reuses cached content signals when the default-branch SHA matches the
    cached entry.  Always refreshes volatile metrics and registry signals.
    """
    default_branch = cast("str | None", getattr(repository, "default_branch", None))
    default_branch_sha = get_default_branch_sha(repository, default_branch)

    cached_content_signals = cached_signals_for_repository(
        cached_entry,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )

    if cached_content_signals is None:
        content_signals = inspect_repository_content_slow(
            repository,
            ref=default_branch_sha,
            workflow_signals=workflow_signals,
        )
    else:
        content_signals = cached_content_signals
    content_signals["referenced_by_reference_integration"] = (
        referenced_by_reference_integration
    )
    volatile_metrics = collect_volatile_metrics(
        repository,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )
    registry_signals = build_registry_signals(bazel_registry_metadata)

    return build_repo_entry(
        repository_name=repository_name,
        description=cast("str | None", getattr(repository, "description", None)),
        custom_properties=custom_properties,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
        content_signals=content_signals,
        registry_signals=registry_signals,
        volatile_metrics=volatile_metrics,
        volatile_metrics_fetched_at=datetime.now(UTC).isoformat(),
        stars=getattr(repository, "stargazers_count", 0) or 0,
        forks=getattr(repository, "forks_count", 0) or 0,
    )


def collect_volatile_metrics(
    repository: Any,
    *,
    default_branch: str | None,
    default_branch_sha: str | None,
) -> VolatileMetricsPayload:
    """Collect volatile metrics from live API calls.

    This is comparatively slow and intentionally refreshed on demand based on
    the configured volatile-metric TTL.
    """
    open_pull_request_counts = get_open_pull_request_counts(repository)
    merged_pull_request_count = get_merged_pull_request_count_last_30_days(
        repository,
        default_branch=default_branch,
    )
    latest_release = get_latest_release_details(
        repository,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    )
    last_commit_date = get_default_branch_last_commit_date(
        repository,
        default_branch=default_branch,
    )
    return {
        "last_push_date": last_commit_date
        or iso_date(getattr(repository, "pushed_at", None)),
        "merged_prs_30_days": merged_pull_request_count,
        "open_issues": get_open_issue_count(
            repository,
            open_pull_request_total=open_pull_request_counts["total"],
        ),
        "open_prs": open_pull_request_counts["total"],
        "open_ready_prs": open_pull_request_counts["ready"],
        "open_draft_prs": open_pull_request_counts["draft"],
        "latest_release_version": latest_release["version"],
        "latest_release_date": latest_release["date"],
        "commits_since_latest_release": latest_release["commits_since_release"],
        "release_bazel_version": latest_release["release_bazel_version"],
        "release_bazel_deps": latest_release["release_bazel_deps"],
    }


def get_default_branch_last_commit_date(
    repository: Any,
    *,
    default_branch: str | None,
) -> str | None:
    if not default_branch:
        return None

    try:
        branch = repository.get_branch(default_branch)
    except Exception:
        return None

    commit = getattr(branch, "commit", None)
    nested_commit = getattr(commit, "commit", None)
    committer = getattr(nested_commit, "committer", None)
    timestamp = getattr(committer, "date", None)
    return iso_date(timestamp)


def cached_signals_for_repository(
    cached_entry: RepoEntry | None,
    *,
    default_branch: str | None,
    default_branch_sha: str | None,
) -> DeepContentPayload | None:
    if not cached_entry_matches_default_branch(
        cached_entry,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
    ):
        return None

    assert cached_entry is not None
    return {
        "is_bazel_repo": cached_entry.content.is_bazel_repo,
        "bazel_version": cached_entry.content.bazel_version,
        "codeowners": cached_entry.content.codeowners,
        "referenced_by_reference_integration": (
            cached_entry.content.referenced_by_reference_integration
        ),
        "has_lint_config": cached_entry.content.has_lint_config,
        "has_gitlint_config": cached_entry.content.has_gitlint_config,
        "has_pyproject_toml": cached_entry.content.has_pyproject_toml,
        "has_pre_commit_config": cached_entry.content.has_pre_commit_config,
        "has_ci": cached_entry.content.has_ci,
        "matched_workflow_signals": cached_entry.content.matched_workflow_signals,
        "has_coverage_config": cached_entry.content.has_coverage_config,
        "top_languages": cached_entry.content.top_languages,
        "bazel_deps": cached_entry.content.bazel_deps,
    }


def cached_entry_matches_default_branch(
    cached_entry: RepoEntry | None,
    *,
    default_branch: str | None,
    default_branch_sha: str | None,
) -> bool:
    if cached_entry is None:
        return False

    # Reuse cached repository details only when we can prove the default-branch state is unchanged.
    cached_sha = cached_entry.default_branch_sha
    if default_branch_sha is not None:
        return cached_sha == default_branch_sha

    if default_branch is not None:
        return cached_entry.default_branch == default_branch

    return False


def build_repo_entry_from_cached(
    *,
    cached_entry: RepoEntry,
    repository_name: str,
    description: str | None,
    custom_properties: dict[str, CustomPropertyValue],
    default_branch: str | None,
    default_branch_sha: str | None,
    bazel_registry_metadata: RegistrySignalsPayload | None,
    referenced_by_reference_integration: bool,
    stars: int,
    forks: int,
) -> RepoEntry:
    registry = build_registry_signals(bazel_registry_metadata)
    content = replace(
        cached_entry.content,
        referenced_by_reference_integration=referenced_by_reference_integration,
    )
    return replace(
        cached_entry,
        name=repository_name,
        description=description or "(no description)",
        category=normalize_group_name(
            custom_properties.get("category"), DEFAULT_CATEGORY
        ),
        subcategory=normalize_group_name(
            custom_properties.get("subcategory"),
            DEFAULT_SUBCATEGORY,
        ),
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
        content=content,
        registry=registry,
        stars=stars,
        forks=forks,
    )


def build_repo_entry(
    repository_name: str,
    description: str | None,
    custom_properties: dict[str, CustomPropertyValue],
    *,
    default_branch: str | None = None,
    default_branch_sha: str | None = None,
    content_signals: DeepContentPayload,
    registry_signals: RegistrySignals,
    volatile_metrics: VolatileMetricsPayload,
    volatile_metrics_fetched_at: str | None = None,
    stars: int = 0,
    forks: int = 0,
) -> RepoEntry:
    category = normalize_group_name(custom_properties.get("category"), DEFAULT_CATEGORY)
    subcategory = normalize_group_name(
        custom_properties.get("subcategory"),
        DEFAULT_SUBCATEGORY,
    )
    return RepoEntry(
        name=repository_name,
        description=description or "(no description)",
        category=category,
        subcategory=subcategory,
        default_branch=default_branch,
        default_branch_sha=default_branch_sha,
        content=DeepContentSignals(
            is_bazel_repo=content_signals["is_bazel_repo"],
            bazel_version=content_signals["bazel_version"],
            codeowners=content_signals["codeowners"],
            referenced_by_reference_integration=bool(
                content_signals.get("referenced_by_reference_integration", False)
            ),
            has_lint_config=content_signals["has_lint_config"],
            has_gitlint_config=bool(content_signals.get("has_gitlint_config", False)),
            has_pyproject_toml=bool(content_signals.get("has_pyproject_toml", False)),
            has_pre_commit_config=bool(
                content_signals.get("has_pre_commit_config", False)
            ),
            has_ci=content_signals["has_ci"],
            matched_workflow_signals=content_signals["matched_workflow_signals"],
            has_coverage_config=content_signals["has_coverage_config"],
            top_languages=content_signals.get("top_languages", ()),
            bazel_deps=content_signals.get("bazel_deps", ()),
        ),
        registry=registry_signals,
        volatile=VolatileMetricsSnapshot(
            last_push_date=volatile_metrics["last_push_date"],
            merged_prs_30_days=volatile_metrics["merged_prs_30_days"],
            open_issues=volatile_metrics["open_issues"],
            open_prs=volatile_metrics["open_prs"],
            open_ready_prs=volatile_metrics["open_ready_prs"],
            open_draft_prs=volatile_metrics["open_draft_prs"],
            latest_release_version=volatile_metrics["latest_release_version"],
            latest_release_date=volatile_metrics["latest_release_date"],
            commits_since_latest_release=volatile_metrics[
                "commits_since_latest_release"
            ],
            release_bazel_version=volatile_metrics["release_bazel_version"],
            release_bazel_deps=volatile_metrics["release_bazel_deps"],
            volatile_metrics_fetched_at=volatile_metrics_fetched_at,
        ),
        stars=stars,
        forks=forks,
    )


def should_reuse_cached_volatile_metrics(cached_entry: RepoEntry) -> bool:
    fetched_at = parse_datetime_utc(cached_entry.volatile.volatile_metrics_fetched_at)
    if fetched_at is None:
        return False
    ttl = resolve_volatile_metrics_ttl()
    return datetime.now(UTC) - fetched_at <= ttl


def build_registry_signals(
    metadata: RegistrySignalsPayload | None,
) -> RegistrySignals:
    return RegistrySignals(
        maintainers_in_bazel_registry=(
            metadata.get("maintainers_in_bazel_registry")
            if metadata is not None
            else ()
        ),
        latest_bazel_registry_version=(
            metadata.get("latest_bazel_registry_version")
            if metadata is not None
            else None
        ),
    )


def resolve_volatile_metrics_ttl() -> timedelta:
    raw_value = os.getenv(VOLATILE_METRICS_TTL_ENV, "").strip()
    if not raw_value:
        return timedelta(minutes=DEFAULT_VOLATILE_METRICS_TTL_MINUTES)

    try:
        parsed_minutes = int(raw_value)
    except ValueError:
        return timedelta(minutes=DEFAULT_VOLATILE_METRICS_TTL_MINUTES)

    if parsed_minutes < 0:
        return timedelta(minutes=DEFAULT_VOLATILE_METRICS_TTL_MINUTES)
    return timedelta(minutes=parsed_minutes)


def parse_datetime_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_group_name(value: str | list[str] | None, fallback: str) -> str:
    if value is None:
        return fallback
    if isinstance(value, list):
        cleaned = [item.strip() for item in value if item.strip()]
        return ", ".join(cleaned) if cleaned else fallback
    cleaned = value.strip()
    return cleaned or fallback


def get_default_branch_sha(repository: Any, default_branch: str | None) -> str | None:
    if default_branch is None or not hasattr(repository, "get_branch"):
        return None

    try:
        branch = repository.get_branch(default_branch)
    except Exception:
        return None
    return cast("str | None", getattr(getattr(branch, "commit", None), "sha", None))


def get_open_issue_count(repository: Any, *, open_pull_request_total: int) -> int:
    count = getattr(repository, "open_issues_count", 0)
    if not isinstance(count, int):
        return 0
    return max(count - open_pull_request_total, 0)


def get_open_pull_request_counts(repository: Any) -> PullRequestCounts:
    try:
        pulls = repository.get_pulls(state="open")
    except Exception:
        return default_open_pull_request_counts()

    try:
        pull_requests = list(pulls)
    except Exception:
        return default_open_pull_request_counts()

    draft_count = sum(
        is_draft_pull_request(pull_request) for pull_request in pull_requests
    )
    total_count = len(pull_requests)
    return {
        "ready": total_count - draft_count,
        "draft": draft_count,
        "total": total_count,
    }


def get_merged_pull_request_count_last_30_days(
    repository: Any,
    *,
    default_branch: str | None,
) -> int:
    if default_branch is None:
        return 0

    cutoff = datetime.now(UTC) - timedelta(days=MERGED_PULL_REQUEST_WINDOW_DAYS)
    try:
        pulls = repository.get_pulls(
            state="closed",
            sort="updated",
            direction="desc",
            base=default_branch,
        )
    except Exception:
        return 0

    count = 0
    for pull_request in pulls:
        updated_at = normalize_datetime_utc(getattr(pull_request, "updated_at", None))
        # With descending `updated` ordering, once we pass the cutoff we can stop scanning.
        if updated_at is not None and updated_at < cutoff:
            break

        base = getattr(pull_request, "base", None)
        base_ref = getattr(base, "ref", None)
        if isinstance(base_ref, str) and base_ref != default_branch:
            continue

        merged_at = normalize_datetime_utc(getattr(pull_request, "merged_at", None))
        if merged_at is None or merged_at < cutoff:
            continue
        count += 1

    return count


def normalize_datetime_utc(value: object) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    # Treat naive timestamps as UTC so comparisons stay deterministic.
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def default_open_pull_request_counts() -> PullRequestCounts:
    return {"ready": 0, "draft": 0, "total": 0}


def is_draft_pull_request(pull_request: Any) -> bool:
    draft: object
    try:
        draft = getattr(pull_request, "draft", None)
    except Exception:
        draft = None
    if isinstance(draft, bool):
        return draft

    try:
        raw_data = getattr(pull_request, "raw_data", None)
    except Exception:
        raw_data = None
    if isinstance(raw_data, dict):
        draft = cast("object", raw_data.get("draft"))
        if isinstance(draft, bool):
            return draft
    return False


def get_latest_release_details(
    repository: Any,
    *,
    default_branch: str | None,
    default_branch_sha: str | None,
) -> LatestReleaseDetails:
    if not hasattr(repository, "get_latest_release"):
        return default_latest_release_details()
    try:
        release = repository.get_latest_release()
    except Exception:
        return default_latest_release_details()

    release_tag = get_latest_release_version(release)
    release_tree = fetch_repository_tree_paths(repository, ref=release_tag)
    return {
        "version": release_tag,
        "date": get_release_date(release),
        "commits_since_release": get_commits_since_release(
            repository,
            release=release,
            default_branch=default_branch,
            default_branch_sha=default_branch_sha,
        ),
        "release_bazel_version": detect_bazel_version(
            repository,
            tree_paths=release_tree,
            ref=release_tag,
        ),
        "release_bazel_deps": detect_all_bazel_deps(
            repository,
            tree_paths=release_tree,
            ref=release_tag,
        ),
    }


def default_latest_release_details() -> LatestReleaseDetails:
    return {
        "version": None,
        "date": None,
        "commits_since_release": None,
        "release_bazel_version": None,
        "release_bazel_deps": (),
    }


def get_latest_release_version(release: object) -> str | None:
    try:
        raw_data = getattr(release, "raw_data", None)
    except Exception:
        raw_data = None
    if isinstance(raw_data, dict):
        raw_data = cast("dict[str, object]", raw_data)
        for key in ("tag_name", "name"):
            value = raw_data.get(key)
            if isinstance(value, str):
                cleaned = value.strip()
                if cleaned:
                    return cleaned

    for attribute_name in ("name", "title"):
        try:
            value = getattr(release, attribute_name, None)
        except Exception:
            continue
        if isinstance(value, str):
            cleaned = value.strip()
            if cleaned and cleaned.casefold() != "latest":
                return cleaned
    return None


def get_release_date(release: object) -> str | None:
    try:
        return iso_date(getattr(release, "published_at", None))
    except Exception:
        return None


def get_commits_since_release(
    repository: Any,
    *,
    release: Any,
    default_branch: str | None,
    default_branch_sha: str | None,
) -> int | None:
    if not hasattr(repository, "compare"):
        return None

    release_tag = get_latest_release_version(release)
    head_ref = default_branch_sha or default_branch
    if release_tag is None or head_ref is None:
        return None

    try:
        comparison = repository.compare(release_tag, head_ref)
    except Exception:
        return None

    try:
        total_commits = getattr(comparison, "total_commits", None)
        if isinstance(total_commits, int):
            return total_commits

        total_commits = getattr(comparison, "totalCommits", None)
        return total_commits if isinstance(total_commits, int) else None
    except Exception:
        return None


def iso_date(value: object) -> str | None:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return None
