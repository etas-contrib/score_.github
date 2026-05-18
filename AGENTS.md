# AGENTS.md

Context file for AI coding assistants. See `docs/repo-overview-tool-design.md` for architecture, data model, and caching details.

## Quick reference

```sh
uv sync --all-groups --frozen                   # install deps
uv run generate-repo-overview collect --org-config org_config.toml  # GitHub API → snapshot JSON
uv run generate-repo-overview render-overview   # snapshot → profile/README.md
uv run generate-repo-overview render-details    # snapshot → _site/ (index + per-repo pages)
uv run pytest                                   # run tests
uv run ruff check src/ tests/                   # lint
uv run basedpyright src/                        # type check
```

## Key files for website work

```
org_config.toml                        — organization-specific settings (org name, tracked deps, workflow signals)
src/generate_repo_overview/
  org_config.py       — loads and validates org_config.toml
  metrics_html.py     — HTML renderer (index + per-repo detail pages)
  metrics_report.py   — shared helpers: grouping, version comparison, badges
  models.py           — RepoEntry, RepoSnapshot, TrackedDep, WorkflowSignal dataclasses
  cli.py              — render-details writes all pages from render_all_pages()
  constants.py        — default paths (DEFAULT_METRICS_HTML_OUTPUT = _site/)
tests/
  test_cli_render.py  — render output tests
  test_org_config.py  — org config loading/validation tests
  test_repo_overview.py — collector and snapshot round-trip tests
```

## Website rendering notes

- No static site generator or template engine — pure Python string concatenation.
- CSS is inlined per page via the `CSS` constant in `_html_common.py`. Dark theme using CSS variables.
- `render_all_pages(snapshot)` returns `dict[str, str]` of relative path to HTML content.
- Index page: tabs, filters, sortable columns — all client-side JS in `_render_script()`.
- Detail pages (`<repo>/index.html`): static HTML, no JS.
- Repo name links on the index go to detail pages; GitHub links use a separate icon.
