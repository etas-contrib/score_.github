from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ._text_utils import escape_markdown_table_cell

if TYPE_CHECKING:
    from collections.abc import Callable

    from .models import RepoEntry, RepoSnapshot, TrackedDep


HANDLE_PATTERN = re.compile(r"@[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)?")
BAZEL_ICON_URL = "https://bazel.build/_pwa/bazel/icons/icon-72x72.png"


def render_metrics_report(snapshot: RepoSnapshot) -> str:
    repos = sorted(snapshot.repos, key=lambda repo: repo.name.casefold())
    lines = [
        "# Cross-Repo Metrics Report",
        "",
        f"Generated on {snapshot.generated_at}",
        "",
        *render_summary(repos),
        "",
        "## Table Of Contents",
        "",
        "- [Repository Overview](#repository-overview)",
        "- [Versions](#versions)",
        "- [Delivery And Automation](#delivery-and-automation)",
        "",
    ]
    lines.extend(render_overview_section(repos, org_name=snapshot.org_name))
    lines.extend(render_versions_section(repos, snapshot=snapshot))
    lines.extend(render_automation_section(repos, snapshot=snapshot))
    return "\n".join(lines).rstrip() + "\n"


def render_summary(repos: list[RepoEntry]) -> list[str]:
    return [
        f"- Repositories: {len(repos)}",
        f"- With GitHub Actions: {sum(repo.content.has_ci for repo in repos)}",
        f"- With workflow signals: {sum(bool(repo.content.matched_workflow_signals) for repo in repos)}",
        f"- With lint/style config: {sum(repo.content.has_lint_config for repo in repos)}",
        f"- With coverage config: {sum(repo.content.has_coverage_config for repo in repos)}",
        f"- With releases: {sum(has_latest_release(repo) for repo in repos)}",
    ]


def render_overview_section(repos: list[RepoEntry], org_name: str) -> list[str]:
    lines = [
        "## Repository Overview",
        "",
        "- `Open Issues / PRs`: open issues only and open pull requests as `issues / ready+draft`.",
        "- `Merged PRs (30d)`: pull requests merged into each repository's default branch within the last 30 days (`>= 10` is marked `🔥`).",
        "- `Bazel`: icon shown next to the repository name when the repo contains `.bazelversion`, `MODULE.bazel`, `WORKSPACE`, or `WORKSPACE.bazel`.",
        "- `Latest Release`: release tag name, falling back to the release name when needed.",
        "- `Commits Since Release`: compare the latest release tag to current default branch head.",
        "- Icons: `🟢` healthy, `🟡` caution, `🔴` alert.",
        "- `Codeowners`: owners resolved for the `.github/CODEOWNERS` path from that repository's `.github/CODEOWNERS` file.",
        "- `Maintainers In Bazel Registry`: shown only for bazel repos when handles are available.",
        "",
    ]
    lines.extend(
        render_category_tables(
            repos,
            org_name=org_name,
            header="| Repository | Ownership | Merged PRs (30d) | Open Issues / PRs (ready+draft) | Latest Release + Commits Since Release | Stars / Forks |",
            divider="|------------|-----------|------------------|-------------------------------|----------------------------------------|---------------|",
            row_renderer=render_overview_row,
        )
    )
    return lines


def render_versions_section(repos: list[RepoEntry], *, snapshot: RepoSnapshot) -> list[str]:
    """Render the Versions table with one column per tracked dep plus Bazel and Ref-Int."""
    from .models import lookup_bazel_dep_version

    tracked_deps = snapshot.tracked_deps
    max_bazel_version = get_max_bazel_version(repos)
    latest_dep_versions = {
        dep.module_name: get_latest_tracked_dep_version(repos, dep)
        for dep in tracked_deps
    }

    dep_labels = [tracked_dep_label(dep) for dep in tracked_deps]

    def render_row(entry: RepoEntry, *, org_name: str) -> str:
        url = f"https://github.com/{org_name}/{entry.name}"
        bazel_cell = render_bazel_version_status(entry.content.bazel_version, max_bazel_version)
        dep_cells = " | ".join(
            render_dep_version_status(
                lookup_bazel_dep_version(entry.content.bazel_deps, dep.module_name),
                latest_dep_versions.get(dep.module_name),
            )
            for dep in tracked_deps
        )
        refint = render_bool(entry.content.referenced_by_reference_integration)
        parts = f"| [{entry.name}]({url}) | {bazel_cell} |"
        if dep_cells:
            parts += f" {dep_cells} |"
        return f"{parts} {refint} |"

    dep_headers = " | ".join(f"{label} Version" for label in dep_labels)
    dep_dividers = " | ".join("---" for _ in dep_labels)
    header = f"| Repository | {render_bazel_version_column_header()} |"
    divider = "|------------|---------------|"
    if dep_headers:
        header += f" {dep_headers} |"
        divider += f" {dep_dividers} |"
    header += " Reference Integration |"
    divider += " ----------------------|"

    lines = [
        "## Versions",
        "",
        "- Generic view of repository version signals.",
        "- `Reference Integration`: `yes` when the repository is a direct `bazel_dep(...)` in the reference integration's root `MODULE.bazel` or included module files.",
        "- `Bazel Version`: highest version in the table is `🟢`; every other value is `🔴`.",
    ]
    for label in dep_labels:
        lines.append(
            f"- `{label} Version`: `⚪` if missing, `🟢` if equal to latest release, `🟡` if same major.minor, else `🔴`."
        )
    lines.append("")
    lines.extend(
        render_category_tables(
            repos,
            org_name=snapshot.org_name,
            header=header,
            divider=divider,
            row_renderer=render_row,
        )
    )
    return lines


def render_automation_section(repos: list[RepoEntry], *, snapshot: RepoSnapshot) -> list[str]:
    """Render the Automation table with one column per workflow signal."""
    signal_labels = snapshot.workflow_signal_labels

    def render_row(entry: RepoEntry, *, org_name: str) -> str:
        url = f"https://github.com/{org_name}/{entry.name}"
        signal_cells = " | ".join(
            render_bool(label in entry.content.matched_workflow_signals)
            for label in signal_labels
        )
        parts = (
            f"| [{entry.name}]({url}) | {render_presence(entry.content.has_gitlint_config, icon='🔍')} | "
            f"{render_presence(entry.content.has_pyproject_toml, icon='🐍')} | "
            f"{render_presence(entry.content.has_pre_commit_config, icon='🪝')} | "
            f"{render_presence(entry.content.has_ci, icon='⚙')} |"
        )
        if signal_cells:
            parts += f" {signal_cells} |"
        return f"{parts} {render_bool(entry.content.has_coverage_config)} |"

    signal_headers = " | ".join(signal_labels)
    signal_dividers = " | ".join("---" for _ in signal_labels)
    header = "| Repository | 🔍 Gitlint | 🐍 Pyproject | 🪝 Pre-commit | ⚙ GitHub Actions |"
    divider = "|------------|------------|-------------|---------------|------------------|"
    if signal_headers:
        header += f" {signal_headers} |"
        divider += f" {signal_dividers} |"
    header += " Coverage Config |"
    divider += " ---------------|"

    lines = [
        "## Delivery And Automation",
        "",
        "- `🔍 Gitlint`: shown when `.gitlint` exists.",
        "- `🐍 Pyproject`: shown when `pyproject.toml` exists.",
        "- `🪝 Pre-commit`: shown when `.pre-commit-config.yaml` exists.",
        "- `⚙ GitHub Actions`: shown when `.github/workflows` exists.",
    ]
    for label in signal_labels:
        lines.append(f"- `{label}`: `yes` if a matching workflow reference is detected.")
    lines.extend([
        "- `Coverage Config`: `yes` if `coverage.yml`, `coverage.xml`, `pytest.ini`, or `.coveragerc` exists.",
        "",
    ])
    lines.extend(
        render_category_tables(
            repos,
            org_name=snapshot.org_name,
            header=header,
            divider=divider,
            row_renderer=render_row,
        )
    )
    return lines


def render_category_tables(
    repos: list[RepoEntry],
    *,
    org_name: str,
    header: str,
    divider: str,
    row_renderer: Callable[..., str],
    heading_level: int = 3,
) -> list[str]:
    lines: list[str] = []
    heading_prefix = "#" * heading_level
    for category, category_repos in group_repos_by_category(repos):
        lines.extend(
            [
                f"{heading_prefix} {category}",
                "",
                header,
                divider,
            ]
        )
        for repo in category_repos:
            lines.append(row_renderer(repo, org_name=org_name))
        lines.append("")
    return lines


def group_repos_by_category(
    repos: list[RepoEntry],
) -> list[tuple[str, list[RepoEntry]]]:
    grouped: dict[str, list[RepoEntry]] = {}
    for repo in repos:
        grouped.setdefault(repo.category, []).append(repo)

    return [
        (category, sorted(category_repos, key=lambda repo: repo.name.casefold()))
        for category, category_repos in sorted(
            grouped.items(), key=lambda item: item[0].casefold()
        )
    ]


def render_overview_row(entry: RepoEntry, *, org_name: str) -> str:
    url = f"https://github.com/{org_name}/{entry.name}"
    return (
        f"| {render_repo_link_with_bazel_icon(entry, url)} | {render_ownership_cell(entry)} | "
        f"{render_merged_pr_count(entry.volatile.merged_prs_30_days)} | "
        f"{render_open_issues_and_prs(entry.volatile.open_issues, entry.volatile.open_ready_prs, entry.volatile.open_draft_prs)} | "
        f"{render_release_and_commits(entry.volatile.latest_release_version, entry.volatile.commits_since_latest_release)} | "
        f"{entry.stars} / {entry.forks} |"
    )


def render_repo_link_with_bazel_icon(entry: RepoEntry, url: str) -> str:
    repo_link = f"[{entry.name}]({url})"
    if entry.content.is_bazel_repo:
        return f"{repo_link} {render_bazel_icon()}"
    return repo_link


def render_open_issues_and_prs(
    open_issues: int, open_ready_prs: int, open_draft_prs: int
) -> str:
    return f"{open_issues} / {render_ready_pr_count(open_ready_prs)}+{open_draft_prs}"


def render_release_and_commits(
    latest_release_version: str | None, commits_since_release: int | None
) -> str:
    latest_release = render_plain_value(latest_release_version)
    commits = render_commits_since_release(commits_since_release)
    if latest_release == "-" and commits == "-":
        return "-"
    return f"{latest_release} + {commits}"



def render_bool(value: bool) -> str:
    return "yes" if value else "no"


def render_plain_value(value: str | None) -> str:
    if value is None or not value.strip():
        return "-"
    return escape_markdown_table_cell(value.strip())


def render_ready_pr_count(value: int) -> str:
    if value > 5:
        return f"🔴 {value}"
    return str(value)


def render_merged_pr_count(value: int) -> str:
    if value >= 10:
        return f"🔥 {value}"
    return str(value)


def render_commits_since_release(value: int | None) -> str:
    if value is None:
        return "-"
    if value == 0:
        return "🟢 0"
    if value <= 20:
        return f"🟡 {value}"
    return f"🔴 {value}"


def render_bazel_version_column_header() -> str:
    return f"{render_bazel_icon()} Bazel Version"


def render_bazel_icon() -> str:
    return f'<img src="{BAZEL_ICON_URL}" alt="Bazel" width="16" height="16">'


def render_presence(value: bool, *, icon: str) -> str:
    return icon if value else "-"


def render_ownership_cell(entry: RepoEntry) -> str:
    codeowners = render_people_list(entry.content.codeowners, handles_only=True)
    lines: list[str] = []
    if codeowners != "-":
        lines.append(f"Codeowners: {codeowners}")

    if entry.content.is_bazel_repo:
        maintainers = render_people_list(
            entry.registry.maintainers_in_bazel_registry,
            handles_only=True,
        )
        if maintainers != "-":
            lines.append(f"Maintainers In Bazel Registry: {maintainers}")

    if not lines:
        return "-"

    return f"<small><sub><small>{'<br><br>'.join(lines)}</small></sub></small>"


def render_people_list(values: tuple[str, ...], *, handles_only: bool = False) -> str:
    if not values:
        return "-"

    cleaned_values = values
    if handles_only:
        handles: list[str] = []
        for value in values:
            handles.extend(extract_handles(value))
        cleaned_values = tuple(dict.fromkeys(handles))

    if not cleaned_values:
        return "-"

    return escape_markdown_table_cell(", ".join(cleaned_values))


def extract_handles(value: str) -> list[str]:
    return HANDLE_PATTERN.findall(value)


def parse_version_key(value: str | None) -> tuple[int, ...] | None:
    if value is None:
        return None
    numeric_parts = re.findall(r"\d+", value)
    if not numeric_parts:
        return None
    return tuple(int(part) for part in numeric_parts[:3])


def get_max_bazel_version(repos: list[RepoEntry]) -> tuple[int, ...] | None:
    keys = [
        key
        for repo in repos
        if (key := parse_version_key(repo.content.bazel_version)) is not None
    ]
    return max(keys) if keys else None


def get_latest_tracked_dep_version(repos: list[RepoEntry], dep: TrackedDep) -> str | None:
    repo_short_name = dep.repo.rsplit("/", 1)[-1]
    for repo in repos:
        if repo.name == repo_short_name:
            v = repo.volatile.latest_release_version
            return v.removeprefix("v").strip() if v else None
    return None


def tracked_dep_label(dep: TrackedDep) -> str:
    return dep.repo.rsplit("/", 1)[-1].replace("-", " ").replace("_", " ").title()


def render_bazel_version_status(
    bazel_version: str | None,
    max_bazel_version: tuple[int, ...] | None,
) -> str:
    if bazel_version is None or not bazel_version.strip():
        return "⚪ -"

    cleaned = bazel_version.strip()
    parsed = parse_version_key(cleaned)
    if (
        parsed is not None
        and max_bazel_version is not None
        and parsed == max_bazel_version
    ):
        return f"🟢 {escape_markdown_table_cell(cleaned)}"
    return f"🔴 {escape_markdown_table_cell(cleaned)}"


def major_minor(version: str) -> tuple[int, int] | None:
    parsed = parse_version_key(version)
    if parsed is None or len(parsed) < 2:
        return None
    return (parsed[0], parsed[1])


def render_dep_version_status(
    dep_version: str | None,
    latest_version: str | None,
) -> str:
    if dep_version is None or not dep_version.strip():
        return "⚪ -"

    cleaned = dep_version.strip()
    if latest_version is None:
        return f"⚪ {escape_markdown_table_cell(cleaned)}"

    latest_cleaned = latest_version.strip()
    if cleaned == latest_cleaned:
        return f"🟢 {escape_markdown_table_cell(cleaned)}"

    cleaned_major_minor = major_minor(cleaned)
    latest_major_minor = major_minor(latest_cleaned)
    if cleaned_major_minor is not None and cleaned_major_minor == latest_major_minor:
        return f"🟡 {escape_markdown_table_cell(cleaned)}"

    return f"🔴 {escape_markdown_table_cell(cleaned)}"


def has_latest_release(entry: RepoEntry) -> bool:
    return (
        entry.volatile.latest_release_version is not None
        or entry.volatile.latest_release_date is not None
    )
