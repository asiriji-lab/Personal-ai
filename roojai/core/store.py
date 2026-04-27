from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from roojai.core.models import Note, utc_now_iso


class NoteStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL UNIQUE,
                    type TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    aliases TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created TEXT NOT NULL,
                    updated TEXT NOT NULL,
                    source_path TEXT,
                    content TEXT NOT NULL DEFAULT '',
                    file_path TEXT NOT NULL UNIQUE
                );

                CREATE TABLE IF NOT EXISTS edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, type)
                );

                CREATE INDEX IF NOT EXISTS idx_notes_title ON notes(title);
                CREATE INDEX IF NOT EXISTS idx_notes_type ON notes(type);
                CREATE INDEX IF NOT EXISTS idx_edges_target_id ON edges(target_id);
                """
            )

    def insert_note(self, note: Note) -> None:
        try:
            with self.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO notes (
                        id, title, type, tags, aliases, status, created, updated,
                        source_path, content, file_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        note.id,
                        note.title,
                        note.note_type,
                        json.dumps(note.tags),
                        json.dumps(note.aliases),
                        note.status,
                        note.created,
                        note.updated,
                        note.source_path,
                        note.content,
                        str(note.file_path),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            if "notes.title" in str(exc) or "UNIQUE constraint failed: notes.title" in str(exc):
                raise ValueError(f'Note with title "{note.title}" already exists.') from exc
            raise

    def get_note_by_title(self, title: str) -> Note | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM notes WHERE title = ?",
                (title,),
            ).fetchone()
        return self._row_to_note(row) if row else None

    def get_note_by_alias(self, alias: str) -> Note | None:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM notes").fetchall()
        for row in rows:
            note = self._row_to_note(row)
            if alias in note.aliases:
                return note
        return None

    def list_notes(self, note_type: str | None = None) -> list[Note]:
        query = "SELECT * FROM notes"
        params: tuple[str, ...] = ()
        if note_type is not None:
            query += " WHERE type = ?"
            params = (note_type,)
        query += " ORDER BY title COLLATE NOCASE"
        with self.connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_note(row) for row in rows]

    def suggest_titles(self, partial: str, limit: int = 5) -> list[str]:
        pattern = f"%{partial}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT title FROM notes
                WHERE lower(title) LIKE lower(?)
                ORDER BY title COLLATE NOCASE
                LIMIT ?
                """,
                (pattern, limit),
            ).fetchall()
        return [row["title"] for row in rows]

    def insert_edge(self, source_id: str, target_id: str) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO edges (source_id, target_id, type, weight, created)
                VALUES (?, ?, 'RELATED_TO', 1.0, ?)
                ON CONFLICT(source_id, target_id, type)
                DO UPDATE SET weight = excluded.weight
                """,
                (source_id, target_id, utc_now_iso()),
            )

    def search_notes(self, keyword: str) -> list[dict[str, str]]:
        pattern = f"%{keyword}%"
        with self.connect() as connection:
            rows = connection.execute(
                """
                SELECT title, type, content
                FROM notes
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY title COLLATE NOCASE
                """,
                (pattern, pattern),
            ).fetchall()
        return [
            {
                "title": row["title"],
                "type": row["type"],
                "snippet": self._build_snippet(row["content"], keyword, row["title"]),
            }
            for row in rows
        ]

    def _build_snippet(self, content: str, keyword: str, title: str) -> str:
        haystack = content or ""
        lower_content = haystack.lower()
        lower_keyword = keyword.lower()
        match_index = lower_content.find(lower_keyword)
        if match_index == -1:
            title_index = title.lower().find(lower_keyword)
            if title_index != -1:
                return title
            return (haystack[:80] + "...") if len(haystack) > 80 else haystack
        start = max(0, match_index - 30)
        end = min(len(haystack), match_index + len(keyword) + 50)
        snippet = haystack[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(haystack):
            snippet = snippet + "..."
        return snippet

    def _row_to_note(self, row: sqlite3.Row) -> Note:
        return Note(
            id=row["id"],
            title=row["title"],
            note_type=row["type"],
            tags=json.loads(row["tags"]),
            aliases=json.loads(row["aliases"]),
            created=row["created"],
            updated=row["updated"],
            status=row["status"],
            source_path=row["source_path"],
            content=row["content"],
            file_path=Path(row["file_path"]),
        )
