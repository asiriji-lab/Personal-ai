# Roojai

Roojai is a local-first personal knowledge system built around human-owned Markdown notes, a small SQLite graph, and a CLI workflow.

The current codebase includes the Phase 1 note foundation and the Phase 2 ingestion foundation. Roojai can manage Markdown notes, store explicit `RELATED_TO` edges, ingest Markdown/text/PDF sources, and create pending-review entity notes plus review-queue claims from AI extraction.

## What Exists

- `roojai init`: create a vault directory, note storage, review queue, extraction log, and SQLite database
- `roojai note new`: create a note with YAML frontmatter and a UUID-backed file path
- `roojai note open`: open a note by exact title match
- `roojai note list`: list notes with optional `--type` and `--status` filters
- `roojai ingest`: import `.md`, `.txt`, or `.pdf` files
- `roojai review`: print the current review queue
- `roojai search`: keyword search over note titles and content using SQLite `LIKE`

## Current Behavior

### Phase 1 note foundation

- notes are stored as `vault/notes/<uuid>.md`
- titles live in frontmatter only
- explicit wiki-links create `RELATED_TO` edges
- unresolved wiki-links create stub notes and review-queue entries

### Phase 2 ingestion foundation

- `.md` files use Phase 1 parsing and can also run AI extraction when Gemini is available
- `.txt` and `.pdf` files use AI extraction
- extracted entities may become notes with `status: pending_review`
- extracted claims do not become notes
- claims are written to `vault/system/review-queue.md`
- raw extraction and validation responses are appended to `vault/system/extraction_log.jsonl`
- validation is best-effort; skipped validation is recorded in the queue

## Project Layout

```text
.
|-- cli.py
|-- pyproject.toml
|-- README.md
|-- docs/
|   |-- phase1spec.txt
|   |-- phase2.txt
|   `-- worklog.txt
|-- scripts/
|   `-- bootstrap.ps1
|-- tests/
|   `-- test_cli.py
`-- roojai/
    |-- config.py
    |-- core/
    |   |-- markdown.py
    |   |-- models.py
    |   `-- store.py
    `-- ingest/
        |-- extractor.py
        |-- parser.py
        |-- pdf.py
        |-- prompts.py
        `-- validator.py
```

## Development Environment

The project should be developed in a repo-local `.venv`. Do not rely on a global interpreter for editor analysis or CLI work.

Python `3.10+` is required. Python `3.12` is the preferred target for this repo.

Bootstrap the environment from PowerShell:

```powershell
.\scripts\bootstrap.ps1
```

This creates `.venv`, seeds `pip` into it, and installs Roojai in editable mode.

Manual fallback:

```powershell
.\scripts\bootstrap.ps1 -PythonExe "C:\path\to\python.exe"
```

If the editable install fails, the environment was created but dependency download did not complete. Re-run the final `pip install -e .` once package access is available.

## Runtime Requirements

Phase 1 commands require only the Python dependencies in `pyproject.toml`.

Phase 2 AI ingest also depends on:

- `GEMINI_API_KEY` for Gemini extraction
- a reachable Ollama instance for local validation
- either `PyMuPDF` or `pdfplumber` for real PDF ingest

Default Ollama settings:

- URL: `http://localhost:11434`
- model: `qwen3.5:4b`

Environment overrides:

- `ROOJAI_OLLAMA_URL`
- `ROOJAI_OLLAMA_MODEL`

## Quick Start

Initialize a vault in the current working directory:

```powershell
roojai init
```

Create a note:

```powershell
roojai note new "First Note" --type concept --tags ai,tools
```

List notes:

```powershell
roojai note list
roojai note list --status pending_review
```

Import a Markdown file:

```powershell
roojai ingest path/to/file.md
```

Import a text file:

```powershell
roojai ingest path/to/file.txt
```

Import a PDF:

```powershell
roojai ingest path/to/file.pdf
```

Show review queue:

```powershell
roojai review
```

Search:

```powershell
roojai search notebook
```

## Vault Structure

After `roojai init`, the vault looks like this:

```text
vault/
|-- graph.db
|-- notes/
|   `-- <uuid>.md
`-- system/
    |-- extraction_log.jsonl
    `-- review-queue.md
```

Notes are stored as `vault/notes/<uuid>.md`. Titles live in frontmatter only, so renaming a note does not require moving the file.

## Note Format

Each note is a Markdown file with YAML frontmatter:

```yaml
---
id: 123e4567-e89b-12d3-a456-426614174000
title: First Note
type: concept
tags:
  - ai
  - tools
created: 2026-04-27T16:00:00Z
updated: 2026-04-27T16:00:00Z
aliases: []
status: active
---
```

Wiki-links in the body use `[[Title]]` syntax.

Phase 2 note metadata is also stored in SQLite:

- `source_chunk_index`
- `confidence`
- `rationale`

## Ingest Rules

### Markdown ingest

- `source_path` is stored as an absolute path
- wiki-links resolve by exact title, then exact alias
- unresolved wiki-links create stub notes
- stub notes use `type: stub`, `status: stub`, and empty body content
- explicit wiki-links create `RELATED_TO` edges with weight `1.0`
- unresolved links are appended to `vault/system/review-queue.md`
- if Gemini is unavailable, Markdown ingest still succeeds with Phase 1 behavior

### AI extraction ingest

- entity dedup uses case-insensitive exact match after trim
- new extracted entities become notes with `status: pending_review`
- claim text goes to the review queue, not note bodies
- claim validation uses Ollama when available
- invalid or unavailable validator responses degrade to skipped validation
- `.txt` and `.pdf` ingest fail cleanly if Gemini is unavailable

## Current Constraints

- titles are unique
- `note open` uses exact title match only
- search is keyword-only
- only one edge type exists: `RELATED_TO`
- claims are review items, not first-class notes
- no embeddings or vector search
- no MCP, dashboard, merge, or contradiction logic

## Testing

Run the test suite:

```powershell
python -m unittest -v
```

Compile-check the package:

```powershell
python -m compileall cli.py roojai tests
```

The GitHub Actions workflow runs the same checks on push and pull request.

## Development

The workspace is configured to use:

```text
${workspaceFolder}\.venv\Scripts\python.exe
```

If VS Code still points somewhere else, run `Python: Select Interpreter` and choose the `.venv` interpreter manually.

The implementation contracts live in:

- [docs/phase1spec.txt](docs/phase1spec.txt)
- [docs/phase2.txt](docs/phase2.txt)
