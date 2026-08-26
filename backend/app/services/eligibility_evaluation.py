"""Stage 6B-3 — deterministic eligibility evaluation.

Compares validated official criteria with conversation-scoped citizen answers.
No LLM decisions. No web retrieval. No scheme-specific hard-coding.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from app.services.eligibility_criteria import (
    CriterionConfidence,
    CriterionType,
    EligibilityCriteriaResult,
    EligibilityCriterion,
)

logger = logging.getLogger("gramsakhi.eligibility_evaluation")


class EvaluationStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class CriterionOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    UNKNOWN = "UNKNOWN"


class DecisionReasonCode(str, Enum):
    ALL_MANDATORY_PASS = "ALL_MANDATORY_PASS"
    MANDATORY_FAIL = "MANDATORY_FAIL"
    REQUIRED_UNKNOWN = "REQUIRED_UNKNOWN"
    MISSING_INFORMATION = "MISSING_INFORMATION"
    SCHEME_IDENTITY_MISMATCH = "SCHEME_IDENTITY_MISMATCH"
    CONVERSATION_MISMATCH = "CONVERSATION_MISMATCH"
    CRITERIA_UNAVAILABLE = "CRITERIA_UNAVAILABLE"
    EVIDENCE_NOT_VALIDATED = "EVIDENCE_NOT_VALIDATED"
    NO_EVALUABLE_CRITERIA = "NO_EVALUABLE_CRITERIA"


_STATE_CANONICAL = {
    "karnataka": "karnataka",
    "ಕರ್ನಾಟಕ": "karnataka",
    "कर्नाटक": "karnataka",
    "kerala": "kerala",
    "tamil nadu": "tamil nadu",
    "maharashtra": "maharashtra",
    "chhattisgarh": "chhattisgarh",
    "delhi": "delhi",
    "uttar pradesh": "uttar pradesh",
    "west bengal": "west bengal",
    "andhra pradesh": "andhra pradesh",
    "telangana": "telangana",
    "gujarat": "gujarat",
    "rajasthan": "rajasthan",
    "punjab": "punjab",
    "haryana": "haryana",
    "bihar": "bihar",
    "odisha": "odisha",
    "madhya pradesh": "madhya pradesh",
    "assam": "assam",
    "jharkhand": "jharkhand",
}

_OCCUPATION_ALIASES = {
    "farmer": {"farmer", "agricultural worker", "agriculturist", "krushik", "kisan"},
    "agricultural worker": {"farmer", "agricultural worker", "agriculturist"},
    "student": {"student", "students"},
    "unemployed": {"unemployed", "jobless", "nirudyogi"},
    "entrepreneur": {"entrepreneur", "entrepreneurs"},
    "self_employed": {"self employed", "self-employed"},
}


@dataclass
class CriterionEvaluationResult:
    criterion_index: int
    criterion_type: str
    statement: str
    operator: Optional[str] = None
    expected_value: Any = None
    expected_value_max: Any = None
    citizen_value: Any = None
    outcome: str = CriterionOutcome.UNKNOWN.value
    mandatory: bool = True
    logical_connector: Optional[str] = None
    source_url: Optional[str] = None
    document_url: Optional[str] = None
    document_id: Optional[str] = None
    scheme_name: Optional[str] = None
    scheme_id: Optional[str] = None
    reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EligibilityEvaluationResult:
    status: str = EvaluationStatus.CANNOT_DETERMINE.value
    scheme_name: Optional[str] = None
    scheme_id: Optional[str] = None
    criteria_results: List[CriterionEvaluationResult] = field(default_factory=list)
    passed_criteria: List[int] = field(default_factory=list)
    failed_criteria: List[int] = field(default_factory=list)
    unknown_criteria: List[int] = field(default_factory=list)
    evaluated_criteria_count: int = 0
    total_criteria_count: int = 0
    evaluation_complete: bool = False
    decision_reason_code: str = DecisionReasonCode.REQUIRED_UNKNOWN.value
    group_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "scheme_name": self.scheme_name,
            "scheme_id": self.scheme_id,
            "criteria_results": [c.to_dict() for c in self.criteria_results],
            "passed_criteria": list(self.passed_criteria),
            "failed_criteria": list(self.failed_criteria),
            "unknown_criteria": list(self.unknown_criteria),
            "evaluated_criteria_count": self.evaluated_criteria_count,
            "total_criteria_count": self.total_criteria_count,
            "evaluation_complete": self.evaluation_complete,
            "decision_reason_code": self.decision_reason_code,
            "group_results": list(self.group_results),
        }


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _norm_state(value: Any) -> str:
    raw = _norm_text(value)
    return _STATE_CANONICAL.get(raw, raw)


def _norm_gender(value: Any) -> str:
    raw = _norm_text(value)
    if raw in ("female", "woman", "women", "f"):
        return "female"
    if raw in ("male", "man", "men", "m"):
        return "male"
    return raw


def _norm_occupation(value: Any) -> str:
    raw = _norm_text(value)
    for canon, aliases in _OCCUPATION_ALIASES.items():
        if raw == canon or raw in aliases:
            return canon
    return raw


def _to_number(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    raw = str(value).replace(",", "").strip().lower()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def criteria_result_from_dict(data: Dict[str, Any]) -> EligibilityCriteriaResult:
    crits = []
    for i, item in enumerate(data.get("criteria") or []):
        if isinstance(item, EligibilityCriterion):
            crits.append(item)
        elif isinstance(item, dict):
            crits.append(EligibilityCriterion(**item))
    return EligibilityCriteriaResult(
        scheme_name=data.get("scheme_name"),
        scheme_id=data.get("scheme_id"),
        criteria=crits,
        unstructured_statements=list(data.get("unstructured_statements") or []),
        rejected=bool(data.get("rejected")),
        rejection_reason=data.get("rejection_reason"),
        extraction_status=str(data.get("extraction_status") or "ok"),
    )


def _scheme_keys(name: Optional[str], sid: Optional[str] = None) -> Tuple[str, str]:
    try:
        from app.services.myscheme_service import normalize_scheme_key

        key = normalize_scheme_key(name or "")
    except Exception:
        key = _norm_text(name)
    return key, _norm_text(sid or "")


def _scheme_identity_matches(
    *,
    criteria: EligibilityCriteriaResult,
    session_scheme: Optional[str],
    session_scheme_id: Optional[str],
    requested_scheme: Optional[str] = None,
) -> bool:
    _ = requested_scheme
    crit_key, crit_sid = _scheme_keys(criteria.scheme_name, criteria.scheme_id)
    sess_key, sess_sid = _scheme_keys(session_scheme, session_scheme_id)
    if not sess_key:
        return True
    if crit_sid and sess_sid and crit_sid == sess_sid:
        return True
    if crit_key and sess_key:
        return bool(
            crit_key == sess_key or crit_key in sess_key or sess_key in crit_key
        )
    return False


def _is_mandatory(criterion: EligibilityCriterion) -> bool:
    if criterion.confidence == CriterionConfidence.UNSTRUCTURED.value:
        return False
    if criterion.criterion_type == CriterionType.OTHER.value and not criterion.operator:
        return False
    if not criterion.explicitly_stated:
        return False
    return criterion.confidence == CriterionConfidence.EXPLICIT.value


def _citizen_value_for_type(
    criterion_type: str,
    answers: Dict[str, Any],
) -> Any:
    if criterion_type == CriterionType.AGE.value:
        return answers.get("age")
    if criterion_type == CriterionType.GENDER.value:
        return answers.get("gender")
    if criterion_type in (CriterionType.STATE.value, CriterionType.DISTRICT.value, CriterionType.RESIDENCE.value):
        return answers.get(criterion_type) or answers.get("state") or answers.get("residence")
    return answers.get(criterion_type)


def _build_eval_groups(criteria: Sequence[EligibilityCriterion]) -> List[List[EligibilityCriterion]]:
    groups: List[List[EligibilityCriterion]] = []
    i = 0
    items = list(criteria)
    while i < len(items):
        group = [items[i]]
        while i < len(items) - 1 and (items[i].logical_connector or "").upper() == "OR":
            i += 1
            group.append(items[i])
        groups.append(group)
        i += 1
    return groups


def _evaluate_single_criterion(
    criterion: EligibilityCriterion,
    *,
    index: int,
    citizen_value: Any,
) -> CriterionEvaluationResult:
    base = CriterionEvaluationResult(
        criterion_index=index,
        criterion_type=criterion.criterion_type,
        statement=criterion.statement,
        operator=criterion.operator,
        expected_value=criterion.value,
        expected_value_max=criterion.value_max,
        citizen_value=citizen_value,
        mandatory=_is_mandatory(criterion),
        logical_connector=criterion.logical_connector,
        source_url=criterion.source_url,
        document_url=criterion.document_url,
        document_id=criterion.document_id,
        scheme_name=criterion.scheme_name,
        scheme_id=criterion.scheme_id,
    )

    if not _is_mandatory(criterion):
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "non_mandatory_or_unstructured"
        return base

    if citizen_value is None or citizen_value == "":
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "missing_citizen_value"
        return base

    op = (criterion.operator or "").strip()
    ctype = criterion.criterion_type

    if ctype == CriterionType.AGE.value:
        citizen_num = _to_number(citizen_value)
        if citizen_num is None:
            base.outcome = CriterionOutcome.UNKNOWN.value
            base.reason = "unparseable_age"
            return base
        if op == ">=":
            base.outcome = (
                CriterionOutcome.PASS.value
                if citizen_num >= float(criterion.value or 0)
                else CriterionOutcome.FAIL.value
            )
            return base
        if op == "<=":
            base.outcome = (
                CriterionOutcome.PASS.value
                if citizen_num <= float(criterion.value or 0)
                else CriterionOutcome.FAIL.value
            )
            return base
        if op == "between":
            lo = float(criterion.value or 0)
            hi = float(criterion.value_max or criterion.value or 0)
            base.outcome = (
                CriterionOutcome.PASS.value
                if lo <= citizen_num <= hi
                else CriterionOutcome.FAIL.value
            )
            return base
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "unsupported_age_operator"
        return base

    if ctype == CriterionType.INCOME.value:
        citizen_num = _to_number(citizen_value)
        expected = _to_number(criterion.value)
        if citizen_num is None or expected is None:
            base.outcome = CriterionOutcome.UNKNOWN.value
            base.reason = "unparseable_income"
            return base
        if op in ("<=", "<"):
            base.outcome = (
                CriterionOutcome.PASS.value
                if citizen_num <= expected
                else CriterionOutcome.FAIL.value
            )
            return base
        if op in (">=", ">"):
            base.outcome = (
                CriterionOutcome.PASS.value
                if citizen_num >= expected
                else CriterionOutcome.FAIL.value
            )
            return base
        if op in ("=", "=="):
            base.outcome = (
                CriterionOutcome.PASS.value
                if citizen_num == expected
                else CriterionOutcome.FAIL.value
            )
            return base
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "unsupported_income_operator"
        return base

    if ctype == CriterionType.GENDER.value:
        if op in ("=", "==") or not op:
            base.outcome = (
                CriterionOutcome.PASS.value
                if _norm_gender(citizen_value) == _norm_gender(criterion.value)
                else CriterionOutcome.FAIL.value
            )
            return base
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "unsupported_gender_operator"
        return base

    if ctype in (CriterionType.STATE.value, CriterionType.DISTRICT.value, CriterionType.RESIDENCE.value):
        if op in ("=", "==") or not op:
            base.outcome = (
                CriterionOutcome.PASS.value
                if _norm_state(citizen_value) == _norm_state(criterion.value)
                else CriterionOutcome.FAIL.value
            )
            return base
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "unsupported_state_operator"
        return base

    if ctype == CriterionType.OCCUPATION.value:
        citizen_occ = _norm_occupation(citizen_value)
        expected_occ = _norm_occupation(criterion.value)
        if op in ("=", "==") or not op:
            if citizen_occ == expected_occ:
                base.outcome = CriterionOutcome.PASS.value
            elif citizen_occ in _OCCUPATION_ALIASES.get(expected_occ, {expected_occ}):
                base.outcome = CriterionOutcome.PASS.value
            else:
                base.outcome = CriterionOutcome.FAIL.value
            return base
        base.outcome = CriterionOutcome.UNKNOWN.value
        base.reason = "unsupported_occupation_operator"
        return base

    if op in ("=", "==") and criterion.value is not None:
        base.outcome = (
            CriterionOutcome.PASS.value
            if _norm_text(citizen_value) == _norm_text(criterion.value)
            else CriterionOutcome.FAIL.value
        )
        return base

    base.outcome = CriterionOutcome.UNKNOWN.value
    base.reason = "not_safely_evaluable"
    return base


def _evaluate_group(
    group: List[EligibilityCriterion],
    *,
    start_index: int,
    answers: Dict[str, Any],
) -> Tuple[str, List[CriterionEvaluationResult]]:
    results: List[CriterionEvaluationResult] = []
    for offset, criterion in enumerate(group):
        idx = start_index + offset
        citizen_val = _citizen_value_for_type(criterion.criterion_type, answers)
        results.append(
            _evaluate_single_criterion(criterion, index=idx, citizen_value=citizen_val)
        )

    mandatory = [r for r in results if r.mandatory]
    if not mandatory:
        return CriterionOutcome.UNKNOWN.value, results

    if len(group) == 1:
        return mandatory[0].outcome, results

    outcomes = [r.outcome for r in mandatory]
    if any(o == CriterionOutcome.PASS.value for o in outcomes):
        return CriterionOutcome.PASS.value, results
    if all(o == CriterionOutcome.FAIL.value for o in outcomes):
        return CriterionOutcome.FAIL.value, results
    return CriterionOutcome.UNKNOWN.value, results


def _aggregate_overall(
    group_outcomes: List[Tuple[str, bool]],
) -> Tuple[str, str]:
    """Mandatory group outcomes → overall status. Priority: FAIL > UNKNOWN > PASS."""
    mandatory_outcomes = [o for o, mandatory in group_outcomes if mandatory]
    if not mandatory_outcomes:
        return EvaluationStatus.CANNOT_DETERMINE.value, DecisionReasonCode.NO_EVALUABLE_CRITERIA.value
    if any(o == CriterionOutcome.FAIL.value for o in mandatory_outcomes):
        return EvaluationStatus.NOT_ELIGIBLE.value, DecisionReasonCode.MANDATORY_FAIL.value
    if any(o == CriterionOutcome.UNKNOWN.value for o in mandatory_outcomes):
        return EvaluationStatus.CANNOT_DETERMINE.value, DecisionReasonCode.REQUIRED_UNKNOWN.value
    if all(o == CriterionOutcome.PASS.value for o in mandatory_outcomes):
        return EvaluationStatus.ELIGIBLE.value, DecisionReasonCode.ALL_MANDATORY_PASS.value
    return EvaluationStatus.CANNOT_DETERMINE.value, DecisionReasonCode.REQUIRED_UNKNOWN.value


def evaluate_eligibility(
    *,
    criteria: Union[EligibilityCriteriaResult, Dict[str, Any]],
    citizen_answers: Dict[str, Any],
    scheme_name: Optional[str] = None,
    scheme_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    session_conversation_id: Optional[str] = None,
    evidence_validated: bool = True,
    required_information: Optional[Sequence[str]] = None,
) -> EligibilityEvaluationResult:
    """Deterministic eligibility evaluation — no LLM, no network."""
    logger.info("ELIGIBILITY_EVALUATION_START scheme=%s", (scheme_name or "")[:80])

    if isinstance(criteria, dict):
        criteria_obj = criteria_result_from_dict(criteria)
    else:
        criteria_obj = criteria

    result = EligibilityEvaluationResult(
        scheme_name=scheme_name or criteria_obj.scheme_name,
        scheme_id=scheme_id or criteria_obj.scheme_id,
    )

    if conversation_id and session_conversation_id and conversation_id != session_conversation_id:
        logger.warning("ELIGIBILITY_IDENTITY_MISMATCH reason=conversation_mismatch")
        result.status = EvaluationStatus.CANNOT_DETERMINE.value
        result.decision_reason_code = DecisionReasonCode.CONVERSATION_MISMATCH.value
        return result

    if not evidence_validated:
        result.status = EvaluationStatus.CANNOT_DETERMINE.value
        result.decision_reason_code = DecisionReasonCode.EVIDENCE_NOT_VALIDATED.value
        return result

    if criteria_obj.rejected or criteria_obj.extraction_status != "ok" or not criteria_obj.criteria:
        result.status = EvaluationStatus.CANNOT_DETERMINE.value
        result.decision_reason_code = DecisionReasonCode.CRITERIA_UNAVAILABLE.value
        return result

    if not _scheme_identity_matches(
        criteria=criteria_obj,
        session_scheme=scheme_name,
        session_scheme_id=scheme_id,
    ):
        logger.warning("ELIGIBILITY_IDENTITY_MISMATCH reason=scheme_mismatch")
        result.status = EvaluationStatus.CANNOT_DETERMINE.value
        result.decision_reason_code = DecisionReasonCode.SCHEME_IDENTITY_MISMATCH.value
        return result

    answers = dict(citizen_answers or {})
    required = list(required_information or criteria_obj.required_information_types())
    for req in required:
        if req not in answers or answers.get(req) in (None, ""):
            # Missing required field → overall cannot determine (not fail)
            pass

    groups = _build_eval_groups([c for c in criteria_obj.criteria if _is_mandatory(c)])
    if not groups:
        result.status = EvaluationStatus.CANNOT_DETERMINE.value
        result.decision_reason_code = DecisionReasonCode.NO_EVALUABLE_CRITERIA.value
        return result

    group_outcomes: List[Tuple[str, bool]] = []
    idx = 0
    for group in groups:
        group_status, crit_results = _evaluate_group(group, start_index=idx, answers=answers)
        result.criteria_results.extend(crit_results)
        idx += len(group)
        mandatory_group = any(r.mandatory for r in crit_results)
        group_outcomes.append((group_status, mandatory_group))
        result.group_results.append(
            {
                "outcome": group_status,
                "mandatory": mandatory_group,
                "criterion_indices": [r.criterion_index for r in crit_results],
            }
        )
        for cr in crit_results:
            if cr.outcome == CriterionOutcome.PASS.value:
                result.passed_criteria.append(cr.criterion_index)
                logger.info(
                    "ELIGIBILITY_CRITERION_PASS index=%s type=%s",
                    cr.criterion_index,
                    cr.criterion_type,
                )
            elif cr.outcome == CriterionOutcome.FAIL.value:
                result.failed_criteria.append(cr.criterion_index)
                logger.info(
                    "ELIGIBILITY_CRITERION_FAIL index=%s type=%s",
                    cr.criterion_index,
                    cr.criterion_type,
                )
            else:
                result.unknown_criteria.append(cr.criterion_index)
                logger.info(
                    "ELIGIBILITY_CRITERION_UNKNOWN index=%s type=%s",
                    cr.criterion_index,
                    cr.criterion_type,
                )

    status, reason = _aggregate_overall(group_outcomes)
    result.status = status
    result.decision_reason_code = reason

    if status != EvaluationStatus.NOT_ELIGIBLE.value and required:
        for req in required:
            if req not in answers or answers.get(req) in (None, ""):
                result.status = EvaluationStatus.CANNOT_DETERMINE.value
                result.decision_reason_code = DecisionReasonCode.MISSING_INFORMATION.value
                break

    result.evaluation_complete = True
    result.total_criteria_count = len(result.criteria_results)
    result.evaluated_criteria_count = len(result.criteria_results)
    logger.info("ELIGIBILITY_EVALUATION_COMPLETE status=%s", result.status)
    return result


def evaluate_session_if_ready(
    session: Any,
    *,
    evidence_validated: bool = True,
) -> Optional[EligibilityEvaluationResult]:
    """Evaluate when Stage 6B-2 session is complete."""
    if session is None or not getattr(session, "completed", False):
        return None
    answers = getattr(session, "collected_answers", None) or getattr(session, "known_information", {}) or {}
    return evaluate_eligibility(
        criteria=getattr(session, "criteria_snapshot", {}) or {},
        citizen_answers=dict(answers),
        scheme_name=getattr(session, "active_scheme", None),
        scheme_id=getattr(session, "scheme_id", None),
        conversation_id=getattr(session, "conversation_id", None),
        session_conversation_id=getattr(session, "conversation_id", None),
        evidence_validated=evidence_validated,
        required_information=getattr(session, "required_information", None),
    )
