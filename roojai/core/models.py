from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


ALLOWED_ENTITY_NOTE_TYPES = {"concept", "person", "project", "tool"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class Note:
    id: str
    title: str
    note_type: str
    tags: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    created: str = field(default_factory=utc_now_iso)
    updated: str = field(default_factory=utc_now_iso)
    status: str = "active"
    source_path: str | None = None
    source_chunk_index: int | None = None
    confidence: float = 0.5
    rationale: str | None = None
    content: str = ""
    file_path: Path = field(default_factory=Path)

    def __post_init__(self) -> None:
        uuid.UUID(self.id)
        if not self.title.strip():
            raise ValueError("Note title must not be empty.")
        self.title = self.title.strip()
        self.note_type = self.note_type.strip() or "note"
        self.tags = [tag.strip() for tag in self.tags if tag and tag.strip()]
        self.aliases = [alias.strip() for alias in self.aliases if alias and alias.strip()]
        self.content = self.content or ""
        self.confidence = float(self.confidence)
        if self.source_chunk_index is not None:
            self.source_chunk_index = int(self.source_chunk_index)
        if self.rationale is not None:
            self.rationale = self.rationale.strip() or None

    @classmethod
    def new(
        cls,
        title: str,
        note_type: str,
        file_path: Path | None = None,
        tags: list[str] | None = None,
        aliases: list[str] | None = None,
        source_path: str | None = None,
        source_chunk_index: int | None = None,
        confidence: float = 0.5,
        rationale: str | None = None,
        content: str = "",
        status: str = "active",
    ) -> "Note":
        note_id = str(uuid.uuid4())
        timestamp = utc_now_iso()
        return cls(
            id=note_id,
            title=title,
            note_type=note_type,
            tags=tags or [],
            aliases=aliases or [],
            created=timestamp,
            updated=timestamp,
            status=status,
            source_path=source_path,
            source_chunk_index=source_chunk_index,
            confidence=confidence,
            rationale=rationale,
            content=content,
            file_path=file_path or Path(f"{note_id}.md"),
        )

    @classmethod
    def stub(cls, title: str, file_path: Path | None = None) -> "Note":
        return cls.new(
            title=title,
            note_type="stub",
            file_path=file_path,
            status="stub",
            content="",
        )
