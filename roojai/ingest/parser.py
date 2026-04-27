from __future__ import annotations

from pathlib import Path

from roojai.config import VaultPaths
from roojai.core.markdown import (
    extract_headings,
    extract_wiki_links,
    parse_markdown_file,
    serialize_note,
)
from roojai.core.models import Note, utc_now_iso
from roojai.core.store import NoteStore


def ingest_markdown_file(paths: VaultPaths, store: NoteStore, source_file: Path) -> Note:
    frontmatter, body = parse_markdown_file(source_file)
    _ = extract_headings(body)

    note = Note.new(
        title=str(frontmatter.get("title") or source_file.stem),
        note_type=str(frontmatter.get("type") or "note"),
        tags=_normalize_string_list(frontmatter.get("tags")),
        aliases=_normalize_string_list(frontmatter.get("aliases")),
        source_path=str(source_file.resolve()),
        content=body,
        status=str(frontmatter.get("status") or "active"),
    )
    if isinstance(frontmatter.get("id"), str):
        note.id = frontmatter["id"]
    if isinstance(frontmatter.get("created"), str):
        note.created = frontmatter["created"]
    if isinstance(frontmatter.get("updated"), str):
        note.updated = frontmatter["updated"]
    note.file_path = paths.note_path_for_id(note.id)

    store.insert_note(note)
    note.file_path.write_text(serialize_note(note), encoding="utf-8")

    for link_title in extract_wiki_links(body):
        target = store.get_note_by_title(link_title) or store.get_note_by_alias(link_title)
        if target is None:
            target = Note.stub(link_title)
            target.file_path = paths.note_path_for_id(target.id)
            store.insert_note(target)
            target.file_path.write_text(serialize_note(target), encoding="utf-8")
            append_review_queue_item(paths.review_queue_path, target, note)
        store.insert_edge(note.id, target.id)

    return note


def append_review_queue_item(review_queue_path: Path, stub_note: Note, source_note: Note) -> None:
    item = (
        f'- [ ] Resolve stub: "{stub_note.title}"\n'
        f"  stub_id: {stub_note.id}\n"
        f'  source_note: "{source_note.title}"\n'
        f"  source_id: {source_note.id}\n"
        f"  created: {utc_now_iso()}\n"
    )
    with review_queue_path.open("a", encoding="utf-8") as handle:
        if review_queue_path.stat().st_size > 0:
            handle.write("\n")
        handle.write(item)


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
