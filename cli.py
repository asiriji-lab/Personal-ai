from __future__ import annotations

from pathlib import Path

import click

from roojai.config import AIConfig, VaultPaths, open_in_editor, resolve_ai_config, resolve_vault_paths
from roojai.core.markdown import serialize_note
from roojai.core.models import Note
from roojai.core.store import NoteStore
from roojai.ingest.extractor import ExtractionUnavailableError
from roojai.ingest.parser import ingest_file


@click.group()
@click.option("--vault", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.pass_context
def cli(ctx: click.Context, vault: Path | None) -> None:
    ctx.ensure_object(dict)
    ctx.obj["vault"] = resolve_vault_paths(vault)
    ctx.obj["ai"] = resolve_ai_config()


def get_store(paths: VaultPaths) -> NoteStore:
    return NoteStore(paths.db_path)


def get_ai_config(ctx: click.Context) -> AIConfig:
    return ctx.obj["ai"]


@cli.command("init")
@click.pass_context
def init_command(ctx: click.Context) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    paths.ensure_layout()
    get_store(paths).initialize()
    click.echo(f"Initialized vault at {paths.root}")


@cli.group("note")
def note_group() -> None:
    pass


@note_group.command("new")
@click.argument("title")
@click.option("--type", "note_type", default="note", show_default=True)
@click.option("--tags", default="", help="Comma-separated tags.")
@click.pass_context
def note_new(ctx: click.Context, title: str, note_type: str, tags: str) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    paths.ensure_layout()
    store = get_store(paths)
    store.initialize()

    note = Note.new(
        title=title,
        note_type=note_type,
        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
    )
    note.file_path = paths.note_path_for_id(note.id)
    try:
        store.insert_note(note)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    note.file_path.write_text(serialize_note(note), encoding="utf-8")
    if not open_in_editor(note.file_path):
        click.echo(str(note.file_path))


@note_group.command("open")
@click.argument("title")
@click.pass_context
def note_open(ctx: click.Context, title: str) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    store = get_store(paths)
    store.initialize()
    note = store.get_note_by_title(title)
    if note is None:
        suggestions = store.suggest_titles(title, limit=5)
        message = f'No note found with title "{title}".'
        if suggestions:
            message += "\nSuggestions:\n" + "\n".join(f"- {item}" for item in suggestions)
        raise click.ClickException(message)
    if not open_in_editor(note.file_path):
        click.echo(str(note.file_path))


@note_group.command("list")
@click.option("--type", "note_type", default=None)
@click.option("--status", default=None)
@click.pass_context
def note_list(ctx: click.Context, note_type: str | None, status: str | None) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    store = get_store(paths)
    store.initialize()
    for note in store.list_notes(note_type=note_type, status=status):
        tags = ", ".join(note.tags)
        click.echo(f"{note.title}\t{note.note_type}\t{note.status}\t{tags}")


@cli.command("ingest")
@click.argument("file_path", type=click.Path(path_type=Path, exists=True, dir_okay=False))
@click.pass_context
def ingest_command(ctx: click.Context, file_path: Path) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    paths.ensure_layout()
    store = get_store(paths)
    store.initialize()
    try:
        result = ingest_file(paths, store, file_path, get_ai_config(ctx))
    except (ValueError, ExtractionUnavailableError) as exc:
        raise click.ClickException(str(exc)) from exc
    if result.primary_note is not None:
        click.echo(
            f'Ingested "{result.primary_note.title}" as {result.primary_note.id} '
            f"(entities={result.entities_created}, review_items={result.review_items_added})"
        )
    else:
        click.echo(
            f"Ingested {file_path.name} "
            f"(entities={result.entities_created}, review_items={result.review_items_added})"
        )


@cli.command("review")
@click.pass_context
def review_command(ctx: click.Context) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    paths.ensure_layout()
    click.echo(paths.review_queue_path.read_text(encoding="utf-8"), nl=False)


@cli.command("search")
@click.argument("keyword")
@click.pass_context
def search_command(ctx: click.Context, keyword: str) -> None:
    paths: VaultPaths = ctx.obj["vault"]
    store = get_store(paths)
    store.initialize()
    for result in store.search_notes(keyword):
        click.echo(f"{result['title']}\t{result['type']}\t{result['snippet']}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
