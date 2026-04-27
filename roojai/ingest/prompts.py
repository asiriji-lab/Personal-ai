from __future__ import annotations

import json


def build_extraction_prompt(chunk_text: str) -> str:
    schema = {
        "entities": [{"title": "Entity Title", "type": "concept|person|project|tool"}],
        "edges": [{"source_title": "Entity A", "target_title": "Entity B", "type": "RELATED_TO"}],
        "claims": [
            {
                "text": "A grounded claim from the source text.",
                "confidence": 0.8,
                "rationale": "Short explanation grounded in the source text.",
                "associated_entities": ["Entity A", "Entity B"],
            }
        ],
    }
    return (
        "Extract named entities, RELATED_TO edges, and grounded claims from the source text. "
        "Return JSON only. Use only the allowed entity types concept, person, project, tool. "
        "Claims must include associated_entities drawn from extracted entity titles.\n\n"
        f"Required JSON schema:\n{json.dumps(schema, indent=2)}\n\n"
        f"Source text:\n{chunk_text}"
    )


def build_validation_prompt(chunk_text: str, claim_text: str) -> str:
    return (
        'Answer whether the claim accurately reflects the source text. Return JSON only in the form '
        '{"verdict":"pass|fail","explanation":"..."}.\n\n'
        f"Claim:\n{claim_text}\n\n"
        f"Source text:\n{chunk_text}"
    )
