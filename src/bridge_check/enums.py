"""Single definition of every machine enum (contract §1, §2, §6, §8; guide L-01).

Every other module imports these names; no enum value is written twice by hand. Values
are plain strings so they can be used in Pydantic `Literal` types, YAML tables and, later,
SQLite `CHECK` constraints (contract §11).
"""

from __future__ import annotations

from typing import Literal

# --- Status codes (contract §1) ----------------------------------------------------

Status = Literal["supported", "not_supported", "insufficient", "conflict", "review"]
STATUS_CODES: tuple[str, ...] = ("supported", "not_supported", "insufficient", "conflict", "review")

# --- Condition and sub-result IDs (contract §2) --------------------------------------

CONDITION_IDS: tuple[str, ...] = (
    "age_18",
    "bmi_path_a",
    "bmi_path_b",
    "bmi_path_b.bmi",
    "bmi_path_b.hfpef",
    "bmi_path_b.htn",
    "bmi_path_b.ckd",
    "bmi_path_c",
    "bmi_path_c.bmi",
    "bmi_path_c.prediabetes",
    "bmi_path_c.mi",
    "bmi_path_c.stroke",
    "bmi_path_c.pad",
    "exclusion.t2dm",
    "exclusion.osa",
    "exclusion.mash",
    "exclusion.part_d_glp1",
    "patient_identity",
    "lifestyle.nutrition",
    "lifestyle.activity",
)
"""Every fixed condition ID. `claim.<id>` entries are dynamic and are not rules-table rows."""

EXCLUSION_IDS: tuple[str, ...] = tuple(i for i in CONDITION_IDS if i.startswith("exclusion."))
CLAIM_PREFIX = "claim."

# --- Assertion axes (contract §6) ----------------------------------------------------

Certainty = Literal["present", "negated", "uncertain"]
Subject = Literal["patient", "family", "other"]
Temporality = Literal["current", "historical", "resolved", "hypothetical"]
CERTAINTY: tuple[str, ...] = ("present", "negated", "uncertain")
SUBJECT: tuple[str, ...] = ("patient", "family", "other")
TEMPORALITY: tuple[str, ...] = ("current", "historical", "resolved", "hypothetical")
AXES: dict[str, tuple[str, ...]] = {
    "certainty": CERTAINTY,
    "subject": SUBJECT,
    "temporality": TEMPORALITY,
}
AXIS_DEFAULTS: dict[str, str] = {
    "certainty": "present",
    "subject": "patient",
    "temporality": "current",
}

# --- Flags (contract §6) -------------------------------------------------------------

FLAGS: tuple[str, ...] = (
    "id_missing",
    "inconsistent_values",
    "imprecise_source",
    "table_source",
    "timing_disagreement",
    "combination_pill",
    "class_ambiguous",
    "cv_history_only",
    "boundary_value",
    "unrecognized",
    "ambiguous_match",
    "post_initiation_exclusion",
    "same_note_list",
    "height_from_other_date",
    "uncovered_keyword",
)

# --- Documents (contract §6, §7.1) ----------------------------------------------------

DocRole = Literal["clinical", "referral", "pa_draft"]
DOC_ROLES: tuple[str, ...] = ("clinical", "referral", "pa_draft")
DocOrigin = Literal["mtsamples", "case_report", "authored"]
DOC_ORIGINS: tuple[str, ...] = ("mtsamples", "case_report", "authored")
MTSAMPLES_DOC_ID_PREFIX = "D2-mtsamples"

# --- Extraction fields (contract §7.2) -------------------------------------------------

EXTRACTION_FIELDS: tuple[str, ...] = (
    "patient_identity",
    "doc_dates",
    "glp1_start",
    "prior_glp1",
    "anthropometrics",
    "bp_readings",
    "labs",
    "medications",
    "medication_lists",
    "diagnoses",
    "lifestyle",
    "pa_form_claims",
)

# --- Gold (contract §8) ----------------------------------------------------------------

GoldOrigin = Literal["spec", "model_candidate", "keyword_scan", "human_inventory"]
GOLD_ORIGINS: tuple[str, ...] = ("spec", "model_candidate", "keyword_scan", "human_inventory")
GOLD_REVIEW = "human_verified"
RelativeToInitiation = Literal["at", "before", "after", "unknown"]
RELATIVE_TO_INITIATION: tuple[str, ...] = ("at", "before", "after", "unknown")

# --- Blind draft and adjudication log (guide §9, §10) ---------------------------------

Presence = Literal["present", "absent", "unsure"]
PRESENCE: tuple[str, ...] = ("present", "absent", "unsure")
AdjudicationItem = Literal["fact", "condition"]
Decision = Literal["accept", "modify", "reject", "add", "absent"]
ADJUDICATION_DECISIONS: tuple[str, ...] = ("accept", "modify", "reject", "add", "absent")
IdentityMatch = Literal["match", "mismatch", "missing"]
IDENTITY_MATCH: tuple[str, ...] = ("match", "mismatch", "missing")
GUIDELINE_CLAUSE_PATTERN = r"^[PSATCKGWBLUR]-\d\d$"

# L-01 allow-list for `candidate` and `final`: position keys refer to the quote by offsets
# only; value keys are the normalized values. Everything else is never written.
POSITION_KEYS: tuple[str, ...] = ("doc_id", "start", "end", "sha8")
VALUE_KEYS: tuple[str, ...] = (
    "field",
    "kind",
    "concept",
    "norm_value",
    "norm_unit",
    "sbp",
    "dbp",
    "event_date",
    "date_precision",
    "period_start",
    "period_end",
    "end_kind",
    "certainty",
    "subject",
    "temporality",
    "relative_to_glp1_initiation",
    "drug_canonical",
    "program_type",
    "attendance",
    "osa_severity",
    "ahi",
    "fibrosis_stage",
    "cirrhosis",
    "ckd_stage",
    "symptomatic",
    "payer",
    "purpose",
    "claim_id",
    "claimed_value",
    "target_doc_id",
    "date",
    "status",
    "identity_match",
)
ALLOWED_ENTRY_KEYS: frozenset[str] = frozenset(POSITION_KEYS) | frozenset(VALUE_KEYS)
FORBIDDEN_ENTRY_KEYS: tuple[str, ...] = (
    "quote",
    "raw_value",
    "raw_unit",
    "description",
    "indication",
    "section_title",
    "name",
    "patient_id",
    "dob",
)
SCAN_HIT_KEYS: tuple[str, ...] = ("doc_id", "start", "end", "sha8", "term")

# --- Controlled vocabularies of value keys (contract §6, §7.2, §8) ----------------------

SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
KINDS: tuple[str, ...] = (
    "height",
    "weight",
    "bmi",
    "bmi_percentile",
    "a1c",
    "fpg",
    "egfr",
    "nutrition",
    "activity",
)
CONCEPTS: tuple[str, ...] = (
    "t2dm",
    "prediabetes",
    "osa",
    "mash",
    "hfpef",
    "ckd",
    "mi",
    "stroke",
    "pad",
    "hypertension",
    "other",
)
NORM_UNITS: tuple[str, ...] = ("cm", "kg", "kg/m2", "mmHg", "%", "mg/dL", "mL/min/1.73m2")
PAYERS: tuple[str, ...] = ("part_d", "medicaid", "self_pay", "bridge", "commercial", "unknown")
PURPOSES: tuple[str, ...] = ("weight", "mace", "other", "unknown")
END_KINDS: tuple[str, ...] = ("ongoing", "ended", "unknown")
OSA_SEVERITIES: tuple[str, ...] = ("mild", "moderate", "severe", "unspecified")
SYMPTOMATIC: tuple[str, ...] = ("yes", "no", "unknown")
PROGRAM_TYPES: tuple[str, ...] = (
    "structured_clinical",
    "commercial",
    "advice_only",
    "referral_pending",
    "declined",
    "none_stated",
)
ATTENDANCE: tuple[str, ...] = ("regular", "irregular", "unknown")
DATE_PRECISIONS: tuple[str, ...] = ("day", "month", "year")
FIBROSIS_STAGE_PATTERN = r"^F[0-4]$"
CKD_STAGE_PATTERN = r"^(1|2|3a|3b|4|5)$"
# Claim IDs (contract §2): one per PA-form checkbox, named after what it is checked against.
CLAIM_IDS: tuple[str, ...] = (
    "claim.drug",
    "claim.bmi_bracket",
    *(f"claim.{cid}" for cid in CONDITION_IDS),
)
# A claimed value is the box or bracket as written (guide K-02, K-04), never prose. Which
# shapes are allowed depends on the claim: a box token, a BMI bracket (`<27`, `30-34.9`,
# `35+`, `≥40`) or a GLP-1 drug name (`claim.drug`).
CLAIMED_VALUE_TOKENS: tuple[str, ...] = ("yes", "no", "checked", "unchecked", "unknown")
BMI_BRACKET_PATTERN = r"^(<\d{2}|\d{2}(\.\d)?-\d{2}(\.\d)?|\d{2}\+|≥\d{2})$"
# GLP-1 drugs named in the guide (W-01): canonical generic names for glp1_start /
# prior_glp1, and every name (generic or brand) a PA form may carry under `claim.drug`.
GLP1_CANONICALS: tuple[str, ...] = ("semaglutide", "tirzepatide", "liraglutide")
GLP1_NAMES: tuple[str, ...] = (
    *GLP1_CANONICALS,
    "Wegovy",
    "Ozempic",
    "Zepbound",
    "Mounjaro",
    "Saxenda",
    "Foundayo",
)

ENUM_VALUE_KEYS: dict[str, tuple[str, ...]] = {
    "field": EXTRACTION_FIELDS,
    "kind": KINDS,
    "concept": CONCEPTS,
    "norm_unit": NORM_UNITS,
    "certainty": CERTAINTY,
    "subject": SUBJECT,
    "temporality": TEMPORALITY,
    "relative_to_glp1_initiation": RELATIVE_TO_INITIATION,
    "payer": PAYERS,
    "purpose": PURPOSES,
    "end_kind": END_KINDS,
    "osa_severity": OSA_SEVERITIES,
    "symptomatic": SYMPTOMATIC,
    "program_type": PROGRAM_TYPES,
    "attendance": ATTENDANCE,
    "status": STATUS_CODES,
    "identity_match": IDENTITY_MATCH,
    "date_precision": DATE_PRECISIONS,
}
NUMERIC_VALUE_KEYS: tuple[str, ...] = ("norm_value", "sbp", "dbp", "ahi")
DATE_VALUE_KEYS: tuple[str, ...] = ("event_date", "date", "period_start", "period_end")

# --- Run state and storage (contract §1, §2, §6, §11) ------------------------------------

RunStatus = Literal["running", "completed", "failed"]
RUN_STATUSES: tuple[str, ...] = ("running", "completed", "failed")
FailedStage = Literal[
    "input", "extract", "parse", "verify", "compute", "rules", "store", "interrupted"
]
FAILED_STAGES: tuple[str, ...] = (
    "input",
    "extract",
    "parse",
    "verify",
    "compute",
    "rules",
    "store",
    "interrupted",
)
# A run may be asked to stop at a stage boundary (CLI `--stop-after`, tests only).
STOP_AFTER_STAGES: tuple[str, ...] = ("extract", "verify")
AttemptStatus = Literal[
    "started",
    "response_saved",
    "parsed",
    "parse_failed",
    "refused",
    "truncated",
    "api_error",
    "unknown_outcome",
]
ATTEMPT_STATUSES: tuple[str, ...] = (
    "started",
    "response_saved",
    "parsed",
    "parse_failed",
    "refused",
    "truncated",
    "api_error",
    "unknown_outcome",
)
PARSE_CLASS_ATTEMPT_STATUSES: tuple[str, ...] = ("parse_failed", "refused", "truncated")
# Where a run's extraction came from (contract §11 lookup order).
ExtractionSource = Literal["cache", "replay", "api"]
EXTRACTION_SOURCES: tuple[str, ...] = ("cache", "replay", "api")
POSITION_STATUSES: tuple[str, ...] = ("verbatim", "normalized", "candidate", "not_found")
ASSERTION_CHECKS: tuple[str, ...] = ("matched", "mismatch", "unrecognized")
DECISION_KINDS: tuple[str, ...] = ("condition", "path", "sub", "exclusion", "lifestyle", "claim")
EVIDENCE_EXCLUSION_REASONS: tuple[str, ...] = (
    "quote_not_found",
    "value_not_in_quote",
    "assertion_mismatch",
    "wrong_patient",
    "unparseable_value",
    "claim_document",
)
CONDITION_EXCLUSION_REASONS: tuple[str, ...] = (
    "after_initiation",
    "before_initiation",
    "timing_unknown",
    "period_unknown",
    "candidate_only",
    "superseded_by_at",
)

# --- Extraction output (contract §7.2) ------------------------------------------------------

DatePrecision = Literal["day", "month", "year"]
# §7.2 union-limit fallback, `event_date` only: no date is `""` with precision `none`.
ExtractionDatePrecision = Literal["day", "month", "year", "none"]
EXTRACTION_DATE_PRECISIONS: tuple[str, ...] = (*DATE_PRECISIONS, "none")
AnthropometricKind = Literal["height", "weight", "bmi", "bmi_percentile"]
LabKind = Literal["a1c", "fpg", "egfr"]
LifestyleKind = Literal["nutrition", "activity"]
Concept = Literal[
    "t2dm",
    "prediabetes",
    "osa",
    "mash",
    "hfpef",
    "ckd",
    "mi",
    "stroke",
    "pad",
    "hypertension",
    "other",
]
Payer = Literal["part_d", "medicaid", "self_pay", "bridge", "commercial", "unknown"]
Purpose = Literal["weight", "mace", "other", "unknown"]
EndKind = Literal["ongoing", "ended", "unknown"]
OsaSeverity = Literal["mild", "moderate", "severe", "unspecified"]
Symptomatic = Literal["yes", "no", "unknown"]
ProgramType = Literal[
    "structured_clinical",
    "commercial",
    "advice_only",
    "referral_pending",
    "declined",
    "none_stated",
]
Attendance = Literal["regular", "irregular", "unknown"]
