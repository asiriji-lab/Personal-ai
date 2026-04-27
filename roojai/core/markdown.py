from __future__ import annotations

import re
from pathlib import Path

import yaml
from yaml import YAMLError

from roojai.core.models import Note

WIKI_LINK_PATTERN = re.compile(r"\[\[([^\[\]]+)\]\]")
HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


def parse_markdown_file(file_path: Path) -> tuple[dict, str]:
    raw_text = file_path.read_text(encoding="utf-8")
    return parse_markdown_text(raw_text)


def parse_markdown_text(raw_text: str) -> tuple[dict, str]:
    if not raw_text.startswith("---"):
        return {}, raw_text

    parts = raw_text.split("---", 2)
    if len(parts) < 3:
        return {}, raw_text

    frontmatter_text = parts[1]
    body = parts[2].lstrip("\r\n")
    try:
        data = yaml.safe_load(frontmatter_text) or {}
    except YAMLError as exc:
        raise ValueError("Invalid YAML frontmatter.") from exc
    if not isinstance(data, dict):
        raise ValueError("Frontmatter must be a YAML mapping.")
    return data, body


def serialize_note(note: Note) -> str:
    frontmatter = {
        "id": note.id,
        "title": note.title,
        "type": note.note_type,
        "tags": note.tags,
        "created": note.created,
        "updated": note.updated,
        "aliases": note.aliases,
        "status": note.status,
    }
    if note.source_path:
        frontmatter["source_path"] = note.source_path
    yaml_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True).strip()
    body = note.content or ""
    return f"---\n{yaml_text}\n---\n{body}"


def extract_wiki_links(content: str) -> list[str]:
    seen: set[str] = set()
    links: list[str] = []
    for match in WIKI_LINK_PATTERN.findall(content):
        title = match.strip()
        if title and title not in seen:
            seen.add(title)
            links.append(title)
    return links


def extract_headings(content: str) -> list[str]:
    return [match[1].strip() for match in HEADING_PATTERN.findall(content)]
