from __future__ import annotations

import html
from pathlib import Path
from typing import TYPE_CHECKING

from .metrics_report import parse_version_key

if TYPE_CHECKING:
    from .models import RepoEntry

_TEMPLATES = Path(__file__).parent / "templates"

CSS = (_TEMPLATES / "styles.css").read_text(encoding="utf-8")

BAZEL_ICON = (
    '<img src="https://bazel.build/_pwa/bazel/icons/icon-72x72.png"'
    ' alt="Bazel" class="icon-bazel">'
)

GITHUB_ICON = (
    '<svg viewBox="0 0 16 16" fill="currentColor">'
    '<path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17'
    ".55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94"
    "-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87"
    " 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59"
    ".82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27"
    ".68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51"
    '.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07'
    '-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0016 8c0-4.42-3.58-8-8-8z"/>'
    "</svg>"
)


_LANGUAGE_COLORS: dict[str, str] = {
    "Python": "#3572A5",
    "C++": "#f34b7d",
    "C": "#555555",
    "Go": "#00ADD8",
    "Rust": "#dea584",
    "Java": "#b07219",
    "Kotlin": "#A97BFF",
    "TypeScript": "#3178c6",
    "JavaScript": "#f1e05a",
    "Starlark": "#76d275",
    "Shell": "#89e051",
    "CMake": "#DA3434",
    "Makefile": "#427819",
}


def e(text: str) -> str:
    return html.escape(text, quote=True)


def language_badge(lang: str | None) -> str:
    if not lang:
        return '<span class="text-muted">—</span>'
    color = _LANGUAGE_COLORS.get(lang, "#888888")
    return (
        f'<span class="lang-badge" style="--lang-color:{color}">'
        f"{e(lang)}</span>"
    )


def repo_name_cell(entry: RepoEntry, org_name: str, *, bazel_icon: bool = True) -> str:
    detail_url = f"{e(entry.name)}/"
    github_url = f"https://github.com/{org_name}/{entry.name}"
    title_attr = f' title="{e(entry.description)}"' if entry.description else ""
    cell = f'<a href="{detail_url}"{title_attr}>{e(entry.name)}</a>'
    if bazel_icon and entry.content.is_bazel_repo:
        cell += f" {BAZEL_ICON}"
    cell += (
        f' <a href="{e(github_url)}" class="gh-link" title="Open on GitHub ↗"'
        f' target="_blank" rel="noopener">{GITHUB_ICON}</a>'
    )
    return cell


def version_badge(
    version: str | None,
    max_bazel: tuple[int, ...] | None,
    *,
    latest_dep_version: str | None,
    is_bazel: bool,
) -> str:
    """Render a colored version badge span.

    Bazel versions are green when equal to *max_bazel*, red otherwise.
    Dep versions compare against *latest_dep_version*: green if equal,
    yellow if same major.minor, red if older, muted if unknown.
    """
    if version is None or not version.strip():
        return '<span class="badge muted">—</span>'

    cleaned = version.strip()
    parsed = parse_version_key(cleaned)

    if is_bazel:
        if parsed is not None and max_bazel is not None and parsed == max_bazel:
            return f'<span class="badge green">{e(cleaned)}</span>'
        return f'<span class="badge red">{e(cleaned)}</span>'

    if latest_dep_version is None:
        return f'<span class="badge muted">{e(cleaned)}</span>'
    latest_cleaned = latest_dep_version.strip()
    if cleaned == latest_cleaned:
        return f'<span class="badge green">{e(cleaned)}</span>'
    if parsed is not None:
        latest_parsed = parse_version_key(latest_cleaned)
        if (
            latest_parsed is not None
            and len(parsed) >= 2
            and len(latest_parsed) >= 2
            and parsed[:2] == latest_parsed[:2]
        ):
            return f'<span class="badge yellow">{e(cleaned)}</span>'
    return f'<span class="badge red">{e(cleaned)}</span>'
