from pathlib import Path

import generate_repo_overview.cli as cli
from generate_repo_overview.collector import write_snapshot
from generate_repo_overview.models import (
    SNAPSHOT_SCHEMA_VERSION,
    DeepContentSignals,
    RepoEntry,
    RepoSnapshot,
    TraceabilityTypeMetrics,
    TrackedDep,
    VolatileMetricsSnapshot,
)


def _make_snapshot() -> RepoSnapshot:
    return RepoSnapshot(
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
                    bazel_version="8.4.2",
                    has_lint_config=True,
                    has_ci=True,
                    has_coverage_config=False,
                ),
                volatile=VolatileMetricsSnapshot(
                    last_push_date="2026-04-12",
                    open_issues=2,
                    open_prs=1,
                    open_ready_prs=1,
                    open_draft_prs=0,
                    latest_release_date="2026-04-01",
                ),
                stars=3,
                forks=4,
            ),
        ),
    )


def test_render_overview_writes_readme(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    readme_output = tmp_path / "README.md"
    write_snapshot(_make_snapshot(), snapshot_path)

    exit_code = cli.main(
        [
            "render-overview",
            "--input",
            str(snapshot_path),
            "--output",
            str(readme_output),
        ]
    )

    assert exit_code == 0
    assert readme_output.exists()
    assert "### Infrastructure" in readme_output.read_text(encoding="utf-8")


def test_render_details_writes_html(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    output_dir = tmp_path / "_site"
    write_snapshot(_make_snapshot(), snapshot_path)

    exit_code = cli.main(
        [
            "render-details",
            "--input",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    index = output_dir / "index.html"
    assert index.exists()
    content = index.read_text(encoding="utf-8")
    assert "Cross-Repo Metrics" in content
    assert "<!DOCTYPE html>" in content


def test_render_details_writes_repo_detail_pages(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    output_dir = tmp_path / "_site"
    write_snapshot(_make_snapshot(), snapshot_path)

    cli.main(
        [
            "render-details",
            "--input",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    detail = output_dir / "tools" / "index.html"
    assert detail.exists()
    detail_content = detail.read_text(encoding="utf-8")
    assert "tools" in detail_content
    assert "../" in detail_content
    assert "<!DOCTYPE html>" in detail_content


def test_render_detail_page_shows_tracked_dep_versions(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    output_dir = tmp_path / "_site"
    write_snapshot(_make_snapshot_with_dac(), snapshot_path)

    cli.main(
        [
            "render-details",
            "--input",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    detail = output_dir / "my-dac-repo" / "index.html"
    assert detail.exists()
    detail_content = detail.read_text(encoding="utf-8")
    assert "Docs As Code Version" in detail_content


def _make_snapshot_with_dac() -> RepoSnapshot:
    return RepoSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        org_name="eclipse-score",
        generated_at="2026-04-13T12:00:00+00:00",
        tracked_deps=(
            TrackedDep(repo="eclipse-score/docs-as-code", module_name="score_docs_as_code"),
        ),
        repos=(
            RepoEntry(
                name="my-dac-repo",
                description="A repo with docs-as-code",
                category="Components",
                subcategory="General",
                content=DeepContentSignals(
                    bazel_deps=(("score_docs_as_code", "4.0.1"),),
                ),
                traceability=(
                    TraceabilityTypeMetrics(
                        type_name="feature",
                        req_total=10,
                        req_with_code_link=8,
                        req_with_test_link=6,
                        req_fully_linked=5,
                        tests_total=20,
                        tests_linked=15,
                    ),
                ),
            ),
            RepoEntry(
                name="plain-repo",
                description="No docs-as-code",
                category="Infrastructure",
                subcategory="General",
            ),
        ),
    )


def test_render_details_traceability_tab(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    output_dir = tmp_path / "_site"
    write_snapshot(_make_snapshot_with_dac(), snapshot_path)

    cli.main(
        [
            "render-details",
            "--input",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    content = (output_dir / "index.html").read_text(encoding="utf-8")
    assert 'data-tab="traceability"' in content
    assert "Traceability" in content
    assert 'data-repo="my-dac-repo"' in content
    assert 'data-repo="plain-repo"' not in content
    # Server-rendered metrics values
    assert "Feature" in content
    assert ">10<" in content  # req_total
    assert "1 / 1" in content  # repos loaded summary
    # No client-side fetch variables
    assert "traceabilityRepos" not in content
    assert "orgName" not in content


def test_render_details_index_links_to_detail_pages(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "repo_overview.json"
    output_dir = tmp_path / "_site"
    write_snapshot(_make_snapshot(), snapshot_path)

    cli.main(
        [
            "render-details",
            "--input",
            str(snapshot_path),
            "--output",
            str(output_dir),
        ]
    )

    index_content = (output_dir / "index.html").read_text(encoding="utf-8")
    assert 'href="tools/"' in index_content
