from __future__ import annotations

import json
from dataclasses import dataclass
from urllib import error, request

from roojai.config import AIConfig
from roojai.ingest.prompts import build_validation_prompt


class ValidationUnavailableError(RuntimeError):
    pass


@dataclass
class ValidationResult:
    verdict: str
    explanation: str
    raw_response: dict[str, object]


def validate_claim(chunk_text: str, claim_text: str, config: AIConfig) -> ValidationResult:
    url = f"{config.ollama_url.rstrip('/')}/api/generate"
    payload = {
        "model": config.ollama_model,
        "prompt": build_validation_prompt(chunk_text, claim_text),
        "stream": False,
        "format": "json",
    }
    data = json.dumps(payload).encode("utf-8")
    req = request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with request.urlopen(req, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except error.URLError as exc:
        raise ValidationUnavailableError("Local validator is unavailable.") from exc

    response_text = raw.get("response")
    if not isinstance(response_text, str):
        raise ValueError("Validator response did not include JSON output.")
    try:
        parsed = json.loads(response_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Validator returned invalid JSON.") from exc

    verdict = str(parsed.get("verdict", "")).strip().lower()
    explanation = str(parsed.get("explanation", "")).strip()
    if verdict not in {"pass", "fail"}:
        raise ValueError("Validator verdict must be pass or fail.")
    return ValidationResult(verdict=verdict, explanation=explanation, raw_response=raw)
