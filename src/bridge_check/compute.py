"""Deterministic computation over verified evidence (contract §4, §5, §7.3; guide T-02–T-09).

`compute(evidence, ctx)` reads `CheckedEvidence` only — never the extraction JSON and never
document text — and produces `ComputedFacts`, the only input of `rules.py`. Step 0 of every
decision table happens here: evidence with a non-empty `exclusion_reasons` (or not found) is
dropped; `candidate` positions are kept apart in `candidate_only` so that rules can list them
as excluded. Every value is a `Decimal`; nothing is rounded.

Timepoints: a fact with its own verified date (`event_date_source == "llm"`) is compared with
the initiation date by interval; a fact whose quote names a date but whose model date is empty
uses that quote date and never inherits; a fact with no date of its own inherits the verified
document date (`event_date_source = doc_dates:<evidence_id>`); everything else is `unknown`.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Literal

from bridge_check.enums import GLP1_CANONICALS, RelativeToInitiation
from bridge_check.rules_schema import ANTIHYPERTENSIVE_CLASSES, Drug, DrugTable
from bridge_check.verify import LOCATED, CheckedEvidence, parse_raw_number

# --- Dates ---------------------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class DateInterval:
    """An inclusive calendar interval at the precision the text gives (contract §5)."""

    start: date
    end: date
    precision: str

    @classmethod
    def parse(cls, iso: str | None) -> DateInterval | None:
        if not iso:
            return None
        parts = iso.split("-")
        try:
            if len(parts) == 1:
                y = int(parts[0])
                return cls(date(y, 1, 1), date(y, 12, 31), "year")
            if len(parts) == 2:
                y, m = int(parts[0]), int(parts[1])
                return cls(date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1]), "month")
            d = date.fromisoformat(iso)
        except ValueError:
            return None
        return cls(d, d, "day")

    @classmethod
    def day(cls, d: date) -> DateInterval:
        return cls(d, d, "day")

    def relative_to(self, initiation: DateInterval) -> RelativeToInitiation:
        """`at` only for the identical single day; wholly before / after; overlap → unknown."""
        if self.start == self.end == initiation.start == initiation.end:
            return "at"
        if self.end < initiation.start:
            return "before"
        if self.start > initiation.end:
            return "after"
        return "unknown"

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end

    def overlaps(self, other: DateInterval) -> bool:
        return self.start <= other.end and other.start <= self.end

    def iso(self) -> str:
        if self.precision == "year":
            return f"{self.start.year:04d}"
        if self.precision == "month":
            return f"{self.start.year:04d}-{self.start.month:02d}"
        return self.start.isoformat()

    def distance_days(self, d: date) -> int:
        if self.contains(d):
            return 0
        return min(abs((self.start - d).days), abs((self.end - d).days))


def years_between(birth: date, on: date) -> int:
    """Completed years of age on `on` for someone born on `birth`."""
    years = on.year - birth.year
    if (on.month, on.day) < (birth.month, birth.day):
        years -= 1
    return years


def shift_years(d: date, years: int) -> date:
    """`d` moved by `years` (29 February lands on 28 February)."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


# --- Evidence-side records ---------------------------------------------------------------------

TimepointSource = Literal["llm", "quote", "doc_date", "none"]


@dataclass(frozen=True)
class Timepoint:
    relative: RelativeToInitiation
    date: DateInterval | None
    source: TimepointSource
    source_evidence_id: int | None = None


@dataclass(frozen=True)
class Source:
    """What rules need from one evidence row: ids for `used_evidence`, flags for step 8, axes
    for diagnosis logic and the computed timepoint."""

    evidence_id: int
    ref: str
    doc_id: str
    field: str
    position_status: str
    flags: tuple[str, ...]
    certainty: str
    subject: str
    temporality: str
    tp: Timepoint

    @property
    def affirmed(self) -> bool:
        """The patient's own present or historical fact (contract §3.2)."""
        return (
            self.subject == "patient"
            and self.certainty == "present"
            and self.temporality in ("current", "historical")
        )

    @property
    def negated(self) -> bool:
        return self.subject == "patient" and self.certainty == "negated"


@dataclass(frozen=True)
class Initiation:
    date: DateInterval
    purpose: str
    drug_canonical: str
    src: Source
    drug_name: str = ""
    """The product or ingredient name as extracted, casefolded (a claim compares products)."""


@dataclass(frozen=True)
class AgeInterval:
    """Completed age in whole years on the reference date, as `[lo_years, hi_years]`."""

    lo_years: int
    hi_years: int
    origin: Literal["dob", "stated_age"]
    reference: Literal["initiation", "own_date"]
    src: Source

    def whole_at_least(self, years: int) -> bool:
        return self.lo_years >= years

    def whole_below(self, years: int) -> bool:
        return self.hi_years < years


@dataclass(frozen=True)
class AnthroValue:
    kind: str
    value: Decimal
    unit: str
    integer_only: bool
    src: Source


@dataclass(frozen=True)
class BmiCandidate:
    value: Decimal
    origin: Literal["stated", "computed"]
    integer_only: bool
    sources: tuple[Source, ...]
    tp: Timepoint
    flags: tuple[str, ...]

    @property
    def evidence_ids(self) -> tuple[int, ...]:
        return tuple(s.evidence_id for s in self.sources)

    @property
    def all_flags(self) -> frozenset[str]:
        return frozenset(self.flags) | {f for s in self.sources for f in s.flags}


@dataclass(frozen=True)
class BpReading:
    sbp: int
    dbp: int
    src: Source


@dataclass(frozen=True)
class MedPeriod:
    drug_canonical: str
    class_: str | None
    class_ambiguous: bool
    components: tuple[str, ...]
    recognized: bool
    start: DateInterval | None
    end: DateInterval | None
    end_kind: str
    list_id: str
    list_complete: bool | None
    in_use_on: tuple[DateInterval, ...]
    same_note_list: bool
    src: Source

    @property
    def antihypertensive(self) -> bool:
        return self.class_ in ANTIHYPERTENSIVE_CLASSES

    @property
    def agents(self) -> tuple[str, ...]:
        return self.components or (self.drug_canonical,)

    def certain_intervals(self) -> tuple[DateInterval, ...]:
        """Days on which the drug is certainly in use (`unknown_med_period: not_ongoing`):
        the latest possible start to the earliest possible end, and the exact days a current
        list places it on. An observation at month or year precision could have happened on
        the earliest day of that period, so it bounds nothing later than that day."""
        out = [iv for iv in self.in_use_on if iv.precision == "day"]
        lo: date | None = self.start.end if self.start else None
        hi: date | None = None
        if self.end is not None:
            hi = self.end.start - timedelta(days=1)
        elif self.end_kind == "ongoing" and self.src.tp.date is not None:
            hi = self.src.tp.date.start
        if lo is not None and hi is not None and lo <= hi:
            out.append(DateInterval(lo, hi, "day"))
        return tuple(out)

    def overlaps(self, day: DateInterval) -> bool:
        return any(iv.start <= day.start and day.end <= iv.end for iv in self.certain_intervals())


@dataclass(frozen=True)
class MedListRecord:
    list_id: str
    complete: bool
    src: Source


@dataclass(frozen=True)
class LabValue:
    kind: str
    value: Decimal
    unit: str
    src: Source


@dataclass(frozen=True)
class Dx:
    concept: str
    osa_severity: str
    ahi: Decimal | None
    fibrosis_stage: str
    cirrhosis: bool | None
    ckd_stage: str
    symptomatic: str
    src: Source


@dataclass(frozen=True)
class PriorGlp1Record:
    drug_canonical: str
    date: DateInterval | None
    payer: str
    compounded: bool | None
    src: Source


@dataclass(frozen=True)
class LifestyleRecord:
    kind: str
    program_type: str
    attendance: str
    start: DateInterval | None
    end: DateInterval | None
    end_kind: str
    has_limitation: bool
    applicable: bool
    distance_days: int | None
    src: Source


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    claimed_value: str
    src: Source


@dataclass(frozen=True)
class BmiBracket:
    lo: Decimal
    hi: Decimal | None

    def contains(self, value: Decimal) -> bool:
        return self.lo <= value and (self.hi is None or value < self.hi)

    def label(self) -> str:
        return f"[{self.lo},{self.hi})" if self.hi is not None else f">={self.lo}"


@dataclass(frozen=True)
class EvidenceUpdate:
    """Columns compute writes back onto one `evidence` row."""

    evidence_id: int
    relative_computed: RelativeToInitiation | None
    event_date_source: str | None
    event_date: str | None
    date_precision: str | None
    norm_value: str | None
    norm_unit: str | None
    flags: tuple[str, ...]
    exclusion_reasons: tuple[str, ...]


@dataclass(frozen=True)
class DocFactComputed:
    identity_status: str
    doc_date: DateInterval | None
    doc_date_evidence_id: int | None
    doc_date_disagreement: tuple[int, ...] = ()
    doc_date_src: Source | None = None
    """The verified `doc_dates` row; a decision that uses an inherited date lists it too."""


@dataclass(frozen=True)
class OverlapResult:
    """Antihypertensive periods around one reading (contract §3.2 step 3)."""

    unambiguous: tuple[MedPeriod, ...]
    ambiguous: tuple[MedPeriod, ...]
    period_unknown: tuple[MedPeriod, ...]
    complete_lists: tuple[Source, ...]

    def products(self) -> int:
        return len({p.drug_canonical for p in self.unambiguous})

    def agents(self) -> int:
        return len({a for p in self.unambiguous for a in p.agents})

    def products_with_ambiguous(self) -> int:
        return len({p.drug_canonical for p in (*self.unambiguous, *self.ambiguous)})


@dataclass(frozen=True)
class CaseContext:
    """Case input the program compares against (never sent to the model, contract §7.1)."""

    target_drug: str
    target_start: date
    assessment_date: date
    doc_roles: Mapping[str, str]
    doc_identity: Mapping[str, str]
    drugs: DrugTable
    evidence_ids: Sequence[int] | None = None


@dataclass(frozen=True)
class ComputedFacts:
    """The middle column of contract §7.3; attribute names are the rule `requires` names."""

    doc_facts: Mapping[str, DocFactComputed]
    wrong_patient: frozenset[str]
    initiation: Initiation | None
    age_interval_at_initiation: tuple[AgeInterval, ...]
    heights: tuple[AnthroValue, ...]
    weights: tuple[AnthroValue, ...]
    stated_bmis: tuple[AnthroValue, ...]
    bmi_candidates: tuple[BmiCandidate, ...]
    bp_readings: tuple[BpReading, ...]
    med_periods: tuple[MedPeriod, ...]
    medication_lists: tuple[MedListRecord, ...]
    a1c: tuple[LabValue, ...]
    fpg_mg_dl: tuple[LabValue, ...]
    egfr: tuple[LabValue, ...]
    dx: tuple[Dx, ...]
    prior_glp1: tuple[PriorGlp1Record, ...]
    lifestyle_applicable: tuple[LifestyleRecord, ...]
    bmi_bracket: BmiBracket | None
    bmi_bracket_ambiguous: bool
    claims: tuple[ClaimRecord, ...]
    candidate_only: tuple[Source, ...]
    case_flags: tuple[str, ...]
    evidence_updates: tuple[EvidenceUpdate, ...]
    assessment_date: date

    @property
    def initiation_date(self) -> DateInterval | None:
        return self.initiation.date if self.initiation else None

    @property
    def initiation_purpose(self) -> str | None:
        return self.initiation.purpose if self.initiation else None

    @property
    def bp_at_initiation(self) -> tuple[BpReading, ...]:
        return tuple(r for r in self.bp_readings if r.src.tp.relative == "at")

    def distinct_antihypertensives_overlapping(
        self, day: DateInterval, *, doc_id: str | None = None
    ) -> OverlapResult:
        """Antihypertensive periods certainly in use on `day`, deduplicated by rules through
        `drug_canonical`; `class` only says whether a drug is an antihypertensive."""
        unambiguous: list[MedPeriod] = []
        ambiguous: list[MedPeriod] = []
        unknown: list[MedPeriod] = []
        for p in self.med_periods:
            if not p.antihypertensive:
                continue
            if not p.overlaps(day):
                unknown.append(p)
            elif p.class_ambiguous:
                ambiguous.append(p)
            else:
                unambiguous.append(p)
        complete = tuple(
            m.src
            for m in self.medication_lists
            if m.complete and (doc_id is None or m.src.doc_id == doc_id)
        )
        return OverlapResult(tuple(unambiguous), tuple(ambiguous), tuple(unknown), complete)


# --- Value comparison (contract §4) ------------------------------------------------------------


@dataclass(frozen=True)
class Tolerance:
    abs: Decimal | None = None
    rel: Decimal | None = None


BMI_TOLERANCE = Tolerance(abs=Decimal("0.2"))
WEIGHT_TOLERANCE = Tolerance(rel=Decimal("0.01"))
HEIGHT_TOLERANCE = Tolerance(abs=Decimal("1"))
EXACT = Tolerance(abs=Decimal("0"))
AGE_TOLERANCE_YEARS = 1


@dataclass(frozen=True)
class ValueComparison:
    straddled: frozenset[Decimal]
    inconsistent: bool
    low: Decimal
    high: Decimal


def compare_values(
    values: Sequence[Decimal], thresholds: Iterable[Decimal], tol: Tolerance
) -> ValueComparison:
    """Threshold first, then tolerance: `straddled` holds every threshold with values on both
    sides (a value equal to the threshold is on the upper side); `inconsistent` is true when
    the spread exceeds the tolerance."""
    if not values:
        raise ValueError("compare_values needs at least one value")
    low, high = min(values), max(values)
    straddled = frozenset(t for t in thresholds if low < t <= high)
    spread = high - low
    inconsistent = False
    if tol.abs is not None and spread > tol.abs:
        inconsistent = True
    if tol.rel is not None and low > 0 and spread / low > tol.rel:
        inconsistent = True
    return ValueComparison(straddled, inconsistent, low, high)


def same_timepoint(a: Timepoint, b: Timepoint, same_doc: bool) -> bool:
    """Contract §4 "same fact": both `at`, overlapping date intervals, or both undated in the
    same document."""
    if a.relative == b.relative == "at":
        return True
    if a.date is not None and b.date is not None:
        return a.date.overlaps(b.date)
    return a.date is None and b.date is None and same_doc


# --- Units ---------------------------------------------------------------------------------------

_WEIGHT_UNITS: dict[str, Decimal] = {
    "kg": Decimal("1"),
    "kgs": Decimal("1"),
    "kilogram": Decimal("1"),
    "kilograms": Decimal("1"),
    "lb": Decimal("0.45359237"),
    "lbs": Decimal("0.45359237"),
    "pound": Decimal("0.45359237"),
    "pounds": Decimal("0.45359237"),
}
_HEIGHT_UNITS: dict[str, Decimal] = {
    "cm": Decimal("1"),
    "centimeter": Decimal("1"),
    "centimeters": Decimal("1"),
    "m": Decimal("100"),
    "meter": Decimal("100"),
    "meters": Decimal("100"),
    "in": Decimal("2.54"),
    "inch": Decimal("2.54"),
    "inches": Decimal("2.54"),
    '"': Decimal("2.54"),
    "ft": Decimal("30.48"),
    "feet": Decimal("30.48"),
    "foot": Decimal("30.48"),
    "'": Decimal("30.48"),
}
_BMI_UNITS = frozenset({"", "kg/m2", "kg/m²", "kg/m^2", "kg/m 2"})
_A1C_UNITS = frozenset({"", "%", "percent"})
_FPG_UNITS: dict[str, Decimal] = {
    "": Decimal("1"),
    "mg/dl": Decimal("1"),
    "g/l": Decimal("100"),
    "mmol/l": Decimal("18.016"),
}
NORM_UNIT: dict[str, str] = {
    "height": "cm",
    "weight": "kg",
    "bmi": "kg/m2",
    "a1c": "%",
    "fpg": "mg/dL",
    "egfr": "mL/min/1.73m2",
}


def _unit(raw_unit: str | None) -> str:
    return re.sub(r"\s+", " ", (raw_unit or "").strip().rstrip(".")).casefold()


def _decimal(raw_value: str | None) -> tuple[Decimal | None, bool]:
    """(value, integer_only) from a raw token; None when the token is not a plain number."""
    token = parse_raw_number(raw_value or "")
    if token is None or not token[:1].isdigit():
        return None, False
    return Decimal(token), "." not in token


def normalize_value(
    kind: str, raw_value: str | None, raw_unit: str | None
) -> tuple[Decimal, bool] | None:
    """The normalized value (contract §8 units) and whether the text gave only an integer."""
    value, integer_only = _decimal(raw_value)
    if value is None:
        return None
    unit = _unit(raw_unit)
    if kind == "weight":
        factor = _WEIGHT_UNITS.get(unit)
    elif kind == "height":
        factor = _HEIGHT_UNITS.get(unit)
    elif kind == "bmi":
        factor = Decimal("1") if unit in _BMI_UNITS else None
    elif kind == "a1c":
        factor = Decimal("1") if unit in _A1C_UNITS else None
    elif kind == "fpg":
        factor = _FPG_UNITS.get(unit)
    elif kind == "egfr":
        factor = Decimal("1") if unit == "" or unit.startswith("ml/min") else None
    else:
        return None
    if factor is None:
        return None
    return value * factor, integer_only and factor == 1


def bmi_from(weight_kg: Decimal, height_cm: Decimal) -> Decimal:
    metres = height_cm / Decimal("100")
    return weight_kg / (metres * metres)


BMI_BRACKET_EDGES: tuple[Decimal, ...] = tuple(Decimal(x) for x in ("27", "30", "35", "40"))


def bracket_of(value: Decimal) -> BmiBracket:
    """The half-open display bracket chosen from the unrounded value (contract §10)."""
    lo = Decimal("0")
    for edge in BMI_BRACKET_EDGES:
        if value < edge:
            return BmiBracket(lo, edge)
        lo = edge
    return BmiBracket(lo, None)


def parse_bracket(claimed: str) -> BmiBracket | None:
    """A PA-form bracket as written: `<27`, `30-34.9`, `35+`, `≥40` (guide K-04)."""
    text = claimed.strip().replace(" ", "")
    m = re.fullmatch(r"<(\d+(?:\.\d+)?)", text)
    if m:
        return BmiBracket(Decimal("0"), Decimal(m.group(1)))
    m = re.fullmatch(r"(\d+(?:\.\d+)?)-(\d+(?:\.\d+)?)", text)
    if m:
        hi_text = m.group(2)
        hi = Decimal(hi_text)
        # "30-34.9" means [30, 35): the written upper bound is the last displayed value
        decimals = len(hi_text.split(".")[1]) if "." in hi_text else 0
        step = Decimal(1).scaleb(-decimals)
        return BmiBracket(Decimal(m.group(1)), hi + step)
    m = re.fullmatch(r"(?:≥|>=)?(\d+(?:\.\d+)?)\+?", text)
    if m and (text.endswith("+") or text.startswith(("≥", ">="))):
        return BmiBracket(Decimal(m.group(1)), None)
    return None


# --- Drugs ---------------------------------------------------------------------------------------

GLP1_BRANDS: dict[str, str] = {
    "wegovy": "semaglutide",
    "ozempic": "semaglutide",
    "rybelsus": "semaglutide",
    "zepbound": "tirzepatide",
    "mounjaro": "tirzepatide",
    "saxenda": "liraglutide",
    "victoza": "liraglutide",
}


def glp1_canonical(name: str) -> str:
    key = re.sub(r"\s+", " ", name.strip()).casefold()
    if key in GLP1_CANONICALS:
        return key
    return GLP1_BRANDS.get(key, key)


class DrugIndex:
    """Case-insensitive name → entry lookup over `rules/drugs-v1.yaml`."""

    def __init__(self, table: DrugTable) -> None:
        self._by_name: dict[str, Drug] = {}
        for drug in table.drugs:
            for name in drug.names:
                for variant in _name_variants(name):
                    self._by_name.setdefault(variant, drug)

    def lookup(self, name: str) -> Drug | None:
        for variant in _name_variants(name):
            hit = self._by_name.get(variant)
            if hit is not None:
                return hit
        stripped = re.sub(r"\s+\d.*$", "", name.strip())
        if stripped != name.strip():
            return self.lookup(stripped)
        return None


def _name_variants(name: str) -> tuple[str, ...]:
    base = re.sub(r"\s+", " ", name.strip()).casefold()
    return (base, base.replace("-", "/"), base.replace("/", "-"), base.replace(" ", ""))


# --- compute -------------------------------------------------------------------------------------


@dataclass
class _Row:
    evidence_id: int
    ev: CheckedEvidence
    tp: Timepoint = field(default_factory=lambda: Timepoint("unknown", None, "none"))
    flags: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    norm: tuple[Decimal, str] | None = None
    integer_only: bool = False
    inherited: tuple[str, str, int] | None = None  # (event_date, precision, doc_dates id)

    @property
    def usable(self) -> bool:
        return not self.reasons and self.ev.position_status in LOCATED

    @property
    def candidate(self) -> bool:
        return not self.reasons and self.ev.position_status == "candidate"

    @property
    def patient_fact(self) -> bool:
        """A usable row the model asserts as the patient's own, actual fact: measurements,
        medications, programs and events of a relative, a denied or a hypothetical mention
        never become clinical facts (contract §3 step 0, guide A-10)."""
        return (
            self.usable
            and self.ev.subject_llm == "patient"
            and self.ev.certainty_llm == "present"
            and self.ev.temporality_llm != "hypothetical"
        )

    @property
    def anchored(self) -> bool:
        """A patient fact whose assertion and value the verifier fully recognized: the only
        rows allowed to establish the initiation date or a document date."""
        return (
            self.patient_fact
            and self.ev.assertion_check == "matched"
            and "unrecognized" not in self.flags
        )

    def attr(self, key: str) -> Any:
        return self.ev.attributes.get(key)

    def source(self) -> Source:
        return Source(
            evidence_id=self.evidence_id,
            ref=self.ev.ref,
            doc_id=self.ev.doc_id,
            field=self.ev.field,
            position_status=self.ev.position_status,
            flags=tuple(self.flags),
            certainty=self.ev.certainty_llm,
            subject=self.ev.subject_llm,
            temporality=self.ev.temporality_llm,
            tp=self.tp,
        )


def compute(evidence: Sequence[CheckedEvidence], ctx: CaseContext) -> ComputedFacts:
    ids = list(ctx.evidence_ids) if ctx.evidence_ids is not None else list(range(len(evidence)))
    if len(ids) != len(evidence):
        raise ValueError("evidence_ids must match the evidence")
    rows = [
        _Row(i, ev, flags=list(ev.flags), reasons=list(ev.exclusion_reasons))
        for i, ev in zip(ids, evidence, strict=True)
    ]

    _normalize(rows)
    doc_facts = _doc_facts(rows, ctx)
    initiation = _initiation(rows, ctx)
    _timepoints(rows, doc_facts, initiation)
    # Anchors are re-read after the timepoints so that their final flags (a timing
    # disagreement on the date sentence or the start sentence) travel into decisions.
    by_id = {r.evidence_id: r for r in rows}
    doc_facts = {
        d: replace(f, doc_date_src=by_id[f.doc_date_evidence_id].source())
        if f.doc_date_evidence_id is not None
        else f
        for d, f in doc_facts.items()
    }
    if initiation is not None:
        initiation = replace(initiation, src=by_id[initiation.src.evidence_id].source())

    usable = [r for r in rows if r.usable]
    clinical = [r for r in rows if r.patient_fact]
    heights, weights, stated = _anthropometrics(clinical)
    candidates = _bmi_candidates(heights, weights, stated)
    at_values = [c.value for c in candidates if c.tp.relative == "at"]
    brackets = {bracket_of(v) for v in at_values}
    bracket = next(iter(brackets)) if len(brackets) == 1 else None

    return ComputedFacts(
        doc_facts=doc_facts,
        wrong_patient=frozenset(d for d, f in doc_facts.items() if f.identity_status == "mismatch"),
        initiation=initiation,
        age_interval_at_initiation=_ages(clinical, initiation, ctx),
        heights=heights,
        weights=weights,
        stated_bmis=stated,
        bmi_candidates=candidates,
        bp_readings=tuple(
            BpReading(int(r.attr("sbp")), int(r.attr("dbp")), r.source())
            for r in clinical
            if r.ev.field == "bp_readings"
        ),
        med_periods=_med_periods(clinical, ctx),
        medication_lists=tuple(
            MedListRecord(str(r.attr("list_id") or ""), bool(r.attr("complete")), r.source())
            for r in clinical
            if r.ev.field == "medication_lists"
        ),
        a1c=_labs(clinical, "a1c"),
        fpg_mg_dl=_labs(clinical, "fpg"),
        egfr=_labs(clinical, "egfr"),
        dx=tuple(_dx(r) for r in usable if r.ev.field == "diagnoses"),
        prior_glp1=tuple(
            PriorGlp1Record(
                glp1_canonical(str(r.attr("drug") or "")),
                DateInterval.parse(r.attr("date")),
                str(r.attr("payer") or "unknown"),
                r.attr("compounded"),
                r.source(),
            )
            for r in clinical
            if r.ev.field == "prior_glp1"
        ),
        lifestyle_applicable=tuple(
            _lifestyle(r, ctx.assessment_date) for r in clinical if r.ev.field == "lifestyle"
        ),
        bmi_bracket=bracket,
        bmi_bracket_ambiguous=len(brackets) > 1,
        claims=tuple(
            ClaimRecord(str(r.attr("claim_id")), str(r.attr("claimed_value")), r.source())
            for r in usable
            if r.ev.field == "pa_form_claims" and ctx.doc_roles.get(r.ev.doc_id) == "pa_draft"
        ),
        candidate_only=tuple(r.source() for r in rows if r.candidate),
        case_flags=("mace_purpose",) if initiation and initiation.purpose == "mace" else (),
        evidence_updates=tuple(_update(r) for r in rows),
        assessment_date=ctx.assessment_date,
    )


def _normalize(rows: list[_Row]) -> None:
    for r in rows:
        if r.ev.field not in ("anthropometrics", "labs") or r.reasons:
            continue
        kind = r.ev.kind or ""
        if kind == "bmi_percentile":
            continue  # never a kg/m² value (project policy pediatric_bmi_percentile_is_bmi)
        norm = normalize_value(kind, r.ev.raw_value, r.ev.raw_unit)
        if norm is None:
            r.reasons.append("unparseable_value")
            continue
        r.norm = (norm[0], NORM_UNIT[kind])
        r.integer_only = norm[1]


def _doc_facts(rows: list[_Row], ctx: CaseContext) -> dict[str, DocFactComputed]:
    dated: dict[str, list[tuple[int, DateInterval, _Row]]] = {}
    for r in rows:
        # Only a row whose quote the verifier bound to the target document (no `unrecognized`)
        # can date that document (contract §5 item 3).
        if r.ev.field != "doc_dates" or not r.anchored:
            continue
        iv = DateInterval.parse(r.attr("date"))
        target = str(r.attr("target_doc_id") or "")
        if iv is None or target not in ctx.doc_identity:
            continue
        dated.setdefault(target, []).append((r.evidence_id, iv, r))
    out: dict[str, DocFactComputed] = {}
    for doc_id, status in ctx.doc_identity.items():
        found = sorted(dated.get(doc_id, []), key=lambda x: x[0])
        if not found:
            out[doc_id] = DocFactComputed(status, None, None)
        elif len({iv for _, iv, _r in found}) == 1:
            first_id, iv, row = found[0]
            out[doc_id] = DocFactComputed(status, iv, first_id, (), row.source())
        else:
            out[doc_id] = DocFactComputed(status, None, None, tuple(i for i, _, _r in found))
    return out


def _initiation(rows: list[_Row], ctx: CaseContext) -> Initiation | None:
    """The verified start of the target course: every anchored `glp1_start` row naming the
    course and containing its start day. The lowest evidence id is the record; the purpose is
    `mace` when any matching row says so (guide C-20), whatever the evidence order."""
    target = glp1_canonical(ctx.target_drug)
    matches: list[tuple[int, DateInterval, _Row]] = []
    for r in rows:
        if r.ev.field != "glp1_start" or not r.anchored:
            continue
        if glp1_canonical(str(r.attr("drug") or "")) != target:
            continue
        iv = DateInterval.parse(r.attr("date"))
        if iv is None or not iv.contains(ctx.target_start):
            continue
        r.tp = Timepoint("at", iv, "llm" if r.ev.event_date_source == "llm" else "quote")
        matches.append((r.evidence_id, iv, r))
    if not matches:
        return None
    matches.sort(key=lambda x: x[0])
    purposes = {str(r.attr("purpose") or "unknown") for _, _, r in matches}
    purpose = "mace" if "mace" in purposes else str(matches[0][2].attr("purpose") or "unknown")
    first = matches[0][2]
    return Initiation(
        matches[0][1],
        purpose,
        target,
        first.source(),
        re.sub(r"\s+", " ", str(first.attr("drug") or "")).strip().casefold(),
    )


def _own_date(r: _Row) -> tuple[DateInterval, TimepointSource] | None:
    if r.ev.event_date_source == "llm":
        iv = DateInterval.parse(r.ev.event_date)
        if iv is not None:
            return iv, "llm"
    quote_date = r.attr("quote_date")
    if isinstance(quote_date, Mapping):
        iso = str(quote_date.get("date", ""))
        if r.ev.field == "patient_identity" and _is_dob(r, iso):
            return None
        iv = DateInterval.parse(iso)
        if iv is not None:
            return iv, "quote"
    if r.ev.field in _DATED_FIELDS:
        # The fact's own verified date value (a start, a fill, a document date) is its date.
        iv = DateInterval.parse(r.attr("date"))
        if iv is not None:
            return iv, "quote"
    return None


_DATED_FIELDS = frozenset({"glp1_start", "prior_glp1", "doc_dates"})


def _is_dob(r: _Row, iso: str) -> bool:
    if r.attr("dob") == iso:
        return True
    return any(
        isinstance(x, list | tuple) and x and x[0] == iso for x in r.attr("dobs_in_text") or []
    )


def _timepoints(
    rows: list[_Row], doc_facts: Mapping[str, DocFactComputed], initiation: Initiation | None
) -> None:
    for r in rows:
        if r.reasons or r.ev.position_status == "not_found":
            continue
        own = _own_date(r)
        tp: Timepoint
        if own is not None:
            tp = Timepoint("unknown", own[0], own[1])
        else:
            df = doc_facts.get(r.ev.doc_id)
            if df is not None and df.doc_date is not None and df.doc_date_evidence_id is not None:
                tp = Timepoint("unknown", df.doc_date, "doc_date", df.doc_date_evidence_id)
                r.inherited = (df.doc_date.iso(), df.doc_date.precision, df.doc_date_evidence_id)
            else:
                tp = Timepoint("unknown", None, "none")
        if tp.date is not None and initiation is not None:
            tp = Timepoint(
                tp.date.relative_to(initiation.date), tp.date, tp.source, tp.source_evidence_id
            )
            # Any difference from the model's value is recorded (contract §5 item 1).
            if tp.relative != r.ev.relative_llm and "timing_disagreement" not in r.flags:
                r.flags.append("timing_disagreement")
        r.tp = tp


def _anthropometrics(
    usable: list[_Row],
) -> tuple[tuple[AnthroValue, ...], tuple[AnthroValue, ...], tuple[AnthroValue, ...]]:
    by_kind: dict[str, list[AnthroValue]] = {"height": [], "weight": [], "bmi": []}
    for r in usable:
        if r.ev.field != "anthropometrics" or r.norm is None or r.ev.kind not in by_kind:
            continue
        by_kind[r.ev.kind].append(
            AnthroValue(r.ev.kind, r.norm[0], r.norm[1], r.integer_only, r.source())
        )
    return tuple(by_kind["height"]), tuple(by_kind["weight"]), tuple(by_kind["bmi"])


def _nearest_heights(weight: AnthroValue, heights: Sequence[AnthroValue]) -> list[AnthroValue]:
    """Every height record equally nearest to the weight (contract §3.1 step 1): two heights
    of the same day both yield a candidate, so a straddled threshold is a conflict and not a
    matter of extraction order."""
    if not heights:
        return []

    def key(h: AnthroValue) -> tuple[int, int]:
        wd, hd = weight.src.tp.date, h.src.tp.date
        if wd is not None and hd is not None:
            return (0, min(hd.distance_days(wd.start), hd.distance_days(wd.end)))
        return (1, 0 if h.src.doc_id == weight.src.doc_id else 1)

    best = min(key(h) for h in heights)
    return sorted((h for h in heights if key(h) == best), key=lambda h: h.src.evidence_id)


def _bmi_candidates(
    heights: Sequence[AnthroValue], weights: Sequence[AnthroValue], stated: Sequence[AnthroValue]
) -> tuple[BmiCandidate, ...]:
    out: list[BmiCandidate] = []
    for w in weights:
        for h in _nearest_heights(w, heights):
            flags: tuple[str, ...] = ()
            wd, hd = w.src.tp.date, h.src.tp.date
            if wd != hd or (wd is None and h.src.doc_id != w.src.doc_id):
                flags = ("height_from_other_date",)
            out.append(
                BmiCandidate(
                    bmi_from(w.value, h.value), "computed", False, (w.src, h.src), w.src.tp, flags
                )
            )
    for s in stated:
        out.append(BmiCandidate(s.value, "stated", s.integer_only, (s.src,), s.src.tp, ()))
    return tuple(sorted(out, key=lambda c: c.evidence_ids))


def _ages(
    usable: list[_Row], initiation: Initiation | None, ctx: CaseContext
) -> tuple[AgeInterval, ...]:
    out: list[AgeInterval] = []
    for r in usable:
        if r.ev.field != "patient_identity":
            continue
        dob = DateInterval.parse(r.attr("dob")) if r.attr("dob") else None
        stated = r.attr("stated_age")
        if dob is not None and dob.precision == "day":
            ref = initiation.date if initiation else DateInterval.day(ctx.assessment_date)
            # A date of birth is absolute: when the row's own date was written does not bear
            # on it, so a timing flag of that row does not travel with the age it gives.
            src = r.source()
            src = replace(src, flags=tuple(f for f in src.flags if f != "timing_disagreement"))
            out.append(
                AgeInterval(
                    years_between(dob.start, ref.start),
                    years_between(dob.start, ref.end),
                    "dob",
                    "initiation" if initiation else "own_date",
                    src,
                )
            )
        if isinstance(stated, int) and not isinstance(stated, bool) and r.tp.date is not None:
            d0, d1 = r.tp.date.start, r.tp.date.end
            birth_lo = shift_years(d0, -(stated + 1)) + timedelta(days=1)
            birth_hi = shift_years(d1, -stated)
            ref = initiation.date if initiation else r.tp.date
            out.append(
                AgeInterval(
                    years_between(birth_hi, ref.start),
                    years_between(birth_lo, ref.end),
                    "stated_age",
                    "initiation" if initiation else "own_date",
                    r.source(),
                )
            )
    return tuple(out)


def _med_periods(usable: list[_Row], ctx: CaseContext) -> tuple[MedPeriod, ...]:
    index = DrugIndex(ctx.drugs)
    lists: dict[tuple[str, str], _Row] = {
        (r.ev.doc_id, str(r.attr("list_id"))): r for r in usable if r.ev.field == "medication_lists"
    }
    out: list[MedPeriod] = []
    for r in usable:
        if r.ev.field != "medications":
            continue
        name = str(r.attr("name") or "")
        drug = index.lookup(name)
        start = DateInterval.parse(r.attr("start"))
        end = DateInterval.parse(r.attr("end"))
        list_id = str(r.attr("list_id") or "")
        list_row = lists.get((r.ev.doc_id, list_id)) if list_id else None
        end_kind = str(r.attr("end_kind") or "unknown")
        in_use: list[DateInterval] = []
        same_note = False
        # T-09: an undated entry of a verified *current* list in a dated note is in use on that
        # note's date (the date the entry inherited or carries), never on a date another
        # sentence quotes, and never when the entry or the list is historical or ended.
        # The list must be verified as current from its own heading (guide T-09), not only
        # asserted current by the model.
        current = (
            r.ev.temporality_llm == "current"
            and list_row is not None
            and list_row.ev.temporality_llm == "current"
            and list_row.attr("list_status") == "current"
        )
        # The list's own verified date wins over the date its entries inherited from the note.
        note_date = r.tp.date
        if list_row is not None and list_row.tp.source in ("llm", "quote"):
            note_date = list_row.tp.date
        before_stop = end is None or (note_date is not None and note_date.end < end.start)
        if start is None and current and end_kind != "ended" and before_stop and note_date:
            in_use.append(note_date)
            same_note = True
        if same_note and "same_note_list" not in r.flags:
            r.flags.append("same_note_list")
        out.append(
            MedPeriod(
                drug_canonical=drug.drug_canonical if drug else name.casefold(),
                class_=drug.class_ if drug else None,
                class_ambiguous=drug.class_ambiguous if drug else False,
                components=tuple(c.drug_canonical for c in drug.components)
                if drug and drug.components
                else (),
                recognized=drug is not None,
                start=start,
                end=end,
                end_kind=end_kind,
                list_id=list_id,
                list_complete=bool(list_row.attr("complete")) if list_row is not None else None,
                in_use_on=tuple(in_use),
                same_note_list=same_note,
                src=r.source(),
            )
        )
    return tuple(out)


def _labs(usable: list[_Row], kind: str) -> tuple[LabValue, ...]:
    return tuple(
        LabValue(kind, r.norm[0], r.norm[1], r.source())
        for r in usable
        if r.ev.field == "labs" and r.ev.kind == kind and r.norm is not None
    )


def _dx(r: _Row) -> Dx:
    ahi = r.attr("ahi")
    return Dx(
        concept=r.ev.concept or "other",
        osa_severity=str(r.attr("osa_severity") or "unspecified"),
        ahi=Decimal(str(ahi)) if ahi is not None else None,
        fibrosis_stage=str(r.attr("fibrosis_stage") or ""),
        cirrhosis=r.attr("cirrhosis"),
        ckd_stage=str(r.attr("ckd_stage") or ""),
        symptomatic=str(r.attr("symptomatic") or "unknown"),
        src=r.source(),
    )


def _lifestyle(r: _Row, assessment: date) -> LifestyleRecord:
    start = DateInterval.parse(r.attr("start"))
    end = DateInterval.parse(r.attr("end"))
    end_kind = str(r.attr("end_kind") or "unknown")
    program = str(r.attr("program_type") or "")
    dated = start is not None or r.tp.date is not None
    anchor = start or r.tp.date
    applicable = True
    # Coverage must be certain (guide C-18): a verified date or period must place the record
    # on the assessment date; the latest possible start and the earliest possible end must
    # enclose it. An undated record, ongoing or not, proves nothing about that day.
    if not dated:
        applicable = False
    elif anchor is not None and anchor.end > assessment:
        applicable = False  # may start, or be recorded, after the assessment date
    elif end is not None:
        applicable = end.start >= assessment
    elif end_kind == "ended":
        applicable = False
    distance: int | None = None
    if anchor is not None:
        distance = anchor.distance_days(assessment)
    return LifestyleRecord(
        kind=r.ev.kind or "",
        program_type=program,
        attendance=str(r.attr("attendance") or "unknown"),
        start=start,
        end=end,
        end_kind=end_kind,
        has_limitation=bool(r.attr("limitation")),
        applicable=applicable,
        distance_days=distance,
        src=r.source(),
    )


def _update(r: _Row) -> EvidenceUpdate:
    flags = tuple(r.flags)
    usable_or_candidate = r.usable or r.candidate
    return EvidenceUpdate(
        evidence_id=r.evidence_id,
        relative_computed=r.tp.relative if usable_or_candidate else None,
        event_date_source=f"doc_dates:{r.inherited[2]}" if r.inherited else None,
        event_date=r.inherited[0] if r.inherited else None,
        date_precision=r.inherited[1] if r.inherited else None,
        norm_value=str(r.norm[0]) if r.norm else None,
        norm_unit=r.norm[1] if r.norm else None,
        flags=flags,
        exclusion_reasons=tuple(r.reasons),
    )
