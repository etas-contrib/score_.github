from __future__ import annotations

import argparse
from pathlib import Path
from textwrap import dedent
from typing import TYPE_CHECKING

from .collector import collect_snapshot, load_snapshot
from .console import print_status
from .constants import (
    DEFAULT_CACHE,
    DEFAULT_METRICS_HTML_OUTPUT,
    DEFAULT_OUTPUT,
    DEFAULT_TOKEN_ENV,
)
from .metrics_html import render_all_pages
from .org_config import load_org_config
from .profile_readme import load_config, load_template, render_readme

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .models import RepoSnapshot


CLI_EPILOG = dedent(
    f"""\
    Quick start:
      uv run generate-repo-overview collect --org-config org_config.toml
          Sync the cached snapshot from GitHub.

      uv run generate-repo-overview render-overview
          Re-render the profile README from the local cache.

      uv run generate-repo-overview render-details
          Re-render the HTML metrics page from the local cache.

    Defaults:
      Cache:   {DEFAULT_CACHE}
      README:  {DEFAULT_OUTPUT}

    Use `uv run generate-repo-overview <command> --help` for command-specific options.
    """
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Collect cached GitHub organization repository overviews and render "
            "different views from the same snapshot."
        ),
        epilog=CLI_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(
        dest="command",
        metavar="command",
    )

    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect and write the cached repository snapshot.",
    )
    collect_parser.add_argument(
        "--org-config",
        type=Path,
        required=True,
        help="Path to an org_config.toml file with organization-specific settings",
    )
    collect_parser.add_argument(
        "--cache", type=Path, default=DEFAULT_CACHE, help="JSON snapshot cache file"
    )
    collect_parser.add_argument(
        "--token-env",
        default=DEFAULT_TOKEN_ENV,
        help="Environment variable that contains the GitHub token",
    )
    collect_parser.add_argument(
        "--deep",
        action="store_true",
        help=(
            "Force a deep refresh for every repository. "
            "By default, unchanged repositories reuse cached detailed signals."
        ),
    )

    overview_parser = subparsers.add_parser(
        "render-overview",
        help="Render the profile README from a cached snapshot.",
    )
    overview_parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_CACHE,
        help="JSON snapshot file to render from",
    )
    overview_parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT, help="Markdown file to write"
    )
    overview_parser.add_argument(
        "--template",
        type=Path,
        help="Optional markdown template file with a {{ repo_sections }} placeholder",
    )
    overview_parser.add_argument(
        "--config",
        type=Path,
        help="Optional category config file that defines order and descriptions",
    )

    details_parser = subparsers.add_parser(
        "render-details",
        help="Render the HTML metrics page from a cached snapshot.",
    )
    details_parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_CACHE,
        help="JSON snapshot file to render from",
    )
    details_parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_METRICS_HTML_OUTPUT,
        help="Output directory for HTML pages",
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command

    if command is None:
        parser.print_help()
        return 0

    if command == "collect":
        return run_collect(args)
    if command == "render-overview":
        return run_render_overview(args)
    if command == "render-details":
        return run_render_details(args)
    raise ValueError(f"Unsupported command {command!r}.")


def run_collect(args: argparse.Namespace) -> int:
    try:
        config = load_org_config(args.org_config)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    collect_snapshot(
        config=config,
        token_env=args.token_env,
        cache_path=args.cache,
        reuse_unchanged_repositories=not args.deep,
        status_prefix="repo-overview",
    )
    return 0


def run_render_overview(args: argparse.Namespace) -> int:
    snapshot = load_snapshot(args.input)
    markdown = render_profile_readme(
        snapshot,
        template_path=args.template,
        config_path=args.config,
    )
    write_text_file(path=args.output, content=markdown, status_prefix="repo-overview")
    return 0


def run_render_details(args: argparse.Namespace) -> int:
    snapshot = load_snapshot(args.input)
    pages = render_all_pages(snapshot)
    output_dir: Path = args.output
    for relative_path, content in pages.items():
        write_text_file(
            path=output_dir / relative_path,
            content=content,
            status_prefix="repo-overview",
        )
    return 0


def render_profile_readme(
    snapshot: RepoSnapshot,
    *,
    template_path: Path | None,
    config_path: Path | None,
) -> str:
    template = load_template(template_path)
    config = load_config(config_path)
    return render_readme(
        list(snapshot.repos),
        template=template,
        config=config,
        org_name=snapshot.org_name,
    )


def write_text_file(*, path: Path, content: str, status_prefix: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print_status(f"Wrote {path}", prefix=status_prefix)
