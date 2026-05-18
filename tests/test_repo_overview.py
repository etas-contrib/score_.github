import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest

import generate_repo_overview.collector as collector
import generate_repo_overview.collector.reference_integration as reference_integration
import generate_repo_overview.collector.registry_metadata as registry_metadata
import generate_repo_overview.collector.repo_entry as repo_entry
import generate_repo_overview.collector.signal_detection as signal_detection
import generate_repo_overview.collector.snapshot_io as snapshot_io
from generate_repo_overview.metrics_report import render_metrics_report
from generate_repo_overview.models import (
    SNAPSHOT_SCHEMA_VERSION,
    DeepContentSignals,
    RegistrySignals,
    RepoEntry,
    RepoSnapshot,
    TrackedDep,
    VolatileMetricsSnapshot,
    WorkflowSignal,
)
from generate_repo_overview.org_config import OrgConfig


def test_snapshot_round_trip_preserves_repository_overview(tmp_path: Path) -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                default_branch="main",
                default_branch_sha="abc123",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    bazel_version="8.4.2",
                    codeowners=("@infra-team",),
                    referenced_by_reference_integration=True,
                    has_lint_config=True,
                    has_gitlint_config=True,
                    has_pyproject_toml=True,
                    has_pre_commit_config=True,
                    has_ci=True,
                    matched_workflow_signals=("Daily Workflow",),
                    has_coverage_config=False,
                ),
                registry=RegistrySignals(
                    maintainers_in_bazel_registry=("Andrey Babanin (@4og)",),
                    latest_bazel_registry_version="0.2.5",
                ),
                volatile=VolatileMetricsSnapshot(
                    last_push_date="2026-04-12",
                    open_issues=2,
                    open_prs=1,
                    open_ready_prs=1,
                    open_draft_prs=0,
                    latest_release_version="v1.2.3",
                    latest_release_date="2026-04-01",
                    commits_since_latest_release=7,
                ),
                stars=3,
                forks=4,
            ),
        ),
        tracked_deps=(
            TrackedDep(repo="eclipse-score/docs-as-code", module_name="score_docs_as_code"),
        ),
        workflow_signal_labels=("Daily Workflow",),
    )
    snapshot_path = tmp_path / "repo_overview.json"

    snapshot_io.write_snapshot(snapshot, snapshot_path)

    assert snapshot_io.load_snapshot(snapshot_path) == snapshot


def test_ensure_snapshot_prefers_existing_cache(tmp_path: Path) -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(RepoEntry("tools", "Tooling", "Infrastructure", "Tooling"),),
    )
    snapshot_path = tmp_path / "repo_overview.json"
    snapshot_io.write_snapshot(snapshot, snapshot_path)

    loaded_snapshot = collector.ensure_snapshot(
        config=OrgConfig(org_name="eclipse-score"),
        cache_path=snapshot_path,
    )

    assert loaded_snapshot == snapshot


def test_fetch_repositories_reuses_cached_content_signals() -> None:
    pushed_at = datetime(2026, 4, 13, 10, 0, tzinfo=UTC)
    release_at = datetime(2026, 4, 1, 8, 0, tzinfo=UTC)

    class FakeRepo:
        archived = False
        name = "tools"
        description = "Tooling"
        default_branch = "main"

        def __init__(self) -> None:
            self.tree_calls = 0
            self.pushed_at = pushed_at
            self.open_issues_count = 3
            self.stargazers_count = 3
            self.forks_count = 4

        def get_branch(self, branch_name: str) -> SimpleNamespace:
            assert branch_name == "main"
            return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

        def get_git_tree(self, ref: str, recursive: bool = True) -> SimpleNamespace:
            self.tree_calls += 1
            return SimpleNamespace(tree=[])

        def get_pulls(
            self,
            state: str = "open",
            **_: Any,
        ) -> list[SimpleNamespace]:
            if state == "open":
                return [SimpleNamespace(draft=False)]
            if state == "closed":
                return []
            raise AssertionError(f"Unexpected pull state: {state}")

        def get_latest_release(self) -> SimpleNamespace:
            return SimpleNamespace(
                raw_data={"tag_name": "v1.2.3"},
                tag_name="latest",
                published_at=release_at,
            )

        def compare(self, base: str, head: str) -> SimpleNamespace:
            assert base == "v1.2.3"
            assert head == "abc123"
            return SimpleNamespace(total_commits=7)

    fake_repo = FakeRepo()
    organization = SimpleNamespace(login="eclipse-score")
    cached_snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                default_branch="main",
                default_branch_sha="abc123",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    bazel_version="8.4.2",
                    codeowners=("@infra-team",),
                    has_lint_config=True,
                    has_ci=True,
                    matched_workflow_signals=("Daily Workflow",),
                    has_coverage_config=False,
                ),
                volatile=VolatileMetricsSnapshot(
                    volatile_metrics_fetched_at="2026-04-13T11:30:00+00:00",
                ),
            ),
        ),
    )

    original_fetch_active_repositories = collector.fetch_active_repositories
    try:
        collector.fetch_active_repositories = lambda organization, **_kwargs: {
            "tools": collector.ActiveRepositoryData(
                repository=fake_repo,
                custom_properties={},
            )
        }
        repos = collector.fetch_repositories(
            cast("Any", organization),
            existing_snapshot=cached_snapshot,
        )
    finally:
        collector.fetch_active_repositories = original_fetch_active_repositories

    assert fake_repo.tree_calls == 1
    assert len(repos) == 1
    entry = repos[0]
    assert entry.name == "tools"
    assert entry.default_branch_sha == "abc123"
    assert entry.content.is_bazel_repo is True
    assert entry.content.bazel_version == "8.4.2"
    assert entry.volatile.last_push_date == "2026-04-13"
    assert entry.volatile.open_issues == 2
    assert entry.volatile.open_prs == 1
    assert entry.volatile.open_ready_prs == 1
    assert entry.volatile.open_draft_prs == 0
    assert entry.volatile.latest_release_version == "v1.2.3"
    assert entry.volatile.latest_release_date == "2026-04-01"
    assert entry.volatile.commits_since_latest_release == 7
    assert entry.volatile.volatile_metrics_fetched_at is not None
    assert entry.stars == 3
    assert entry.forks == 4


def test_fetch_repositories_invalidates_cache_when_signal_labels_change() -> None:
    """D4.1: When workflow signal labels in config differ from cached snapshot,
    content cache is ignored and signals are re-evaluated from scratch."""
    pushed_at = datetime(2026, 4, 13, 10, 0, tzinfo=UTC)

    class FakeRepo:
        archived = False
        name = "tools"
        description = "Tooling"
        default_branch = "main"

        def __init__(self) -> None:
            self.pushed_at = pushed_at
            self.open_issues_count = 0
            self.stargazers_count = 0
            self.forks_count = 0

        def get_branch(self, branch_name: str) -> SimpleNamespace:
            return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

        def get_git_tree(self, ref: str, recursive: bool = True) -> SimpleNamespace:
            return SimpleNamespace(tree=[])

        def get_pulls(self, state: str = "open", **_: Any) -> list[SimpleNamespace]:
            return []

        def get_latest_release(self) -> SimpleNamespace:
            raise Exception("no releases")

    fake_repo = FakeRepo()
    organization = SimpleNamespace(login="eclipse-score")

    cached_snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        workflow_signal_labels=("Daily Workflow",),
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                default_branch="main",
                default_branch_sha="abc123",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    matched_workflow_signals=("Daily Workflow",),
                ),
            ),
        ),
    )

    config = OrgConfig(
        org_name="eclipse-score",
        workflow_signals=(
            WorkflowSignal(label="Nightly Build", reference="org/ref@"),
        ),
    )

    original_fetch = collector.fetch_active_repositories
    try:
        collector.fetch_active_repositories = lambda organization, **_kwargs: {
            "tools": collector.ActiveRepositoryData(
                repository=fake_repo,
                custom_properties={},
            )
        }
        repos = collector.fetch_repositories(
            cast("Any", organization),
            existing_snapshot=cached_snapshot,
            config=config,
        )
    finally:
        collector.fetch_active_repositories = original_fetch

    assert len(repos) == 1
    entry = repos[0]
    # Cache was invalidated: is_bazel_repo should be False (empty tree)
    # instead of True (from cache)
    assert entry.content.is_bazel_repo is False
    assert entry.content.matched_workflow_signals == ()


def test_collect_repository_entry_reuses_cached_details_when_unchanged() -> None:
    class FakeRepo:
        default_branch = "main"
        description = "Tooling (updated)"
        stargazers_count = 12
        forks_count = 3

        def get_branch(self, branch_name: str) -> SimpleNamespace:
            assert branch_name == "main"
            return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

        def get_git_tree(self, ref: str, recursive: bool = True) -> SimpleNamespace:
            raise AssertionError(
                "get_git_tree should not be called in cache-aware fast mode"
            )

        def get_pulls(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
            raise AssertionError(
                "get_pulls should not be called in cache-aware fast mode"
            )

        def get_latest_release(self) -> SimpleNamespace:
            raise AssertionError(
                "get_latest_release should not be called in cache-aware fast mode"
            )

    repo = FakeRepo()
    cached_entry = RepoEntry(
        name="tools",
        description="Tooling",
        category="Infrastructure",
        subcategory="Tooling",
        default_branch="main",
        default_branch_sha="abc123",
        content=DeepContentSignals(
            is_bazel_repo=True,
            bazel_version="8.4.2",
            codeowners=("@infra-team",),
            referenced_by_reference_integration=False,
            has_lint_config=True,
            has_gitlint_config=True,
            has_pyproject_toml=True,
            has_pre_commit_config=True,
            has_ci=True,
            matched_workflow_signals=("Daily Workflow",),
            has_coverage_config=True,
            bazel_deps=(("score_docs_as_code", "1.2.3"),),
        ),
        registry=RegistrySignals(
            maintainers_in_bazel_registry=("Old Maintainer",),
            latest_bazel_registry_version="0.1.0",
        ),
        volatile=VolatileMetricsSnapshot(
            last_push_date="2026-04-10",
            merged_prs_30_days=8,
            open_issues=7,
            open_prs=4,
            open_ready_prs=3,
            open_draft_prs=1,
            latest_release_version="v1.2.3",
            latest_release_date="2026-04-01",
            commits_since_latest_release=5,
            volatile_metrics_fetched_at="2099-01-01T00:00:00+00:00",
        ),
        stars=1,
        forks=1,
    )

    entry = repo_entry.collect_repository_entry(
        repository_name="tools",
        repository=repo,
        custom_properties={"category": "Engineering", "subcategory": "Platform"},
        bazel_registry_metadata={
            "maintainers_in_bazel_registry": ("New Maintainer",),
            "latest_bazel_registry_version": "0.2.0",
        },
        cached_entry=cached_entry,
        referenced_by_reference_integration=True,
        reuse_cached_entry_when_unchanged=True,
    )

    assert entry == RepoEntry(
        name="tools",
        description="Tooling (updated)",
        category="Engineering",
        subcategory="Platform",
        default_branch="main",
        default_branch_sha="abc123",
        content=DeepContentSignals(
            is_bazel_repo=True,
            bazel_version="8.4.2",
            codeowners=("@infra-team",),
            referenced_by_reference_integration=True,
            has_lint_config=True,
            has_gitlint_config=True,
            has_pyproject_toml=True,
            has_pre_commit_config=True,
            has_ci=True,
            matched_workflow_signals=("Daily Workflow",),
            has_coverage_config=True,
            bazel_deps=(("score_docs_as_code", "1.2.3"),),
        ),
        registry=RegistrySignals(
            maintainers_in_bazel_registry=("New Maintainer",),
            latest_bazel_registry_version="0.2.0",
        ),
        volatile=VolatileMetricsSnapshot(
            last_push_date="2026-04-10",
            merged_prs_30_days=8,
            open_issues=7,
            open_prs=4,
            open_ready_prs=3,
            open_draft_prs=1,
            latest_release_version="v1.2.3",
            latest_release_date="2026-04-01",
            commits_since_latest_release=5,
            volatile_metrics_fetched_at="2099-01-01T00:00:00+00:00",
        ),
        stars=12,
        forks=3,
    )


def test_collect_repository_entry_does_not_reuse_cached_registry_when_metadata_missing() -> (
    None
):
    class FakeRepo:
        default_branch = "main"
        description = "Tooling"
        stargazers_count = 5
        forks_count = 2

        def get_branch(self, branch_name: str) -> SimpleNamespace:
            assert branch_name == "main"
            return SimpleNamespace(commit=SimpleNamespace(sha="abc123"))

        def get_git_tree(self, ref: str, recursive: bool = True) -> SimpleNamespace:
            raise AssertionError(
                "get_git_tree should not be called in cache-aware fast mode"
            )

        def get_pulls(self, *args: Any, **kwargs: Any) -> list[SimpleNamespace]:
            raise AssertionError(
                "get_pulls should not be called in cache-aware fast mode"
            )

        def get_latest_release(self) -> SimpleNamespace:
            raise AssertionError(
                "get_latest_release should not be called in cache-aware fast mode"
            )

    cached_entry = RepoEntry(
        name="tools",
        description="Tooling",
        category="Infrastructure",
        subcategory="Tooling",
        default_branch="main",
        default_branch_sha="abc123",
        content=DeepContentSignals(is_bazel_repo=True),
        registry=RegistrySignals(
            maintainers_in_bazel_registry=("Stale Maintainer",),
            latest_bazel_registry_version="9.9.9",
        ),
        volatile=VolatileMetricsSnapshot(
            volatile_metrics_fetched_at="2099-01-01T00:00:00+00:00",
        ),
    )

    entry = repo_entry.collect_repository_entry(
        repository_name="tools",
        repository=FakeRepo(),
        custom_properties={},
        bazel_registry_metadata=None,
        cached_entry=cached_entry,
        reuse_cached_entry_when_unchanged=True,
    )

    assert entry.registry == RegistrySignals()


def test_collect_repository_entry_refreshes_stale_volatile_metrics_without_tree_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            current = cls(2026, 4, 17, 12, 0, tzinfo=UTC)
            return current if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr(repo_entry, "datetime", FixedDatetime)

    class FakeRepo:
        default_branch = "main"
        description = "Tooling"
        stargazers_count = 2
        forks_count = 3
        pushed_at = datetime(2026, 4, 16, 12, 0, tzinfo=UTC)
        open_issues_count = 6

        def __init__(self) -> None:
            self.tree_calls = 0

        def get_branch(self, branch_name: str) -> SimpleNamespace:
            assert branch_name == "main"
            return SimpleNamespace(
                commit=SimpleNamespace(
                    sha="abc123",
                    commit=SimpleNamespace(
                        committer=SimpleNamespace(date=self.pushed_at)
                    ),
                )
            )

        def get_git_tree(self, ref: str, recursive: bool = True) -> SimpleNamespace:
            self.tree_calls += 1
            return SimpleNamespace(tree=[])

        def get_pulls(self, state: str = "open", **_: Any) -> list[SimpleNamespace]:
            if state == "open":
                return [SimpleNamespace(draft=False), SimpleNamespace(draft=True)]
            return []

        def get_latest_release(self) -> SimpleNamespace:
            return SimpleNamespace(
                raw_data={"tag_name": "v1.0.0"}, published_at=self.pushed_at
            )

        def compare(self, base: str, head: str) -> SimpleNamespace:
            assert base == "v1.0.0"
            assert head == "abc123"
            return SimpleNamespace(total_commits=4)

    repo = FakeRepo()
    cached_entry = RepoEntry(
        name="tools",
        description="Tooling",
        category="Infrastructure",
        subcategory="Tooling",
        default_branch="main",
        default_branch_sha="abc123",
        content=DeepContentSignals(
            is_bazel_repo=True,
            bazel_version="8.4.2",
            codeowners=("@infra-team",),
            has_lint_config=True,
            has_ci=True,
            matched_workflow_signals=("Daily Workflow",),
            has_coverage_config=False,
        ),
        volatile=VolatileMetricsSnapshot(
            open_issues=1,
            open_prs=1,
            open_ready_prs=1,
            merged_prs_30_days=1,
            latest_release_version="v0.9.0",
            latest_release_date="2026-04-01",
            commits_since_latest_release=1,
            volatile_metrics_fetched_at="2026-04-17T09:00:00+00:00",
        ),
    )

    entry = repo_entry.collect_repository_entry(
        repository_name="tools",
        repository=repo,
        custom_properties={},
        bazel_registry_metadata=None,
        cached_entry=cached_entry,
        reuse_cached_entry_when_unchanged=True,
    )

    assert repo.tree_calls == 1
    assert entry.content.is_bazel_repo is True
    assert entry.volatile.open_prs == 2
    assert entry.volatile.open_ready_prs == 1
    assert entry.volatile.open_draft_prs == 1
    assert entry.volatile.open_issues == 4
    assert entry.volatile.latest_release_version == "v1.0.0"
    assert entry.volatile.commits_since_latest_release == 4
    assert entry.volatile.volatile_metrics_fetched_at == "2026-04-17T12:00:00+00:00"


def test_get_open_pull_request_counts_splits_ready_and_draft() -> None:
    repository = SimpleNamespace(
        get_pulls=lambda state="open": [
            SimpleNamespace(draft=False),
            SimpleNamespace(raw_data={"draft": True}),
            SimpleNamespace(draft=False),
        ]
    )

    assert repo_entry.get_open_pull_request_counts(repository) == {
        "ready": 2,
        "draft": 1,
        "total": 3,
    }
    assert (
        repo_entry.get_open_issue_count(
            SimpleNamespace(open_issues_count=5),
            open_pull_request_total=3,
        )
        == 2
    )


def test_get_merged_pull_request_count_last_30_days_filters_by_branch_and_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> datetime:
            return now if tz is not None else now.replace(tzinfo=None)

    now = FixedDatetime(2026, 4, 17, 12, 0, tzinfo=UTC)
    cutoff = now - repo_entry.timedelta(days=repo_entry.MERGED_PULL_REQUEST_WINDOW_DAYS)

    monkeypatch.setattr(repo_entry, "datetime", FixedDatetime)

    def get_pulls(
        *, state: str, sort: str, direction: str, base: str
    ) -> list[SimpleNamespace]:
        assert state == "closed"
        assert sort == "updated"
        assert direction == "desc"
        assert base == "main"
        return [
            SimpleNamespace(
                merged_at=now - repo_entry.timedelta(days=5),
                updated_at=now - repo_entry.timedelta(days=4),
                base=SimpleNamespace(ref="main"),
            ),
            SimpleNamespace(
                merged_at=now - repo_entry.timedelta(days=2),
                updated_at=now - repo_entry.timedelta(days=1),
                base=SimpleNamespace(ref="release"),
            ),
            SimpleNamespace(
                merged_at=None,
                updated_at=now - repo_entry.timedelta(days=1),
                base=SimpleNamespace(ref="main"),
            ),
            SimpleNamespace(
                merged_at=cutoff - repo_entry.timedelta(days=1),
                updated_at=cutoff - repo_entry.timedelta(days=1),
                base=SimpleNamespace(ref="main"),
            ),
        ]

    repository = SimpleNamespace(get_pulls=get_pulls)

    assert (
        repo_entry.get_merged_pull_request_count_last_30_days(
            repository,
            default_branch="main",
        )
        == 1
    )


def test_get_merged_pull_request_count_last_30_days_returns_zero_without_default_branch() -> (
    None
):
    repository = SimpleNamespace(get_pulls=lambda **kwargs: [])

    assert (
        repo_entry.get_merged_pull_request_count_last_30_days(
            repository,
            default_branch=None,
        )
        == 0
    )


def test_get_latest_release_details_returns_none_when_release_lookup_is_lazy() -> None:
    class LazyFailingRelease:
        @property
        def tag_name(self) -> str:
            raise RuntimeError("Not Found")

    repository = SimpleNamespace(get_latest_release=lambda: LazyFailingRelease())

    assert repo_entry.get_latest_release_details(
        repository,
        default_branch="main",
        default_branch_sha="abc123",
    ) == {
        "version": None,
        "date": None,
        "commits_since_release": None,
        "release_bazel_version": None,
        "release_bazel_deps": (),
    }


def test_get_latest_release_version_prefers_raw_tag_name() -> None:
    release = SimpleNamespace(
        raw_data={"tag_name": "v0.2.5", "name": "Release 0.2.5"},
        name="Release 0.2.5",
        tag_name="latest",
    )

    assert repo_entry.get_latest_release_version(release) == "v0.2.5"


def test_get_latest_release_version_ignores_latest_sentinel_without_raw_data() -> None:
    release = SimpleNamespace(name="latest", title="latest")

    assert repo_entry.get_latest_release_version(release) is None


def test_detect_bazel_version_ignores_module_version_without_dot_bazelversion() -> None:
    assert (
        signal_detection.detect_bazel_version(
            SimpleNamespace(),
            tree_paths={"MODULE.bazel"},
            ref="abc123",
        )
        is None
    )


def test_get_all_bazel_dep_versions_extracts_dependency_versions() -> None:
    assert signal_detection.get_all_bazel_dep_versions(
        'bazel_dep(name = "score_docs_as_code", version = "4.0.0")\n'
        'bazel_dep(name = "score_process", version = "1.2.3")\n',
    ) == (("score_docs_as_code", "4.0.0"), ("score_process", "1.2.3"))


def test_get_all_bazel_dep_versions_returns_empty_for_no_deps() -> None:
    assert signal_detection.get_all_bazel_dep_versions("# no deps\n") == ()


def test_reference_integration_reads_recursive_included_module_files(
    tmp_path: Path,
) -> None:
    (tmp_path / "MODULE.bazel").write_text(
        """
bazel_dep(name = "score_root")
include("//bazel_common:deps.MODULE.bazel")
""".strip(),
        encoding="utf-8",
    )
    bazel_common = tmp_path / "bazel_common"
    bazel_common.mkdir()
    (bazel_common / "deps.MODULE.bazel").write_text(
        """
bazel_dep(name = "score_tooling")
include(":nested.MODULE.bazel")
""".strip(),
        encoding="utf-8",
    )
    (bazel_common / "nested.MODULE.bazel").write_text(
        'bazel_dep(name = "score_logging")\n',
        encoding="utf-8",
    )

    contents = reference_integration.read_included_module_files(tmp_path)

    assert set(contents) == {
        Path("MODULE.bazel"),
        Path("bazel_common/deps.MODULE.bazel"),
        Path("bazel_common/nested.MODULE.bazel"),
    }
    assert reference_integration.get_bazel_dep_names_from_contents(
        contents.values()
    ) == ("score_root", "score_tooling", "score_logging")


def test_reference_integration_maps_git_overrides_to_active_repositories() -> None:
    assert reference_integration.get_git_override_repositories_from_text(
        """
git_override(
    module_name = "score_tooling",
    commit = "abc123",
    remote = "https://github.com/eclipse-score/tooling.git",
)
git_override(
    module_name = "external",
    remote = "https://github.com/example/external.git",
)
""".strip(),
        active_repository_names={"tooling"},
        org_name="eclipse-score",
    ) == {"score_tooling": "tooling"}


def test_reference_integration_maps_bazel_registry_modules_to_repositories(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registry_root = tmp_path / "bazel_registry_checkout"
    metadata_dir = registry_root / "modules" / "score_process"
    metadata_dir.mkdir(parents=True)
    (metadata_dir / "metadata.json").write_text(
        """
{
  "repository": ["github:eclipse-score/process_description"],
  "versions": ["1.0.0"]
}
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        reference_integration,
        "BAZEL_REGISTRY_LOCAL_CHECKOUT",
        registry_root,
    )

    assert reference_integration.get_bazel_registry_repositories_by_module(
        active_repository_names={"process_description"}
    ) == {"score_process": "process_description"}


def test_get_codeowners_for_path_prefers_specific_codeowners_rule() -> None:
    assert signal_detection.get_codeowners_for_path(
        """
* @infra-team
.github/CODEOWNERS @docs-team @platform-team
""".strip(),
        target_path=".github/CODEOWNERS",
    ) == ("@docs-team", "@platform-team")


def test_get_codeowners_for_path_normalizes_comma_separated_owners() -> None:
    assert signal_detection.get_codeowners_for_path(
        """
* @armin-acn, @johannes-esr, @masc2023
""".strip(),
        target_path=".github/CODEOWNERS",
    ) == ("@armin-acn", "@johannes-esr", "@masc2023")


def test_parse_bazel_registry_metadata_maps_active_repository_and_latest_version() -> (
    None
):
    metadata = registry_metadata.parse_bazel_registry_metadata(
        """
{
  "maintainers": [
    {
      "name": "Andrey Babanin",
      "github": "4og"
    }
  ],
  "repository": [
    "github:eclipse-score/baselibs",
    "github:someone-else/ignored"
  ],
  "versions": ["0.2.5", "0.2.4"]
}
""".strip(),
        active_repository_names={"baselibs"},
    )

    assert metadata == {
        "baselibs": {
            "maintainers_in_bazel_registry": ("Andrey Babanin (@4og)",),
            "latest_bazel_registry_version": "0.2.5",
        }
    }


def test_merge_bazel_registry_metadata_combines_owners_and_keeps_latest_version() -> (
    None
):
    assert registry_metadata.merge_bazel_registry_metadata(
        {
            "maintainers_in_bazel_registry": ("Andrey Babanin (@4og)",),
            "latest_bazel_registry_version": "0.2.5",
        },
        {
            "maintainers_in_bazel_registry": (
                "Andrey Babanin (@4og)",
                "Nikola Radakovic (@nradakovic)",
            ),
            "latest_bazel_registry_version": "0.2.4",
        },
    ) == {
        "maintainers_in_bazel_registry": (
            "Andrey Babanin (@4og)",
            "Nikola Radakovic (@nradakovic)",
        ),
        "latest_bazel_registry_version": "0.2.5",
    }


def test_detect_matched_workflow_signals_detects_shared_workflow_reference() -> None:
    from generate_repo_overview.models import WorkflowSignal

    class FakeRepo:
        def get_contents(self, path: str, ref: str) -> SimpleNamespace:
            assert path == ".github/workflows/nightly.yml"
            assert ref == "abc123"
            return SimpleNamespace(
                decoded_content=(
                    b"jobs:\n"
                    b"  daily:\n"
                    b"    uses: eclipse-score/cicd-workflows/.github/workflows/daily.yml@main\n"
                )
            )

    assert signal_detection.detect_matched_workflow_signals(
        FakeRepo(),
        tree_paths={".github/workflows/nightly.yml"},
        ref="abc123",
        workflow_signals=(
            WorkflowSignal(
                label="Daily Workflow",
                reference="eclipse-score/cicd-workflows/.github/workflows/daily.yml@",
            ),
        ),
    ) == ("Daily Workflow",)


def test_detect_matched_workflow_signals_multiple_signals_partial_match() -> None:
    from generate_repo_overview.models import WorkflowSignal

    class FakeRepo:
        def get_contents(self, path: str, ref: str) -> SimpleNamespace:
            return SimpleNamespace(
                decoded_content=(
                    b"jobs:\n"
                    b"  daily:\n"
                    b"    uses: org/workflows/.github/workflows/daily.yml@main\n"
                )
            )

    result = signal_detection.detect_matched_workflow_signals(
        FakeRepo(),
        tree_paths={".github/workflows/ci.yml"},
        ref="abc",
        workflow_signals=(
            WorkflowSignal(label="Daily Workflow", reference="org/workflows/.github/workflows/daily.yml@"),
            WorkflowSignal(label="Nightly Build", reference="org/workflows/.github/workflows/nightly.yml@"),
        ),
    )
    assert result == ("Daily Workflow",)


def test_get_commits_since_release_returns_none_when_compare_is_lazy() -> None:
    class LazyComparison:
        @property
        def total_commits(self) -> int:
            raise RuntimeError("Not Found")

    repository = SimpleNamespace(compare=lambda base, head: LazyComparison())
    release = SimpleNamespace(tag_name="v1.2.3")

    assert (
        repo_entry.get_commits_since_release(
            repository,
            release=release,
            default_branch="main",
            default_branch_sha="abc123",
        )
        is None
    )


def test_collect_snapshot_reports_rest_api_limits_before_and_after(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fake_github_module = ModuleType("github")

    class FakeToken:
        def __init__(self, token: str) -> None:
            self.token = token

    class FakeAuth:
        Token = FakeToken

    class FakeGithub:
        def __init__(self, *, auth: FakeToken, lazy: bool) -> None:
            self.auth = auth
            self.lazy = lazy
            self.rate_limit_calls = 0

        def get_rate_limit(self) -> SimpleNamespace:
            self.rate_limit_calls += 1
            return SimpleNamespace(
                core=SimpleNamespace(
                    limit=5000,
                    remaining=5000 - self.rate_limit_calls,
                    used=self.rate_limit_calls,
                    reset=datetime(2026, 4, 14, 12, 0, tzinfo=UTC),
                )
            )

        def get_organization(self, org_name: str) -> SimpleNamespace:
            return SimpleNamespace(name=org_name)

    fake_github_module_any = cast("Any", fake_github_module)
    fake_github_module_any.Auth = FakeAuth
    fake_github_module_any.Github = FakeGithub

    monkeypatch.setitem(sys.modules, "github", fake_github_module)
    monkeypatch.setattr(collector, "resolve_github_token", lambda token_env: "token")
    monkeypatch.setattr(collector, "fetch_repositories", lambda *args, **kwargs: [])

    snapshot = collector.collect_snapshot(
        config=OrgConfig(org_name="eclipse-score"),
        cache_path=None,
    )

    captured = capsys.readouterr()

    assert snapshot.org_name == "eclipse-score"
    assert snapshot.repos == ()
    assert (
        "GitHub REST API rate limit before collection: remaining 4999/5000, "
        "used 1, resets at 2026-04-14T12:00:00+00:00" in captured.err
    )
    assert (
        "GitHub REST API rate limit after collection: remaining 4998/5000, "
        "used 2, resets at 2026-04-14T12:00:00+00:00" in captured.err
    )


def test_fetch_repositories_reports_per_repository_progress(
    capsys: pytest.CaptureFixture[str],
) -> None:
    tools_repo = SimpleNamespace(archived=False, name="tools")
    alpha_repo = SimpleNamespace(archived=False, name="alpha")
    organization = SimpleNamespace(login="eclipse-score")
    cached_snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="alpha",
                description="Alpha",
                category="Infrastructure",
                subcategory="Tooling",
            ),
        ),
    )

    original_collect_repository_entry = repo_entry.collect_repository_entry
    original_fetch_active_repositories = collector.fetch_active_repositories

    def fake_collect_repository_entry(**kwargs: Any) -> RepoEntry:
        return RepoEntry(
            name=kwargs["repository_name"],
            description="placeholder",
            category="Infrastructure",
            subcategory="Tooling",
        )

    try:
        collector.fetch_active_repositories = lambda organization, **_kwargs: {
            "tools": collector.ActiveRepositoryData(
                repository=tools_repo,
                custom_properties={},
            ),
            "alpha": collector.ActiveRepositoryData(
                repository=alpha_repo,
                custom_properties={},
            ),
        }
        repo_entry.collect_repository_entry = fake_collect_repository_entry
        collector.fetch_repositories(
            cast("Any", organization),
            existing_snapshot=cached_snapshot,
        )
    finally:
        repo_entry.collect_repository_entry = original_collect_repository_entry
        collector.fetch_active_repositories = original_fetch_active_repositories

    captured = capsys.readouterr()

    assert "Found 2 active repositories" in captured.err
    assert "Extracted custom properties for 0 repositories" in captured.err
    assert "Collecting repository details with up to 2 parallel workers" in captured.err


def test_fetch_repositories_preserves_sorted_output_with_parallel_collection() -> None:
    alpha_repo = SimpleNamespace(archived=False, name="alpha")
    tools_repo = SimpleNamespace(archived=False, name="tools")
    organization = SimpleNamespace(login="eclipse-score")

    original_collect_repository_entry = repo_entry.collect_repository_entry
    original_fetch_active_repositories = collector.fetch_active_repositories
    try:
        collector.fetch_active_repositories = lambda organization, **_kwargs: {
            "tools": collector.ActiveRepositoryData(
                repository=tools_repo,
                custom_properties={},
            ),
            "alpha": collector.ActiveRepositoryData(
                repository=alpha_repo,
                custom_properties={},
            ),
        }

        def fake_collect_repository_entry(**kwargs: Any) -> RepoEntry:
            if kwargs["repository_name"] == "alpha":
                time.sleep(0.03)
            return RepoEntry(
                name=kwargs["repository_name"],
                description="placeholder",
                category="Infrastructure",
                subcategory="Tooling",
            )

        repo_entry.collect_repository_entry = fake_collect_repository_entry
        repos = collector.fetch_repositories(cast("Any", organization))
    finally:
        repo_entry.collect_repository_entry = original_collect_repository_entry
        collector.fetch_active_repositories = original_fetch_active_repositories

    assert [repo.name for repo in repos] == ["alpha", "tools"]


def test_resolve_max_collection_workers_prefers_positive_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPO_OVERVIEW_MAX_WORKERS", "12")

    assert collector.resolve_max_collection_workers() == 12


def test_resolve_max_collection_workers_ignores_invalid_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPO_OVERVIEW_MAX_WORKERS", "nope")

    assert (
        collector.resolve_max_collection_workers()
        == collector.DEFAULT_MAX_COLLECTION_WORKERS
    )


def test_metrics_report_renders_summary_and_table() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        workflow_signal_labels=("Daily Workflow",),
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    bazel_version="8.4.2",
                    codeowners=(
                        "@docs-team",
                        "@platform-team",
                        "@infra-team",
                        "@qa-team",
                    ),
                    referenced_by_reference_integration=True,
                    has_lint_config=True,
                    has_ci=True,
                    matched_workflow_signals=("Daily Workflow",),
                    has_coverage_config=False,
                ),
                registry=RegistrySignals(
                    maintainers_in_bazel_registry=(
                        "Andrey Babanin (@4og)",
                        "Nikola Radakovic (@nradakovic)",
                        "Pawel Rutka (@pawelrutkaq)",
                    ),
                    latest_bazel_registry_version="0.2.5",
                ),
                volatile=VolatileMetricsSnapshot(
                    merged_prs_30_days=11,
                    open_issues=2,
                    open_prs=2,
                    open_ready_prs=1,
                    open_draft_prs=1,
                    latest_release_version="v1.2.3",
                    latest_release_date="2026-04-01",
                    commits_since_latest_release=7,
                ),
                stars=3,
                forks=4,
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "# Cross-Repo Metrics Report" in markdown
    assert "- Repositories: 1" in markdown
    assert "- With GitHub Actions: 1" in markdown
    assert "- With workflow signals: 1" in markdown
    assert "## Table Of Contents" in markdown
    assert "- [Repository Overview](#repository-overview)" in markdown
    assert "- [Versions](#versions)" in markdown
    assert "- [Ownership](#ownership)" not in markdown
    assert "- [Ownership With Versions](#ownership-with-versions)" not in markdown
    assert "`⚙ GitHub Actions`: shown when `.github/workflows` exists." in markdown
    assert "## Repository Overview" in markdown
    assert "## Versions" in markdown
    assert (
        "| Repository | Ownership | Merged PRs (30d) | Open Issues / PRs (ready+draft) | Latest Release + Commits Since Release | Stars / Forks |"
        in markdown
    )
    assert "## Ownership" not in markdown
    assert "## Ownership With Versions" not in markdown
    assert "## Delivery And Automation" in markdown
    assert "### Infrastructure" in markdown
    assert (
        "| [tools](https://github.com/eclipse-score/tools) "
        '<img src="https://bazel.build/_pwa/bazel/icons/icon-72x72.png" alt="Bazel" width="16" height="16"> | '
        "<small><sub><small>Codeowners: @docs-team, @platform-team, @infra-team, @qa-team<br><br>"
        "Maintainers In Bazel Registry: @4og, @nradakovic, @pawelrutkaq</small></sub></small> | "
        "🔥 11 | 2 / 1+1 | v1.2.3 + 🟡 7 | 3 / 4 |" in markdown
    )
    assert (
        "| [tools](https://github.com/eclipse-score/tools) | "
        "🟢 8.4.2 | yes |" in markdown
    )
    assert (
        "| [tools](https://github.com/eclipse-score/tools) | - | - | - | ⚙ | yes | no |"
        in markdown
    )


def test_metrics_report_uses_no_for_non_bazel_repo_in_overview() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert (
        "| [tools](https://github.com/eclipse-score/tools) | - "
        "| 0 | 0 / 0+0 | - | 0 / 0 |" in markdown
    )


def test_metrics_report_shows_fire_icon_for_high_merged_pr_activity() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                volatile=VolatileMetricsSnapshot(merged_prs_30_days=10),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "| [tools](https://github.com/eclipse-score/tools) | - | 🔥 10 |" in markdown


def test_metrics_report_ownership_cell_skips_maintainers_for_non_bazel_repo() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    is_bazel_repo=False,
                    codeowners=("@docs-team",),
                ),
                registry=RegistrySignals(
                    maintainers_in_bazel_registry=("Andrey Babanin (@4og)",),
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "<small><sub><small>Codeowners: @docs-team</small></sub></small>" in markdown
    assert "Maintainers In Bazel Registry:" not in markdown


def test_metrics_report_ownership_cell_marks_missing_maintainers_for_bazel_repo() -> (
    None
):
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tooling",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    codeowners=("@docs-team",),
                ),
                registry=RegistrySignals(
                    maintainers_in_bazel_registry=(),
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "Maintainers In Bazel Registry:" not in markdown


def test_metrics_report_renders_versions_table() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        tracked_deps=(
            TrackedDep(repo="eclipse-score/docs-as-code", module_name="score_docs_as_code"),
        ),
        repos=(
            RepoEntry(
                name="process_description",
                description="Process docs",
                category="Infrastructure",
                subcategory="tooling",
                content=DeepContentSignals(
                    is_bazel_repo=True,
                    bazel_version="8.4.2",
                    bazel_deps=(("score_docs_as_code", "4.0.0"),),
                    referenced_by_reference_integration=True,
                    has_ci=True,
                    matched_workflow_signals=("Daily Workflow",),
                ),
                volatile=VolatileMetricsSnapshot(
                    last_push_date="2026-04-12",
                    open_issues=35,
                    open_prs=8,
                    open_ready_prs=6,
                    open_draft_prs=2,
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "## Versions" in markdown
    assert "🔴 6" in markdown
    assert (
        "| [process_description](https://github.com/eclipse-score/process_description) | "
        "🟢 8.4.2 | ⚪ 4.0.0 | yes |" in markdown
    )


def test_versions_table_tracked_dep_color_rules() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        tracked_deps=(
            TrackedDep(repo="eclipse-score/docs-as-code", module_name="score_docs_as_code"),
        ),
        repos=(
            RepoEntry(
                name="docs-as-code",
                description="Docs",
                category="Infrastructure",
                subcategory="Tooling",
                volatile=VolatileMetricsSnapshot(latest_release_version="v4.1.3"),
                content=DeepContentSignals(bazel_version="8.6.0"),
            ),
            RepoEntry(
                name="same-release",
                description="Same",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    bazel_deps=(("score_docs_as_code", "4.1.3"),),
                    bazel_version="8.5.0",
                ),
            ),
            RepoEntry(
                name="same-minor",
                description="Minor",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    bazel_deps=(("score_docs_as_code", "4.1.1"),),
                    bazel_version="8.4.0",
                ),
            ),
            RepoEntry(
                name="older",
                description="Older",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    bazel_deps=(("score_docs_as_code", "3.9.9"),),
                    bazel_version="8.3.0",
                ),
            ),
            RepoEntry(
                name="none",
                description="None",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    bazel_version=None,
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert (
        "| [docs-as-code](https://github.com/eclipse-score/docs-as-code) | 🟢 8.6.0 | ⚪ - | no |"
        in markdown
    )
    assert (
        "| [same-release](https://github.com/eclipse-score/same-release) | 🔴 8.5.0 | 🟢 4.1.3 | no |"
        in markdown
    )
    assert (
        "| [same-minor](https://github.com/eclipse-score/same-minor) | 🔴 8.4.0 | 🟡 4.1.1 | no |"
        in markdown
    )
    assert (
        "| [older](https://github.com/eclipse-score/older) | 🔴 8.3.0 | 🔴 3.9.9 | no |"
        in markdown
    )
    assert (
        "| [none](https://github.com/eclipse-score/none) | ⚪ - | ⚪ - | no |"
        in markdown
    )


def test_versions_table_multiple_tracked_deps() -> None:
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        tracked_deps=(
            TrackedDep(repo="eclipse-score/docs-as-code", module_name="score_docs_as_code"),
            TrackedDep(repo="eclipse-score/toolchain", module_name="score_toolchain"),
        ),
        repos=(
            RepoEntry(
                name="docs-as-code",
                description="Docs",
                category="Infrastructure",
                subcategory="Tooling",
                volatile=VolatileMetricsSnapshot(latest_release_version="v4.1.3"),
                content=DeepContentSignals(bazel_version="8.6.0"),
            ),
            RepoEntry(
                name="toolchain",
                description="TC",
                category="Infrastructure",
                subcategory="Tooling",
                volatile=VolatileMetricsSnapshot(latest_release_version="v2.0.0"),
                content=DeepContentSignals(bazel_version="8.6.0"),
            ),
            RepoEntry(
                name="consumer",
                description="Consumer",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    bazel_version="8.6.0",
                    bazel_deps=(
                        ("score_docs_as_code", "4.1.3"),
                        ("score_toolchain", "1.9.0"),
                    ),
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "Docs As Code Version" in markdown
    assert "Toolchain Version" in markdown
    assert "🟢 4.1.3 | 🔴 1.9.0" in markdown


def test_metrics_report_renders_without_tracked_deps_or_signals() -> None:
    """D4.2: Versions/Automation tables with zero deps and zero signals."""
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        tracked_deps=(),
        workflow_signal_labels=(),
        repos=(
            RepoEntry(
                name="basic-repo",
                description="Basic",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(bazel_version="8.0.0", has_ci=True),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "## Versions" in markdown
    assert "## Delivery And Automation" in markdown
    assert "| Reference Integration |" in markdown
    assert "| Coverage Config |" in markdown
    assert "Daily Workflow" not in markdown


def test_metrics_report_automation_with_multiple_signals() -> None:
    """D4.3: Automation table with 2 signal columns."""
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        workflow_signal_labels=("Daily Workflow", "Nightly Build"),
        repos=(
            RepoEntry(
                name="repo-a",
                description="A",
                category="Infrastructure",
                subcategory="Tooling",
                content=DeepContentSignals(
                    has_ci=True,
                    matched_workflow_signals=("Daily Workflow",),
                ),
            ),
        ),
    )

    markdown = render_metrics_report(snapshot)

    assert "Daily Workflow" in markdown
    assert "Nightly Build" in markdown
    assert "| yes | no |" in markdown


def test_snapshot_from_dict_filters_empty_tracked_deps() -> None:
    """D4.6: TrackedDep with empty repo/module_name is dropped during deserialization."""
    snapshot = RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="test",
        generated_at="2026-01-01",
        repos=(),
        tracked_deps=(TrackedDep(repo="org/valid", module_name="valid_mod"),),
    )
    raw = snapshot.to_dict()
    raw["tracked_deps"].append({"repo": "", "module_name": "empty_repo"})
    raw["tracked_deps"].append({"repo": "org/x", "module_name": ""})

    loaded = RepoSnapshot.from_dict(raw)

    assert len(loaded.tracked_deps) == 1
    assert loaded.tracked_deps[0].repo == "org/valid"


def test_load_snapshot_if_present_ignores_mismatched_schema(tmp_path: Path) -> None:
    cache_path = tmp_path / "repo_overview.json"
    cache_path.write_text(
        (
            "{\n"
            '  "schema_version": 2,\n'
            '  "org_name": "eclipse-score",\n'
            '  "generated_at": "2026-04-13T12:00:00+00:00",\n'
            '  "repos": []\n'
            "}\n"
        ),
        encoding="utf-8",
    )

    assert snapshot_io.load_snapshot_if_present(cache_path) is None
