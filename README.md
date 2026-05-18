# eclipse-score .github repository

This repository hosts the start page when you visit the eclipse-score GitHub organization. It contains links to the Eclipse Score website, documentation, and other resources related to the Eclipse Score project.

The Python tool in this repo now acts as a small repo-overview generator: it collects a cached snapshot of organization metadata once, then renders multiple Markdown views from that shared snapshot.

## Development

Use `uv` to create a virtual environment and install the project dependencies:

```
uv sync --all-groups
```

The CLI now has a built-in overview:

```sh
uv run generate-repo-overview
```

For a cache-only re-render of the profile README and the HTML dashboard:

```sh
uv run generate-repo-overview render-overview
uv run generate-repo-overview render-details
```

For a fresh GitHub pull before rendering, run:

```sh
uv run generate-repo-overview collect --org-config org_config.toml
```

By default, `collect` now does a cache-aware refresh: it checks fast, high-level
repository state and reuses cached deep details for repositories whose default
branch SHA has not changed. Use this for regular updates.

For volatile repository metrics (open PRs/issues, release counters, and recent
activity), fast mode keeps a per-repository fetch timestamp and refreshes those
values automatically when they are older than 1 hour.

You can tune this freshness window with `REPO_OVERVIEW_VOLATILE_TTL_MINUTES`
(default: `60`).

If you need a full deep refresh for every repository, run:

```sh
uv run generate-repo-overview collect --deep
```

If you only want the profile README:

```sh
uv run generate-repo-overview render-overview
```

Category order and category descriptions are configured in
`src/generate_repo_overview/profile_readme_config.toml`. Pass
`--config /path/to/file.toml` to use a different config file.

The generator reads repository custom properties from GitHub and expects `GITHUB_TOKEN` to be set. If `GITHUB_TOKEN` is not set, it falls back to `gh auth token`.

Architecture notes for the package live in [src/generate_repo_overview/README.md](src/generate_repo_overview/README.md). The broader design notes are in [docs/repo-overview-tool-design.md](docs/repo-overview-tool-design.md).

To run the local checks:

```sh
uv run pre-commit run --all-files
```
