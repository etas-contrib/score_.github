from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from generate_repo_overview.models import TrackedDep, WorkflowSignal
from generate_repo_overview.org_config import OrgConfig, load_org_config

if TYPE_CHECKING:
    from pathlib import Path


class TestOrgConfigDefaults:
    def test_org_name_is_required(self) -> None:
        with pytest.raises(TypeError):
            OrgConfig()  # type: ignore[call-arg]

    def test_signal_defaults_are_empty(self) -> None:
        config = OrgConfig(org_name="my-org")
        assert config.repo_include_patterns == ()
        assert config.tracked_deps == ()
        assert config.workflow_signals == ()
        assert config.reference_integration_repo == ""
        assert config.registry_repo == ""


class TestLoadOrgConfig:
    def test_load_minimal_toml(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "org.toml"
        toml_path.write_text('org_name = "my-org"\n', encoding="utf-8")
        config = load_org_config(toml_path)
        assert config.org_name == "my-org"
        assert config.repo_include_patterns == ()
        assert config.tracked_deps == ()

    def test_toml_without_org_name_errors(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "org.toml"
        toml_path.write_text("", encoding="utf-8")
        with pytest.raises(ValueError, match="org_name is required"):
            load_org_config(toml_path)

    def test_load_full_toml(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "other-org"
            repo_include_patterns = ["lib-*", "tool-*"]

            [signals]
            reference_integration_repo = "other-org/ref-int"
            registry_repo = "other-org/my_registry"

            [[signals.tracked_deps]]
            repo = "other-org/my-docs"
            module_name = "my_docs_dep"

            [[signals.workflow_signals]]
            label = "Nightly"
            reference = "other-org/my-cicd/.github/workflows/nightly.yml@"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        config = load_org_config(toml_path)
        assert config.org_name == "other-org"
        assert config.repo_include_patterns == ("lib-*", "tool-*")
        assert config.tracked_deps == (
            TrackedDep(repo="other-org/my-docs", module_name="my_docs_dep"),
        )
        assert config.workflow_signals == (
            WorkflowSignal(
                label="Nightly",
                reference="other-org/my-cicd/.github/workflows/nightly.yml@",
            ),
        )
        assert config.reference_integration_repo == "other-org/ref-int"
        assert config.registry_repo == "other-org/my_registry"

    def test_missing_signals_section_uses_empty_defaults(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            repo_include_patterns = ["foo*"]
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        config = load_org_config(toml_path)
        assert config.repo_include_patterns == ("foo*",)
        assert config.tracked_deps == ()
        assert config.registry_repo == ""


class TestRepoMatchesFilter:
    def test_empty_patterns_matches_all(self) -> None:
        config = OrgConfig(org_name="x", repo_include_patterns=())
        assert config.repo_matches_filter("anything") is True
        assert config.repo_matches_filter("lib-foo") is True

    def test_glob_patterns(self) -> None:
        config = OrgConfig(org_name="x", repo_include_patterns=("lib-*", "tool-*"))
        assert config.repo_matches_filter("lib-a") is True
        assert config.repo_matches_filter("lib-module-a") is True
        assert config.repo_matches_filter("tool-cli") is True
        assert config.repo_matches_filter("other-repo") is False
        assert config.repo_matches_filter("my-lib-thing") is False

    def test_exact_name_pattern(self) -> None:
        config = OrgConfig(org_name="x", repo_include_patterns=("specific-repo",))
        assert config.repo_matches_filter("specific-repo") is True
        assert config.repo_matches_filter("specific-repo-2") is False

    def test_question_mark_glob(self) -> None:
        config = OrgConfig(org_name="x", repo_include_patterns=("lib-?",))
        assert config.repo_matches_filter("lib-a") is True
        assert config.repo_matches_filter("lib-ab") is False


class TestConfigValidation:
    def test_whitespace_only_org_name_errors(self, tmp_path: Path) -> None:
        toml_path = tmp_path / "org.toml"
        toml_path.write_text('org_name = "   "\n', encoding="utf-8")
        with pytest.raises(ValueError, match="org_name is required"):
            load_org_config(toml_path)

    def test_repo_include_patterns_string_instead_of_list_errors(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            repo_include_patterns = "single-pattern"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="Expected a list"):
            load_org_config(toml_path)

    def test_repo_without_slash_in_reference_integration_repo_errors(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            [signals]
            reference_integration_repo = "just-a-name"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="org/repo"):
            load_org_config(toml_path)

    def test_whitespace_stripped_from_patterns(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            repo_include_patterns = [" lib-* ", "  tool-*  "]
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        config = load_org_config(toml_path)
        assert config.repo_include_patterns == ("lib-*", "tool-*")


    def test_registry_repo_without_slash_errors(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            [signals]
            registry_repo = "just-a-name"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        with pytest.raises(ValueError, match="org/repo"):
            load_org_config(toml_path)

    def test_malformed_tracked_deps_entries_are_skipped(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            [signals]
            [[signals.tracked_deps]]
            repo = "org/valid"
            module_name = "valid_mod"
            [[signals.tracked_deps]]
            repo = "org/missing-module"
            [[signals.tracked_deps]]
            module_name = "missing-repo"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        config = load_org_config(toml_path)
        assert len(config.tracked_deps) == 1
        assert config.tracked_deps[0].repo == "org/valid"

    def test_malformed_workflow_signals_entries_are_skipped(self, tmp_path: Path) -> None:
        content = dedent("""\
            org_name = "test"
            [signals]
            [[signals.workflow_signals]]
            label = "Valid"
            reference = "org/ref@"
            [[signals.workflow_signals]]
            label = "Missing Reference"
            [[signals.workflow_signals]]
            reference = "org/no-label@"
        """)
        toml_path = tmp_path / "org.toml"
        toml_path.write_text(content, encoding="utf-8")
        config = load_org_config(toml_path)
        assert len(config.workflow_signals) == 1
        assert config.workflow_signals[0].label == "Valid"


class TestReferenceIntegrationOrgName:
    def test_parse_github_remote_with_custom_org(self) -> None:
        from generate_repo_overview.collector.reference_integration import (
            parse_github_remote_repository_name,
        )

        result = parse_github_remote_repository_name(
            "https://github.com/other-org/my-repo.git",
            org_name="other-org",
        )
        assert result == "my-repo"

    def test_parse_github_remote_rejects_wrong_org(self) -> None:
        from generate_repo_overview.collector.reference_integration import (
            parse_github_remote_repository_name,
        )

        result = parse_github_remote_repository_name(
            "https://github.com/other-org/my-repo.git",
            org_name="wrong-org",
        )
        assert result is None
