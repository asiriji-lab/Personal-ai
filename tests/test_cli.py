from __future__ import annotations

import shutil
import sqlite3
import uuid
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

from cli import cli


class RoojaiCliTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.test_root = Path.cwd() / ".tmp-tests"
        cls.test_root.mkdir(exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.test_root.exists():
            shutil.rmtree(cls.test_root, ignore_errors=True)

    def setUp(self) -> None:
        self.runner = CliRunner()
        self.workspace = self.test_root / str(uuid.uuid4())
        self.workspace.mkdir(parents=True)
        self.vault = self.workspace / "vault"

    def tearDown(self) -> None:
        if self.workspace.exists():
            shutil.rmtree(self.workspace, ignore_errors=True)

    def invoke(self, *args: str):
        with patch("cli.open_in_editor", return_value=False):
            return self.runner.invoke(cli, ["--vault", str(self.vault), *args])

    def test_init_creates_vault_layout(self) -> None:
        result = self.invoke("init")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.vault / "notes").is_dir())
        self.assertTrue((self.vault / "system").is_dir())
        self.assertTrue((self.vault / "graph.db").exists())
        self.assertTrue((self.vault / "system" / "review-queue.md").exists())

    def test_note_new_writes_markdown_and_rejects_duplicate_title(self) -> None:
        self.invoke("init")

        first = self.invoke("note", "new", "First Note", "--type", "concept", "--tags", "alpha,beta")
        second = self.invoke("note", "new", "First Note")

        self.assertEqual(first.exit_code, 0, first.output)
        self.assertIn(".md", first.output)
        self.assertEqual(second.exit_code, 1, second.output)
        self.assertIn('Note with title "First Note" already exists.', second.output)

        note_files = list((self.vault / "notes").glob("*.md"))
        self.assertEqual(len(note_files), 1)
        content = note_files[0].read_text(encoding="utf-8")
        self.assertIn("title: First Note", content)
        self.assertIn("type: concept", content)
        self.assertIn("- alpha", content)
        self.assertIn("- beta", content)

    def test_note_open_miss_shows_partial_match_suggestions(self) -> None:
        self.invoke("init")
        self.invoke("note", "new", "Alpha Note")
        self.invoke("note", "new", "Beta Note")

        result = self.invoke("note", "open", "Alp")

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn('No note found with title "Alp".', result.output)
        self.assertIn("Suggestions:", result.output)
        self.assertIn("- Alpha Note", result.output)

    def test_note_list_filters_by_type(self) -> None:
        self.invoke("init")
        self.invoke("note", "new", "Concept Note", "--type", "concept")
        self.invoke("note", "new", "Project Note", "--type", "project")

        result = self.invoke("note", "list", "--type", "concept")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Concept Note\tconcept", result.output)
        self.assertNotIn("Project Note", result.output)

    def test_ingest_creates_stub_review_item_and_edges(self) -> None:
        self.invoke("init")
        self.invoke("note", "new", "Existing Target")

        source_file = self.workspace / "import.md"
        source_file.write_text(
            "---\n"
            "title: Imported Note\n"
            "aliases:\n"
            "  - Import Alias\n"
            "---\n"
            "Body with [[Missing Link]] and [[Existing Target]].\n",
            encoding="utf-8",
        )

        result = self.invoke("ingest", str(source_file))

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn('Ingested "Imported Note"', result.output)

        review_queue = (self.vault / "system" / "review-queue.md").read_text(encoding="utf-8")
        self.assertIn('Resolve stub: "Missing Link"', review_queue)
        self.assertIn('source_note: "Imported Note"', review_queue)

        with sqlite3.connect(self.vault / "graph.db") as connection:
            notes = {
                row[1]: row[0]
                for row in connection.execute("SELECT id, title FROM notes").fetchall()
            }
            edges = connection.execute(
                "SELECT source_id, target_id, type, weight FROM edges ORDER BY target_id"
            ).fetchall()

        self.assertIn("Imported Note", notes)
        self.assertIn("Existing Target", notes)
        self.assertIn("Missing Link", notes)
        self.assertEqual(len(edges), 2)
        self.assertTrue(all(edge[2] == "RELATED_TO" for edge in edges))
        self.assertTrue(all(edge[3] == 1.0 for edge in edges))

    def test_search_matches_title_and_content(self) -> None:
        self.invoke("init")
        self.invoke("note", "new", "Notebook Tools")

        source_file = self.workspace / "search.md"
        source_file.write_text(
            "---\n"
            "title: Imported Search Note\n"
            "---\n"
            "This body mentions notebook workflows.\n",
            encoding="utf-8",
        )
        self.invoke("ingest", str(source_file))

        result = self.invoke("search", "notebook")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Notebook Tools\tnote\tNotebook Tools", result.output)
        self.assertIn("Imported Search Note\tnote\tThis body mentions notebook workflows.", result.output)
