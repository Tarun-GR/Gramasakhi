"""Stage 6B-2 — interactive eligibility questioning (conversation-scoped).

Deterministic state handling. No eligibility decisions. No permanent profiles.
Session snapshots are stored inside assistant message sources_json (internal marker).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.services.citizen_assistance import CitizenIntent, classify_citizen_intent
from app.services.eligibility_criteria import (
    EligibilityCriteriaResult,
    enrich_assistance_fields_from_criteria,
)

SESSION_MARKER = "_gramsakhi_eligibility_session"

# Deterministic question order (stable for tests).
CRITERION_ORDER: Tuple[str, ...] = (
    "age",
    "gender",
    "state",
    "district",
    "residence",
    "occupation",
    "employment",
    "income",
    "landholding",
    "education",
    "marital_status",
    "social_category",
    "beneficiary_status",
    "ownership",
    "other",
)

_QUESTION_TEMPLATES: Dict[str, Dict[str, str]] = {
    "age": {
        "EN": "What is your age?",
        "KN": "ನಿಮ್ಮ ವಯಸ್ಸು ಎಷ್ಟು?",
        "HI": "आपकी उम्र कितनी है?",
    },
    "gender": {
        "EN": "What is your gender?",
        "KN": "ನಿಮ್ಮ ಲಿಂಗ ಯಾವುದು?",
        "HI": "आपका लिंग क्या है?",
    },
    "state": {
        "EN": "Which state do you live in?",
        "KN": "ನೀವು ಯಾವ ರಾಜ್ಯದಲ್ಲಿ ವಾಸಿಸುತ್ತೀರಿ?",
        "HI": "आप किस राज्य में रहते हैं?",
    },
    "district": {
        "EN": "Which district do you live in?",
        "KN": "ನೀವು ಯಾವ ಜಿಲ್ಲೆಯಲ್ಲಿ ವಾಸಿಸುತ್ತೀರಿ?",
        "HI": "आप किस जिले में रहते हैं?",
    },
    "residence": {
        "EN": "Where do you currently reside?",
        "KN": "ನೀವು ಪ್ರಸ್ತುತ ಎಲ್ಲಿ ವಾಸಿಸುತ್ತೀರಿ?",
        "HI": "आप वर्तमान में कहाँ रहते हैं?",
    },
    "occupation": {
        "EN": "What is your occupation?",
        "KN": "ನಿಮ್ಮ ವೃತ್ತಿ ಯಾವುದು?",
        "HI": "आपका व्यवसाय क्या है?",
    },
    "employment": {
        "EN": "What is your employment status?",
        "KN": "ನಿಮ್ಮ ಉದ್ಯೋಗ ಸ್ಥಿತಿ ಯಾವುದು?",
        "HI": "आपकी रोज़गार स्थिति क्या है?",
    },
    "income": {
        "EN": "What is your approximate annual household income?",
        "KN": "ನಿಮ್ಮ ಅಂದಾಜು ವಾರ್ಷಿಕ ಗೃಹ ಆದಾಯ ಎಷ್ಟು?",
        "HI": "आपकी अनुमानित वार्षिक घरेलू आय कितनी है?",
    },
    "landholding": {
        "EN": "How much land do you hold (in acres or hectares)?",
        "KN": "ನಿಮ್ಮ ಬಳಿ ಎಷ್ಟು ಭೂಮಿ (ಎಕರೆ/ಹೆಕ್ಟೇರ್) ಇದೆ?",
        "HI": "आपके पास कितनी ज़मीन (एकड़/हेक्टेयर) है?",
    },
    "education": {
        "EN": "What is your highest level of education?",
        "KN": "ನಿಮ್ಮ ಉನ್ನತ ಶಿಕ್ಷಣ ಮಟ್ಟ ಯಾವುದು?",
        "HI": "आपकी उच्चतम शिक्षा का स्तर क्या है?",
    },
    "marital_status": {
        "EN": "What is your marital status?",
        "KN": "ನಿಮ್ಮ ವೈವಾಹಿಕ ಸ್ಥಿತಿ ಯಾವುದು?",
        "HI": "आपकी वैवाहिक स्थिति क्या है?",
    },
    "social_category": {
        "EN": "Which social category do you belong to (if applicable)?",
        "KN": "ನೀವು ಯಾವ ಸामाजिक ವರ್ಗಕ್ಕೆ ಸೇರಿದ್ದೀರಿ (ಅನ್ವಯಿಸಿದರೆ)?",
        "HI": "आप किस सामाजिक श्रेणी से हैं (यदि लागू हो)?",
    },
    "beneficiary_status": {
        "EN": "Do you already receive benefits under this or a related scheme?",
        "KN": "ನೀವು ಈ ಅಥವಾ ಸಂಬಂಧಿತ ಯೋಜನೆಯ ಪ್ರಯೋಜನಗಳನ್ನು ಈಗಾಗಲೇ ಪಡೆಯುತ್ತಿದ್ದೀರಾ?",
        "HI": "क्या आप पहले से इस या संबंधित योजना का लाभ ले रहे हैं?",
    },
    "ownership": {
        "EN": "Do you own the required asset or property for this scheme?",
        "KN": "ಈ ಯೋಜನೆಗೆ ಅಗತ್ಯವಾದ ಆಸ್ತಿ/ಸ್ವತ್ತು ನಿಮ್ಮ ಬಳಿ ಇದೆಯೇ?",
        "HI": "क्या आपके पास इस योजना के लिए आवश्यक संपत्ति है?",
    },
    "other": {
        "EN": "Please share the additional detail needed for eligibility.",
        "KN": "ದಯವಿಟ್ಟು ಅರ್ಹತೆಗೆ ಅಗತ್ಯವಾದ ಹೆಚ್ಚುವರಿ ವಿವರವನ್ನು ಹಂಚಿಕೊಳ್ಳಿ.",
        "HI": "कृपया पात्रता के लिए आवश्यक अतिरिक्त जानकारी साझा करें।",
    },
}

_INTRO_TEMPLATES = {
    "EN": "I can help check your eligibility for {scheme}. ",
    "KN": "{scheme} ಯೋಜನೆಯ ಅರ್ಹತೆಯನ್ನು ಪರಿಶೀಲಿಸಲು ನಾನು ಸಹಾಯ ಮಾಡಬಲ್ಲೆ. ",
    "HI": "मैं {scheme} योजना की पात्रता जांचने में मदद कर सकता/सकती हूँ। ",
}

_COMPLETION_TEMPLATES = {
    "EN": (
        "Thank you. I have the information needed to check the eligibility criteria "
        "for this scheme."
    ),
    "KN": (
        "ಧನ್ಯವಾದ. ಈ ಯೋಜನೆಯ ಅರ್ಹತೆ ಮಾನದಂಡಗಳನ್ನು ಪರಿಶೀಲಿಸಲು ಅಗತ್ಯವಾದ ಮಾಹಿತಿ "
        "ನನ್ನ ಬಳಿ ಇದೆ."
    ),
    "HI": (
        "धन्यवाद। इस योजना की पात्रता मानदंडों की जांच के लिए आवश्यक जानकारी "
        "मेरे पास है।"
    ),
}

_UNCLEAR_TEMPLATES = {
    "age": {
        "EN": "I didn't quite understand that. Could you tell me your age in years?",
        "KN": "ನನಗೆ ಸ್ಪಷ್ಟವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ವಯಸ್ಸನ್ನು ವರ್ಷಗಳಲ್ಲಿ ಹೇಳಿ.",
        "HI": "मुझे समझ नहीं आया। कृपया अपनी उम्र वर्षों में बताएं।",
    },
    "income": {
        "EN": "I didn't quite understand that. Could you tell me your approximate annual household income?",
        "KN": "ನನಗೆ ಸ್ಪಷ್ಟವಾಗಲಿಲ್ಲ. ದಯವಿಟ್ಟು ನಿಮ್ಮ ಅಂದಾಜು ವಾರ್ಷಿಕ ಗೃಹ ಆದಾಯವನ್ನು ಹೇಳಿ.",
        "HI": "मुझे समझ नहीं आया। कृपया अपनी अनुमानित वार्षिक घरेलू आय बताएं।",
    },
}

_INSUFFICIENT_TEMPLATES = {
    "EN": (
        "I couldn't find enough official eligibility information to check this right now."
    ),
    "KN": (
        "ಈ ಯೋಜನೆಯ ಅಧಿಕೃತ ಅರ್ಹತೆ ಮಾಹಿತಿ ಸಾಕಷ್ಟು ದೊರಕಲಿಲ್ಲ; ಈಗ ಪರಿಶೀಲಿಸಲು "
        "ಸಾಧ್ಯವಾಗಲಿಲ್ಲ."
    ),
    "HI": (
        "मुझे इस योजना की आधिकारिक पात्रता जानकारी पर्याप्त नहीं मिली; अभी "
        "जांच संभव नहीं है।"
    ),
}

_STATE_CANONICAL = {
    "karnataka": "Karnataka",
    "ಕರ್ನಾಟಕ": "Karnataka",
    "कर्नाटक": "Karnataka",
    "maharashtra": "Maharashtra",
    "tamil nadu": "Tamil Nadu",
    "uttar pradesh": "Uttar Pradesh",
    "chhattisgarh": "Chhattisgarh",
    "delhi": "Delhi",
    "gujarat": "Gujarat",
    "rajasthan": "Rajasthan",
    "kerala": "Kerala",
    "punjab": "Punjab",
    "haryana": "Haryana",
    "west bengal": "West Bengal",
    "bihar": "Bihar",
    "odisha": "Odisha",
    "telangana": "Telangana",
    "andhra pradesh": "Andhra Pradesh",
    "madhya pradesh": "Madhya Pradesh",
    "assam": "Assam",
    "jharkhand": "Jharkhand",
}

_AGE_PATTERNS = (
    re.compile(r"\b(?:i am|i'm|age is|aged)\s*(\d{1,3})\b", re.I),
    re.compile(r"\b(\d{1,3})\s*(?:years?\s*old|yrs?\s*old|varsha|वर्ष)\b", re.I),
    re.compile(r"\bvayassu\s*(\d{1,3})\b", re.I),
    re.compile(r"ವಯಸ್ಸು\s*(\d{1,3})", re.I),
    re.compile(r"\bumr\s*(\d{1,3})\b", re.I),
    re.compile(r"\bage\s*(\d{1,3})\b", re.I),
    re.compile(r"(\d{1,3})\s*(?:varsha|ವರ್ಷ)", re.I),
)

_INCOME_PATTERNS = (
    re.compile(
        r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr)\b",
        re.I,
    ),
    re.compile(r"(?:₹|rs\.?|inr)\s*([\d,]+)", re.I),
)

_GENDER_EXTRACT = (
    (re.compile(r"\b(woman|women|female|girl|mahila|ಮಹಿಳ)\b", re.I), "female"),
    (re.compile(r"\b(man|men|male|boy|purush|ಪುರುಷ)\b", re.I), "male"),
)

_OCCUPATION_EXTRACT = (
    (re.compile(r"\bfarmers?\b|\bkrushik\b|\bkisan\b|\bकिसान\b", re.I), "farmer"),
    (re.compile(r"\bentrepreneurs?\b", re.I), "entrepreneur"),
    (re.compile(r"\bstudents?\b", re.I), "student"),
    (re.compile(r"\bunemployed\b", re.I), "unemployed"),
    (re.compile(r"\bself[- ]?employed\b", re.I), "self_employed"),
)

_UNRELATED_INTENTS = frozenset(
    {
        CitizenIntent.OVERVIEW,
        CitizenIntent.BENEFITS,
        CitizenIntent.DOCUMENTS,
        CitizenIntent.APPLICATION,
        CitizenIntent.DEADLINE,
        CitizenIntent.APPLICATION_PORTAL,
        CitizenIntent.COMPARISON,
    }
)


@dataclass
class EligibilitySession:
    conversation_id: str
    active_scheme: str
    scheme_id: Optional[str] = None
    criteria_snapshot: Dict[str, Any] = field(default_factory=dict)
    required_information: List[str] = field(default_factory=list)
    known_information: Dict[str, Any] = field(default_factory=dict)
    missing_information: List[str] = field(default_factory=list)
    current_question_type: Optional[str] = None
    completed: bool = False
    session_active: bool = True
    response_language: str = "EN"
    collected_answers: Dict[str, Any] = field(default_factory=dict)
    evaluation_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EligibilitySession":
        return cls(
            conversation_id=str(data.get("conversation_id") or ""),
            active_scheme=str(data.get("active_scheme") or ""),
            scheme_id=data.get("scheme_id"),
            criteria_snapshot=dict(data.get("criteria_snapshot") or {}),
            required_information=list(data.get("required_information") or []),
            known_information=dict(data.get("known_information") or {}),
            missing_information=list(data.get("missing_information") or []),
            current_question_type=data.get("current_question_type"),
            completed=bool(data.get("completed")),
            session_active=bool(data.get("session_active", True)),
            response_language=str(data.get("response_language") or "EN"),
            collected_answers=dict(data.get("collected_answers") or {}),
            evaluation_result=(dict(data["evaluation_result"]) if data.get("evaluation_result") else None),
        )


@dataclass
class EligibilityTurnOutcome:
    handled: bool = False
    skip_rag: bool = False
    answer: Optional[str] = None
    session: Optional[EligibilitySession] = None
    eligibility_criteria: Optional[Dict[str, Any]] = None
    required_information: Optional[List[str]] = None
    missing_information: Optional[List[str]] = None
    known_information: Optional[Dict[str, Any]] = None
    eligibility_session_active: bool = False
    eligibility_question: Optional[str] = None
    eligibility_completed: bool = False
    validated: bool = True
    knowledge_source: str = "eligibility_questioning"


def _lang(code: Optional[str]) -> str:
    c = (code or "EN").strip().upper()[:2]
    return c if c in ("EN", "KN", "HI") else "EN"


def sort_missing(required: Sequence[str], missing: Sequence[str]) -> List[str]:
    order = {k: i for i, k in enumerate(CRITERION_ORDER)}
    return sorted(missing, key=lambda x: order.get(x, len(CRITERION_ORDER)))


def question_for_type(
    info_type: str,
    *,
    language: str,
    scheme_name: str = "",
    criteria_snapshot: Optional[Dict[str, Any]] = None,
    include_intro: bool = False,
) -> str:
    lang = _lang(language)
    tmpl = _QUESTION_TEMPLATES.get(info_type, _QUESTION_TEMPLATES["other"])
    q = tmpl.get(lang) or tmpl["EN"]
    if include_intro and scheme_name:
        intro = _INTRO_TEMPLATES.get(lang) or _INTRO_TEMPLATES["EN"]
        return intro.format(scheme=scheme_name) + q
    return q


def completion_message(language: str) -> str:
    lang = _lang(language)
    return _COMPLETION_TEMPLATES.get(lang) or _COMPLETION_TEMPLATES["EN"]


def insufficient_evidence_message(language: str) -> str:
    lang = _lang(language)
    return _INSUFFICIENT_TEMPLATES.get(lang) or _INSUFFICIENT_TEMPLATES["EN"]


def unclear_message(info_type: str, language: str) -> str:
    lang = _lang(language)
    bucket = _UNCLEAR_TEMPLATES.get(info_type) or _UNCLEAR_TEMPLATES.get("age", {})
    return bucket.get(lang) or bucket.get("EN") or question_for_type(info_type, language=lang)


def _parse_income_value(text: str) -> Optional[int]:
    for pat in _INCOME_PATTERNS:
        m = pat.search(text)
        if not m:
            continue
        num = m.group(1).replace(",", "")
        try:
            val = float(num)
        except ValueError:
            continue
        unit = (m.group(2) or "").lower() if m.lastindex and m.lastindex >= 2 else ""
        if unit in ("lakh", "lac"):
            return int(val * 100_000)
        if unit in ("crore", "cr"):
            return int(val * 10_000_000)
        if val >= 1000:
            return int(val)
    return None


def _parse_age_value(text: str) -> Optional[int]:
    for pat in _AGE_PATTERNS:
        m = pat.search(text)
        if m:
            age = int(m.group(1))
            if 1 <= age <= 120:
                return age
    return None


def _parse_state_value(text: str) -> Optional[str]:
    low = text.lower()
    for key, canon in _STATE_CANONICAL.items():
        if key in low:
            return canon
    m = re.search(
        r"(?:live in|from|reside in|based in|alli iddini|mein rehte|rahta hoon)\s+([A-Za-z\u0C80-\u0CFF\u0900-\u097F\s]+)",
        text,
        re.I,
    )
    if m:
        fragment = m.group(1).strip().split(".")[0].split(",")[0][:40]
        for key, canon in _STATE_CANONICAL.items():
            if key in fragment.lower():
                return canon
        if len(fragment) >= 3:
            return fragment.title()
    return None


def extract_known_information_from_text(text: str) -> Dict[str, Any]:
    """Extract explicitly stated citizen facts — no stereotypes."""
    raw = (text or "").strip()
    if not raw:
        return {}
    known: Dict[str, Any] = {}
    age = _parse_age_value(raw)
    if age is not None:
        known["age"] = age
    for pat, gender in _GENDER_EXTRACT:
        if pat.search(raw):
            known["gender"] = gender
            break
    state = _parse_state_value(raw)
    if state:
        known["state"] = state
        if "district" not in known:
            known["residence"] = state
    income = _parse_income_value(raw)
    if income is not None and re.search(r"income|aad|salary|₹|rs\.?|lakh|lac", raw, re.I):
        known["income"] = income
    for pat, occ in _OCCUPATION_EXTRACT:
        if pat.search(raw):
            known["occupation"] = occ
            break
    if re.search(r"\bfarmer\b|\bkrushik\b|\bkisan\b", raw, re.I) and "occupation" not in known:
        known["occupation"] = "farmer"
    yes_no_farmer = re.search(r"\b(?:are you|am i)\s+a\s+farmer\b", raw, re.I)
    if yes_no_farmer and re.search(r"\byes\b", raw, re.I):
        known["occupation"] = "farmer"
    return known


def parse_answer_for_type(info_type: str, text: str) -> Tuple[bool, Optional[Any], bool]:
    """Return (parsed_ok, normalized_value, unclear)."""
    raw = (text or "").strip()
    if not raw:
        return False, None, True
    if is_unrelated_question(raw):
        return False, None, False
    if info_type == "age":
        if re.fullmatch(r"\d{1,3}", raw):
            age = int(raw)
            if 1 <= age <= 120:
                return True, age, False
        age = _parse_age_value(raw)
        if age is not None:
            return True, age, False
        return False, None, True
    if info_type == "gender":
        for pat, gender in _GENDER_EXTRACT:
            if pat.search(raw):
                return True, gender, False
        if raw.lower() in ("male", "female", "woman", "man"):
            return True, "female" if raw.lower() in ("female", "woman") else "male", False
        return False, None, True
    if info_type in ("state", "district", "residence"):
        state = _parse_state_value(raw)
        if state:
            return True, state, False
        if len(raw) >= 2 and not raw.endswith("?"):
            return True, raw.strip().title(), False
        return False, None, True
    if info_type == "income":
        income = _parse_income_value(raw)
        if income is not None:
            return True, income, False
        return False, None, True
    if info_type == "occupation":
        for pat, occ in _OCCUPATION_EXTRACT:
            if pat.search(raw):
                return True, occ, False
        if re.search(r"\byes\b", raw, re.I):
            return True, "yes", False
        if len(raw) >= 2 and not raw.endswith("?"):
            return True, raw.strip().lower(), False
        return False, None, True
    if len(raw) >= 2 and not raw.endswith("?"):
        return True, raw.strip(), False
    return False, None, True


def is_unrelated_question(text: str) -> bool:
    intent = classify_citizen_intent(text)
    if intent in _UNRELATED_INTENTS:
        return True
    if "?" in text and re.search(
        r"\b(what|how|when|where|why|benefits?|documents?|apply|application)\b",
        text,
        re.I,
    ):
        return True
    return False


def schemes_differ(a: Optional[str], b: Optional[str]) -> bool:
    if not a or not b:
        return False
    try:
        from app.services.myscheme_service import normalize_scheme_key

        return normalize_scheme_key(a) != normalize_scheme_key(b)
    except Exception:
        return a.strip().lower() != b.strip().lower()


def apply_known_to_session(session: EligibilitySession, known: Dict[str, Any]) -> None:
    for key, value in known.items():
        if key not in session.required_information:
            continue
        session.known_information[key] = value
        session.collected_answers[key] = value
        if key in session.missing_information:
            session.missing_information.remove(key)
    session.missing_information = sort_missing(
        session.required_information, session.missing_information
    )


def next_question_type(session: EligibilitySession) -> Optional[str]:
    missing = sort_missing(session.required_information, session.missing_information)
    return missing[0] if missing else None


def advance_session(session: EligibilitySession, *, include_intro: bool = False) -> str:
    if not session.missing_information:
        session.completed = True
        session.session_active = False
        session.current_question_type = None
        return completion_message(session.response_language)
    qtype = next_question_type(session)
    session.current_question_type = qtype
    return question_for_type(
        qtype or "other",
        language=session.response_language,
        scheme_name=session.active_scheme,
        criteria_snapshot=session.criteria_snapshot,
        include_intro=include_intro,
    )


def start_session_from_criteria(
    *,
    conversation_id: str,
    active_scheme: str,
    scheme_id: Optional[str],
    criteria: EligibilityCriteriaResult,
    response_language: str,
    seed_text: str = "",
) -> Optional[EligibilitySession]:
    if criteria.rejected or criteria.extraction_status != "ok":
        return None
    required, _, missing = enrich_assistance_fields_from_criteria(criteria)
    if not required:
        return None
    session = EligibilitySession(
        conversation_id=conversation_id,
        active_scheme=active_scheme,
        scheme_id=scheme_id,
        criteria_snapshot=criteria.to_dict(),
        required_information=list(required),
        missing_information=sort_missing(required, missing),
        response_language=_lang(response_language),
    )
    seed = extract_known_information_from_text(seed_text)
    if seed:
        apply_known_to_session(session, seed)
    if not session.missing_information:
        session.completed = True
        session.session_active = False
    else:
        session.current_question_type = next_question_type(session)
    return session


def capture_session_answer(
    session: EligibilitySession,
    user_text: str,
) -> Tuple[bool, bool, Optional[str]]:
    """Process an answer for the current question. Returns (captured, unrelated, answer)."""
    if session.completed or not session.session_active:
        return False, False, None
    expected = session.current_question_type
    if not expected:
        return False, False, None
    if is_unrelated_question(user_text):
        return False, True, None
    multi = extract_known_information_from_text(user_text)
    if multi:
        apply_known_to_session(session, multi)
    ok, value, unclear = parse_answer_for_type(expected, user_text)
    if ok and value is not None:
        session.known_information[expected] = value
        session.collected_answers[expected] = value
        if expected in session.missing_information:
            session.missing_information.remove(expected)
        session.missing_information = sort_missing(
            session.required_information, session.missing_information
        )
    elif not multi and unclear:
        return False, False, unclear_message(expected, session.response_language)
    if not session.missing_information:
        session.completed = True
        session.session_active = False
        session.current_question_type = None
        return True, False, completion_message(session.response_language)
    session.current_question_type = next_question_type(session)
    q = question_for_type(
        session.current_question_type or "other",
        language=session.response_language,
        scheme_name=session.active_scheme,
        criteria_snapshot=session.criteria_snapshot,
    )
    return True, False, q


def load_session_from_messages(messages: Sequence[Any]) -> Optional[EligibilitySession]:
    for msg in reversed(list(messages or [])):
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        if role != "assistant":
            continue
        raw_json = getattr(msg, "sources_json", None)
        if raw_json is None and isinstance(msg, dict):
            sources = msg.get("sources") or []
        else:
            try:
                sources = json.loads(raw_json) if raw_json else []
            except Exception:
                sources = []
        if not isinstance(sources, list):
            sources = []
        for item in sources or []:
            if isinstance(item, dict) and item.get("_internal") == SESSION_MARKER:
                payload = item.get("session")
                if isinstance(payload, dict):
                    try:
                        return EligibilitySession.from_dict(payload)
                    except (TypeError, ValueError, KeyError):
                        continue
    return None


def embed_session_in_sources(
    sources: Optional[List[Any]],
    session: Optional[EligibilitySession],
) -> List[Any]:
    out = [
        s
        for s in (sources or [])
        if not (isinstance(s, dict) and s.get("_internal") == SESSION_MARKER)
    ]
    if session is not None:
        out.append({"_internal": SESSION_MARKER, "session": session.to_dict()})
    return out


def strip_internal_sources(sources: Optional[List[Any]]) -> List[Any]:
    return [
        s
        for s in (sources or [])
        if not (isinstance(s, dict) and s.get("_internal") == SESSION_MARKER)
    ]


def session_outcome_from(session: Optional[EligibilitySession]) -> Dict[str, Any]:
    if session is None:
        return {
            "eligibility_session_active": False,
            "eligibility_question": None,
            "eligibility_completed": False,
            "known_information": None,
            "missing_information": None,
        }
    return {
        "eligibility_session_active": bool(session.session_active and not session.completed),
        "eligibility_question": session.current_question_type,
        "eligibility_completed": bool(session.completed),
        "known_information": dict(session.known_information) if session.known_information else None,
        "missing_information": list(session.missing_information) if session.missing_information else None,
    }


def try_handle_active_session(
    *,
    original_query: str,
    prior_session: Optional[EligibilitySession],
    detected_scheme: Optional[str],
    response_language: str,
) -> EligibilityTurnOutcome:
    """Answer capture path — skips RAG when handling eligibility answers."""
    outcome = EligibilityTurnOutcome()
    if prior_session is None or not prior_session.session_active or prior_session.completed:
        return outcome
    if schemes_differ(detected_scheme, prior_session.active_scheme):
        return outcome
    if is_unrelated_question(original_query):
        return outcome
    captured, unrelated, answer = capture_session_answer(prior_session, original_query)
    if unrelated:
        return outcome
    if captured and answer:
        outcome.handled = True
        outcome.skip_rag = True
        outcome.answer = answer
        outcome.session = prior_session
        outcome.eligibility_criteria = prior_session.criteria_snapshot
        outcome.required_information = list(prior_session.required_information)
        outcome.missing_information = list(prior_session.missing_information)
        outcome.known_information = dict(prior_session.known_information)
        outcome.eligibility_session_active = prior_session.session_active and not prior_session.completed
        outcome.eligibility_question = prior_session.current_question_type
        outcome.eligibility_completed = prior_session.completed
        return outcome
    return outcome


def build_first_question_response(
    *,
    session: EligibilitySession,
) -> str:
    if session.completed:
        return completion_message(session.response_language)
    return question_for_type(
        session.current_question_type or "other",
        language=session.response_language,
        scheme_name=session.active_scheme,
        criteria_snapshot=session.criteria_snapshot,
        include_intro=True,
    )
