from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request

from roojai.config import AIConfig
from roojai.ingest.prompts import build_extraction_prompt


class ExtractionUnavailableError(RuntimeError):
    pass


@dataclass
class ExtractionResult:
    entities: list[dict[str, object]]
    edges: list[dict[str, object]]
    claims: list[dict[str, object]]
    raw_response: dict[str, object]


def extract_chunk(chunk_text: str, config: AIConfig) -> ExtractionResult:
    if not config.gemini_api_key:
        raise ExtractionUnavailableError("Gemini API key is not configured.")

    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"gemini-1.5-flash:generateContent?key={config.gemini_api_key}"
    )
    payload = {
        "contents": [{"parts": [{"text": build_extraction_prompt(chunk_text)}]}],
        "generationConfig": {"responseMimeType": "application/json"},
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise ExtractionUnavailableError("Gemini extraction is unavailable.") from exc

    text = _extract_response_text(raw)
    try:
        parsed = json.loads(_strip_code_fences(text))
    except json.JSONDecodeError as exc:
        raise ValueError("Gemini returned invalid extraction JSON.") from exc

    return ExtractionResult(
        entities=_normalize_list(parsed.get("entities")),
        edges=_normalize_list(parsed.get("edges")),
        claims=_normalize_list(parsed.get("claims")),
        raw_response=raw,
    )


def _extract_response_text(raw: dict[str, object]) -> str:
    try:
        candidates = raw["candidates"]
        first_candidate = candidates[0]
        parts = first_candidate["content"]["parts"]
        return "".join(str(part.get("text", "")) for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError("Gemini response did not contain extractable text.") from exc


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        return "\n".join(lines).strip()
    return stripped


def _normalize_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
