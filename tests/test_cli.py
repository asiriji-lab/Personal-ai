from __future__ import annotations

import shutil
import sqlite3
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from click.testing import CliRunner

from cli import cli
from roojai.config import AIConfig
from roojai.ingest.extractor import ExtractionUnavailableError
from roojai.ingest.validator import ValidationUnavailableError


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

    def invoke(self, *args: str, ai_config: AIConfig | None = None):
        config = ai_config or AIConfig(
            gemini_api_key=None,
            ollama_url="http://localhost:11434",
            ollama_model="qwen3.5:4b",
        )
        with ExitStack() as stack:
            stack.enter_context(patch("cli.open_in_editor", return_value=False))
            stack.enter_context(patch("cli.resolve_ai_config", return_value=config))
            return self.runner.invoke(cli, ["--vault", str(self.vault), *args])

    def test_init_creates_vault_layout(self) -> None:
        result = self.invoke("init")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertTrue((self.vault / "notes").is_dir())
        self.assertTrue((self.vault / "system").is_dir())
        self.assertTrue((self.vault / "graph.db").exists())
        self.assertTrue((self.vault / "system" / "review-queue.md").exists())
        self.assertTrue((self.vault / "system" / "extraction_log.jsonl").exists())

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

    def test_note_list_filters_by_type_and_status(self) -> None:
        self.invoke("init")
        self.invoke("note", "new", "Concept Note", "--type", "concept")
        self.invoke("note", "new", "Project Note", "--type", "project")

        result = self.invoke("note", "list", "--type", "concept", "--status", "active")

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Concept Note\tconcept\tactive", result.output)
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

    def test_ingest_malformed_frontmatter_returns_friendly_error(self) -> None:
        self.invoke("init")

        source_file = self.workspace / "broken.md"
        source_file.write_text(
            "---\n"
            "title: Broken Note\n"
            "aliases: [one, two\n"
            "---\n"
            "Body text.\n",
            encoding="utf-8",
        )

        result = self.invoke("ingest", str(source_file))

        self.assertEqual(result.exit_code, 1, result.output)
        self.assertIn("Invalid YAML frontmatter.", result.output)
        self.assertNotIn("Traceback", result.output)

    def test_ingest_reuses_existing_stub_and_review_entry(self) -> None:
        self.invoke("init")

        first_file = self.workspace / "first.md"
        first_file.write_text(
            "---\n"
            "title: First Import\n"
            "---\n"
            "Links to [[New Concept]].\n",
            encoding="utf-8",
        )
        second_file = self.workspace / "second.md"
        second_file.write_text(
            "---\n"
            "title: Second Import\n"
            "---\n"
            "Also links to [[New Concept]].\n",
            encoding="utf-8",
        )

        first_result = self.invoke("ingest", str(first_file))
        second_result = self.invoke("ingest", str(second_file))

        self.assertEqual(first_result.exit_code, 0, first_result.output)
        self.assertEqual(second_result.exit_code, 0, second_result.output)

        review_queue = (self.vault / "system" / "review-queue.md").read_text(encoding="utf-8")
        self.assertEqual(review_queue.count('Resolve stub: "New Concept"'), 1)

        with sqlite3.connect(self.vault / "graph.db") as connection:
            stub_rows = connection.execute(
                "SELECT id FROM notes WHERE title = ?",
                ("New Concept",),
            ).fetchall()
            edges = connection.execute(
                """
                SELECT COUNT(*)
                FROM edges
                WHERE target_id = (
                    SELECT id FROM notes WHERE title = ?
                )
                """,
                ("New Concept",),
            ).fetchone()

        self.assertEqual(len(stub_rows), 1)
        self.assertEqual(edges[0], 2)

    def test_phase2_pdf_ingest_creates_pending_review_entities_and_claim_entries(self) -> None:
        self.invoke("init")
        pdf_file = self.workspace / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")
        ai_config = AIConfig(gemini_api_key="test-key", ollama_url="http://ollama", ollama_model="qwen3.5:4b")

        extraction = {
            "entities": [{"title": "Gemini Flash", "type": "tool"}],
            "edges": [],
            "claims": [
                {
                    "text": "Gemini Flash supports JSON output.",
                    "confidence": 0.82,
                    "rationale": "Mentioned in the source.",
                    "associated_entities": ["Gemini Flash"],
                }
            ],
        }

        with ExitStack() as stack:
            stack.enter_context(
                patch("roojai.ingest.parser.extract_pdf_text", return_value="Gemini Flash emits JSON.")
            )
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.extract_chunk",
                    return_value=type("Extraction", (), {**extraction, "raw_response": {"ok": True}})(),
                )
            )
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.validate_claim",
                    return_value=type(
                        "Validation",
                        (),
                        {"verdict": "pass", "explanation": "Grounded.", "raw_response": {"ok": True}},
                    )(),
                )
            )
            result = self.invoke("ingest", str(pdf_file), ai_config=ai_config)

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("entities=", result.output)

        with sqlite3.connect(self.vault / "graph.db") as connection:
            row = connection.execute(
                "SELECT title, type, status, confidence FROM notes WHERE lower(title) = lower(?)",
                ("Gemini Flash",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[0], "Gemini Flash")
        self.assertEqual(row[1], "tool")
        self.assertEqual(row[2], "pending_review")
        self.assertEqual(row[3], 0.82)

        review_queue = (self.vault / "system" / "review-queue.md").read_text(encoding="utf-8")
        self.assertIn('Review claim: "Gemini Flash supports JSON output."', review_queue)
        self.assertIn("validator_verdict: pass", review_queue)

    def test_phase2_validation_skipped_when_ollama_unavailable(self) -> None:
        self.invoke("init")
        pdf_file = self.workspace / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")
        ai_config = AIConfig(gemini_api_key="test-key", ollama_url="http://ollama", ollama_model="qwen3.5:4b")

        extraction = {
            "entities": [{"title": "Local Model", "type": "tool"}],
            "edges": [],
            "claims": [
                {
                    "text": "Local Model validates claims.",
                    "confidence": 0.55,
                    "rationale": "Seen in text.",
                    "associated_entities": ["Local Model"],
                }
            ],
        }

        with ExitStack() as stack:
            stack.enter_context(patch("roojai.ingest.parser.extract_pdf_text", return_value="Local Model text."))
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.extract_chunk",
                    return_value=type("Extraction", (), {**extraction, "raw_response": {"ok": True}})(),
                )
            )
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.validate_claim",
                    side_effect=ValidationUnavailableError("down"),
                )
            )
            result = self.invoke("ingest", str(pdf_file), ai_config=ai_config)

        self.assertEqual(result.exit_code, 0, result.output)
        review_queue = (self.vault / "system" / "review-queue.md").read_text(encoding="utf-8")
        self.assertIn("validator_verdict: skipped", review_queue)

    def test_phase2_markdown_falls_back_when_gemini_unavailable(self) -> None:
        self.invoke("init")
        source_file = self.workspace / "fallback.md"
        source_file.write_text(
            "---\n"
            "title: Markdown Fallback\n"
            "---\n"
            "Body with [[Fallback Target]].\n",
            encoding="utf-8",
        )

        result = self.invoke("ingest", str(source_file))

        self.assertEqual(result.exit_code, 0, result.output)
        with sqlite3.connect(self.vault / "graph.db") as connection:
            notes = connection.execute("SELECT title FROM notes ORDER BY title").fetchall()
        self.assertEqual([row[0] for row in notes], ["Fallback Target", "Markdown Fallback"])

    def test_phase2_markdown_falls_back_when_gemini_runtime_fails(self) -> None:
        self.invoke("init")
        source_file = self.workspace / "runtime-fallback.md"
        source_file.write_text(
            "---\n"
            "title: Runtime Fallback\n"
            "---\n"
            "Body with [[Runtime Target]].\n",
            encoding="utf-8",
        )
        ai_config = AIConfig(gemini_api_key="test-key", ollama_url="http://ollama", ollama_model="qwen3.5:4b")

        with patch(
            "roojai.ingest.parser.extract_chunk",
            side_effect=ExtractionUnavailableError("down"),
        ):
            result = self.invoke("ingest", str(source_file), ai_config=ai_config)

        self.assertEqual(result.exit_code, 0, result.output)
        with sqlite3.connect(self.vault / "graph.db") as connection:
            notes = connection.execute("SELECT title FROM notes ORDER BY title").fetchall()
        self.assertEqual([row[0] for row in notes], ["Runtime Fallback", "Runtime Target"])

    def test_phase2_validation_skipped_when_validator_output_is_invalid(self) -> None:
        self.invoke("init")
        pdf_file = self.workspace / "invalid-validator.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")
        ai_config = AIConfig(gemini_api_key="test-key", ollama_url="http://ollama", ollama_model="qwen3.5:4b")

        extraction = {
            "entities": [{"title": "Validator Entity", "type": "tool"}],
            "edges": [],
            "claims": [
                {
                    "text": "Validator Entity appears in the source.",
                    "confidence": 0.61,
                    "rationale": "Seen in text.",
                    "associated_entities": ["Validator Entity"],
                }
            ],
        }

        with ExitStack() as stack:
            stack.enter_context(patch("roojai.ingest.parser.extract_pdf_text", return_value="Validator Entity text."))
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.extract_chunk",
                    return_value=type("Extraction", (), {**extraction, "raw_response": {"ok": True}})(),
                )
            )
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.validate_claim",
                    side_effect=ValueError("bad json"),
                )
            )
            result = self.invoke("ingest", str(pdf_file), ai_config=ai_config)

        self.assertEqual(result.exit_code, 0, result.output)
        review_queue = (self.vault / "system" / "review-queue.md").read_text(encoding="utf-8")
        self.assertIn("validator_verdict: skipped", review_queue)

    def test_phase2_duplicate_entity_ingest_reuses_existing_note(self) -> None:
        self.invoke("init")
        pdf_file = self.workspace / "dup.pdf"
        pdf_file.write_bytes(b"%PDF-1.4\n")
        ai_config = AIConfig(gemini_api_key="test-key", ollama_url="http://ollama", ollama_model="qwen3.5:4b")

        extraction = {
            "entities": [{"title": "Repeated Entity", "type": "project"}],
            "edges": [],
            "claims": [
                {
                    "text": "Repeated Entity exists.",
                    "confidence": 0.71,
                    "rationale": "Mentioned.",
                    "associated_entities": ["Repeated Entity"],
                }
            ],
        }

        with ExitStack() as stack:
            stack.enter_context(patch("roojai.ingest.parser.extract_pdf_text", return_value="Repeated Entity text."))
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.extract_chunk",
                    return_value=type("Extraction", (), {**extraction, "raw_response": {"ok": True}})(),
                )
            )
            stack.enter_context(
                patch(
                    "roojai.ingest.parser.validate_claim",
                    return_value=type(
                        "Validation",
                        (),
                        {"verdict": "pass", "explanation": "Grounded.", "raw_response": {"ok": True}},
                    )(),
                )
            )
            first = self.invoke("ingest", str(pdf_file), ai_config=ai_config)
            second = self.invoke("ingest", str(pdf_file), ai_config=ai_config)

        self.assertEqual(first.exit_code, 0, first.output)
        self.assertEqual(second.exit_code, 0, second.output)
        with sqlite3.connect(self.vault / "graph.db") as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM notes WHERE lower(title) = lower(?)",
                ("Repeated Entity",),
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_phase2_schema_migration_updates_phase1_vault(self) -> None:
        self.vault.mkdir(parents=True, exist_ok=True)
        (self.vault / "notes").mkdir(exist_ok=True)
        (self.vault / "system").mkdir(exist_ok=True)
        (self.vault / "system" / "review-queue.md").write_text("", encoding="utf-8")
        db_path = self.vault / "graph.db"
        with sqlite3.connect(db_path) as connection:
            connection.executescript(
                """
                CREATE TABLE notes (
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

                CREATE TABLE edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    weight REAL NOT NULL,
                    created TEXT NOT NULL,
                    PRIMARY KEY (source_id, target_id, type)
                );
                """
            )

        result = self.invoke("init")

        self.assertEqual(result.exit_code, 0, result.output)
        with sqlite3.connect(db_path) as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(notes)").fetchall()]
        self.assertIn("source_chunk_index", columns)
        self.assertIn("confidence", columns)
        self.assertIn("rationale", columns)
