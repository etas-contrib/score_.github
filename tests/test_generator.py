from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import generate_repo_overview.collector as collector
import generate_repo_overview.collector.repo_entry as repo_entry
import generate_repo_overview.collector.signal_detection as signal_detection
import generate_repo_overview.profile_readme as profile_readme
from generate_repo_overview.collector import (
    fetch_repositories,
    fetch_repository_descriptions,
    get_gh_auth_token,
    resolve_github_token,
)
from generate_repo_overview.collector.repo_entry import (
    build_repo_entry,
    normalize_group_name,
)
from generate_repo_overview.console import print_status
from generate_repo_overview.models import (
    CategoryConfig,
    ReadmeConfig,
    RegistrySignals,
    RepoEntry,
    SubcategoryConfig,
)
from generate_repo_overview.profile_readme import (
    describe_config_source,
    group_repositories,
    load_config,
    render_readme,
)


def test_normalize_group_name_uses_fallback_for_empty_values() -> None:
    assert normalize_group_name(None, "Fallback") == "Fallback"
    assert normalize_group_name("", "Fallback") == "Fallback"
    assert normalize_group_name([], "Fallback") == "Fallback"


def test_normalize_group_name_joins_multi_select_values() -> None:
    assert (
        normalize_group_name(["Tooling", "Automation"], "Fallback")
        == "Tooling, Automation"
    )


def test_group_repositories_sorts_everything_case_insensitively() -> None:
    repos = [
        RepoEntry("zeta", "desc", "infra", "beta"),
        RepoEntry("Alpha", "desc", "Apps", "alpha"),
        RepoEntry("beta", "desc", "apps", "Alpha"),
    ]

    grouped = group_repositories(repos)

    assert list(grouped) == ["Apps", "apps", "infra"]
    assert list(grouped["apps"]) == ["Alpha"]
    assert [entry.name for entry in grouped["apps"]["Alpha"]] == ["beta"]


def test_group_repositories_prefers_configured_category_order() -> None:
    repos = [
        RepoEntry("website", "desc", "Website", "General"),
        RepoEntry("tools", "desc", "Infrastructure", "General"),
        RepoEntry("score", "desc", "Modules", "General"),
        RepoEntry("misc", "desc", "Uncategorized", "General"),
    ]
    config = ReadmeConfig(
        categories=(
            CategoryConfig("Modules", "Module repos"),
            CategoryConfig("Infrastructure", "Infrastructure repos"),
            CategoryConfig("Website", "Website repos"),
            CategoryConfig("Uncategorized", "Other repos"),
        )
    )

    grouped = group_repositories(repos, config=config)

    assert list(grouped) == ["Modules", "Infrastructure", "Website", "Uncategorized"]


def test_group_repositories_matches_configured_category_order_case_insensitively() -> (
    None
):
    repos = [
        RepoEntry("website", "desc", "website", "General"),
        RepoEntry("tools", "desc", "infrastructure", "General"),
        RepoEntry("score", "desc", "modules", "General"),
        RepoEntry("misc", "desc", "Uncategorized", "General"),
    ]
    config = ReadmeConfig(
        categories=(
            CategoryConfig("Modules", "Module repos"),
            CategoryConfig("Infrastructure", "Infrastructure repos"),
            CategoryConfig("Website", "Website repos"),
            CategoryConfig("Uncategorized", "Other repos"),
        )
    )

    grouped = group_repositories(repos, config=config)

    assert list(grouped) == ["modules", "infrastructure", "website", "Uncategorized"]


def test_build_repo_entry_uses_custom_properties_and_description_fallback() -> None:
    entry = build_repo_entry(
        repository_name="tools",
        description=None,
        custom_properties={"category": "Infrastructure", "subcategory": None},
        content_signals=signal_detection.default_content_signals(),
        registry_signals=RegistrySignals(),
        volatile_metrics={
            "last_push_date": None,
            "merged_prs_30_days": 0,
            "open_issues": 0,
            "open_prs": 0,
            "open_ready_prs": 0,
            "open_draft_prs": 0,
            "latest_release_version": None,
            "latest_release_date": None,
            "commits_since_latest_release": None,
            "release_bazel_version": None,
            "release_bazel_deps": (),
        },
    )

    assert entry == RepoEntry(
        name="tools",
        description="(no description)",
        category="Infrastructure",
        subcategory="General",
    )


def test_fetch_repository_descriptions_skips_archived_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active_repo = SimpleNamespace(name="active-repo", description="Active")

    monkeypatch.setattr(
        collector,
        "fetch_active_repositories",
        lambda organization, **_kwargs: {
            "active-repo": collector.ActiveRepositoryData(
                repository=active_repo,
                custom_properties={},
            )
        },
    )
    assert fetch_repository_descriptions(cast("Any", object())) == {
        "active-repo": "Active"
    }


def test_fetch_repositories_does_not_reintroduce_archived_repositories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeRequester:
        is_not_lazy = False

        def requestJsonAndCheck(  # noqa: N802
            self,
            verb: str,
            url: str,
            parameters: dict[str, Any] | None = None,
            headers: dict[str, str] | None = None,
        ) -> tuple[dict[str, str], Any]:
            assert verb == "GET"
            assert url == "/orgs/eclipse-score/repos"
            assert parameters is not None
            assert parameters.get("page") == 1
            return (
                {},
                [
                    {
                        "name": "active-repo",
                        "archived": False,
                        "description": "Active",
                        "default_branch": "main",
                        "custom_properties": {
                            "category": "Infrastructure",
                            "subcategory": "General",
                        },
                    },
                    {
                        "name": "archived-repo",
                        "archived": True,
                        "description": "Archived",
                        "default_branch": "main",
                        "custom_properties": {
                            "category": "Infrastructure",
                            "subcategory": "General",
                        },
                    },
                ],
            )

    organization = SimpleNamespace(
        login="eclipse-score",
        requester=FakeRequester(),
    )

    monkeypatch.setattr(
        repo_entry,
        "collect_repository_entry",
        lambda **kwargs: RepoEntry(
            name=kwargs["repository_name"],
            description=kwargs["repository"].description,
            category=kwargs["custom_properties"].get("category", "Uncategorized"),
            subcategory=kwargs["custom_properties"].get("subcategory", "General"),
        ),
    )
    repos = fetch_repositories(cast("Any", organization))

    assert len(repos) == 1
    assert repos[0].name == "active-repo"
    assert repos[0].description == "Active"
    assert repos[0].category == "Infrastructure"
    assert repos[0].subcategory == "General"


def test_render_readme_uses_simple_markdown_sections() -> None:
    template = """# Title

{{ repo_sections }}
"""

    markdown = render_readme(
        [
            RepoEntry("tools", "Tooling repo", "Infrastructure", "Tooling"),
            RepoEntry("score", "(no description)", "Modules", "Core"),
        ],
        template=template,
        org_name="eclipse-score",
    )

    assert "# Title" in markdown
    assert "### Infrastructure" in markdown
    assert "#### Tooling" in markdown
    assert (
        "| [tools](https://github.com/eclipse-score/tools) | Tooling repo |" in markdown
    )
    assert "\n---\n\n### Modules\n" in markdown
    assert markdown.endswith("\n")


def test_render_repo_row_escapes_markdown_table_metacharacters() -> None:
    row = profile_readme.render_repo_row(
        RepoEntry("tools", "Line 1 | Line 2\nLine 3", "Infrastructure", "General"),
        org_name="eclipse-score",
    )

    assert row == (
        "| [tools](https://github.com/eclipse-score/tools) | "
        r"Line 1 \| Line 2 Line 3 |"
    )


def test_render_readme_omits_general_subheading_for_single_subcategory() -> None:
    template = """# Title

{{ repo_sections }}
"""

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "Infrastructure", "General")],
        template=template,
        org_name="eclipse-score",
    )

    assert "### Infrastructure" in markdown
    assert "#### General" not in markdown
    assert "| Repository | Description |" in markdown
    assert (
        "| [infra](https://github.com/eclipse-score/infra) | Infra repo |" in markdown
    )


def test_render_readme_uses_category_descriptions_from_config() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "Infrastructure",
                "Shared tooling and project infrastructure.",
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "Infrastructure", "General")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "### Infrastructure" in markdown
    assert "Shared tooling and project infrastructure." in markdown


def test_render_readme_uses_subcategory_descriptions_from_config() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "Infrastructure",
                "Shared tooling and project infrastructure.",
                subcategories=(
                    SubcategoryConfig(
                        "Tooling",
                        "Developer tools and automation used across the project.",
                    ),
                ),
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "Infrastructure", "Tooling")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "#### Tooling" in markdown
    assert "Developer tools and automation used across the project." in markdown


def test_render_readme_uses_general_subcategory_description_without_heading() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "Infrastructure",
                "Shared tooling and project infrastructure.",
                subcategories=(
                    SubcategoryConfig(
                        "General",
                        "Repositories that do not need a more specific infrastructure bucket.",
                    ),
                ),
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "Infrastructure", "General")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "#### General" not in markdown
    assert (
        "Repositories that do not need a more specific infrastructure bucket."
        in markdown
    )


def test_render_readme_matches_category_descriptions_case_insensitively() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "Infrastructure",
                "Shared tooling and project infrastructure.",
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "infrastructure", "General")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "### Infrastructure" in markdown
    assert "Shared tooling and project infrastructure." in markdown


def test_render_readme_matches_subcategory_descriptions_case_insensitively() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "Infrastructure",
                "Shared tooling and project infrastructure.",
                subcategories=(
                    SubcategoryConfig(
                        "Tooling",
                        "Developer tools and automation used across the project.",
                    ),
                ),
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("infra", "Infra repo", "infrastructure", "tooling")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "### Infrastructure" in markdown
    assert "#### Tooling" in markdown
    assert "Developer tools and automation used across the project." in markdown


def test_render_readme_uses_config_casing_for_category_and_subcategory_names() -> None:
    template = """# Title

{{ repo_sections }}
"""
    config = ReadmeConfig(
        categories=(
            CategoryConfig(
                "MODULES",
                "Core modules.",
                subcategories=(
                    SubcategoryConfig(
                        "CORE",
                        "Primary building blocks.",
                    ),
                ),
            ),
        )
    )

    markdown = render_readme(
        [RepoEntry("score", "Core repo", "modules", "core")],
        template=template,
        config=config,
        org_name="eclipse-score",
    )

    assert "### MODULES" in markdown
    assert "#### CORE" in markdown


def test_load_config_reads_categories_in_file_order(tmp_path: Path) -> None:
    config_path = tmp_path / "profile_readme_config.toml"
    config_path.write_text(
        """
[[categories]]
name = "Modules"
description = "Core S-CORE modules."
subcategories = []

[[categories]]
name = "Infrastructure"
description = "Tooling and integration infrastructure."
subcategories = [
  { name = "Tooling", description = "Developer tools and automation." },
]
""".strip(),
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config == ReadmeConfig(
        categories=(
            CategoryConfig("Modules", "Core S-CORE modules."),
            CategoryConfig(
                "Infrastructure",
                "Tooling and integration infrastructure.",
                subcategories=(
                    SubcategoryConfig(
                        "Tooling",
                        "Developer tools and automation.",
                    ),
                ),
            ),
        )
    )


def test_describe_config_source_uses_package_default_label() -> None:
    assert describe_config_source(None) == "package default config"
    assert describe_config_source(Path("config.toml")) == "config.toml"


def test_resolve_github_token_prefers_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_GITHUB_TOKEN", "env-token")
    monkeypatch.setattr(collector, "get_gh_auth_token", lambda: "gh-token")

    assert resolve_github_token("TEST_GITHUB_TOKEN") == "env-token"


def test_get_gh_auth_token_returns_trimmed_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        collector.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(stdout="gh-token\n"),
    )

    assert get_gh_auth_token() == "gh-token"


def test_get_gh_auth_token_returns_none_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_called_process_error(*args: object, **kwargs: object) -> None:
        raise collector.subprocess.CalledProcessError(1, ["gh", "auth", "token"])

    monkeypatch.setattr(collector.subprocess, "run", raise_called_process_error)

    assert get_gh_auth_token() is None


def test_print_status_writes_to_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    print_status("Loading repos")

    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == "[repo-overview] Loading repos\n"
