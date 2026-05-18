from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from ._html_common import (
    BAZEL_ICON,
    CSS,
    e,
    language_badge,
    repo_name_cell,
    version_badge,
)
from .metrics_report import (
    get_latest_tracked_dep_version,
    get_max_bazel_version,
    group_repos_by_category,
    has_latest_release,
    parse_version_key,
    tracked_dep_label,
)

if TYPE_CHECKING:
    from .models import RepoEntry, RepoSnapshot, TrackedDep

_INDEX_JS = (Path(__file__).parent / "templates" / "index.js").read_text(
    encoding="utf-8"
)


def render_index_page(snapshot: RepoSnapshot) -> str:
    repos = sorted(snapshot.repos, key=lambda r: r.name.casefold())
    categories = group_repos_by_category(repos)
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"  <title>Cross-Repo Metrics — {e(snapshot.org_name)}</title>\n"
        f"  <style>{CSS}</style>\n"
        "</head>\n<body>\n"
        + _render_header(snapshot, repos)
        + _render_tab_bar()
        + _render_filters_placeholder()
        + '<div id="sections">\n'
        + _render_overview_sections(categories, snapshot.org_name)
        + _render_versions_sections(categories, snapshot)
        + _render_automation_sections(categories, snapshot)
        + _render_traceability_section(repos, snapshot)
        + "</div>\n"
        + _render_footer(snapshot)
        + _render_script(categories)
        + "</body>\n</html>\n"
    )


def _render_header(snapshot: RepoSnapshot, repos: list[RepoEntry]) -> str:
    total = len(repos)
    with_ci = sum(r.content.has_ci for r in repos)
    with_releases = sum(has_latest_release(r) for r in repos)
    with_lint = sum(r.content.has_lint_config for r in repos)
    bazel_repos = sum(r.content.is_bazel_repo for r in repos)

    lang_chips = _render_language_distribution(repos)

    return (
        "<header>\n"
        "  <h1>Cross-Repo Metrics Report</h1>\n"
        f'  <p class="subtitle">Generated {e(snapshot.generated_at)}</p>\n'
        '  <div id="summary">\n'
        f'    <span class="summary-chip"><span class="dot" style="background:var(--accent)"></span>{total} repositories</span>\n'
        f'    <span class="summary-chip"><span class="dot" style="background:var(--green)"></span>{with_ci} with CI</span>\n'
        f'    <span class="summary-chip"><span class="dot" style="background:var(--yellow)"></span>{with_releases} with releases</span>\n'
        f'    <span class="summary-chip"><span class="dot" style="background:var(--orange)"></span>{bazel_repos} Bazel repos</span>\n'
        f'    <span class="summary-chip"><span class="dot" style="background:var(--muted)"></span>{with_lint} with lint config</span>\n'
        "  </div>\n"
        + (f'  <div id="lang-summary">{lang_chips}</div>\n' if lang_chips else "")
        + "</header>\n\n"
    )


def _render_language_distribution(repos: list[RepoEntry]) -> str:
    counts = Counter(
        r.content.top_languages[0] for r in repos if r.content.top_languages
    )
    if not counts:
        return ""
    top = counts.most_common(4)
    other = sum(counts.values()) - sum(c for _, c in top)
    parts = [
        f"{language_badge(lang)} <span class='lang-count'>{count}</span>"
        for lang, count in top
    ]
    if other > 0:
        parts.append(f'<span class="text-muted">+{other} other</span>')
    return " ".join(parts)


def _render_tab_bar() -> str:
    return (
        '<div class="tab-bar">\n'
        '  <button class="tab-btn active" data-tab="overview">Repository Overview</button>\n'
        '  <button class="tab-btn" data-tab="versions">Versions</button>\n'
        '  <button class="tab-btn" data-tab="tech-stack">Tech Stack</button>\n'
        '  <button class="tab-btn" data-tab="traceability">Traceability</button>\n'
        "</div>\n\n"
    )


def _render_filters_placeholder() -> str:
    return '<div id="filters"></div>\n\n'


def _render_overview_sections(
    categories: list[tuple[str, list[RepoEntry]]],
    org_name: str,
) -> str:
    parts: list[str] = []
    for category, cat_repos in categories:
        rows = "\n".join(_overview_row(r, org_name) for r in cat_repos)
        parts.append(
            f'<div class="section" data-tab="overview" data-category="{e(category)}">\n'
            f'  <div class="section-header">\n'
            f'    <span class="section-title">{e(category)}</span>\n'
            f'    <span class="section-count">{len(cat_repos)}</span>\n'
            f"  </div>\n"
            f"  <table>\n"
            f"    <thead><tr>\n"
            f'      <th data-sort="name">Repository <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="merged" class="text-right" title="Number of pull requests merged into the main branch in the last 30 days. A higher number means more active development.">Merged PRs (30d) <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="issues" class="text-right" data-tooltip="Number of open issues in this repository, including bug reports and feature requests.">Open Issues <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="prs" class="text-right" data-tooltip="Open pull requests: the first number is ready for review, the second is still in draft. A red badge means more than 5 are waiting for review.">Open PRs <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="release" title="The most recent published release. Green = no unreleased commits, yellow = up to 20 commits not yet released, red = more than 20 commits not yet released.">Latest Release <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="stars" class="text-right">Stars / Forks <span class="sort-arrow"></span></th>\n'
            f"    </tr></thead>\n"
            f"    <tbody>\n{rows}\n    </tbody>\n"
            f"  </table>\n"
            f"</div>\n"
        )
    return "".join(parts)


def _overview_row(entry: RepoEntry, org_name: str) -> str:
    name_cell = repo_name_cell(entry, org_name)
    repo_url = f"https://github.com/{org_name}/{entry.name}"

    merged = _render_merged_badge(entry.volatile.merged_prs_30_days)
    issues_cell = _render_issues_cell(entry.volatile.open_issues, repo_url)
    prs_cell = _render_prs_cell(
        entry.volatile.open_ready_prs,
        entry.volatile.open_draft_prs,
        repo_url,
    )
    release = _render_release(
        entry.volatile.latest_release_version,
        entry.volatile.commits_since_latest_release,
    )
    stars_forks = f"{entry.stars} / {entry.forks}"

    cnt = entry.volatile.merged_prs_30_days
    if cnt == 0:
        merged_tip = "No pull requests were merged in the last 30 days."
    elif cnt >= 10:
        merged_tip = f"\U0001f525 {cnt} pull requests merged in the last 30 days — very active!"
    else:
        merged_tip = (
            f"{cnt} pull request{'s' if cnt != 1 else ''} merged in the last 30 days."
        )

    n = entry.volatile.open_issues
    issues_tip = f"{n} open issue{'s' if n != 1 else ''} in this repository."

    ready = entry.volatile.open_ready_prs
    draft = entry.volatile.open_draft_prs
    total_prs = ready + draft
    prs_tip = f"{ready} ready for review + {draft} in draft — {total_prs} open pull request{'s' if total_prs != 1 else ''} in total."

    ver = entry.volatile.latest_release_version
    commits = entry.volatile.commits_since_latest_release
    if ver is None:
        release_tip = "No release has been published for this repository."
    elif commits is None:
        release_tip = str(ver)
    elif commits == 0:
        release_tip = f"{ver} — the main branch is fully up to date with this release."
    else:
        release_tip = f"{ver} — {commits} commit{'s' if commits != 1 else ''} on the main branch not yet included in a release."

    stars_tip = f"{entry.stars} star{'s' if entry.stars != 1 else ''} · {entry.forks} fork{'s' if entry.forks != 1 else ''}"

    return (
        f'    <tr data-name="{e(entry.name)}" data-merged="{entry.volatile.merged_prs_30_days}"'
        f' data-issues="{entry.volatile.open_issues}" data-stars="{entry.stars}">\n'
        f"      <td>{name_cell}</td>\n"
        f'      <td class="text-right" data-tooltip="{e(merged_tip)}">{merged}</td>\n'
        f'      <td class="text-right" data-tooltip="{e(issues_tip)}">{issues_cell}</td>\n'
        f'      <td class="text-right" data-tooltip="{e(prs_tip)}">{prs_cell}</td>\n'
        f'      <td data-tooltip="{e(release_tip)}">{release}</td>\n'
        f'      <td class="text-right" data-tooltip="{e(stars_tip)}">{stars_forks}</td>\n'
        f"    </tr>"
    )


def _render_merged_badge(count: int) -> str:
    if count >= 10:
        return f'<span class="badge fire">\U0001f525 {count}</span>'
    return str(count)


def _render_issues_cell(issues: int, repo_url: str) -> str:
    if issues == 0:
        return '<span class="text-muted">—</span>'
    url = e(f"{repo_url}/issues")
    return (
        f'<a href="{url}" class="gh-count" target="_blank" rel="noopener">{issues}</a>'
    )


def _render_prs_cell(ready_prs: int, draft_prs: int, repo_url: str) -> str:
    if ready_prs == 0 and draft_prs == 0:
        return '<span class="text-muted">—</span>'
    url = e(f"{repo_url}/pulls")
    if ready_prs > 5:
        content = f'<span class="badge red">{ready_prs}</span>+{draft_prs}'
    else:
        content = f"{ready_prs}+{draft_prs}"
    return (
        f'<a href="{url}" class="gh-count" target="_blank" rel="noopener">{content}</a>'
    )


def _render_release(version: str | None, commits_since: int | None) -> str:
    if version is None and commits_since is None:
        return '<span class="text-muted">—</span>'
    ver = e(version) if version else "—"
    if commits_since is None:
        return f'<span class="mono">{ver}</span>'
    badge_class = (
        "green" if commits_since == 0 else ("yellow" if commits_since <= 20 else "red")
    )
    icon = "✓" if commits_since == 0 else str(commits_since)
    return (
        f'<span class="mono">{ver}</span> '
        f'<span class="badge {badge_class}">+{icon}</span>'
    )


def _is_tracked_dep_repo(
    entry: RepoEntry, tracked_deps: tuple[TrackedDep, ...]
) -> bool:
    from .models import lookup_bazel_dep_version

    return any(
        lookup_bazel_dep_version(entry.content.bazel_deps, dep.module_name) is not None
        or entry.name == dep.repo.rsplit("/", 1)[-1]
        for dep in tracked_deps
    )


def _build_version_tooltip(
    *,
    dependency_version_as_used_on_main_branch: str | None,
    latest_available_dependency_version: str | None,
    dependency_version_as_used_in_last_release: str | None,
    component_name: str,
    last_release_tag: str | None = None,
) -> str:
    """Build a human-readable tooltip for version comparison.

    Generic function to compare a component's current version (on main) with the
    latest available version and what was used in the last release.

    Args:
        dependency_version_as_used_on_main_branch: Version currently in use on main branch
        latest_available_dependency_version: Latest available version globally
        dependency_version_as_used_in_last_release: Version used in the most recent release
        component_name: Human-readable component name (e.g., "Bazel", "Docs-As-Code")
        last_release_tag: Optional release tag for "was X at <tag>" suffix

    Returns:
        Human-readable tooltip text
    """
    if dependency_version_as_used_on_main_branch is not None:
        assert (
            dependency_version_as_used_on_main_branch
            == dependency_version_as_used_on_main_branch.strip()
        )
    if latest_available_dependency_version is not None:
        assert (
            latest_available_dependency_version
            == latest_available_dependency_version.strip()
        )

    # Handle component not in use
    if not dependency_version_as_used_on_main_branch:
        if dependency_version_as_used_in_last_release:
            return (
                f"{component_name} is not currently used on the main branch,"
                f" but was used in the last release."
            )
        else:
            return f"{component_name} is not used in this repository."

    # Handle missing latest version (no comparison possible)
    if latest_available_dependency_version is None:
        return f"{component_name} {dependency_version_as_used_on_main_branch} is in use."

    # Build intro: note if version changed between the last release and main
    version_changed = (
        dependency_version_as_used_in_last_release
        and last_release_tag
        and dependency_version_as_used_in_last_release
        != dependency_version_as_used_on_main_branch
    )
    if version_changed:
        tip = (
            f"{component_name} was {dependency_version_as_used_in_last_release}"
            f" at {last_release_tag}, updated to"
            f" {dependency_version_as_used_on_main_branch} on the main branch"
        )
    else:
        tip = f"{component_name} {dependency_version_as_used_on_main_branch}"

    # Append up-to-date status
    if dependency_version_as_used_on_main_branch == latest_available_dependency_version:
        tip += " — now up to date." if version_changed else " — up to date (latest known version)."
    else:
        current_parts = parse_version_key(dependency_version_as_used_on_main_branch)
        latest_parts = parse_version_key(latest_available_dependency_version)
        is_patch_only = (
            current_parts
            and latest_parts
            and len(current_parts) >= 2
            and len(latest_parts) >= 2
            and current_parts[:2] == latest_parts[:2]
        )
        if is_patch_only:
            tip += f" — a patch update to {latest_available_dependency_version} is available."
        else:
            tip += f" — an update to {latest_available_dependency_version} is available."

    return tip


def _render_dep_changes(
    entry: RepoEntry, excluded_deps: frozenset[str] = frozenset()
) -> tuple[str, str]:
    """Return (cell_html, tooltip) for the Other Dep Changes column."""
    if entry.volatile.latest_release_version is None:
        return '<span class="text-muted">—</span>', "No release has been published — nothing to compare against."

    head_deps = dict(entry.content.bazel_deps)
    release_deps = dict(entry.volatile.release_bazel_deps)

    changes: list[str] = []
    all_names = sorted(set(head_deps) | set(release_deps))
    for name in all_names:
        if name in excluded_deps:
            continue
        hv = head_deps.get(name)
        rv = release_deps.get(name)
        if hv != rv:
            changes.append(f"{name}: {rv or '—'} → {hv or '—'}")

    count = len(changes)
    if count == 0:
        tip = f"No dependency changes between {entry.volatile.latest_release_version} and the current main branch."
        cell = '<span class="badge green">no changes</span>'
        return cell, tip

    badge_class = "yellow" if count <= 5 else "red"
    cell = f'<span class="badge {badge_class}">{count} changed</span>'
    tip = "; ".join(changes[:8])
    if len(changes) > 8:
        tip += f" (+{len(changes) - 8} more)"
    return cell, tip


def _render_versions_sections(
    categories: list[tuple[str, list[RepoEntry]]],
    snapshot: RepoSnapshot,
) -> str:
    repos = sorted(snapshot.repos, key=lambda r: r.name.casefold())
    max_bazel = get_max_bazel_version(repos)
    tracked_deps = snapshot.tracked_deps
    latest_dep_versions = {
        dep.module_name: get_latest_tracked_dep_version(repos, dep)
        for dep in tracked_deps
    }
    org_name = snapshot.org_name
    parts: list[str] = []
    for category, cat_repos in categories:
        rows = "\n".join(
            _versions_row(r, org_name, max_bazel, tracked_deps, latest_dep_versions)
            for r in cat_repos
        )
        dep_headers = "".join(
            f'      <th data-sort="dep-{i}" title="Version of the {e(tracked_dep_label(dep))} dependency.">'
            f'{e(tracked_dep_label(dep))} Version <span class="sort-arrow"></span></th>\n'
            for i, dep in enumerate(tracked_deps)
        )
        parts.append(
            f'<div class="section hidden" data-tab="versions" data-category="{e(category)}">\n'
            f'  <div class="section-header">\n'
            f'    <span class="section-title">{e(category)}</span>\n'
            f'    <span class="section-count">{len(cat_repos)}</span>\n'
            f"  </div>\n"
            f"  <table>\n"
            f"    <thead><tr>\n"
            f'      <th data-sort="name">Repository <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="bazel" title="The version of Bazel (the build tool) in use. Green = on the latest known version, red = a newer version is available.">{BAZEL_ICON} Bazel Version <span class="sort-arrow"></span></th>\n'
            f"{dep_headers}"
            f'      <th data-sort="refint" class="text-center" title="Whether this repository is included in the shared reference integration test suite.">Reference Integration <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="release" title="The most recent published release. Green = no unreleased commits, yellow = up to 20 commits not yet released, red = more than 20 commits not yet released.">Latest Release <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="depchanges" title="Number of dependency version changes on the main branch since the last release. Tracked dependency versions are shown in their own columns.">Other Dep Changes <span class="sort-arrow"></span></th>\n'
            f"    </tr></thead>\n"
            f"    <tbody>\n{rows}\n    </tbody>\n"
            f"  </table>\n"
            f"</div>\n"
        )
    return "".join(parts)


def _versions_row(
    entry: RepoEntry,
    org_name: str,
    max_bazel: tuple[int, ...] | None,
    tracked_deps: tuple[TrackedDep, ...],
    latest_dep_versions: dict[str, str | None],
) -> str:
    from .models import lookup_bazel_dep_version

    name_cell = repo_name_cell(entry, org_name)

    bazel_cell = version_badge(
        entry.content.bazel_version, max_bazel, latest_dep_version=None, is_bazel=True
    )
    release_bazel = entry.volatile.release_bazel_version
    if release_bazel and release_bazel != entry.content.bazel_version:
        bazel_cell = (
            f'<span class="mono text-muted">{e(release_bazel)}</span> → {bazel_cell}'
        )

    release_deps = dict(entry.volatile.release_bazel_deps)
    dedicated_dep_names = frozenset(dep.module_name for dep in tracked_deps)

    dep_cells: list[str] = []
    for dep in tracked_deps:
        dep_label = tracked_dep_label(dep)
        head_ver = lookup_bazel_dep_version(entry.content.bazel_deps, dep.module_name)
        release_ver = release_deps.get(dep.module_name)
        latest_ver = latest_dep_versions.get(dep.module_name)
        cell = version_badge(head_ver, None, latest_dep_version=latest_ver, is_bazel=False)
        if release_ver and release_ver != head_ver:
            cell = f'<span class="mono text-muted">{e(release_ver)}</span> → {cell}'
        tip = _build_version_tooltip(
            dependency_version_as_used_on_main_branch=head_ver,
            latest_available_dependency_version=latest_ver,
            dependency_version_as_used_in_last_release=release_ver,
            component_name=dep_label,
            last_release_tag=entry.volatile.latest_release_version,
        )
        dep_cells.append(f'      <td data-tooltip="{e(tip)}">{cell}</td>\n')

    refint = (
        '<span class="badge green">yes</span>'
        if entry.content.referenced_by_reference_integration
        else '<span class="text-muted">no</span>'
    )

    max_bazel_str = ".".join(str(x) for x in max_bazel) if max_bazel else None
    bazel_tip = _build_version_tooltip(
        dependency_version_as_used_on_main_branch=entry.content.bazel_version,
        latest_available_dependency_version=max_bazel_str,
        dependency_version_as_used_in_last_release=release_bazel,
        component_name="Bazel",
        last_release_tag=entry.volatile.latest_release_version,
    )

    refint_tip = (
        "This repository is included in the shared reference integration."
        if entry.content.referenced_by_reference_integration
        else "This repository is not included in the shared reference integration."
    )

    release = _render_release(
        entry.volatile.latest_release_version,
        entry.volatile.commits_since_latest_release,
    )
    ver = entry.volatile.latest_release_version
    commits = entry.volatile.commits_since_latest_release
    if ver is None:
        release_tip = "No release has been published for this repository."
    elif commits is None:
        release_tip = str(ver)
    elif commits == 0:
        release_tip = f"{ver} — the main branch is fully up to date with this release."
    else:
        release_tip = f"{ver} — {commits} commit{'s' if commits != 1 else ''} on the main branch not yet included in a release."

    dep_changes_cell, dep_changes_tip = _render_dep_changes(entry, dedicated_dep_names)

    return (
        f"    <tr>\n"
        f"      <td>{name_cell}</td>\n"
        f'      <td data-tooltip="{e(bazel_tip)}">{bazel_cell}</td>\n'
        + "".join(dep_cells)
        + f'      <td class="text-center" data-tooltip="{e(refint_tip)}">{refint}</td>\n'
        f'      <td data-tooltip="{e(release_tip)}">{release}</td>\n'
        f'      <td data-tooltip="{e(dep_changes_tip)}">{dep_changes_cell}</td>\n'
        f"    </tr>"
    )


def _render_automation_sections(
    categories: list[tuple[str, list[RepoEntry]]],
    snapshot: RepoSnapshot,
) -> str:
    signal_labels = snapshot.workflow_signal_labels
    org_name = snapshot.org_name
    parts: list[str] = []
    for category, cat_repos in categories:
        rows = "\n".join(
            _automation_row(r, org_name, signal_labels) for r in cat_repos
        )
        signal_headers = "".join(
            f'      <th data-sort="signal-{i}" class="text-center" title="Whether this repository matches the {e(label)} workflow signal.">'
            f'{e(label)} <span class="sort-arrow"></span></th>\n'
            for i, label in enumerate(signal_labels)
        )
        parts.append(
            f'<div class="section hidden" data-tab="tech-stack" data-category="{e(category)}">\n'
            f'  <div class="section-header">\n'
            f'    <span class="section-title">{e(category)}</span>\n'
            f'    <span class="section-count">{len(cat_repos)}</span>\n'
            f"  </div>\n"
            f"  <table>\n"
            f"    <thead><tr>\n"
            f'      <th data-sort="name">Repository <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="lang">Language <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="bazel" class="text-center" title="Whether this repository uses Bazel as its build system.">Bazel <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="gitlint" class="text-center" title="Whether this repository enforces commit message formatting rules (gitlint).">Gitlint <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="pyproject" class="text-center" title="Whether this repository has a pyproject.toml — the standard configuration file for Python projects.">Pyproject <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="precommit" class="text-center" title="Whether this repository runs automated checks (formatting, linting, etc.) before each commit is accepted.">Pre-commit <span class="sort-arrow"></span></th>\n'
            f'      <th data-sort="ci" class="text-center" title="Whether this repository has automated CI/CD pipelines that run on every push or pull request.">GitHub Actions <span class="sort-arrow"></span></th>\n'
            f"{signal_headers}"
            f'      <th data-sort="coverage" class="text-center" title="Whether this repository measures test coverage — tracking how much of the code is exercised by automated tests.">Coverage <span class="sort-arrow"></span></th>\n'
            f"    </tr></thead>\n"
            f"    <tbody>\n{rows}\n    </tbody>\n"
            f"  </table>\n"
            f"</div>\n"
        )
    return "".join(parts)


def _automation_row(
    entry: RepoEntry, org_name: str, signal_labels: tuple[str, ...]
) -> str:
    name_cell = repo_name_cell(entry, org_name, bazel_icon=False)
    c = entry.content

    def _presence(val: bool, icon: str) -> str:
        if val:
            return f'<span class="badge green">{icon}</span>'
        return '<span class="text-muted">—</span>'

    def _yesno(val: bool) -> str:
        if val:
            return '<span class="badge green">yes</span>'
        return '<span class="text-muted">no</span>'

    tips = {
        "bazel": "This repository uses Bazel as its build system."
        if c.is_bazel_repo
        else "This repository does not use Bazel.",
        "gitlint": "This repository enforces commit message formatting rules (gitlint)."
        if c.has_gitlint_config
        else "This repository has no commit message formatting rules configured.",
        "pyproject": "This repository has a pyproject.toml (standard Python project configuration)."
        if c.has_pyproject_toml
        else "This repository does not have a pyproject.toml.",
        "precommit": "This repository runs automated checks (formatting, linting, etc.) before each commit is accepted."
        if c.has_pre_commit_config
        else "This repository has no automated pre-commit checks configured.",
        "ci": "This repository has automated CI/CD pipelines that run on every push or pull request."
        if c.has_ci
        else "This repository has no automated CI/CD pipelines.",
        "coverage": "This repository measures test coverage — tracking how much of the code is exercised by automated tests."
        if c.has_coverage_config
        else "This repository does not measure test coverage.",
    }

    signal_cells = ""
    for label in signal_labels:
        matched = label in c.matched_workflow_signals
        tip = (
            f"This repository matches the {label} workflow signal."
            if matched
            else f"This repository does not match the {label} workflow signal."
        )
        signal_cells += f'      <td class="text-center" data-tooltip="{e(tip)}">{_yesno(matched)}</td>\n'

    langs = entry.content.top_languages
    lang_cell = (
        " ".join(language_badge(lang) for lang in langs)
        if langs
        else '<span class="text-muted">—</span>'
    )
    lang_tip = ", ".join(langs) if langs else "Language unknown"

    return (
        f"    <tr>\n"
        f"      <td>{name_cell}</td>\n"
        f'      <td data-tooltip="{e(lang_tip)}">{lang_cell}</td>\n'
        f'      <td class="text-center" data-tooltip="{e(tips["bazel"])}">{_presence(c.is_bazel_repo, BAZEL_ICON)}</td>\n'
        f'      <td class="text-center" data-tooltip="{e(tips["gitlint"])}">{_presence(c.has_gitlint_config, "\U0001f50d")}</td>\n'
        f'      <td class="text-center" data-tooltip="{e(tips["pyproject"])}">{_presence(c.has_pyproject_toml, "\U0001f40d")}</td>\n'
        f'      <td class="text-center" data-tooltip="{e(tips["precommit"])}">{_presence(c.has_pre_commit_config, "\U0001fa9d")}</td>\n'
        f'      <td class="text-center" data-tooltip="{e(tips["ci"])}">{_presence(c.has_ci, "⚙️")}</td>\n'
        f"{signal_cells}"
        f'      <td class="text-center" data-tooltip="{e(tips["coverage"])}">{_yesno(c.has_coverage_config)}</td>\n'
        f"    </tr>"
    )


def _trace_progress_cell(count: int, total: int) -> str:
    pct = (count / total * 100) if total > 0 else 0.0
    color = "var(--green)" if pct >= 80 else ("var(--yellow)" if pct >= 40 else "var(--red)")
    return (
        f'{count} <span class="text-muted">({pct:.0f}%)</span>'
        f'<div class="trace-bar"><div class="trace-bar-fill" '
        f'style="width:{pct:.1f}%;background:{color}"></div></div>'
    )


def _format_type_name(key: str) -> str:
    return key.replace("_", " ").title()


def _render_traceability_section(
    repos: list[RepoEntry],
    snapshot: RepoSnapshot,
) -> str:
    org_name = snapshot.org_name
    dep_repos = [r for r in repos if _is_tracked_dep_repo(r, snapshot.tracked_deps)]
    if not dep_repos:
        return ""

    total_reqs = 0
    total_code_linked = 0
    total_test_linked = 0
    total_fully_linked = 0
    loaded_count = 0

    row_parts: list[str] = []
    for r in dep_repos:
        name_cell = repo_name_cell(r, org_name, bazel_icon=False)
        if not r.traceability:
            row_parts.append(
                f'    <tr data-repo="{e(r.name)}">'
                f"<td>{name_cell}</td>"
                f'<td class="text-right" colspan="6">'
                f'<span class="text-muted">— not available</span></td>'
                f"</tr>"
            )
            continue

        loaded_count += 1
        types = r.traceability
        for ti, tm in enumerate(types):
            total_reqs += tm.req_total
            total_code_linked += tm.req_with_code_link
            total_test_linked += tm.req_with_test_link
            total_fully_linked += tm.req_fully_linked

            tests_linked_pct = (
                f"{tm.tests_linked / tm.tests_total * 100:.0f}"
                if tm.tests_total > 0
                else "0"
            )

            cells = (
                f"<td>{e(_format_type_name(tm.type_name))}</td>"
                f'<td class="text-right" data-sort-value="{tm.req_total}">{tm.req_total}</td>'
                f'<td class="text-right" data-sort-value="{tm.req_with_code_link}">'
                f"{_trace_progress_cell(tm.req_with_code_link, tm.req_total)}</td>"
                f'<td class="text-right" data-sort-value="{tm.req_with_test_link}">'
                f"{_trace_progress_cell(tm.req_with_test_link, tm.req_total)}</td>"
                f'<td class="text-right" data-sort-value="{tm.req_fully_linked}">'
                f"{_trace_progress_cell(tm.req_fully_linked, tm.req_total)}</td>"
                f'<td class="text-right" data-sort-value="{tm.tests_total}">'
                f'{tm.tests_total} <span class="text-muted">({tests_linked_pct}% linked)</span></td>'
            )

            if ti == 0:
                rowspan = f' rowspan="{len(types)}"' if len(types) > 1 else ""
                row_parts.append(
                    f'    <tr data-repo="{e(r.name)}">'
                    f"<td{rowspan}>{name_cell}</td>{cells}</tr>"
                )
            else:
                row_parts.append(f"    <tr data-repo=\"{e(r.name)}\">{cells}</tr>")

    rows = "\n".join(row_parts)

    code_cov = f"{total_code_linked / total_reqs * 100:.0f}%" if total_reqs > 0 else "—"
    test_cov = f"{total_test_linked / total_reqs * 100:.0f}%" if total_reqs > 0 else "—"
    fully_cov = f"{total_fully_linked / total_reqs * 100:.0f}%" if total_reqs > 0 else "—"

    return (
        f'<div class="section hidden" data-tab="traceability">\n'
        f'  <div class="section-header">\n'
        f'    <span class="section-title">Requirement Traceability</span>\n'
        f'    <span class="section-count">{len(dep_repos)}</span>\n'
        f"  </div>\n"
        f'  <div id="trace-summary">\n'
        f'    <div class="stat-grid">\n'
        f'      <div class="stat-card"><div class="stat-value">{loaded_count} / {len(dep_repos)}</div><div class="stat-label">Repos Reporting</div></div>\n'
        f'      <div class="stat-card"><div class="stat-value">{total_reqs}</div><div class="stat-label">Total Requirements</div></div>\n'
        f'      <div class="stat-card"><div class="stat-value">{code_cov}</div><div class="stat-label">Code Link Coverage</div></div>\n'
        f'      <div class="stat-card"><div class="stat-value">{test_cov}</div><div class="stat-label">Test Link Coverage</div></div>\n'
        f'      <div class="stat-card"><div class="stat-value">{fully_cov}</div><div class="stat-label">Fully Linked</div></div>\n'
        f"    </div>\n"
        f"  </div>\n"
        f"  <table>\n"
        f"    <thead><tr>\n"
        f'      <th data-sort="name">Repository <span class="sort-arrow"></span></th>\n'
        f'      <th>Type</th>\n'
        f'      <th data-sort="req-total" class="text-right">Requirements <span class="sort-arrow"></span></th>\n'
        f'      <th data-sort="code-link" class="text-right">Code Links <span class="sort-arrow"></span></th>\n'
        f'      <th data-sort="test-link" class="text-right">Test Links <span class="sort-arrow"></span></th>\n'
        f'      <th data-sort="fully-linked" class="text-right">Fully Linked <span class="sort-arrow"></span></th>\n'
        f'      <th data-sort="tests" class="text-right">Tests <span class="sort-arrow"></span></th>\n'
        f"    </tr></thead>\n"
        f"    <tbody>\n{rows}\n    </tbody>\n"
        f"  </table>\n"
        f"</div>\n"
    )


def _render_footer(snapshot: RepoSnapshot) -> str:
    return (
        f"\n<footer>\n"
        f"  Cross-repo metrics for <strong>{e(snapshot.org_name)}</strong> "
        f"— generated {e(snapshot.generated_at)}\n"
        f'  <div class="machine-readable">'
        f'<a href="data.json">Machine-readable JSON</a>'
        f" — format is unstable and may change without notice"
        f"</div>\n"
        f"</footer>\n\n"
    )


def _render_script(
    categories: list[tuple[str, list[RepoEntry]]],
) -> str:
    cat_names = json.dumps(["all"] + [c for c, _ in categories])
    return (
        f"<script>\nconst categories = {cat_names};\n"
        f"</script>\n"
        f"<script>\n{_INDEX_JS}</script>\n"
    )
