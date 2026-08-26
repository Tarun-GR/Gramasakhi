"""Deterministic language/factual quality gate for GramSakhi answers.

Runs AFTER Evidence Validator + generation. Does not redesign RAG.
Critical mismatches are hard FAIL (not soft averages).
"""

from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.services.kannada_glossary import ALLOWED_LATIN_TOKENS, PRESERVE_ENTITIES
from app.services.language_service import LANG_EN, LANG_HI, LANG_KN, normalize_language_code

logger = logging.getLogger(__name__)

# Soft thresholds (language fluency). Critical checks are separate hard gates.
KN_MIN_SCRIPT_RATIO = 0.28
KN_MAX_ENGLISH_PROSE_RATIO = 0.55
HI_MIN_SCRIPT_RATIO = 0.28


@dataclass
class QualityResult:
    passed: bool
    failures: List[str] = field(default_factory=list)
    soft_failures: List[str] = field(default_factory=list)
    scores: Dict[str, float] = field(default_factory=dict)
    details: Dict[str, Any] = field(default_factory=dict)

    def failure_summary(self) -> str:
        return "; ".join(self.failures or self.soft_failures) or "quality_fail"


def normalize_unicode_display(text: str) -> str:
    """NFC normalize without changing intended visible Kannada meaning."""
    return unicodedata.normalize("NFC", text or "")


def _is_kn(ch: str) -> bool:
    return "\u0c80" <= ch <= "\u0cff"


def _is_hi(ch: str) -> bool:
    return "\u0900" <= ch <= "\u097f"


def _is_latin_letter(ch: str) -> bool:
    return ("a" <= ch.lower() <= "z") if ch.isalpha() else False


def script_ratios(text: str) -> Dict[str, float]:
    t = text or ""
    letters = [ch for ch in t if ch.isalpha() or _is_kn(ch) or _is_hi(ch)]
    if not letters:
        return {"kn": 0.0, "hi": 0.0, "latin": 0.0, "alpha": 0}
    kn = sum(1 for ch in letters if _is_kn(ch))
    hi = sum(1 for ch in letters if _is_hi(ch))
    latin = sum(1 for ch in letters if _is_latin_letter(ch))
    n = len(letters)
    return {"kn": kn / n, "hi": hi / n, "latin": latin / n, "alpha": float(n)}


def extract_urls(text: str) -> List[str]:
    found = re.findall(r"https?://[^\s<>\"')\]]+", text or "", flags=re.I)
    cleaned = []
    for u in found:
        cleaned.append(u.rstrip(".,;:!?)]}'\"、。"))
    return cleaned


def extract_years(text: str) -> Set[str]:
    return set(re.findall(r"\b(?:19|20)\d{2}\b", text or ""))


def extract_percentages(text: str) -> Set[str]:
    found = set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*%", text or ""):
        found.add(_norm_num(m.group(1)))
    return found


def _norm_num(raw: str) -> str:
    s = (raw or "").replace(",", "").replace(" ", "").strip()
    if not s:
        return s
    try:
        f = float(s)
        if abs(f - int(f)) < 1e-9:
            return str(int(f))
        return f"{f:.4f}".rstrip("0").rstrip(".")
    except ValueError:
        return s


def extract_currency_amounts(text: str) -> Set[str]:
    """Extract Rs/INR/\u20b9 amounts and other significant money-like numbers."""
    t = text or ""
    amounts: Set[str] = set()
    patterns = (
        r"(?:rs\.?|inr|\u20b9)\s*([0-9][0-9,]*(?:\.\d+)?)",
        r"([0-9][0-9,]*(?:\.\d+)?)\s*(?:rupees|rs\.?)",
    )
    for pat in patterns:
        for m in re.finditer(pat, t, flags=re.I):
            amounts.add(_norm_num(m.group(1)))
    return amounts


def extract_significant_numbers(text: str) -> Set[str]:
    """Numbers that matter for grounding (amounts, counts, ages, years)."""
    t = text or ""
    nums: Set[str] = set()
    nums |= extract_currency_amounts(t)
    nums |= extract_percentages(t)
    nums |= extract_years(t)
    # Standalone integers >= 2 (skip 0/1 noise); keep installment-style small counts 2-12
    for m in re.finditer(r"\b(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?\b", t):
        n = _norm_num(m.group(1))
        try:
            v = float(n)
        except ValueError:
            continue
        if v >= 2:
            nums.add(n)
    return nums


def extract_dates(text: str) -> Set[str]:
    t = text or ""
    dates: Set[str] = set()
    for m in re.finditer(
        r"\b(\d{1,2})\s*(January|February|March|April|May|June|July|August|"
        r"September|October|November|December)\s*((?:19|20)\d{2})\b",
        t,
        flags=re.I,
    ):
        dates.add(f"{int(m.group(1))}-{m.group(2).lower()[:3]}-{m.group(3)}")
    for m in re.finditer(r"\b(\d{1,2})[/-](\d{1,2})[/-]((?:19|20)\d{2})\b", t):
        dates.add(f"{int(m.group(1))}-{int(m.group(2))}-{m.group(3)}")
    dates |= extract_years(t)
    return dates


def evidence_text(evidence: Sequence[Dict[str, Any]]) -> str:
    parts = []
    for doc in evidence or []:
        parts.append(str(doc.get("content") or doc.get("text") or ""))
        for k in ("scheme_name", "source", "ministry", "url", "source_url"):
            v = doc.get(k)
            if v:
                parts.append(str(v))
        meta = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        for k in ("scheme_name", "source", "ministry", "url", "source_url"):
            v = meta.get(k)
            if v:
                parts.append(str(v))
    return "\n".join(parts)


def _latin_words(text: str) -> List[str]:
    return re.findall(r"[A-Za-z][A-Za-z\-]{1,}", text or "")


def english_prose_ratio(text: str) -> float:
    """Fraction of Latin words that look like English prose (not allowlisted)."""
    words = _latin_words(text)
    if not words:
        return 0.0
    prose = 0
    for w in words:
        low = w.lower()
        if low in ALLOWED_LATIN_TOKENS:
            continue
        if any(low == e.lower() or low in e.lower().replace(" ", "") for e in PRESERVE_ENTITIES):
            continue
        if len(low) <= 2:
            continue
        prose += 1
    return prose / max(len(words), 1)


def check_language(
    answer: str,
    *,
    response_language: str,
    strict: bool = False,
) -> Tuple[bool, List[str], Dict[str, float]]:
    code = normalize_language_code(response_language) or LANG_EN
    ratios = script_ratios(answer)
    fails: List[str] = []
    scores = {
        "language_score": 100.0,
        "kn_ratio": ratios["kn"],
        "hi_ratio": ratios["hi"],
        "latin_ratio": ratios["latin"],
        "english_prose_ratio": english_prose_ratio(answer),
    }
    if code == LANG_KN:
        min_ratio = 0.40 if strict else KN_MIN_SCRIPT_RATIO
        max_en = 0.35 if strict else KN_MAX_ENGLISH_PROSE_RATIO
        kn_letters = int(ratios["kn"] * ratios["alpha"]) if ratios["alpha"] else 0
        # Entity-heavy answers (scheme names, URLs) can dilute ratio without being English.
        if ratios["kn"] < min_ratio and not (kn_letters >= 28 and ratios["kn"] >= 0.20):
            fails.append("wrong_language_kannada")
            scores["language_score"] = 0.0
        if scores["english_prose_ratio"] > max_en and ratios["kn"] < 0.45:
            fails.append("english_contamination")
            scores["language_score"] = min(scores["language_score"], 20.0)
        # Hard fail: starts like pure English eligibility essay
        if re.match(r"^\s*(To be eligible|Eligibility|The scheme|Farmers who)\b", answer or "", re.I):
            if ratios["kn"] < 0.15:
                fails.append("wrong_language_kannada")
                scores["language_score"] = 0.0
    elif code == LANG_HI:
        if ratios["hi"] < HI_MIN_SCRIPT_RATIO:
            fails.append("wrong_language_hindi")
            scores["language_score"] = 0.0
    elif code == LANG_EN:
        # Do not require zero Indic; allow names. Fail if mostly KN/HI when EN requested.
        if ratios["kn"] > 0.5 or ratios["hi"] > 0.5:
            fails.append("wrong_language_english")
            scores["language_score"] = 0.0
    return (len(fails) == 0), fails, scores


def check_numeric_preservation(
    source: str,
    answer: str,
    *,
    require_all_source_amounts: bool = False,
) -> Tuple[bool, List[str], Dict[str, float]]:
    src_amt = extract_currency_amounts(source)
    ans_amt = extract_currency_amounts(answer)
    src_nums = extract_significant_numbers(source)
    ans_nums = extract_significant_numbers(answer)
    src_pct = extract_percentages(source)

    fails: List[str] = []
    # Invented large currency amounts not in source — always critical
    invented = sorted(a for a in ans_amt if a not in src_amt and a not in src_nums)
    critical_invented = []
    for a in invented:
        try:
            if float(a) >= 100:
                critical_invented.append(a)
        except ValueError:
            pass
    if critical_invented:
        fails.append(f"invented_amount:{','.join(critical_invented)}")

    # Also catch invented bare large numbers commonly used as money (e.g. 12000)
    for a in sorted(ans_nums - src_nums):
        try:
            v = float(a)
        except ValueError:
            continue
        if v >= 1000 and a not in src_amt:
            # Allow years already handled elsewhere
            if re.fullmatch(r"(?:19|20)\d{2}", a):
                continue
            fails.append(f"invented_amount:{a}")

    if src_amt:
        moneyish = bool(ans_amt) or bool(
            re.search(
                r"\b(rs|inr|\u20b9|rupee|amount|benefit|assistance|\u0cb9\u0ca3)\b",
                answer or "",
                re.I,
            )
        )
        if require_all_source_amounts and moneyish:
            missing_amt = sorted(
                a for a in src_amt if a not in ans_amt and a not in ans_nums
            )
            if missing_amt:
                fails.append(f"changed_or_missing_amount:{','.join(missing_amt)}")
        elif moneyish and not require_all_source_amounts:
            # Generation: require at least the largest source amount (e.g. 6000),
            # not every installment breakdown (2000).
            try:
                primary = max(src_amt, key=lambda x: float(x))
            except ValueError:
                primary = next(iter(src_amt))
            if primary not in ans_amt and primary not in ans_nums:
                fails.append(f"changed_or_missing_amount:{primary}")

    if src_pct and require_all_source_amounts:
        missing_pct = sorted(p for p in src_pct if p not in ans_nums)
        if missing_pct:
            fails.append(f"changed_or_missing_percent:{','.join(missing_pct)}")

    score = 100.0 if not fails else 0.0
    return (len(fails) == 0), fails, {"numeric_score": score}


def check_date_preservation(source: str, answer: str) -> Tuple[bool, List[str], Dict[str, float]]:
    src = extract_dates(source)
    fails: List[str] = []
    src_years = extract_years(source)
    ans_years = extract_years(answer)
    # Critical: do not invent or alter years present in the answer
    extra = sorted(ans_years - src_years) if src_years else []
    if extra and src_years:
        fails.append(f"changed_year:{','.join(extra)}")
    score = 100.0 if not fails else 0.0
    return (len(fails) == 0), fails, {"date_score": score, "src_dates": len(src), "ans_dates": len(ans_years)}


def check_url_preservation(
    source: str,
    answer: str,
    *,
    require_source_urls: bool = False,
) -> Tuple[bool, List[str], Dict[str, float]]:
    src_urls = extract_urls(source)
    ans_urls = extract_urls(answer)
    fails: List[str] = []
    src_norm = {u.rstrip("/") for u in src_urls}
    if require_source_urls:
        for u in src_urls:
            alt = u.rstrip("/")
            if alt not in (answer or "") and (alt + "/") not in (answer or ""):
                fails.append(f"missing_url:{u}")
    for u in ans_urls:
        if u.rstrip("/") not in src_norm and src_norm:
            fails.append(f"invented_url:{u}")
        elif u.rstrip("/") not in src_norm and not src_norm:
            fails.append(f"invented_url:{u}")
    score = 100.0 if not fails else 0.0
    return (len(fails) == 0), fails, {"url_score": score}


_CORE_SCHEME_ENTITIES = (
    "PM-KISAN",
    "PMKISAN",
    "PMFBY",
    "PMAY",
    "PMAY-G",
    "PMSBY",
    "KCC",
    "MGNREGA",
    "MGNREGS",
    "Gruha Lakshmi",
    "Gruhalakshmi",
    "Anna Bhagya",
    "Pradhan Mantri Kisan Samman Nidhi",
)

# Equivalent surface forms — any one satisfies preservation for the group.
_ENTITY_ALIAS_GROUPS: Tuple[Tuple[str, ...], ...] = (
    (
        "PM-KISAN",
        "PMKISAN",
        "PM KISAN",
        "Pradhan Mantri Kisan Samman Nidhi",
        "\u0caa\u0cbf\u0c8e\u0c82-\u0c95\u0cbf\u0cb8\u0cbe\u0ca8\u0ccd",
        "\u0caa\u0cbf\u0c8e\u0c82 \u0c95\u0cbf\u0cb8\u0cbe\u0ca8\u0ccd",
        "\u0caa\u0cbf\u0c8e\u0c82\u0c95\u0cbf\u0cb8\u0cbe\u0ca8\u0ccd",
        "\u092a\u0940\u090f\u092e-\u0915\u093f\u0938\u093e\u0928",
        "\u092a\u0940\u090f\u092e \u0915\u093f\u0938\u093e\u0928",
        "\u092a\u0940\u090f\u092e\u0915\u093f\u0938\u093e\u0928",
    ),
    ("Gruha Lakshmi", "Gruhalakshmi", "\u0c97\u0cc3\u0cb9 \u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cc0", "\u0c97\u0cc3\u0cb9\u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cbf", "\u0917\u0943\u0939 \u0932\u0915\u094d\u0937\u094d\u092e\u0940"),
    ("Anna Bhagya", "\u0c85\u0ca8\u0ccd\u0ca8 \u0cad\u0cbe\u0c97\u0ccd\u0caf", "\u0c85\u0ca8\u0ccd\u0ca8\u0cad\u0cbe\u0c97\u0ccd\u0caf", "\u0905\u0928\u094d\u0928 \u092d\u093e\u0917\u094d\u092f"),
    ("MGNREGA", "MGNREGS", "NREGA"),
    ("PMAY-G", "PMAY"),
)


def _aliases_for(entity: str) -> Tuple[str, ...]:
    e = (entity or "").strip()
    for group in _ENTITY_ALIAS_GROUPS:
        compact_group = {re.sub(r"[\s\-]", "", g).lower() for g in group}
        if e in group or re.sub(r"[\s\-]", "", e).lower() in compact_group:
            return group
    return (e,)


def _text_has_entity(text: str, entity: str) -> bool:
    """True if text contains the entity or an accepted alias form."""
    t = text or ""
    for form in _aliases_for(entity):
        if form and form in t:
            return True
        if form and re.search(re.escape(form), t, flags=re.I):
            return True
        compact = re.sub(r"[\s\-]", "", form)
        if compact and re.search(
            re.escape(compact), re.sub(r"[\s\-]", "", t), flags=re.I
        ):
            return True
    return False


def check_entity_preservation(
    source: str,
    answer: str,
    *,
    strict_entities: bool = False,
    query: Optional[str] = None,
) -> Tuple[bool, List[str], Dict[str, float]]:
    fails: List[str] = []
    seen_groups: Set[str] = set()
    src_l = source or ""
    ans_l = answer or ""
    q_l = query or ""
    entities = PRESERVE_ENTITIES if strict_entities else _CORE_SCHEME_ENTITIES
    for ent in entities:
        if not _text_has_entity(src_l, ent):
            continue
        # Generation: only require entities the citizen actually asked about.
        if not strict_entities:
            if not _text_has_entity(q_l, ent):
                continue
        group_key = "|".join(_aliases_for(ent)[:3])
        if group_key in seen_groups:
            continue
        if _text_has_entity(ans_l, ent):
            seen_groups.add(group_key)
            continue
        seen_groups.add(group_key)
        fails.append(f"missing_entity:{ent}")
    for m in re.finditer(r"\b(PM[A-Z]{2,}|MGNREG[AS]?|PMAY(?:-G)?)\b", ans_l):
        tok = m.group(1)
        if not _text_has_entity(src_l, tok):
            fails.append(f"invented_entity:{tok}")
    score = 100.0 if not fails else 0.0
    return (
        len(fails) == 0,
        fails,
        {"entity_score": score, "terminology_score": 100.0 if not fails else 40.0},
    )


_NEGATION_PATTERNS = (
    (r"\bnot eligible\b", r"\beligible\b", r"\bnot\b|\bunable\b|\bcannot\b|\baren't\b|\bare not\b"),
    (r"\bcannot apply\b", r"\bcan apply\b|\bapply\b", r"\bcannot\b|\bcan not\b|\bunable\b"),
    (r"\bnot applicable\b", r"\bapplicable\b", r"\bnot\b"),
    (r"tenant farmers are not eligible", r"tenant farmers are eligible", r"not"),
)

_KN_NEGATION = ("\u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cb2\u0ccd\u0cb2", "\u0c87\u0cb2\u0ccd\u0cb2", "\u0cac\u0cc7\u0ca1")


def check_negation_preservation(source: str, answer: str) -> Tuple[bool, List[str], Dict[str, float]]:
    """High-risk: evidence negation must not become affirmation."""
    src = (source or "").lower()
    ans = (answer or "").lower()
    fails: List[str] = []
    if "not eligible" in src or "are not eligible" in src:
        # English affirmative without negation nearby
        if re.search(r"\bare eligible\b|\bis eligible\b", ans) and not re.search(
            r"\bnot eligible\b|\bare not\b|\bis not\b", ans
        ):
            # Kannada negation markers may carry the meaning
            if not any(m in (answer or "") for m in _KN_NEGATION):
                fails.append("negation_lost:not_eligible")
    if "cannot apply" in src or "can not apply" in src:
        if re.search(r"\bcan apply\b|\bmay apply\b", ans) and "cannot" not in ans and "can not" not in ans:
            if not any(m in (answer or "") for m in _KN_NEGATION):
                fails.append("negation_lost:cannot_apply")
    score = 100.0 if not fails else 0.0
    return (len(fails) == 0), fails, {"negation_score": score}


def check_condition_connectors(source: str, answer: str) -> Tuple[bool, List[str], Dict[str, float]]:
    """AND/OR must not silently flip when both appear as exclusive patterns."""
    src = (source or "").lower()
    ans = (answer or "").lower()
    fails: List[str] = []
    # If source has "X and Y" eligibility pattern and answer has "X or Y" for same pair — soft/hard
    m = re.search(r"eligible if they satisfy ([a-z0-9 \-]+) and ([a-z0-9 \-]+)", src)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if re.search(re.escape(a) + r"\s+or\s+" + re.escape(b), ans):
            fails.append("condition_and_or_flipped")
    score = 100.0 if not fails else 0.0
    return (len(fails) == 0), fails, {"completeness_score": score}


def validate_answer_quality(
    answer: str,
    *,
    response_language: str,
    evidence: Optional[Sequence[Dict[str, Any]]] = None,
    source_text: Optional[str] = None,
    strict_language_mode: bool = False,
    mode: str = "generation",  # generation | translation
    query: Optional[str] = None,
) -> QualityResult:
    """
    Hard gates: language, amounts, dates, URLs, entities, negation, conditions.
    Soft: naturalness proxies (length).
    """
    answer_n = normalize_unicode_display(answer)
    source = source_text if source_text is not None else evidence_text(evidence or [])
    source_n = normalize_unicode_display(source)

    failures: List[str] = []
    soft: List[str] = []
    scores: Dict[str, float] = {}

    ok_lang, f_lang, s_lang = check_language(
        answer_n, response_language=response_language, strict=strict_language_mode
    )
    scores.update(s_lang)
    failures.extend(f_lang)

    ok_num, f_num, s_num = check_numeric_preservation(
        source_n,
        answer_n,
        require_all_source_amounts=(mode == "translation"),
    )
    scores.update(s_num)
    failures.extend(f_num)

    ok_date, f_date, s_date = check_date_preservation(source_n, answer_n)
    scores.update(s_date)
    failures.extend(f_date)

    ok_url, f_url, s_url = check_url_preservation(
        source_n,
        answer_n,
        require_source_urls=(mode == "translation" and bool(extract_urls(source_n))),
    )
    scores.update(s_url)
    failures.extend(f_url)

    ok_ent, f_ent, s_ent = check_entity_preservation(
        source_n,
        answer_n,
        strict_entities=(mode == "translation"),
        query=query,
    )
    scores.update(s_ent)
    failures.extend(f_ent)

    ok_neg, f_neg, s_neg = check_negation_preservation(source_n, answer_n)
    scores.update(s_neg)
    failures.extend(f_neg)

    ok_cond, f_cond, s_cond = check_condition_connectors(source_n, answer_n)
    scores.update(s_cond)
    failures.extend(f_cond)

    # Soft: very short truncated answers
    if len(answer_n.strip()) < 12:
        soft.append("answer_too_short")
        scores["naturalness_score"] = 40.0
    else:
        scores["naturalness_score"] = 80.0

    # grounding_score collapses critical gates
    critical_ok = not failures
    scores["grounding_score"] = 100.0 if critical_ok else 0.0

    # Soft failures alone do not fail unless language/fact hard fail
    passed = critical_ok
    if soft and mode == "translation" and scores.get("naturalness_score", 100) < 50:
        passed = False
        failures.extend(soft)

    result = QualityResult(
        passed=passed,
        failures=failures,
        soft_failures=soft,
        scores=scores,
        details={"mode": mode, "strict": strict_language_mode},
    )
    logger.info(
        "language_quality passed=%s failures=%s response_language=%s mode=%s",
        result.passed,
        result.failures,
        response_language,
        mode,
    )
    return result


def build_regen_instruction(quality: QualityResult, *, response_language: str) -> str:
    name = {"KN": "Kannada", "HI": "Hindi", "EN": "English"}.get(
        (normalize_language_code(response_language) or "EN"), "English"
    )
    cats = []
    joined = " ".join(quality.failures)
    if "wrong_language" in joined or "english_contamination" in joined:
        cats.append(f"The previous response was not sufficiently in {name}.")
    if "amount" in joined or "percent" in joined or "numeric" in joined:
        cats.append("The previous response changed or omitted a numeric value.")
    if "year" in joined or "date" in joined:
        cats.append("The previous response changed or omitted a date/year.")
    if "url" in joined:
        cats.append("The previous response altered or invented a URL.")
    if "entity" in joined:
        missing = [f.split(":", 1)[-1] for f in quality.failures if f.startswith("missing_entity:")]
        if missing:
            cats.append(
                "Keep these official scheme names in Latin script exactly as written: "
                + ", ".join(dict.fromkeys(missing))
                + ". Do not drop PM-KISAN / scheme identifiers."
            )
        else:
            cats.append("The previous response altered an official scheme or department name.")
    if "negation" in joined:
        cats.append("The previous response lost a negation (e.g. not eligible).")
    if "condition" in joined:
        cats.append("The previous response changed AND/OR eligibility conditions.")
    if not cats:
        cats.append("The previous response failed factual or language quality checks.")
    return (
        "REGENERATION REQUIRED:\n"
        + "\n".join(f"- {c}" for c in cats)
        + f"\nRewrite entirely in {name}. Preserve every amount, date, condition, "
        "scheme name, and URL exactly. Do not add facts."
    )


def translation_cache_key(source_answer: str, target_language: str) -> str:
    raw = f"{normalize_unicode_display(source_answer)}|{normalize_language_code(target_language) or 'EN'}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# Process-local translation cache (no conversation_id; no cross-citizen keying)
_TRANSLATION_CACHE: Dict[str, str] = {}
_TRANSLATION_CACHE_MAX = 128


def cache_get_translation(source_answer: str, target_language: str) -> Optional[str]:
    return _TRANSLATION_CACHE.get(translation_cache_key(source_answer, target_language))


def cache_put_translation(source_answer: str, target_language: str, translated: str) -> None:
    key = translation_cache_key(source_answer, target_language)
    if len(_TRANSLATION_CACHE) >= _TRANSLATION_CACHE_MAX:
        # drop an arbitrary old key
        try:
            _TRANSLATION_CACHE.pop(next(iter(_TRANSLATION_CACHE)))
        except StopIteration:
            pass
    _TRANSLATION_CACHE[key] = translated
