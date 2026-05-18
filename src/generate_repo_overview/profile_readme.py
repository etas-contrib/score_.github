from __future__ import annotations

import tomllib
from collections import defaultdict
from dataclasses import dataclass
from importlib.resources import files
from typing import TYPE_CHECKING, cast

from ._text_utils import escape_markdown_table_cell
from .models import (
    DEFAULT_SUBCATEGORY,
    CategoryConfig,
    ReadmeConfig,
    RepoEntry,
    SubcategoryConfig,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

GroupedRepos = dict[str, dict[str, list[RepoEntry]]]


@dataclass(frozen=True, slots=True)
class ConfigIndex:
    category_positions: dict[str, int]
    category_names: dict[str, str]
    category_descriptions: dict[str, str]
    subcategory_names: dict[str, dict[str, str]]
    subcategory_descriptions: dict[str, dict[str, str]]

    @classmethod
    def from_config(cls, config: ReadmeConfig | None) -> ConfigIndex:
        if config is None:
            return cls(
                category_positions={},
                category_names={},
                category_descriptions={},
                subcategory_names={},
                subcategory_descriptions={},
            )

        category_positions: dict[str, int] = {}
        category_names: dict[str, str] = {}
        category_descriptions: dict[str, str] = {}
        subcategory_names: dict[str, dict[str, str]] = {}
        subcategory_descriptions: dict[str, dict[str, str]] = {}

        for index, category in enumerate(config.categories):
            category_key = category.name.casefold()
            category_positions[category_key] = index
            category_names[category_key] = category.name
            category_descriptions[category_key] = category.description
            subcategory_names[category_key] = {
                subcategory.name.casefold(): subcategory.name
                for subcategory in category.subcategories
            }
            subcategory_descriptions[category_key] = {
                subcategory.name.casefold(): subcategory.description
                for subcategory in category.subcategories
            }

        return cls(
            category_positions=category_positions,
            category_names=category_names,
            category_descriptions=category_descriptions,
            subcategory_names=subcategory_names,
            subcategory_descriptions=subcategory_descriptions,
        )

    def canonical_category_name(self, category: str) -> str:
        return self.category_names.get(category.casefold(), category)

    def category_description(self, category: str) -> str:
        return self.category_descriptions.get(category.casefold(), "")

    def canonical_subcategory_name(self, category: str, subcategory: str) -> str:
        return self.subcategory_names.get(category.casefold(), {}).get(
            subcategory.casefold(),
            subcategory,
        )

    def subcategory_description(self, category: str, subcategory: str) -> str:
        return self.subcategory_descriptions.get(category.casefold(), {}).get(
            subcategory.casefold(),
            "",
        )


def load_template(template_path: Path | None) -> str:
    if template_path is not None:
        return template_path.read_text(encoding="utf-8")
    return (
        files("generate_repo_overview")
        .joinpath("templates/profile_readme.md")
        .read_text(encoding="utf-8")
    )


def load_config(config_path: Path | None) -> ReadmeConfig:
    config_content = (
        config_path.read_text(encoding="utf-8")
        if config_path is not None
        else files("generate_repo_overview")
        .joinpath("profile_readme_config.toml")
        .read_text(encoding="utf-8")
    )
    config_source = describe_config_source(config_path)
    raw_config = cast("dict[str, object]", tomllib.loads(config_content))
    raw_categories = raw_config.get("categories", [])
    if not isinstance(raw_categories, list):
        message = (
            f"Invalid config in {config_source}: 'categories' must be a list of tables."
        )
        raise ValueError(message)

    raw_category_entries = cast("list[object]", raw_categories)
    categories = tuple(
        parse_category_config(raw_category, config_source)
        for raw_category in raw_category_entries
    )
    return ReadmeConfig(categories=categories)


def parse_category_config(raw_category: object, config_source: str) -> CategoryConfig:
    if not isinstance(raw_category, dict):
        message = (
            f"Invalid config in {config_source}: each category entry must be a table."
        )
        raise ValueError(message)

    category = cast("Mapping[str, object]", raw_category)

    name = require_non_empty_string(
        category.get("name"),
        config_source=config_source,
        field_name="each category needs a non-empty name",
    )
    description = require_string(
        category.get("description", ""),
        config_source=config_source,
        field_name="category descriptions must be strings",
    ).strip()

    raw_subcategories = category.get("subcategories", [])
    if not isinstance(raw_subcategories, list):
        message = f"Invalid config in {config_source}: category subcategories must be a list of tables."
        raise ValueError(message)

    raw_subcategory_entries = cast("list[object]", raw_subcategories)
    subcategories = tuple(
        parse_subcategory_config(raw_subcategory, config_source)
        for raw_subcategory in raw_subcategory_entries
    )
    return CategoryConfig(
        name=name,
        description=description,
        subcategories=subcategories,
    )


def parse_subcategory_config(
    raw_subcategory: object,
    config_source: str,
) -> SubcategoryConfig:
    if not isinstance(raw_subcategory, dict):
        message = f"Invalid config in {config_source}: each subcategory entry must be a table."
        raise ValueError(message)

    subcategory = cast("Mapping[str, object]", raw_subcategory)

    return SubcategoryConfig(
        name=require_non_empty_string(
            subcategory.get("name"),
            config_source=config_source,
            field_name="each subcategory needs a non-empty name",
        ),
        description=require_string(
            subcategory.get("description", ""),
            config_source=config_source,
            field_name="subcategory descriptions must be strings",
        ).strip(),
    )


def require_non_empty_string(
    value: object,
    *,
    config_source: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid config in {config_source}: {field_name}.")
    return value.strip()


def require_string(
    value: object,
    *,
    config_source: str,
    field_name: str,
) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Invalid config in {config_source}: {field_name}.")
    return value


def describe_config_source(config_path: Path | None) -> str:
    return str(config_path) if config_path is not None else "package default config"


def group_repositories(
    repos: list[RepoEntry],
    config: ReadmeConfig | None = None,
) -> GroupedRepos:
    grouped: GroupedRepos = defaultdict(lambda: defaultdict(list))
    for repo in repos:
        grouped[repo.category][repo.subcategory].append(repo)

    config_index = ConfigIndex.from_config(config)

    return {
        category: {
            subcategory: sorted(entries, key=lambda entry: entry.name.casefold())
            for subcategory, entries in sorted(
                subcategories.items(),
                key=lambda item: item[0].casefold(),
            )
        }
        for category, subcategories in sorted(
            grouped.items(),
            key=lambda item: (
                config_index.category_positions.get(
                    item[0].casefold(),
                    len(config_index.category_positions),
                ),
                item[0].casefold(),
            ),
        )
    }


def render_readme(
    repos: list[RepoEntry],
    template: str,
    config: ReadmeConfig | None = None,
    *,
    org_name: str,
) -> str:
    grouped = group_repositories(repos, config=config)
    config_index = ConfigIndex.from_config(config)
    lines: list[str] = []

    for index, (category, subcategories) in enumerate(grouped.items()):
        if index > 0:
            lines.extend(("---", ""))
        lines.extend(
            render_category_section(
                category=category,
                subcategories=subcategories,
                config_index=config_index,
                org_name=org_name,
            )
        )

    repo_sections = "\n".join(lines).rstrip()
    markdown = template.replace("{{ repo_sections }}", repo_sections)
    return markdown.rstrip() + "\n"


def render_category_section(
    *,
    category: str,
    subcategories: dict[str, list[RepoEntry]],
    config_index: ConfigIndex,
    org_name: str,
) -> list[str]:
    canonical_category = config_index.canonical_category_name(category)
    lines = [f"### {canonical_category}", ""]

    category_description = config_index.category_description(canonical_category)
    if category_description:
        lines.extend((category_description, ""))

    if len(subcategories) == 1 and DEFAULT_SUBCATEGORY in subcategories:
        lines.extend(
            render_general_subcategory_table(
                category=canonical_category,
                entries=subcategories[DEFAULT_SUBCATEGORY],
                config_index=config_index,
                org_name=org_name,
            )
        )
        return lines

    for subcategory, entries in subcategories.items():
        lines.extend(
            render_subcategory_section(
                category=canonical_category,
                subcategory=subcategory,
                entries=entries,
                config_index=config_index,
                org_name=org_name,
            )
        )

    return lines


def render_general_subcategory_table(
    *,
    category: str,
    entries: list[RepoEntry],
    config_index: ConfigIndex,
    org_name: str,
) -> list[str]:
    lines: list[str] = []
    description = config_index.subcategory_description(category, DEFAULT_SUBCATEGORY)
    if description:
        lines.extend((description, ""))
    lines.extend(render_repo_table(entries, org_name=org_name))
    return lines


def render_subcategory_section(
    *,
    category: str,
    subcategory: str,
    entries: list[RepoEntry],
    config_index: ConfigIndex,
    org_name: str,
) -> list[str]:
    canonical_subcategory = config_index.canonical_subcategory_name(
        category,
        subcategory,
    )
    lines = [f"#### {canonical_subcategory}"]

    description = config_index.subcategory_description(category, canonical_subcategory)
    if description:
        lines.extend(("", description))

    lines.extend(("", *render_repo_table(entries, org_name=org_name)))
    return lines


def render_repo_table(entries: list[RepoEntry], org_name: str) -> list[str]:
    lines = [
        "| Repository | Description |",
        "|------------|-------------|",
    ]
    lines.extend(render_repo_row(entry, org_name=org_name) for entry in entries)
    lines.append("")
    return lines


def render_repo_row(entry: RepoEntry, org_name: str) -> str:
    url = f"https://github.com/{org_name}/{entry.name}"
    safe_description = escape_markdown_table_cell(entry.description)
    return f"| [{entry.name}]({url}) | {safe_description} |"


