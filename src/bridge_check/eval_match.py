"""Gold matching, key comparison only (contract §8).

`is_match(gold, system)` says whether one system fact can match one gold fact: the three
assertion axes always, `event_date` whenever gold has one (a gold date is not a wildcard), and
the field-specific keys of the §8 table. Numeric values are compared as `Decimal`, with the §4
tolerances for BMI, weight and height and exactly for labs. One-to-one assignment and scoring
are not implemented here.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, InvalidOperation

AXES: tuple[str, ...] = ("certainty", "subject", "temporality")

MATCH_KEYS: dict[str, tuple[str, ...]] = {
    "anthropometrics": ("kind", "doc_id", "norm_value", "relative_to_glp1_initiation"),
    "labs": ("kind", "doc_id", "norm_value", "relative_to_glp1_initiation"),
    "bp_readings": ("doc_id", "sbp", "dbp", "relative_to_glp1_initiation"),
    "diagnoses": ("concept", "doc_id"),
    "medications": ("drug_canonical", "doc_id", "start", "end", "end_kind", "list_id"),
    "medication_lists": ("doc_id", "complete"),
    "glp1_start": ("drug_canonical", "date", "payer", "doc_id"),
    "prior_glp1": ("drug_canonical", "date", "payer", "doc_id"),
    "doc_dates": ("target_doc_id", "date"),
    "patient_identity": ("doc_id", "patient_id", "dob"),
    "lifestyle": ("kind", "program_type", "attendance", "end_kind", "doc_id"),
    "pa_form_claims": ("claim_id", "claimed_value"),
}
# Diagnosis attributes compared only when gold states them (contract §8).
DIAGNOSIS_OPTIONAL: tuple[str, ...] = (
    "osa_severity",
    "ahi",
    "fibrosis_stage",
    "cirrhosis",
    "ckd_stage",
    "symptomatic",
)
_TOLERANCE_ABS: dict[str, Decimal] = {"bmi": Decimal("0.2"), "height": Decimal("1")}
_TOLERANCE_REL: dict[str, Decimal] = {"weight": Decimal("0.01")}


def match_keys(field: str) -> tuple[str, ...]:
    """Every key that must agree for `field`, the three axes included."""
    return (*AXES, "field", *MATCH_KEYS[field])


def _decimal(value: object) -> Decimal | None:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _values_equal(kind: str | None, gold: object, system: object) -> bool:
    g, s = _decimal(gold), _decimal(system)
    if g is None or s is None:
        return False
    if kind in _TOLERANCE_ABS:
        return abs(g - s) <= _TOLERANCE_ABS[kind]
    if kind in _TOLERANCE_REL and g != 0:
        return abs(g - s) / abs(g) <= _TOLERANCE_REL[kind]
    return g == s


def is_match(gold: Mapping[str, object], system: Mapping[str, object]) -> bool:
    field = str(gold.get("field", ""))
    if field not in MATCH_KEYS:
        return False
    for key in match_keys(field):
        if key == "norm_value":
            kind = gold.get("kind")
            if not _values_equal(
                str(kind) if kind is not None else None, gold.get(key), system.get(key)
            ):
                return False
        elif gold.get(key) != system.get(key):
            return False
    if (
        "event_date" in gold
        and gold["event_date"] is not None
        and gold["event_date"] != system.get("event_date")
    ):
        return False
    if field == "diagnoses":
        for key in DIAGNOSIS_OPTIONAL:
            if gold.get(key) not in (None, "") and gold.get(key) != system.get(key):
                return False
    return True
