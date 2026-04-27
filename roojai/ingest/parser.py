from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from roojai.config import AIConfig, VaultPaths
from roojai.core.markdown import (
    extract_headings,
    extract_wiki_links,
    parse_markdown_file,
    serialize_note,
)
from roojai.core.models import ALLOWED_ENTITY_NOTE_TYPES, Note, utc_now_iso
from roojai.core.store import NoteStore
from roojai.ingest.extractor import ExtractionUnavailableError, extract_chunk
from roojai.ingest.pdf import extract_pdf_text
from roojai.ingest.validator import ValidationUnavailableError, validate_claim


@dataclass
class IngestResult:
    primary_note: Note | None
    entities_created: int
    review_items_added: int


def ingest_file(paths: VaultPaths, store: NoteStore, source_file: Path, config: AIConfig) -> IngestResult:
    suffix = source_file.suffix.lower()
    if suffix == ".md":
        return ingest_markdown_with_ai(paths, store, source_file, config)
    if suffix == ".txt":
        return ingest_text_document(paths, store, source_file, config)
    if suffix == ".pdf":
        return ingest_pdf_document(paths, store, source_file, config)
    raise ValueError(f"Unsupported file type: {source_file.suffix}")


def ingest_markdown_with_ai(
    paths: VaultPaths,
    store: NoteStore,
    source_file: Path,
    config: AIConfig,
) -> IngestResult:
    note = ingest_markdown_file(paths, store, source_file)
    if not config.gemini_api_key:
        return IngestResult(primary_note=note, entities_created=0, review_items_added=0)
    try:
        entities_created, review_items_added = _run_ai_ingest(
            paths=paths,
            store=store,
            source_file=source_file,
            raw_text=note.content,
            config=config,
        )
    except ExtractionUnavailableError:
        return IngestResult(primary_note=note, entities_created=0, review_items_added=0)
    return IngestResult(
        primary_note=note,
        entities_created=entities_created,
        review_items_added=review_items_added,
    )


def ingest_text_document(
    paths: VaultPaths,
    store: NoteStore,
    source_file: Path,
    config: AIConfig,
) -> IngestResult:
    if not config.gemini_api_key:
        raise ExtractionUnavailableError("Gemini extraction is unavailable for non-Markdown ingest.")
    raw_text = source_file.read_text(encoding="utf-8")
    entities_created, review_items_added = _run_ai_ingest(
        paths=paths,
        store=store,
        source_file=source_file,
        raw_text=raw_text,
        config=config,
    )
    return IngestResult(primary_note=None, entities_created=entities_created, review_items_added=review_items_added)


def ingest_pdf_document(
    paths: VaultPaths,
    store: NoteStore,
    source_file: Path,
    config: AIConfig,
) -> IngestResult:
    if not config.gemini_api_key:
        raise ExtractionUnavailableError("Gemini extraction is unavailable for non-Markdown ingest.")
    raw_text = extract_pdf_text(source_file)
    entities_created, review_items_added = _run_ai_ingest(
        paths=paths,
        store=store,
        source_file=source_file,
        raw_text=raw_text,
        config=config,
    )
    return IngestResult(primary_note=None, entities_created=entities_created, review_items_added=review_items_added)


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
            append_stub_review_queue_item(paths.review_queue_path, target, note)
        store.insert_edge(note.id, target.id)

    return note


def append_stub_review_queue_item(review_queue_path: Path, stub_note: Note, source_note: Note) -> None:
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


def _run_ai_ingest(
    paths: VaultPaths,
    store: NoteStore,
    source_file: Path,
    raw_text: str,
    config: AIConfig,
) -> tuple[int, int]:
    entities_created = 0
    review_items_added = 0
    source_path = str(source_file.resolve())

    for chunk_index, chunk_text in enumerate(_chunk_text(raw_text)):
        extraction = extract_chunk(chunk_text, config)
        _append_log_entry(
            paths.extraction_log_path,
            {
                "kind": "extraction",
                "source_path": source_path,
                "chunk_index": chunk_index,
                "response": extraction.raw_response,
            },
        )

        claim_records = _build_claim_records(chunk_text, extraction.claims, config, paths, source_path, chunk_index)
        review_items_added += len(claim_records)

        entity_confidence_map = _entity_confidence_map(extraction.claims)
        title_to_note = _resolve_entities(
            paths=paths,
            store=store,
            source_path=source_path,
            chunk_index=chunk_index,
            entities=extraction.entities,
            entity_confidence_map=entity_confidence_map,
        )
        entities_created += sum(1 for note in title_to_note.values() if note.created == note.updated and note.status == "pending_review" and note.source_path == source_path and note.source_chunk_index == chunk_index)

        for edge in extraction.edges:
            source_title = str(edge.get("source_title", "")).strip()
            target_title = str(edge.get("target_title", "")).strip()
            if not source_title or not target_title:
                continue
            source_note = title_to_note.get(_normalize_title(source_title)) or _resolve_or_create_entity_note(
                paths=paths,
                store=store,
                source_path=source_path,
                chunk_index=chunk_index,
                title=source_title,
                entity_type="concept",
                confidence=entity_confidence_map.get(_normalize_title(source_title), 0.5),
                rationale=None,
            )
            target_note = title_to_note.get(_normalize_title(target_title)) or _resolve_or_create_entity_note(
                paths=paths,
                store=store,
                source_path=source_path,
                chunk_index=chunk_index,
                title=target_title,
                entity_type="concept",
                confidence=entity_confidence_map.get(_normalize_title(target_title), 0.5),
                rationale=None,
            )
            title_to_note[_normalize_title(source_title)] = source_note
            title_to_note[_normalize_title(target_title)] = target_note
            store.insert_edge(source_note.id, target_note.id)

        for claim_record in claim_records:
            append_claim_review_queue_item(
                paths.review_queue_path,
                source_path=source_path,
                chunk_index=chunk_index,
                claim_text=claim_record["text"],
                confidence=claim_record["confidence"],
                verdict=claim_record["verdict"],
                explanation=claim_record["explanation"],
            )

    return entities_created, review_items_added


def _build_claim_records(
    chunk_text: str,
    claims: list[dict[str, object]],
    config: AIConfig,
    paths: VaultPaths,
    source_path: str,
    chunk_index: int,
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for claim in claims:
        text = str(claim.get("text", "")).strip()
        if not text:
            continue
        confidence = _coerce_confidence(claim.get("confidence"), default=0.5)
        rationale = str(claim.get("rationale", "")).strip()
        try:
            validation = validate_claim(chunk_text, text, config)
            verdict = validation.verdict
            explanation = validation.explanation
            _append_log_entry(
                paths.extraction_log_path,
                {
                    "kind": "validation",
                    "source_path": source_path,
                    "chunk_index": chunk_index,
                    "claim_text": text,
                    "response": validation.raw_response,
                },
            )
        except (ValidationUnavailableError, ValueError):
            verdict = "skipped"
            explanation = "Validation skipped because the local validator was unavailable or returned invalid output."
        records.append(
            {
                "text": text,
                "confidence": confidence,
                "verdict": verdict,
                "explanation": explanation or rationale,
            }
        )
    return records


def _resolve_entities(
    paths: VaultPaths,
    store: NoteStore,
    source_path: str,
    chunk_index: int,
    entities: list[dict[str, object]],
    entity_confidence_map: dict[str, float],
) -> dict[str, Note]:
    resolved: dict[str, Note] = {}
    for entity in entities:
        title = str(entity.get("title", "")).strip()
        if not title:
            continue
        normalized_title = _normalize_title(title)
        entity_type = str(entity.get("type", "")).strip().lower()
        confidence = entity_confidence_map.get(normalized_title, 0.5)
        note = _resolve_or_create_entity_note(
            paths=paths,
            store=store,
            source_path=source_path,
            chunk_index=chunk_index,
            title=title,
            entity_type=entity_type,
            confidence=confidence,
            rationale=None,
        )
        resolved[normalized_title] = note
    return resolved


def _resolve_or_create_entity_note(
    paths: VaultPaths,
    store: NoteStore,
    source_path: str,
    chunk_index: int,
    title: str,
    entity_type: str,
    confidence: float,
    rationale: str | None,
) -> Note:
    existing = store.get_note_by_normalized_title(title)
    if existing is not None:
        return existing
    note_type = entity_type if entity_type in ALLOWED_ENTITY_NOTE_TYPES else "concept"
    note = Note.new(
        title=title,
        note_type=note_type,
        source_path=source_path,
        source_chunk_index=chunk_index,
        confidence=confidence,
        rationale=rationale,
        status="pending_review",
        content="",
    )
    note.file_path = paths.note_path_for_id(note.id)
    store.insert_note(note)
    note.file_path.write_text(serialize_note(note), encoding="utf-8")
    return note


def append_claim_review_queue_item(
    review_queue_path: Path,
    source_path: str,
    chunk_index: int,
    claim_text: str,
    confidence: float,
    verdict: str,
    explanation: str,
) -> None:
    item = (
        f'- [ ] Review claim: "{claim_text}"\n'
        f"  source_path: {source_path}\n"
        f"  chunk_index: {chunk_index}\n"
        f"  confidence: {confidence:.2f}\n"
        f"  validator_verdict: {verdict}\n"
        f"  validator_explanation: {explanation}\n"
        f"  created: {utc_now_iso()}\n"
    )
    with review_queue_path.open("a", encoding="utf-8") as handle:
        if review_queue_path.stat().st_size > 0:
            handle.write("\n")
        handle.write(item)


def _append_log_entry(log_path: Path, entry: dict[str, object]) -> None:
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _chunk_text(raw_text: str) -> list[str]:
    text = raw_text.strip()
    if not text:
        return []
    headings = extract_headings(text)
    if headings:
        chunks = [chunk.strip() for chunk in text.split("\n#") if chunk.strip()]
        if len(chunks) > 1:
            normalized: list[str] = []
            for index, chunk in enumerate(chunks):
                normalized.append(chunk if index == 0 else "#" + chunk)
            return normalized
    paragraphs = [block.strip() for block in text.split("\n\n") if block.strip()]
    return paragraphs or [text]


def _entity_confidence_map(claims: list[dict[str, object]]) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for claim in claims:
        confidence = _coerce_confidence(claim.get("confidence"), default=0.5)
        associated = claim.get("associated_entities")
        if not isinstance(associated, list):
            continue
        for title in associated:
            normalized = _normalize_title(str(title))
            if not normalized:
                continue
            mapping[normalized] = max(mapping.get(normalized, 0.0), confidence)
    return mapping


def _coerce_confidence(value: object, default: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, confidence))


def _normalize_title(title: str) -> str:
    return title.strip().lower()


def _normalize_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []
