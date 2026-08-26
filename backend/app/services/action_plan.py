"""Stage 6C-2 — personalized action plan from eligibility + scheme guidance.

Uses validated evidence and conversation-scoped context only. No new retrieval.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from app.services.citizen_assistance import CitizenIntent
from app.services.eligibility_evaluation import EvaluationStatus
from app.services.scheme_guidance import (
    GuidanceType,
    SchemeGuidanceResult,
    extract_scheme_guidance,
    guidance_sources_to_official,
)

logger = logging.getLogger("gramsakhi.action_plan")

_URL_IN_TEXT = re.compile(r"https://[^\s<>\"']+", re.I)

_APPEAL_PHRASES = (
    "appeal",
    "reapply",
    "re-apply",
    "correction procedure",
    "rectification",
    "alternative category",
)

_FALLBACK = {
    "EN": "I couldn't find enough verified information to provide a reliable next-step plan.",
    "KN": "ವಿಶ್ವಾಸಾರ್ಹ ಮುಂದಿನ ಹಂತದ ಯೋಜನೆಯನ್ನು ನೀಡಲು ಸಾಕಷ್ಟು ಪರಿಶೀಲಿತ ಮಾಹಿತಿ ದೊರಕಲಿಲ್ಲ.",
    "HI": "विश्वसनीय अगला कदम योजना देने के लिए पर्याप्त सत्यापित जानकारी नहीं मिली।",
}

_SCHEME_MISMATCH = {
    "EN": "I couldn't build an action plan because the scheme context did not match.",
    "KN": "ಯೋಜನೆ ಸಂದರ್ಭ ಹೊಂದಾಣಿಕೆಯಾಗದ ಕಾರಣ ಕ್ರಿಯಾ ಯೋಜನೆಯನ್ನು ರಚಿಸಲು ಸಾಧ್ಯವಾಗಲಿಲ್ಲ.",
    "HI": "योजना संदर्भ मेल नहीं खाने के कारण कार्य योजना नहीं बनाई जा सकी।",
}


class ActionFocus(str, Enum):
    FULL = "full"
    NEXT = "next"
    DOCUMENTS = "documents"
    PORTAL = "portal"
    CAN_APPLY = "can_apply"
    PREREQUISITES = "prerequisites"


ACTION_PLAN_INTENTS = frozenset({CitizenIntent.NEXT_ACTION})


def _lang(code: Optional[str]) -> str:
    c = (code or "EN").strip().upper()[:2]
    return c if c in ("EN", "KN", "HI") else "EN"


def is_action_plan_intent(intent: CitizenIntent) -> bool:
    return intent in ACTION_PLAN_INTENTS


def should_action_plan_followup(query: str) -> bool:
    q = (query or "").lower()
    return any(
        k in q
        for k in (
            "what should i do",
            "what do i do next",
            "what next",
            "can i apply now",
            "do i need anything else",
            "what do i need before",
            "okay, what next",
            "what documents should i keep",
            "ಮುಂದೆ ಏನು",
            "आगे क्या",
        )
    )


def detect_action_focus(query: str) -> ActionFocus:
    q = (query or "").lower()
    if "can i apply" in q or "apply now" in q:
        return ActionFocus.CAN_APPLY
    if any(k in q for k in ("what documents", "documents should i keep", "before applying", "need before")):
        return ActionFocus.DOCUMENTS
    if any(k in q for k in ("where do i apply", "where can i apply", "where to apply")):
        return ActionFocus.PORTAL
    if any(k in q for k in ("what should i do", "what next", "what do i do next")):
        return ActionFocus.NEXT
    if "need anything else" in q or "prerequisite" in q:
        return ActionFocus.PREREQUISITES
    return ActionFocus.FULL


def should_build_action_plan(
    intent: CitizenIntent,
    query: str,
    *,
    has_eligibility: bool = False,
) -> bool:
    if is_action_plan_intent(intent):
        return True
    if should_action_plan_followup(query):
        return True
    if has_eligibility and any(k in (query or "").lower() for k in ("apply now", "next step")):
        return True
    return False


@dataclass
class ActionStep:
    text: str
    source_url: Optional[str] = None
    document_url: Optional[str] = None
    evidence_ref: Optional[str] = None
    scheme_name: Optional[str] = None
    scheme_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionPlan:
    status: Optional[str] = None
    scheme_name: Optional[str] = None
    scheme_id: Optional[str] = None
    steps: List[ActionStep] = field(default_factory=list)
    documents: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    application_method: Optional[str] = None
    application_url: Optional[str] = None
    application_location: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    source_urls: List[Dict[str, Any]] = field(default_factory=list)
    pdf_urls: List[str] = field(default_factory=list)
    next_step: Optional[str] = None
    completion_notes: Optional[str] = None
    failed_criteria: List[str] = field(default_factory=list)
    unknown_criteria: List[str] = field(default_factory=list)
    extraction_status: str = "no_plan"
    rejected: bool = False
    conversation_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["steps"] = [s.to_dict() if isinstance(s, ActionStep) else s for s in self.steps]
        return d


def _criterion_label(cr: Dict[str, Any]) -> str:
    ctype = str(cr.get("criterion_type") or "requirement")
    op = cr.get("operator") or ""
    if ctype == "age" and op == ">=":
        return f"minimum age {cr.get('expected_value')} years"
    if ctype == "income":
        return "income requirement"
    if ctype == "state":
        return f"residence in {cr.get('expected_value')}"
    stmt = str(cr.get("statement") or "")
    return stmt[:100] if stmt else ctype.replace("_", " ")


def _primary_source(guidance: SchemeGuidanceResult) -> Dict[str, Any]:
    if guidance.source_urls:
        return guidance.source_urls[0]
    return {}


def _find_appeal_steps(sources: Sequence[Dict[str, Any]]) -> List[str]:
    steps: List[str] = []
    for doc in sources or []:
        content = str(doc.get("content") or doc.get("text") or "").lower()
        for phrase in _APPEAL_PHRASES:
            if phrase in content:
                for sentence in re.split(r"(?<=[.!?])\s+", content):
                    if phrase in sentence.lower() and len(sentence.strip()) >= 20:
                        steps.append(sentence.strip()[:240])
                        break
    seen: set[str] = set()
    out: List[str] = []
    for s in steps:
        key = s.lower()
        if key not in seen:
            seen.add(key)
            out.append(s)
    return out[:2]


def _guidance_from_meta(
    meta: Optional[Dict[str, Any]],
    *,
    sources: Sequence[Dict[str, Any]],
    scheme_identity: Optional[Dict[str, str]],
    evidence_validated: bool,
) -> SchemeGuidanceResult:
    if meta:
        return SchemeGuidanceResult(**{k: v for k, v in meta.items() if k in SchemeGuidanceResult.__dataclass_fields__})
    app = extract_scheme_guidance(
        sources,
        guidance_type=GuidanceType.APPLICATION,
        scheme_identity=scheme_identity,
        evidence_validated=evidence_validated,
    )
    docs = extract_scheme_guidance(
        sources,
        guidance_type=GuidanceType.DOCUMENTS,
        scheme_identity=scheme_identity,
        evidence_validated=evidence_validated,
    )
    if docs.documents:
        app.documents = docs.documents
    if docs.source_urls and not app.source_urls:
        app.source_urls = docs.source_urls
    if docs.incomplete_document_list:
        app.incomplete_document_list = docs.incomplete_document_list
    return app


def build_action_plan(
    *,
    sources: Sequence[Dict[str, Any]],
    query: str,
    scheme_identity: Optional[Dict[str, str]] = None,
    eligibility_status: Optional[str] = None,
    eligibility_evaluation: Optional[Dict[str, Any]] = None,
    scheme_guidance: Optional[Dict[str, Any]] = None,
    known_information: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    session_conversation_id: Optional[str] = None,
    eligibility_session_active: bool = False,
    evidence_validated: bool = True,
    focus: ActionFocus = ActionFocus.FULL,
) -> ActionPlan:
    """Build structured action plan from validated inputs."""
    logger.info("ACTION_PLAN_START")
    _ = known_information  # reserved for personalization without inferring possession

    if not evidence_validated:
        return ActionPlan(extraction_status="evidence_not_validated", conversation_id=conversation_id)

    if (
        conversation_id
        and session_conversation_id
        and conversation_id != session_conversation_id
    ):
        logger.warning("ACTION_PLAN_IDENTITY_MISMATCH conversation")
        return ActionPlan(extraction_status="conversation_mismatch", conversation_id=conversation_id)

    guidance = _guidance_from_meta(
        scheme_guidance,
        sources=sources,
        scheme_identity=scheme_identity,
        evidence_validated=evidence_validated,
    )
    if guidance.rejected:
        logger.warning("ACTION_PLAN_IDENTITY_MISMATCH scheme")
        return ActionPlan(
            extraction_status="scheme_mismatch",
            rejected=True,
            scheme_name=guidance.scheme_name,
            conversation_id=conversation_id,
        )

    scheme_name = guidance.scheme_name or (scheme_identity or {}).get("scheme_name")
    scheme_id = guidance.scheme_id or (scheme_identity or {}).get("scheme_id")
    src = _primary_source(guidance)
    source_url = str(src.get("url") or src.get("source_url") or "")
    document_url = str(src.get("document_url") or "") or None
    pdf_urls = [s["url"] for s in guidance.source_urls if s.get("is_pdf") and s.get("url")]

    plan = ActionPlan(
        status=eligibility_status,
        scheme_name=scheme_name,
        scheme_id=scheme_id,
        documents=list(guidance.documents or []),
        application_url=guidance.application_url,
        application_location=guidance.application_location,
        source_urls=list(guidance.source_urls or []),
        pdf_urls=pdf_urls,
        conversation_id=conversation_id,
    )

    if guidance.offline_application:
        plan.application_method = "offline_office"
    elif guidance.application_url:
        plan.application_method = "online_portal"
    elif guidance.application_steps:
        plan.application_method = "documented_process"

    if guidance.login_required:
        plan.warnings.append("login_verification_required")
    if guidance.source_blocked:
        plan.warnings.append("source_access_restricted")

    eval_status = (eligibility_status or "").upper()
    crit_results = list((eligibility_evaluation or {}).get("criteria_results") or [])

    for cr in crit_results:
        if not isinstance(cr, dict):
            continue
        outcome = str(cr.get("outcome") or "")
        label = _criterion_label(cr)
        if outcome == "FAIL":
            plan.failed_criteria.append(label)
        elif outcome == "UNKNOWN":
            plan.unknown_criteria.append(label)

    trace = ActionStep(
        text="",
        source_url=source_url or None,
        document_url=document_url,
        scheme_name=scheme_name,
        scheme_id=scheme_id,
    )

    if eval_status == EvaluationStatus.NOT_ELIGIBLE.value:
        plan.warnings.append("not_eligible")
        if plan.failed_criteria:
            plan.steps.append(
                ActionStep(
                    text=f"Review the unmet requirement: {plan.failed_criteria[0]}.",
                    source_url=trace.source_url,
                    document_url=trace.document_url,
                    scheme_name=scheme_name,
                    scheme_id=scheme_id,
                )
            )
        appeals = _find_appeal_steps(sources)
        if appeals:
            for a in appeals:
                plan.steps.append(
                    ActionStep(text=a, source_url=trace.source_url, scheme_name=scheme_name, scheme_id=scheme_id)
                )
                logger.info("ACTION_PLAN_STEP_EXTRACTED kind=appeal")
        else:
            plan.completion_notes = "no_verified_alternative"
        plan.extraction_status = "ok"
        plan.next_step = plan.steps[0].text if plan.steps else None
        logger.info("ACTION_PLAN_BUILT status=NOT_ELIGIBLE")
        return plan

    if eval_status == EvaluationStatus.CANNOT_DETERMINE.value:
        if plan.unknown_criteria:
            plan.steps.append(
                ActionStep(
                    text=(
                        "Eligibility could not be confirmed yet because these details are still unknown: "
                        + "; ".join(plan.unknown_criteria[:3])
                        + "."
                    ),
                    source_url=trace.source_url,
                    document_url=trace.document_url,
                    scheme_name=scheme_name,
                    scheme_id=scheme_id,
                )
            )
        if eligibility_session_active:
            plan.steps.append(
                ActionStep(
                    text="Continue providing the requested details so the remaining criteria can be checked.",
                    source_url=trace.source_url,
                    scheme_name=scheme_name,
                    scheme_id=scheme_id,
                )
            )
        elif guidance.application_steps and focus != ActionFocus.NEXT:
            plan.steps.append(
                ActionStep(
                    text=(
                        "General application information is available, but eligibility has not been confirmed yet."
                    ),
                    source_url=trace.source_url,
                    scheme_name=scheme_name,
                    scheme_id=scheme_id,
                )
            )
        plan.extraction_status = "ok" if plan.steps else "cannot_determine"
        plan.next_step = plan.steps[0].text if plan.steps else None
        logger.info("ACTION_PLAN_BUILT status=CANNOT_DETERMINE")
        return plan

    # ELIGIBLE or no evaluation — build application-oriented plan from 6C-1
    if eval_status == EvaluationStatus.ELIGIBLE.value:
        plan.steps.append(
            ActionStep(
                text="You appear to meet the evaluated eligibility criteria based on the information provided.",
                source_url=trace.source_url,
                document_url=trace.document_url,
                scheme_name=scheme_name,
                scheme_id=scheme_id,
            )
        )

    if plan.documents and focus in (ActionFocus.FULL, ActionFocus.DOCUMENTS, ActionFocus.PREREQUISITES, ActionFocus.NEXT, ActionFocus.CAN_APPLY):
        doc_text = "Keep these verified documents ready: " + "; ".join(plan.documents[:6])
        plan.steps.append(
            ActionStep(
                text=doc_text,
                source_url=trace.source_url,
                document_url=trace.document_url,
                scheme_name=scheme_name,
                scheme_id=scheme_id,
            )
        )
        logger.info("ACTION_PLAN_STEP_EXTRACTED kind=documents")

    for step_text in guidance.application_steps or []:
        plan.steps.append(
            ActionStep(
                text=step_text,
                source_url=trace.source_url,
                document_url=trace.document_url,
                scheme_name=scheme_name,
                scheme_id=scheme_id,
            )
        )
        logger.info("ACTION_PLAN_STEP_EXTRACTED kind=application")

    if guidance.application_url and focus in (ActionFocus.FULL, ActionFocus.PORTAL, ActionFocus.NEXT, ActionFocus.CAN_APPLY):
        plan.steps.append(
            ActionStep(
                text="Apply through the official application portal using the verified link below.",
                source_url=guidance.application_url,
                scheme_name=scheme_name,
                scheme_id=scheme_id,
            )
        )
        logger.info("ACTION_PLAN_PORTAL_ATTACHED")
    elif guidance.offline_application and focus in (ActionFocus.FULL, ActionFocus.PORTAL, ActionFocus.NEXT, ActionFocus.CAN_APPLY):
        plan.steps.append(
            ActionStep(
                text="Submit the application through the designated government office or department.",
                source_url=trace.source_url,
                document_url=trace.document_url,
                scheme_name=scheme_name,
                scheme_id=scheme_id,
            )
        )

    if guidance.login_required and guidance.application_url:
        plan.warnings.append("manual_login_required")

    if pdf_urls:
        logger.info("ACTION_PLAN_PDF_ATTACHED count=%s", len(pdf_urls))

    if not plan.steps:
        if guidance.incomplete_document_list:
            plan.extraction_status = "incomplete_information"
        else:
            plan.extraction_status = "no_steps"
    else:
        plan.extraction_status = "ok"

    plan.next_step = plan.steps[0].text if plan.steps else None
    logger.info("ACTION_PLAN_BUILT status=%s steps=%s", eval_status or "NONE", len(plan.steps))
    return plan


def build_deterministic_action_plan_answer(
    plan: ActionPlan,
    *,
    response_language: str = "EN",
    focus: ActionFocus = ActionFocus.FULL,
) -> str:
    lang = _lang(response_language)
    if plan.rejected:
        return _SCHEME_MISMATCH.get(lang, _SCHEME_MISMATCH["EN"])
    if plan.extraction_status in ("evidence_not_validated", "conversation_mismatch"):
        return _FALLBACK.get(lang, _FALLBACK["EN"])

    scheme = plan.scheme_name or "this scheme"

    if plan.status == EvaluationStatus.NOT_ELIGIBLE.value:
        body = {
            "EN": (
                "Based on the information provided, you do not currently meet one or more verified eligibility "
                "criteria. You should not proceed with an application assuming you are eligible."
            ),
            "KN": (
                "ನೀಡಲಾದ ಮಾಹಿತಿಯ ಆಧಾರದ ಮೇಲೆ, ನೀವು ಒಂದು ಅಥವಾ ಹೆಚ್ಚು ಪರಿಶೀಲಿತ ಅರ್ಹತೆ ಮಾನದಂಡಗಳನ್ನು "
                "ಪ್ರಸ್ತುತ ಪೂರೈಸುವುದಿಲ್ಲ. ನೀವು ಅರ್ಹರಾಗಿದ್ದೀರಿ ಎಂದು ಭಾವಿಸಿ ಅರ್ಜಿ ಮಾಡಬೇಡಿ."
            ),
            "HI": (
                "दी गई जानकारी के आधार पर, आप वर्तमान में एक या अधिक सत्यापित पात्रता मानदंड पूरे नहीं करते। "
                "यह मानकर आवेदन न करें कि आप पात्र हैं।"
            ),
        }.get(lang, "")
        if plan.failed_criteria:
            body += {
                "EN": f"\n\nUnmet requirement: {plan.failed_criteria[0]}.",
                "KN": f"\n\nಪೂರೈಸದ ಅವಶ್ಯಕತೆ: {plan.failed_criteria[0]}.",
                "HI": f"\n\nअपूरी आवश्यकता: {plan.failed_criteria[0]}.",
            }.get(lang, "")
        if plan.steps:
            body += "\n\n" + {
                "EN": "Verified information about this situation:",
                "KN": "ಈ ಸಂದರ್ಭದ ಬಗ್ಗೆ ಪರಿಶೀಲಿತ ಮಾಹಿತಿ:",
                "HI": "इस स्थिति के बारे में सत्यापित जानकारी:",
            }.get(lang, "")
            for i, step in enumerate(plan.steps[:3], start=1):
                body += f"\n{i}. {step.text}"
        elif plan.completion_notes == "no_verified_alternative":
            body += {
                "EN": "\n\nNo verified next step for this situation was found.",
                "KN": "\n\nಈ ಸಂದರ್ಭಕ್ಕೆ ಪರಿಶೀಲಿತ ಮುಂದಿನ ಹಂತ ಕಂಡುಬಂದಿಲ್ಲ.",
                "HI": "\n\nइस स्थिति के लिए कोई सत्यापित अगला कदम नहीं मिला।",
            }.get(lang, "")
        return body

    if plan.status == EvaluationStatus.CANNOT_DETERMINE.value:
        body = {
            "EN": "Your eligibility could not be confirmed yet from the verified information available.",
            "KN": "ಲಭ್ಯವಿರುವ ಪರಿಶೀಲಿತ ಮಾಹಿತಿಯಿಂದ ಇನ್ನೂ ನಿಮ್ಮ ಅರ್ಹತೆಯನ್ನು ದೃಢೀಕರಿಸಲಾಗಿಲ್ಲ.",
            "HI": "उपलब्ध सत्यापित जानकारी से अभी आपकी पात्रता की पुष्टि नहीं हो सकी।",
        }.get(lang, "")
        if plan.unknown_criteria:
            body += {
                "EN": f"\n\nOutstanding details: {'; '.join(plan.unknown_criteria[:3])}.",
                "KN": f"\n\nಬಾಕಿ ವಿವರಗಳು: {'; '.join(plan.unknown_criteria[:3])}.",
                "HI": f"\n\nअनिर्णित विवरण: {'; '.join(plan.unknown_criteria[:3])}.",
            }.get(lang, "")
        if plan.steps:
            body += "\n\n" + "\n".join(f"{i + 1}. {s.text}" for i, s in enumerate(plan.steps[:4]))
        return body

    # ELIGIBLE or general application plan
    intro = {
        "EN": f"Based on the verified information for {scheme}, here are the supported next steps:",
        "KN": f"{scheme} ಯೋಜನೆಯ ಪರಿಶೀಲಿತ ಮಾಹಿತಿಯ ಆಧಾರದ ಮೇಲೆ, ಇವು ಬೆಂಬಲಿತ ಮುಂದಿನ ಹಂತಗಳು:",
        "HI": f"{scheme} योजना की सत्यापित जानकारी के आधार पर, ये समर्थित अगले कदम हैं:",
    }.get(lang, "")

    if focus == ActionFocus.NEXT and plan.next_step:
        steps_text = f"1. {plan.next_step}"
    elif focus == ActionFocus.DOCUMENTS:
        if plan.documents:
            steps_text = _bullet_block(plan.documents, lang)
        else:
            steps_text = {
                "EN": "I couldn't find a complete verified document list in the available official information.",
                "KN": "ಲಭ್ಯವಿರುವ ಅಧಿಕೃತ ಮಾಹಿತಿಯಲ್ಲಿ ಸಂಪೂರ್ಣ ಪರಿಶೀಲಿತ ದಾಖಲೆ ಪಟ್ಟಿ ದೊರಕಲಿಲ್ಲ.",
                "HI": "उपलब्ध आधिकारिक जानकारी में पूरी सत्यापित दस्तावेज़ सूची नहीं मिली।",
            }.get(lang, "")
        return steps_text
    elif focus == ActionFocus.PORTAL:
        if plan.application_url:
            return {
                "EN": "You can apply through the official application portal listed below.",
                "KN": "ಕೆಳಗೆ ನೀಡಿರುವ ಅಧಿಕೃತ ಅರ್ಜಿ ಪೋರ್ಟಲ್‌ ಮೂಲಕ ನೀವು ಅರ್ಜಿ ಸಲ್ಲಿಸಬಹುದು.",
                "HI": "नीचे दिए आधिकारिक आवेदन पोर्टल के माध्यम से आप आवेदन कर सकते हैं।",
            }.get(lang, "")
        if plan.application_method == "offline_office":
            return {
                "EN": "Applications are handled through the designated government office according to verified information.",
                "KN": "ಪರಿಶೀಲಿತ ಮಾಹಿತಿಯ ಪ್ರಕಾರ ಅರ್ಜಿಗಳನ್ನು ನಿಯೋಜಿತ ಸರ್ಕಾರಿ ಕಚೇರಿಯ ಮೂಲಕ ಸ್ವೀಕರಿಸಲಾಗುತ್ತದೆ.",
                "HI": "सत्यापित जानकारी के अनुसार आवेदन निर्धारित सरकारी कार्यालय के माध्यम से किए जाते हैं।",
            }.get(lang, "")
        return _FALLBACK.get(lang, _FALLBACK["EN"])
    elif focus == ActionFocus.CAN_APPLY:
        if plan.status == EvaluationStatus.ELIGIBLE.value:
            intro = {
                "EN": "Based on the evaluated criteria, you appear eligible. The verified application route is:",
                "KN": "ಮೌಲ್ಯಮಾಪನ ಮಾನದಂಡಗಳ ಆಧಾರದ ಮೇಲೆ, ನೀವು ಅರ್ಹರಾಗಿರುವಂತೆ ತೋರುತ್ತದೆ. ಪರಿಶೀಲಿತ ಅರ್ಜಿ ಮಾರ್ಗ:",
                "HI": "मूल्यांकन मानदंडों के आधार पर, आप पात्र प्रतीत होते हैं। सत्यापित आवेदन मार्ग:",
            }.get(lang, "")
        else:
            intro = {
                "EN": "Eligibility has not been fully confirmed, but verified application information says:",
                "KN": "ಅರ್ಹತೆ ಸಂಪೂರ್ಣವಾಗಿ ದೃಢೀಕರಿಸಲಾಗಿಲ್ಲ, ಆದರೆ ಪರಿಶೀಲಿತ ಅರ್ಜಿ ಮಾಹಿತಿ ಹೇಳುತ್ತದೆ:",
                "HI": "पात्रता पूरी तरह पुष्ट नहीं हुई, लेकिन सत्यापित आवेदन जानकारी कहती है:",
            }.get(lang, "")

    if plan.steps:
        steps_text = "\n".join(f"{i + 1}. {s.text}" for i, s in enumerate(plan.steps[:6]))
    else:
        return _FALLBACK.get(lang, _FALLBACK["EN"])

    body = intro + "\n\n" + steps_text

    if "manual_login_required" in plan.warnings:
        body += {
            "EN": "\n\nThe official portal requires manual login or verification.",
            "KN": "\n\nಅಧಿಕೃತ ಪೋರ್ಟಲ್‌ಗೆ manual ಲಾಗಿನ್/ಪರಿಶೀಲನೆ ಅಗತ್ಯ.",
            "HI": "\n\nआधिकारिक पोर्टल में manual लॉगिन/सत्यापन आवश्यक है।",
        }.get(lang, "")

    if plan.pdf_urls:
        body += {
            "EN": "\n\nOfficial scheme document (PDF) is available below.",
            "KN": "\n\nಅಧಿಕೃತ ಯೋಜನೆ ದಾಖಲೆ (PDF) ಕೆಳಗೆ ಲಭ್ಯವಿದೆ.",
            "HI": "\n\nआधिकारिक योजना दस्तावेज़ (PDF) नीचे उपलब्ध है।",
        }.get(lang, "")

    return body


def _bullet_block(items: Sequence[str], lang: str) -> str:
    prefix = {
        "EN": "Verified documents to keep ready:",
        "KN": "ಸಿದ್ಧವಾಗಿಡಬೇಕಾದ ಪರಿಶೀಲಿತ ದಾಖಲೆಗಳು:",
        "HI": "तैयार रखने योग्य सत्यापित दस्तावेज़:",
    }.get(lang, "Documents:")
    return prefix + "\n" + "\n".join(f"• {d}" for d in items)


def _official_from_plan(plan: ActionPlan) -> List[Dict[str, str]]:
    guidance = SchemeGuidanceResult(
        scheme_name=plan.scheme_name,
        application_url=plan.application_url,
        source_urls=plan.source_urls,
    )
    return guidance_sources_to_official(plan.source_urls, guidance)


def build_action_plan_prompt(plan: ActionPlan, *, response_language: str, query: str) -> str:
    from app.services.language_service import build_language_instruction, language_name

    code = _lang(response_language)
    return f"""You are GramSakhi presenting a verified action plan.

RULES:
1. Use ONLY the structured action plan below.
2. Do NOT invent steps, documents, URLs, fees, deadlines, or offices.
3. Do NOT change eligibility status.
4. Do NOT tell the citizen their application will be accepted.
5. The answer must contain useful steps directly in chat, not just a link.
6. {build_language_instruction(code, strict_language_mode=False)}

QUESTION:
{(query or "What should I do next?")}

ACTION PLAN (AUTHORITATIVE):
{json.dumps(plan.to_dict(), ensure_ascii=False, indent=2)}

Write a concise action plan in {language_name(code)}.
"""


def _sanitize_llm_action_plan(text: str, plan: ActionPlan) -> str:
    from app.services.eligibility_explanation import _contradicts_status

    cleaned = (text or "").strip()
    if not cleaned:
        return ""
    if _contradicts_status(cleaned, plan.status):
        logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=contradicts_status")
        return ""
    if plan.status == EvaluationStatus.NOT_ELIGIBLE.value:
        if re.search(r"\b(you are eligible|you can apply now|apply now|proceed with your application)\b", cleaned, re.I):
            logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=contradicts_not_eligible")
            return ""
    if plan.status == EvaluationStatus.ELIGIBLE.value:
        if re.search(r"\b(will be accepted|guaranteed approval|definitely approved)\b", cleaned, re.I):
            logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=approval_claim")
            return ""
    allowed_urls = set(plan.pdf_urls)
    if plan.application_url:
        allowed_urls.add(plan.application_url)
    for s in plan.source_urls:
        if s.get("url"):
            allowed_urls.add(str(s["url"]))
    for match in _URL_IN_TEXT.finditer(cleaned):
        url = match.group(0).rstrip(".,);]")
        if url not in allowed_urls:
            logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=unknown_url")
            return ""
    if not plan.documents and re.search(r"\b(aadhaar|pan|passport|income certificate)\b", cleaned, re.I):
        logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=invented_documents")
        return ""
    generic_steps = (
        r"\b(create an account|upload aadhaar|pay the application fee|wait 30 days|track your application)\b"
    )
    if re.search(generic_steps, cleaned, re.I) and not any(
        k in " ".join(s.text.lower() for s in plan.steps) for k in ("account", "upload", "fee", "track", "wait")
    ):
        logger.info("ACTION_PLAN_OLLAMA_REJECTED reason=invented_generic_step")
        return ""
    return cleaned


def render_action_plan(
    plan: ActionPlan,
    *,
    query: str = "",
    response_language: str = "EN",
    focus: ActionFocus = ActionFocus.FULL,
    use_llm: bool = True,
) -> Dict[str, Any]:
    fallback = build_deterministic_action_plan_answer(plan, response_language=response_language, focus=focus)
    official = _official_from_plan(plan)

    if plan.extraction_status in ("scheme_mismatch", "conversation_mismatch", "evidence_not_validated"):
        logger.info("ACTION_PLAN_FALLBACK status=%s", plan.extraction_status)
        return {
            "answer": fallback,
            "applied": False,
            "fallback": True,
            "llm_invoked": False,
            "official_sources": official,
            "action_plan": plan.to_dict(),
        }

    if plan.extraction_status in ("no_steps", "no_plan") and not plan.steps:
        logger.info("ACTION_PLAN_FALLBACK reason=no_steps")
        return {
            "answer": fallback,
            "applied": False,
            "fallback": True,
            "llm_invoked": False,
            "official_sources": official,
            "action_plan": plan.to_dict(),
        }

    if not use_llm:
        return {
            "answer": fallback,
            "applied": True,
            "fallback": True,
            "llm_invoked": False,
            "official_sources": official,
            "action_plan": plan.to_dict(),
        }

    prompt = build_action_plan_prompt(plan, response_language=response_language, query=query)
    llm_invoked = False
    try:
        from app.services.llm_service import clean_llm_response, generate_from_fixed_prompt

        started = time.perf_counter()
        raw = generate_from_fixed_prompt(prompt)
        llm_invoked = True
        candidate = clean_llm_response(str(raw.get("response") or ""))
        candidate = _sanitize_llm_action_plan(candidate, plan)
        if candidate and len(candidate.strip()) >= 40:
            return {
                "answer": candidate,
                "applied": True,
                "fallback": False,
                "llm_invoked": True,
                "llm_model": raw.get("model"),
                "llm_latency_ms": int((time.perf_counter() - started) * 1000),
                "official_sources": official,
                "action_plan": plan.to_dict(),
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("ACTION_PLAN_FALLBACK reason=llm_error err=%s", type(exc).__name__)

    logger.info("ACTION_PLAN_FALLBACK mode=deterministic")
    return {
        "answer": fallback,
        "applied": True,
        "fallback": True,
        "llm_invoked": llm_invoked,
        "official_sources": official,
        "action_plan": plan.to_dict(),
    }


def apply_action_plan(
    *,
    sources: Sequence[Dict[str, Any]],
    query: str,
    response_language: str,
    intent: CitizenIntent,
    scheme_identity: Optional[Dict[str, str]] = None,
    eligibility_status: Optional[str] = None,
    eligibility_evaluation: Optional[Dict[str, Any]] = None,
    scheme_guidance: Optional[Dict[str, Any]] = None,
    known_information: Optional[Dict[str, Any]] = None,
    conversation_id: Optional[str] = None,
    session_conversation_id: Optional[str] = None,
    eligibility_session_active: bool = False,
    evidence_validated: bool = True,
    use_llm: bool = True,
) -> Dict[str, Any]:
    if not should_build_action_plan(
        intent,
        query,
        has_eligibility=bool(eligibility_status or eligibility_evaluation),
    ):
        return {"applied": False}

    focus = detect_action_focus(query)
    plan = build_action_plan(
        sources=sources,
        query=query,
        scheme_identity=scheme_identity,
        eligibility_status=eligibility_status,
        eligibility_evaluation=eligibility_evaluation,
        scheme_guidance=scheme_guidance,
        known_information=known_information,
        conversation_id=conversation_id,
        session_conversation_id=session_conversation_id,
        eligibility_session_active=eligibility_session_active,
        evidence_validated=evidence_validated,
        focus=focus,
    )
    rendered = render_action_plan(
        plan,
        query=query,
        response_language=response_language,
        focus=focus,
        use_llm=use_llm,
    )
    rendered["focus"] = focus.value
    return rendered
