# Repo Overview Tool Design

## Goals

- Collect GitHub organization data once and reuse it across multiple reports.
- Keep local iteration fast by rendering from a cached snapshot instead of re-querying GitHub on every run.
- Separate GitHub collection, content enrichment, and rendering so new views are easy to add.
- Extend the profile README workflow with cross-repo metrics — Markdown, HTML dashboard, and GitHub Pages deployment — using a shared snapshot.

## Architecture

The tool is split into three layers:

1. `org_config.py`
   - Loads organization-specific settings from `org_config.toml`: org name, repo include patterns, tracked Bazel deps, workflow signals, reference integration repo, and registry repo.
2. `collector/`
   - Connects to GitHub.
   - Loads active repositories and custom properties.
   - Derives content-based signals such as `has_ci`, `has_lint_config`, `has_coverage_config`, `bazel_version`, `matched_workflow_signals`, `bazel_deps`, and `referenced_by_reference_integration`.
   - Writes and reads a local JSON snapshot cache.
3. `profile_readme.py`, `metrics_report.py`, `metrics_html.py` (with `_html_index.py`, `_html_detail.py`, `_html_common.py`)
   - Render different views (Markdown and HTML) from the same normalized data model.
   - Keep presentation decisions out of the collection layer.
4. `cli.py`
   - Orchestrates cache-aware commands: `collect`, `render-overview`, and `render-details`.

## Data Model

The shared model lives in `models.py`.

- `RepoEntry` contains both grouping metadata and overview metrics.
- `RepoSnapshot` stores:
  - schema version
  - organization name
  - generation timestamp
  - normalized repositories
  - tracked Bazel dependency definitions (`tracked_deps`)
  - workflow signal labels (`workflow_signal_labels`)

The snapshot is intentionally renderer-agnostic. It stores neutral values such as booleans and plain strings rather than Markdown-specific markers.

## Caching Strategy

The default cache file is `profile/cache/repo_overview.json`.

The cache is used in two ways:

- Render commands read the snapshot directly and never contact GitHub.
- Collection commands reuse content-derived signals for repositories whose default-branch SHA has not changed.

That means changing a template or report layout is a local-only operation, and refreshing the snapshot only re-fetches file-tree data for repositories whose content likely changed.

## Why The Tool Uses The GitHub API Instead Of Cloning Repositories

The current report set mainly needs:

- repository metadata
- custom properties
- release dates
- open pull request counts
- file-presence checks
- a few small file contents such as `.bazelversion`
- cloned shared metadata repositories such as `bazel_registry` and `reference_integration`

For those needs, API access is cheaper and simpler than cloning every repository.

The collector uses:

- repository metadata from the organization API
- repository trees to detect whether files or directories exist
- targeted file-content reads only when a detector needs a small file

Cloning remains a future option if the project later needs heavyweight analysis such as line counting, local static analysis, or parsing large groups of files.

## Command Surface

The generic entry point is:

```sh
uv run generate-repo-overview <command>
```

Built-in commands:

- `collect --org-config org_config.toml`
  - Sync the cached snapshot from GitHub and write it to disk.
  - Requires `--org-config` pointing to a TOML file with organization-specific settings.
  - Use `--deep` to force a full refresh for every repository instead of reusing cached signals for unchanged ones.
- `render-overview`
  - Render the profile README from an existing snapshot.
- `render-details`
  - Render the HTML metrics page from an existing snapshot.

The `collect` command always performs a sync. The render commands never contact GitHub.

## Extension Points

To add a new view:

1. Extend `RepoEntry` only if the new view needs new normalized data.
2. Add or update detectors in `collector/` if new collection logic is required.
3. Create a new renderer that accepts `RepoSnapshot` or `list[RepoEntry]`.
4. Add a CLI command that reads the cached snapshot and calls the renderer.

To add a new detector, prefer:

- tree-based file existence checks for simple presence signals
- targeted small-file reads for version or config parsing

Avoid coupling detectors directly to output format. The collector should produce plain data; the renderer should decide how that data is displayed.
