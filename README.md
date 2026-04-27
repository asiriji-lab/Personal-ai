# Roojai

Roojai is a local-first personal knowledge system built around human-owned Markdown notes, a small SQLite graph, and a CLI workflow.

Phase 1 is intentionally narrow. It gives you a vault, canonical note files, explicit wiki-link edges, single-file Markdown ingest, and keyword search. It does not include LLM extraction, embeddings, MCP, a dashboard, or automated graph evolution.

## What Exists

- `roojai init`: create a vault directory, note storage, review queue, and SQLite database
- `roojai note new`: create a note with YAML frontmatter and a UUID-backed file path
- `roojai note open`: open a note by exact title match
- `roojai note list`: list notes with type and tags
- `roojai ingest`: import one Markdown file, extract `[[wiki-links]]`, and create `RELATED_TO` edges
- `roojai search`: keyword search over note titles and content using SQLite `LIKE`

## Project Layout

```text
.
|-- cli.py
|-- pyproject.toml
|-- README.md
|-- docs/
|   `-- phase1spec.txt
`-- roojai/
    |-- config.py
    |-- core/
    |   |-- markdown.py
    |   |-- models.py
    |   `-- store.py
    `-- ingest/
        `-- parser.py
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
```

Import a Markdown file:

```powershell
roojai ingest path/to/file.md
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

## Ingest Rules

- `source_path` is stored as an absolute path
- wiki-links resolve by exact title, then exact alias
- unresolved wiki-links create stub notes
- stub notes use `type: stub`, `status: stub`, and empty body content
- all explicit wiki-links create `RELATED_TO` edges with weight `1.0`
- unresolved links are appended to `vault/system/review-queue.md`

## Current Constraints

- titles are unique
- `note open` uses exact title match only
- search is keyword-only
- only single-file ingest is supported
- only one edge type exists in Phase 1: `RELATED_TO`

## Development

The workspace is configured to use:

```text
${workspaceFolder}\.venv\Scripts\python.exe
```

If VS Code still points somewhere else, run `Python: Select Interpreter` and choose the `.venv` interpreter manually.

Compile-check the package:

```powershell
.\.venv\Scripts\python -m compileall cli.py roojai
```

The Phase 1 implementation contract lives in [docs/phase1spec.txt](docs/phase1spec.txt).
