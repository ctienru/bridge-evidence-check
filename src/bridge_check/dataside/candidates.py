"""Route 2: candidate facts proposed on real text, located and sanitized (05 §5.2 step 2).

The proposing model returns candidates with a `quote` and value keys. `locate_candidate`
finds the quote verbatim (`text.locate`): exactly one hit gives `start`, `end`, `sha8`;
zero or several hits keep the candidate with null offsets and a `location` marker
(`not_found` / `ambiguous`). A candidate lacking a valid `doc_id`, `field` or any of the
three axes is `invalid` and never receives offsets, so it cannot cover a keyword hit.
`sanitize` keeps only the L-01 allow-list keys plus
`location`, so no quote or other free text reaches the public candidates file. The full
raw response is saved separately by the script (private repo).
"""

from __future__ import annotations

import json
from typing import Any

from bridge_check.enums import ALLOWED_ENTRY_KEYS, POSITION_KEYS
from bridge_check.gold_schema import claimed_value_problem, value_problem
from bridge_check.text import locate, sha8

LOCATION_KEY = "location"
# JSON mode requires the word JSON in the messages; never rely on the private prompt for it.
JSON_INSTRUCTION = (
    "Respond with a single JSON object in exactly the output_format given; "
    "output JSON only, no prose."
)
LOCATED = "located"
NOT_FOUND = "not_found"
AMBIGUOUS = "ambiguous"
INVALID = "invalid"
# A candidate gets offsets (and may cover scan hits) only with these keys present and valid,
# plus the keys its `field` needs for matching (contract §8 table).
REQUIRED_KEYS: tuple[str, ...] = ("doc_id", "field", "certainty", "subject", "temporality")
REQUIRED_BY_FIELD: dict[str, tuple[str, ...]] = {
    "anthropometrics": ("kind", "norm_value", "norm_unit"),
    "labs": ("kind", "norm_value", "norm_unit"),
    "lifestyle": ("kind",),
    "diagnoses": ("concept",),
    "bp_readings": ("sbp", "dbp"),
    "medications": ("drug_canonical",),
    "glp1_start": ("drug_canonical",),
    "prior_glp1": ("drug_canonical",),
    "doc_dates": ("target_doc_id", "date"),
    "pa_form_claims": ("claim_id", "claimed_value"),
    # identity_match is the annotator's comparison against input.yaml, not the model's
    "patient_identity": (),
    "medication_lists": (),
}
OUTPUT_KEYS: frozenset[str] = ALLOWED_ENTRY_KEYS | {LOCATION_KEY}


def _nullable(*types: str) -> dict[str, Any]:
    return {"type": [*types, "null"]}


# Strict structured output: every property is required and nullable, so the model fills
# what applies and nulls the rest. Only allow-list value keys plus `quote` are offered.
CANDIDATE_PROPERTIES: dict[str, dict[str, Any]] = {
    "doc_id": {"type": "string"},
    "field": {"type": "string"},
    "quote": {"type": "string"},
    "certainty": {"type": "string"},
    "subject": {"type": "string"},
    "temporality": {"type": "string"},
    "kind": _nullable("string"),
    "concept": _nullable("string"),
    "event_date": _nullable("string"),
    "norm_value": _nullable("number"),
    "norm_unit": _nullable("string"),
    "sbp": _nullable("integer"),
    "dbp": _nullable("integer"),
    "drug_canonical": _nullable("string"),
    "period_start": _nullable("string"),
    "period_end": _nullable("string"),
    "end_kind": _nullable("string"),
    "program_type": _nullable("string"),
    "attendance": _nullable("string"),
    "osa_severity": _nullable("string"),
    "ahi": _nullable("number"),
    "fibrosis_stage": _nullable("string"),
    "cirrhosis": _nullable("boolean"),
    "ckd_stage": _nullable("string"),
    "symptomatic": _nullable("string"),
    "payer": _nullable("string"),
    "purpose": _nullable("string"),
    "claim_id": _nullable("string"),
    "claimed_value": _nullable("string", "boolean"),
    "target_doc_id": _nullable("string"),
    "date": _nullable("string"),
    "relative_to_glp1_initiation": _nullable("string"),
}
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["candidates"],
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": list(CANDIDATE_PROPERTIES),
                "properties": CANDIDATE_PROPERTIES,
            },
        }
    },
}
assert set(CANDIDATE_PROPERTIES) - {"quote"} <= ALLOWED_ENTRY_KEYS


def sanitize(candidate: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Keep only L-01 allow-list keys whose values have their controlled shape.

    Returns the kept entries and the number of dropped keys. Position keys are set by
    `locate_candidate`, so they are dropped here too. Nothing a model could type freely
    (prose under `kind`, a nested object under `claimed_value`, ...) survives.
    """
    kept: dict[str, Any] = {}
    dropped = 0
    candidate = {k: v for k, v in candidate.items() if v is not None}  # schema nulls = absent
    for key, value in candidate.items():
        if key == "claimed_value":
            continue  # judged below, together with claim_id
        if (
            key in ALLOWED_ENTRY_KEYS
            and key not in POSITION_KEYS
            and value_problem(key, value) is None
        ):
            kept[key] = value
        else:
            dropped += 1
    if "claimed_value" in candidate:
        value = candidate["claimed_value"]
        if claimed_value_problem(kept.get("claim_id"), value) is None:
            kept["claimed_value"] = value
        else:
            dropped += 1
    return kept, dropped


def locate_candidate(docs: dict[str, str], candidate: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Resolve `quote` to offsets and return (sanitized line, number of dropped keys).

    `doc_id` and `target_doc_id` are kept only when they name a loaded document; the
    dropped count excludes `doc_id` and `quote`, which are always consumed here.
    """
    out, dropped = sanitize(candidate)
    doc_id = candidate.get("doc_id")
    doc = docs.get(doc_id, "") if isinstance(doc_id, str) else ""
    known = isinstance(doc_id, str) and doc_id in docs
    out["doc_id"] = doc_id if known else None
    if "target_doc_id" in out and out["target_doc_id"] not in docs:
        del out["target_doc_id"]
        dropped += 1
    for key in POSITION_KEYS[1:]:
        out[key] = None
    dropped -= (1 if "doc_id" in candidate else 0) + (1 if "quote" in candidate else 0)
    required = REQUIRED_KEYS + REQUIRED_BY_FIELD.get(str(out.get("field")), ())
    if any(out.get(key) is None for key in required):
        out[LOCATION_KEY] = INVALID  # no offsets: an invalid candidate must not cover a scan hit
        return out, dropped
    quote = candidate.get("quote")
    hits = locate(doc, quote) if isinstance(quote, str) else []
    if len(hits) == 1:
        start, end = hits[0]
        out.update({"start": start, "end": end, "sha8": sha8(doc[start:end])})
        out[LOCATION_KEY] = LOCATED
    elif hits:
        out[LOCATION_KEY] = AMBIGUOUS
    else:
        out[LOCATION_KEY] = NOT_FOUND
    return out, dropped


def extract_candidates(raw: Any) -> list[dict[str, Any]]:
    """Accept `{"candidates": [...]}` or a bare list; every item must be an object."""
    items = raw.get("candidates") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        raise ValueError("response must be a list of candidate objects (or {candidates: [...]})")
    return items


def build_messages(
    docs: dict[str, str], roles: dict[str, str], guide_text: str, prompt_text: str
) -> list[dict[str, str]]:
    """System = private prompt + annotation guide; user = the documents with doc_id/role."""
    payload = {
        "documents": [
            {"doc_id": doc_id, "role": roles.get(doc_id, "clinical"), "text": text}
            for doc_id, text in docs.items()
        ],
        "output_format": {
            "candidates": [
                {
                    "doc_id": "<doc_id>",
                    "field": "<extraction field>",
                    "kind|concept": "<as in the contract>",
                    "quote": "<verbatim quote>",
                    "certainty": "present|negated|uncertain",
                    "subject": "patient|family|other",
                    "temporality": "current|historical|resolved|hypothetical",
                    "event_date": "<YYYY[-MM[-DD]] or null>",
                    "...": "field-specific value keys",
                }
            ]
        },
    }
    return [
        {
            "role": "system",
            "content": prompt_text
            + "\n\n"
            + JSON_INSTRUCTION
            + "\n\n# Annotation guide\n\n"
            + guide_text,
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]
