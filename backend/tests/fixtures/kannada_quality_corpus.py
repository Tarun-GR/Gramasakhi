"""Deterministic Kannada quality / translation corpora for Phase quality hardening."""

from __future__ import annotations

from typing import Dict, List, Tuple

# Unicode helpers (avoid editor corruption)
KN_ELIG = "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6"
KN_YOJANE = "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6"
KN_ENU = "\u0c8f\u0ca8\u0cc1"
KN_BAGGE = "\u0cac\u0c97\u0ccd\u0c97\u0cc6"
KN_HELI = "\u0cb9\u0cc7\u0cb3\u0cbf"
KN_DALLI = "\u0c95\u0ca8\u0ccd\u0ca8\u0ca1\u0ca6\u0cb2\u0ccd\u0cb2\u0cbf"
KN_GRUHA = "\u0c97\u0cc3\u0cb9\u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cbf"
KN_ANNA = "\u0c85\u0ca8\u0ccd\u0ca8 \u0cad\u0cbe\u0c97\u0ccd\u0caf"
KN_DOCS = "\u0ca6\u0cbe\u0c96\u0cb2\u0cc6\u0c97\u0cb3\u0cc1"
KN_AMOUNT = "\u0c8e\u0cb7\u0ccd\u0c9f\u0cc1 \u0cb9\u0ca3 \u0cb8\u0cbf\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6"
KN_WHO = "\u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1"
KN_APPLY = "\u0c85\u0cb0\u0ccd\u0c9c\u0cbf \u0cb9\u0cc7\u0c97\u0cc6"
KN_STATUS = "\u0cb8\u0ccd\u0ca5\u0cbf\u0ca4\u0cbf"
KN_PORTAL = "\u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd"
KN_DEADLINE = "\u0c95\u0cca\u0ca8\u0cc6\u0caf \u0ca6\u0cbf\u0ca8\u0cbe\u0c82\u0c95"
KN_EXCLUDE = "\u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cb2\u0ccd\u0cb2"
KN_RENEW = "\u0ca8\u0cb5\u0cc0\u0c95\u0cb0\u0ca3"
KN_GRIEVANCE = "\u0ca6\u0cc2\u0cb0\u0cc1"
KN_FOLLOW = "\u0c85\u0ca6\u0c95\u0ccd\u0c95\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?"

SCHEMES = [
    "PM-KISAN",
    "PMFBY",
    "Gruha Lakshmi",
    "Anna Bhagya",
    "PMAY",
    "PMSBY",
    "KCC",
    "MGNREGA",
]

QUESTION_TYPES = [
    ("eligibility", KN_ELIG),
    ("benefits", "\u0caa\u0ccd\u0cb0\u0caf\u0ccb\u0c9c\u0ca8\u0c97\u0cb3\u0cc1"),
    ("amount", KN_AMOUNT),
    ("deadline", KN_DEADLINE),
    ("documents", KN_DOCS),
    ("application", KN_APPLY),
    ("exclusions", KN_EXCLUDE),
    ("status", KN_STATUS),
    ("renewal", KN_RENEW),
    ("grievance", KN_GRIEVANCE),
    ("portal", KN_PORTAL),
]


def real_style_kannada_questions(min_count: int = 50) -> List[Dict[str, str]]:
    """At least 50 real-style Kannada questions across schemes/domains."""
    out: List[Dict[str, str]] = []
    domains = [
        "agriculture",
        "welfare",
        "women and child",
        "food",
        "housing",
        "labour",
        "education",
        "health",
        "pension",
        "insurance",
        "employment",
        "rural development",
    ]
    i = 0
    while len(out) < min_count:
        scheme = SCHEMES[i % len(SCHEMES)]
        qtype, kn_word = QUESTION_TYPES[i % len(QUESTION_TYPES)]
        domain = domains[i % len(domains)]
        forms = [
            f"{scheme} {KN_YOJANE} {kn_word} {KN_ENU}?",
            f"{scheme} {KN_BAGGE} {KN_DALLI} {KN_HELI}",
            f"{scheme} {KN_YOJANE}yalli {kn_word} {KN_ENU}?",
            f"{scheme} scheme {KN_BAGGE} {kn_word}",
        ]
        text = forms[i % len(forms)]
        out.append(
            {
                "id": f"knq_{len(out)+1:03d}",
                "scheme": scheme,
                "type": qtype,
                "domain": domain,
                "question": text,
                "expected_language": "KN",
            }
        )
        i += 1
    # Exact screenshot regression case
    out.insert(
        0,
        {
            "id": "screenshot_pmkisan_eligibility",
            "scheme": "PM-KISAN",
            "type": "eligibility",
            "domain": "agriculture",
            "question": f"PM-KISAN {KN_YOJANE}y {KN_ELIG} {KN_ENU}?",
            "expected_language": "KN",
        },
    )
    return out[: max(min_count, 51)]


def translation_pair_templates(min_count: int = 100) -> List[Dict[str, str]]:
    """>=100 deterministic EN->KN translation quality fixtures (source side)."""
    templates: List[Tuple[str, str]] = [
        (
            "PM-KISAN provides financial assistance of Rs 6000 per year in 3 installments.",
            "amount",
        ),
        (
            "Tenant farmers are not eligible for PM-KISAN.",
            "negation",
        ),
        (
            "Farmers are eligible if they satisfy landholding and Aadhaar seeding.",
            "condition_and",
        ),
        (
            "Apply on https://pmkisan.gov.in/ before 31 March 2026.",
            "url_date",
        ),
        (
            "The subsidy is 50% of the premium under PMFBY.",
            "percent",
        ),
        (
            "Required documents: Aadhaar, bank passbook, and land records.",
            "documents",
        ),
        (
            "Gruha Lakshmi provides Rs 2000 per month to eligible women.",
            "karnataka",
        ),
        (
            "Anna Bhagya provides food grains to eligible ration card holders.",
            "food",
        ),
        (
            "PMAY-G support is subject to income limits and rural residence.",
            "housing",
        ),
        (
            "MGNREGA guarantees 100 days of wage employment in a financial year.",
            "employment",
        ),
    ]
    out: List[Dict[str, str]] = []
    n = 0
    while len(out) < min_count:
        src, tag = templates[n % len(templates)]
        # Vary with scheme / installment / year suffixes without changing core facts incorrectly
        variant = src
        if n % 5 == 1:
            variant = src + " Source: official government document. Page: 2."
        elif n % 5 == 2:
            variant = "- " + src + "\n- Keep all conditions unchanged."
        elif n % 5 == 3:
            variant = src + " Contact the Department of Agriculture for grievances."
        elif n % 5 == 4:
            variant = "Eligibility note: " + src
        out.append(
            {
                "id": f"tr_{len(out)+1:03d}",
                "source_en": variant,
                "tag": tag,
                "target_language": "KN",
            }
        )
        n += 1
    return out


GOOD_KN_ANSWER_6000 = (
    "PM-KISAN "
    + KN_YOJANE
    + "yalli \u0c85\u0cb0\u0ccd\u0cb9 \u0cb0\u0cc8\u0ca4\u0cb0\u0cbf\u0c97\u0cc6 "
    "\u0cb5\u0cb0\u0ccd\u0cb7\u0c95\u0ccd\u0c95\u0cc6 Rs 6000 "
    "\u0c86\u0cb0\u0ccd\u0ca5\u0cbf\u0c95 \u0ca8\u0cc6\u0cb0\u0cb5\u0cc1 "
    "3 \u0c95\u0c82\u0ca4\u0cc1\u0c97\u0cb3\u0cb2\u0ccd\u0cb2\u0cbf \u0cb8\u0cbf\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6."
)

BAD_EN_ANSWER = (
    "To be eligible for PM-KISAN, a farmer must have cultivable land in their name."
)

BAD_AMOUNT_KN = (
    "PM-KISAN "
    + KN_YOJANE
    + "yalli Rs 12000 "
    "\u0cb8\u0cbf\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6."
)

EVIDENCE_PMKISAN = [
    {
        "content": (
            "PM-KISAN Samman Nidhi provides financial assistance of Rs 6000 per year "
            "to eligible landholding farmer families in 3 installments of Rs 2000 each. "
            "Tenant farmers are not eligible. Apply at https://pmkisan.gov.in/. "
            "Farmers are eligible if they satisfy landholding and Aadhaar seeding."
        ),
        "scheme_name": "PM-KISAN",
        "source": "official government document",
        "page": 2,
        "url": "https://pmkisan.gov.in/",
    }
]
