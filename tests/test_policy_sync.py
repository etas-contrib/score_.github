from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import generate_repo_overview.cli as cli
from generate_repo_overview._html_index import render_index_page
from generate_repo_overview.collector import write_snapshot
from generate_repo_overview.models import (
    SNAPSHOT_SCHEMA_VERSION,
    RepoEntry,
    RepoSnapshot,
)
from generate_repo_overview.org_config import (
    OrgConfig,
    PolicyReportConfig,
    load_org_config,
)
from generate_repo_overview.policy_sync import (
    PolicySyncChange,
    PolicySyncOutcome,
    PolicySyncPolicy,
    PolicySyncReport,
    PolicySyncSummary,
    fetch_policy_report,
    load_policy_sync_report,
    parse_policy_sync_report,
)


def _report_payload() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "policies": [
            {
                "id": "minimum-bazel-version",
                "title": "Keep Bazel current",
                "description": "Use Bazel 8.6.0 or newer.",
                "legacy_names": ["bazel.minimum-version"],
            }
        ],
        "summary": {
            "repositories": 2,
            "synchronized": 2,
            "sync_failures": 0,
            "skipped": 0,
            "evaluations": 2,
            "compliant": 1,
            "drifted": 1,
            "not_applicable": 0,
            "evaluation_failures": 0,
            "pull_requests_created": 0,
            "pull_requests_updated": 0,
            "pull_requests_open": 1,
            "pull_requests_recreated": 0,
            "pull_requests_closed": 0,
            "duration_seconds": 1.5,
        },
        "outcomes": [
            {
                "policy_id": "minimum-bazel-version",
                "repository": "tools",
                "applicable": "yes (live)",
                "status": "changes-required",
                "changes": [
                    {
                        "path": "MODULE.bazel",
                        "description": "update Bazel",
                        "rationale": "central policy",
                    }
                ],
                "pull_request_url": "https://github.com/eclipse-score/tools/pull/1",
                "policy_pr_status": "open",
                "warnings": ["warning text"],
                "error": None,
            },
            {
                "policy_id": "minimum-bazel-version",
                "repository": "score",
                "applicable": "yes (live)",
                "status": "compliant",
                "changes": [],
                "pull_request_url": None,
                "policy_pr_status": "none",
                "warnings": [],
                "error": None,
            },
        ],
    }


def _minimal_snapshot() -> RepoSnapshot:
    return RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-08-30T12:00:00+00:00",
        repos=(),
    )


def _categorized_snapshot() -> RepoSnapshot:
    return RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-08-30T12:00:00+00:00",
        repos=(
            RepoEntry(
                name="tools",
                description="Tools",
                category="Infrastructure",
                subcategory="General",
            ),
            RepoEntry(
                name="score",
                description="Score",
                category="Platform",
                subcategory="General",
            ),
        ),
    )


def test_policy_report_config_defaults_and_loading(tmp_path: Path) -> None:
    default = OrgConfig(org_name="test").policy_report
    assert default.enabled is False
    assert default.filename == "repo-policy-sync-report.json"
    assert default.cache_path == Path(".cache/repo-policy-sync-report.json")

    config_path = tmp_path / "org.toml"
    config_path.write_text(
        """org_name = 'eclipse-score'

[policy_report]
source_repo = 'eclipse-score/tools'
workflow = 'repo-policy-sync.yml'
artifact = 'repo-policy-sync-report'
filename = 'report.json'
cache_path = '.cache/report.json'
""",
        encoding="utf-8",
    )
    config = load_org_config(config_path)
    assert config.policy_report == PolicyReportConfig(
        source_repo="eclipse-score/tools",
        workflow="repo-policy-sync.yml",
        artifact="repo-policy-sync-report",
        filename="report.json",
        cache_path=Path(".cache/report.json"),
    )


@pytest.mark.parametrize(
    ("setting", "message"),
    [
        ("source_repo = 'tools'", "org/repo"),
        ("workflow = 'repo-policy-sync.txt'", "workflow filename"),
        ("artifact = 'policy report'", "whitespace"),
        ("filename = 'report.txt'", "JSON filename"),
        ("cache_path = '../report.json'", "without '..'"),
    ],
)
def test_policy_report_config_rejects_invalid_values(
    tmp_path: Path, setting: str, message: str
) -> None:
    path = tmp_path / "org.toml"
    setting_key = setting.split(" ", 1)[0]
    settings = {
        "source_repo": "source_repo = 'org/tools'",
        "workflow": "workflow = 'repo-policy-sync.yml'",
        "artifact": "artifact = 'report'",
        "filename": "filename = 'report.json'",
        "cache_path": "cache_path = '.cache/report.json'",
    }
    lines = ["org_name = 'test'", "[policy_report]"]
    lines.extend(value for key, value in settings.items() if key != setting_key)
    lines.append(setting)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        load_org_config(path)


def test_policy_report_config_rejects_duplicate_aliases(tmp_path: Path) -> None:
    path = tmp_path / "org.toml"
    path.write_text(
        """org_name = 'test'
[policy_report]
source_repo = 'org/tools'
source_repository = 'org/tools'
workflow = 'repo-policy-sync.yml'
artifact = 'report'
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="source repository"):
        load_org_config(path)


def test_fetch_policy_report_downloads_latest_scheduled_main_artifact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    report_path = tmp_path / "report.json"
    config = PolicyReportConfig(
        source_repo="org/tools",
        workflow="repo-policy-sync.yml",
        artifact="policy-report",
        filename="report.json",
        cache_path=report_path,
    )

    def fake_gh(args: list[str], token: str | None) -> str:
        assert token is None
        if args[:2] == ["run", "list"]:
            assert args[args.index("--event") + 1] == "schedule"
            assert args[args.index("--branch") + 1] == "main"
            return "11\n"
        if args[:2] == ["run", "download"]:
            download_dir = Path(args[args.index("--dir") + 1])
            download_dir.joinpath("nested").mkdir()
            download_dir.joinpath("nested/report.json").write_text(
                json.dumps(_report_payload()), encoding="utf-8"
            )
            return ""
        raise AssertionError(f"unexpected gh command: {args}")

    assert fetch_policy_report(config, gh_runner=fake_gh) is True
    assert json.loads(report_path.read_text(encoding="utf-8")) == _report_payload()


def test_fetch_policy_report_is_non_fatal_when_no_run_exists(tmp_path: Path) -> None:
    config = PolicyReportConfig(
        source_repo="org/tools",
        workflow="repo-policy-sync.yml",
        artifact="policy-report",
        cache_path=tmp_path / "report.json",
    )

    def fake_gh(args: list[str], token: str | None) -> str:
        del token
        assert args[:2] == ["run", "list"]
        assert args[args.index("--event") + 1] == "schedule"
        assert args[args.index("--branch") + 1] == "main"
        return "null\n"

    assert fetch_policy_report(config, token="secret", gh_runner=fake_gh) is False
    assert not config.cache_path.exists()


def test_policy_report_parser_handles_missing_malformed_and_unsupported_reports(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    assert load_policy_sync_report(missing) is None

    malformed = tmp_path / "malformed.json"
    malformed.write_text("not json", encoding="utf-8")
    assert load_policy_sync_report(malformed) is None

    assert parse_policy_sync_report({"schema_version": 1}) is None
    report = parse_policy_sync_report(_report_payload())
    assert report is not None
    assert report.policies[0].description == "Use Bazel 8.6.0 or newer."

    invalid_policy = _report_payload()
    invalid_policy["policies"] = [{"id": "minimum-bazel-version", "description": 7}]
    assert parse_policy_sync_report(invalid_policy) is None

    duplicate_policies = _report_payload()
    duplicate_policies["policies"] = [
        {"id": "duplicate"},
        {"id": "duplicate"},
    ]
    assert parse_policy_sync_report(duplicate_policies) is None


def test_policy_sync_tab_renders_details_links_and_escaped_values() -> None:
    report = PolicySyncReport(
        schema_version=2,
        summary=PolicySyncSummary(repositories=1, evaluations=1, drifted=1),
        outcomes=(
            PolicySyncOutcome(
                policy_id="<policy>",
                repository="<repo>",
                applicable="yes",
                status="changes-required",
                changes=(PolicySyncChange("<path>", "<description>", "<rationale>"),),
                pull_request_url="https://github.com/org/repo/pull/1",
                policy_pr_status="open",
                warnings=("<warning>",),
                error="<error>",
            ),
        ),
        policies=(PolicySyncPolicy(id="<policy>", description="<policy description>"),),
    )
    page = render_index_page(
        _minimal_snapshot(),
        report,
    )

    assert 'data-tab="policy-sync">Policy Sync</button>' in page
    assert "Compliance Matrix" in page
    assert "Changes, Warnings, Errors &amp; Pull Requests" not in page
    assert 'class="policy-matrix-cell"' in page
    assert 'tabindex="0"' in page
    assert "&lt;repo&gt;" in page
    assert "&lt;description&gt;" in page
    assert "&lt;warning&gt;" in page
    assert "&lt;error&gt;" in page
    assert 'data-tooltip="&lt;policy description&gt;"' in page
    assert "<description>" not in page
    assert "<details" not in page
    assert 'href="https://github.com/org/repo/pull/1"' in page
    assert 'href="repo-policy-sync-report.json"' in page


def test_policy_sync_matrix_compacts_long_policy_columns() -> None:
    report = parse_policy_sync_report(_report_payload())
    assert report is not None

    page = render_index_page(_minimal_snapshot(), report)

    # Policy identifiers remain fully visible, while the stylesheet gives each
    # policy column a compact width and allows long identifiers to wrap.
    assert ".policy-sync-matrix {" in page
    assert "overflow-x: auto;" in page
    assert ".policy-matrix th:not(:first-child) {" in page
    assert "width: 7rem;" in page
    assert "table-layout: fixed;" in page
    assert "overflow-wrap: anywhere;" in page
    assert "white-space: normal;" in page
    assert "width: min(32rem, calc(100vw - 2rem));" in page
    assert "minimum-bazel-version" in page


def test_policy_sync_tab_uses_repository_groups_and_pr_states() -> None:
    report = parse_policy_sync_report(_report_payload())
    assert report is not None
    report = PolicySyncReport(
        schema_version=report.schema_version,
        summary=report.summary,
        outcomes=(
            *report.outcomes,
            PolicySyncOutcome(
                policy_id="merged-policy",
                repository="tools",
                applicable="yes",
                status="compliant",
                policy_pr_status="merged",
                pull_request_url="https://github.com/org/tools/pull/2",
            ),
            PolicySyncOutcome(
                policy_id="closed-policy",
                repository="score",
                applicable="yes",
                status="compliant",
                policy_pr_status="closed",
                pull_request_url="https://github.com/org/score/pull/3",
            ),
        ),
    )

    page = render_index_page(_categorized_snapshot(), report)

    assert "style.display = tab === 'traceability' ? 'none' : '';" in page
    assert 'data-category="Infrastructure"' in page
    assert 'data-category="Platform"' in page
    assert 'class="policy-sync-statistics"' in page
    assert (
        '<span class="policy-status compliant" aria-label="Compliant">✓</span>' in page
    )
    assert (
        '<span class="policy-status changes-required" aria-label="Changes Needed">X</span>'
        in page
    )
    assert (
        '<span class="policy-sync-stat-value">1</span><span class="policy-sync-stat-label">Open PRs</span>'
        in page
    )
    assert (
        '<span class="policy-sync-stat-value">1</span><span class="policy-sync-stat-label">Merged PRs</span>'
        in page
    )
    assert "Repositories" not in page
    assert "Evaluations" not in page
    assert "Closed PRs" not in page
    assert "No PRs" not in page
    assert "Evaluation Errors" not in page
    assert "Sync Failures" not in page
    assert "Skipped" not in page
    assert "Actions in this run" not in page
    assert 'class="policy-pr-badge policy-pr-open"' in page
    assert ">Open</a>" in page
    assert (
        '<span class="policy-status changes-required" title="Changes required" aria-label="Changes required">X</span> <a href="https://github.com/org/tools/pull/1"'
        not in page
    )
    assert ".policy-pr-open { color: var(--orange);" in page
    assert (
        'title="Compliant (automated PR)" aria-label="Compliant (automated PR)">✓✓</span>'
        in page
    )
    assert "Status: Compliant\nApplicable:" not in page
    assert "Automated policy PR (merged):" in page
    assert "Automated policy PR (closed):" in page
    assert 'href="https://github.com/org/tools/pull/2"' not in page
    assert 'href="https://github.com/org/score/pull/3"' not in page


def test_policy_sync_error_outcomes_render_red_x() -> None:
    """Error outcomes use a red X in both the summary and matrix."""
    report = PolicySyncReport(
        schema_version=2,
        summary=PolicySyncSummary(evaluation_failures=1),
        outcomes=(
            PolicySyncOutcome(
                policy_id="policy-error",
                repository="repo-error",
                applicable="yes",
                status="error",
                error="evaluation failed",
            ),
        ),
    )

    page = render_index_page(_minimal_snapshot(), report)

    assert (
        '<span class="policy-status error" aria-label="Evaluation Errors">X</span>'
        in page
    )
    assert (
        '<span class="policy-status error" title="Error" aria-label="Error">X</span>'
        in page
    )
    assert ".policy-status.error { color: var(--red);" in page


def test_render_details_discovers_configured_report_and_publishes_raw_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    write_snapshot(_minimal_snapshot(), tmp_path / "snapshot.json")
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "report.json").write_text(
        json.dumps(_report_payload()), encoding="utf-8"
    )
    (tmp_path / "org.toml").write_text(
        """org_name = 'eclipse-score'
[policy_report]
source_repo = 'org/tools'
workflow = 'repo-policy-sync.yml'
artifact = 'policy-report'
filename = 'report.json'
cache_path = '.cache/report.json'
""",
        encoding="utf-8",
    )

    assert (
        cli.main(
            [
                "render-details",
                "--input",
                "snapshot.json",
                "--output",
                "site",
                "--org-config",
                "org.toml",
            ]
        )
        == 0
    )
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert "2" in index
    assert 'data-tooltip="Use Bazel 8.6.0 or newer."' in index
    assert 'href="report.json"' in index
    assert (tmp_path / "site" / "report.json").exists()
