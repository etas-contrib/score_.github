from __future__ import annotations

import json
from typing import TYPE_CHECKING

from ._html_detail import render_detail_page
from ._html_index import render_index_page
from .metrics_report import get_latest_tracked_dep_version, get_max_bazel_version

if TYPE_CHECKING:
    from .models import RepoSnapshot


def render_all_pages(snapshot: RepoSnapshot) -> dict[str, str]:
    repos = sorted(snapshot.repos, key=lambda r: r.name.casefold())
    max_bazel = get_max_bazel_version(list(repos))
    latest_dep_versions = {
        dep.module_name: get_latest_tracked_dep_version(list(repos), dep)
        for dep in snapshot.tracked_deps
    }

    pages: dict[str, str] = {
        "index.html": render_index_page(snapshot),
        "data.json": json.dumps(snapshot.to_dict(), indent=2, sort_keys=True) + "\n",
    }
    for entry in repos:
        pages[f"{entry.name}/index.html"] = render_detail_page(
            entry, snapshot, max_bazel, latest_dep_versions
        )
    return pages
