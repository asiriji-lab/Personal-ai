from __future__ import annotations

import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VaultPaths:
    root: Path
    notes_dir: Path
    system_dir: Path
    db_path: Path
    review_queue_path: Path

    def ensure_layout(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        self.system_dir.mkdir(parents=True, exist_ok=True)
        if not self.review_queue_path.exists():
            self.review_queue_path.write_text("", encoding="utf-8")

    def note_path_for_id(self, note_id: str | None = None) -> Path:
        resolved_id = note_id or str(uuid.uuid4())
        return self.notes_dir / f"{resolved_id}.md"


def resolve_vault_paths(vault_root: Path | None) -> VaultPaths:
    root = (vault_root or Path.cwd() / "vault").expanduser().resolve()
    return VaultPaths(
        root=root,
        notes_dir=root / "notes",
        system_dir=root / "system",
        db_path=root / "graph.db",
        review_queue_path=root / "system" / "review-queue.md",
    )


def open_in_editor(file_path: Path) -> bool:
    editor = os.environ.get("EDITOR")
    if not editor:
        return False
    try:
        subprocess.Popen(f'"{editor}" "{file_path}"', shell=True)
        return True
    except OSError:
        return False
