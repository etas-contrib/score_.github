from __future__ import annotations

from typing import TYPE_CHECKING

from ._html_common import BAZEL_ICON, CSS, GITHUB_ICON, e, language_badge, version_badge
from .metrics_report import tracked_dep_label

if TYPE_CHECKING:
    from .models import RepoEntry, RepoSnapshot


def render_detail_page(
    entry: RepoEntry,
    snapshot: RepoSnapshot,
    max_bazel: tuple[int, ...] | None,
    latest_dep_versions: dict[str, str | None],
) -> str:
    org_name = snapshot.org_name
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '  <meta charset="UTF-8">\n'
        '  <meta name="viewport" content="width=device-width, initial-scale=1.0">\n'
        f"  <title>{e(entry.name)} — {e(org_name)}</title>\n"
        f"  <style>{CSS}</style>\n"
        "</head>\n<body>\n"
        + _render_hero(entry, org_name)
        + _render_stat_grid(entry)
        + _render_release_section(entry)
        + _render_dep_diff_section(entry)
        + _render_tooling_section(entry, snapshot)
        + _render_ownership_section(entry)
        + _render_versions_section(entry, snapshot, max_bazel, latest_dep_versions)
        + _render_footer(snapshot)
        + "</body>\n</html>\n"
    )


def _render_hero(entry: RepoEntry, org_name: str) -> str:
    github_url = f"https://github.com/{org_name}/{entry.name}"
    name_html = e(entry.name)
    if entry.content.is_bazel_repo:
        name_html += f" {BAZEL_ICON}"

    chips = f'<span class="badge muted">{e(entry.category)}</span>'
    if entry.subcategory and entry.subcategory != entry.category:
        chips += f' <span class="badge muted">{e(entry.subcategory)}</span>'
    for lang in entry.content.top_languages:
        chips += f" {language_badge(lang)}"

    desc = e(entry.description) if entry.description else ""

    return (
        "<header>\n"
        '  <nav class="breadcrumb">\n'
        '    <a href="../">Cross-Repo Metrics</a> &rsaquo; '
        f"{e(entry.name)}\n"
        "  </nav>\n"
        f"  <h1>{name_html}"
        f' <a href="{e(github_url)}" class="gh-link" title="Open on GitHub ↗"'
        f' target="_blank" rel="noopener">{GITHUB_ICON}</a>'
        f"</h1>\n"
        f'  <p class="subtitle">{desc}</p>\n'
        f'  <div class="meta-chips">{chips}</div>\n'
        "</header>\n\n"
    )


def _render_stat_grid(entry: RepoEntry) -> str:
    v = entry.volatile
    last_push = e(v.last_push_date) if v.last_push_date else "—"
    prs_text = f"{v.open_ready_prs}+{v.open_draft_prs}"

    cards = [
        (str(entry.stars), "Stars"),
        (str(entry.forks), "Forks"),
        (str(v.open_issues), "Open Issues"),
        (prs_text, "Open PRs (ready+draft)"),
        (str(v.merged_prs_30_days), "Merged PRs (30d)"),
        (last_push, "Last Push"),
    ]

    items = "\n".join(
        f'  <div class="stat-card">'
        f'<div class="stat-value">{e(val)}</div>'
        f'<div class="stat-label">{label}</div>'
        f"</div>"
        for val, label in cards
    )
    return f'<div class="stat-grid">\n{items}\n</div>\n\n'


def _render_release_section(entry: RepoEntry) -> str:
    v = entry.volatile
    if v.latest_release_version is None and v.latest_release_date is None:
        version_html = '<span class="text-muted">No releases</span>'
        return (
            '<section class="detail-section">\n'
            '  <div class="section-header"><span class="section-title">Release</span></div>\n'
            f'  <div class="detail-body">{version_html}</div>\n'
            "</section>\n\n"
        )

    items: list[str] = []
    if v.latest_release_version:
        items.append(
            f'<div class="info-item">'
            f'<div class="info-label">Latest Version</div>'
            f'<span class="mono">{e(v.latest_release_version)}</span>'
            f"</div>"
        )
    if v.latest_release_date:
        items.append(
            f'<div class="info-item">'
            f'<div class="info-label">Release Date</div>'
            f"{e(v.latest_release_date)}"
            f"</div>"
        )
    if v.commits_since_latest_release is not None:
        count = v.commits_since_latest_release
        badge_class = (
            "green" if count == 0 else ("yellow" if count <= 20 else "red")
        )
        items.append(
            f'<div class="info-item">'
            f'<div class="info-label">Commits Since Release</div>'
            f'<span class="badge {badge_class}">{count}</span>'
            f"</div>"
        )

    return (
        '<section class="detail-section">\n'
        '  <div class="section-header"><span class="section-title">Release</span></div>\n'
        f'  <div class="detail-body"><div class="info-grid">{"".join(items)}</div></div>\n'
        "</section>\n\n"
    )


def _render_dep_diff_section(entry: RepoEntry) -> str:
    v = entry.volatile
    if v.latest_release_version is None:
        return ""

    head_deps = dict(entry.content.bazel_deps)
    release_deps = dict(v.release_bazel_deps)

    all_names = sorted(set(head_deps) | set(release_deps))

    head_bazel = entry.content.bazel_version
    release_bazel = v.release_bazel_version

    rows: list[str] = []

    bazel_status, bazel_class = _dep_diff_status(head_bazel, release_bazel)
    rows.append(
        f"      <tr>\n"
        f"        <td><span class='mono'>Bazel</span></td>\n"
        f"        <td><span class='mono'>{e(head_bazel) if head_bazel else '<span class=\"text-muted\">—</span>'}</span></td>\n"
        f"        <td><span class='mono'>{e(release_bazel) if release_bazel else '<span class=\"text-muted\">—</span>'}</span></td>\n"
        f"        <td>{_dep_status_badge(bazel_status, bazel_class)}</td>\n"
        f"      </tr>"
    )

    for name in all_names:
        head_ver = head_deps.get(name)
        rel_ver = release_deps.get(name)
        status, css_class = _dep_diff_status(head_ver, rel_ver)
        rows.append(
            f"      <tr>\n"
            f"        <td><span class='mono'>{e(name)}</span></td>\n"
            f"        <td><span class='mono'>{e(head_ver) if head_ver else '<span class=\"text-muted\">—</span>'}</span></td>\n"
            f"        <td><span class='mono'>{e(rel_ver) if rel_ver else '<span class=\"text-muted\">—</span>'}</span></td>\n"
            f"        <td>{_dep_status_badge(status, css_class)}</td>\n"
            f"      </tr>"
        )

    changed_count = sum(
        1
        for r in rows
        if "badge yellow" in r or "badge green" in r or "badge red" in r
    )

    if changed_count == 0 and v.commits_since_latest_release:
        summary = (
            f'<p class="text-muted" style="margin:0 0 0.5rem">No dependency changes since '
            f"{e(v.latest_release_version)}.</p>"
        )
    else:
        summary = ""

    release_label = e(v.latest_release_version)
    table = (
        f"  <table>\n"
        f"    <thead><tr>\n"
        f"      <th>Dependency</th>\n"
        f"      <th>HEAD</th>\n"
        f"      <th>Release ({release_label})</th>\n"
        f"      <th>Status</th>\n"
        f"    </tr></thead>\n"
        f"    <tbody>\n"
        + "\n".join(rows)
        + "\n    </tbody>\n  </table>"
    )

    return (
        '<section class="detail-section">\n'
        '  <div class="section-header">'
        '<span class="section-title">Dependencies: HEAD vs. Release</span>'
        "</div>\n"
        f"  <div class=\"detail-body\">{summary}{table}</div>\n"
        "</section>\n\n"
    )


def _dep_diff_status(
    head: str | None, release: str | None
) -> tuple[str, str]:
    if head is None and release is None:
        return "—", "muted"
    if release is None:
        return "added", "green"
    if head is None:
        return "removed", "red"
    if head == release:
        return "—", "muted"
    return "changed", "yellow"


def _dep_status_badge(status: str, css_class: str) -> str:
    if status == "—":
        return '<span class="text-muted">—</span>'
    return f'<span class="badge {css_class}">{e(status)}</span>'


def _render_tooling_section(entry: RepoEntry, snapshot: RepoSnapshot) -> str:
    c = entry.content
    signals: list[tuple[bool, str]] = [
        (c.has_ci, "GitHub Actions (CI)"),
    ]
    for label in snapshot.workflow_signal_labels:
        signals.append((label in c.matched_workflow_signals, label))
    signals.extend([
        (c.has_lint_config, "Lint Config"),
        (c.has_gitlint_config, "Gitlint"),
        (c.has_pre_commit_config, "Pre-commit"),
        (c.has_pyproject_toml, "pyproject.toml"),
        (c.has_coverage_config, "Coverage Config"),
        (c.is_bazel_repo, "Bazel Repo"),
    ])

    items = "\n".join(
        f'    <div class="signal-item">'
        f'<span class="signal-{"yes" if val else "no"}">'
        f'{"&#10003;" if val else "—"}</span> {e(label)}</div>'
        for val, label in signals
    )
    return (
        '<section class="detail-section">\n'
        '  <div class="section-header"><span class="section-title">Build &amp; Tooling</span></div>\n'
        f'  <div class="detail-body"><div class="signal-grid">\n{items}\n  </div></div>\n'
        "</section>\n\n"
    )


def _render_ownership_section(entry: RepoEntry) -> str:
    parts: list[str] = []
    if entry.content.codeowners:
        handles = ", ".join(e(h) for h in entry.content.codeowners)
        parts.append(
            f'<div class="info-item">'
            f'<div class="info-label">Codeowners</div>{handles}</div>'
        )
    if entry.registry.maintainers_in_bazel_registry:
        handles = ", ".join(
            e(h) for h in entry.registry.maintainers_in_bazel_registry
        )
        parts.append(
            f'<div class="info-item">'
            f'<div class="info-label">Registry Maintainers</div>{handles}</div>'
        )

    if not parts:
        parts.append('<span class="text-muted">No ownership information available</span>')

    return (
        '<section class="detail-section">\n'
        '  <div class="section-header"><span class="section-title">Ownership</span></div>\n'
        f'  <div class="detail-body"><div class="info-grid">{"".join(parts)}</div></div>\n'
        "</section>\n\n"
    )


def _render_versions_section(
    entry: RepoEntry,
    snapshot: RepoSnapshot,
    max_bazel: tuple[int, ...] | None,
    latest_dep_versions: dict[str, str | None],
) -> str:
    from .models import lookup_bazel_dep_version

    items: list[str] = []

    bazel_badge = version_badge(
        entry.content.bazel_version, max_bazel, latest_dep_version=None, is_bazel=True
    )
    items.append(
        f'<div class="info-item">'
        f'<div class="info-label">Bazel Version</div>{bazel_badge}</div>'
    )

    for dep in snapshot.tracked_deps:
        dep_label = tracked_dep_label(dep)
        dep_ver = lookup_bazel_dep_version(entry.content.bazel_deps, dep.module_name)
        latest_ver = latest_dep_versions.get(dep.module_name)
        badge = version_badge(dep_ver, None, latest_dep_version=latest_ver, is_bazel=False)
        items.append(
            f'<div class="info-item">'
            f'<div class="info-label">{e(dep_label)} Version</div>{badge}</div>'
        )

    refint = (
        '<span class="badge green">yes</span>'
        if entry.content.referenced_by_reference_integration
        else '<span class="text-muted">no</span>'
    )
    items.append(
        f'<div class="info-item">'
        f'<div class="info-label">Reference Integration</div>{refint}</div>'
    )

    if entry.registry.latest_bazel_registry_version:
        items.append(
            f'<div class="info-item">'
            f'<div class="info-label">Latest Registry Version</div>'
            f'<span class="mono">{e(entry.registry.latest_bazel_registry_version)}</span>'
            f"</div>"
        )

    return (
        '<section class="detail-section">\n'
        '  <div class="section-header"><span class="section-title">Versions</span></div>\n'
        f'  <div class="detail-body"><div class="info-grid">{"".join(items)}</div></div>\n'
        "</section>\n\n"
    )


def _render_footer(snapshot: RepoSnapshot) -> str:
    return (
        "\n<footer>\n"
        f'  <a href="../">&larr; Back to overview</a>'
        f" — generated {e(snapshot.generated_at)}\n"
        "</footer>\n\n"
    )
