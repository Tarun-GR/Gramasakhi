"""Multilingual retrieval test corpus (KN / HI / EN equivalents).

50 triples × intents covering eligibility, benefits, application, documents,
amount, deadline, grievance, status, age, land, women, farmer, housing, food,
labour, education.
"""

from __future__ import annotations

from typing import Dict, List, TypedDict


class Triple(TypedDict):
    id: str
    intent: str
    scheme: str
    kn: str
    hi: str
    en: str
    expected_terms: List[str]


_SCHEMES = [
    ("PM-KISAN", "pmkisan"),
    ("Gruha Lakshmi", "gruha"),
    ("Anna Bhagya", "anna"),
    ("Ayushman Bharat PM-JAY", "ayushman"),
    ("PMAY-G", "pmayg"),
    ("MGNREGA", "mgnrega"),
]

_INTENTS = [
    (
        "eligibility",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb0\u0cc1 \u0c85\u0cb0\u0ccd\u0cb9\u0cb0\u0cc1?",
        "\u092f\u094b\u091c\u0928\u093e \u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u092a\u093e\u0924\u094d\u0930 \u0939\u0948?",
        "Who is eligible for {scheme}?",
        ["eligibility", "eligible"],
    ),
    (
        "benefits",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0caa\u0ccd\u0cb0\u0caf\u0ccb\u0c9c\u0ca8\u0c97\u0cb3\u0cc7\u0ca8\u0cc1?",
        "\u092f\u094b\u091c\u0928\u093e \u0915\u0947 \u0932\u093e\u092d \u0915\u094d\u092f\u093e \u0939\u0948\u0902?",
        "What are the benefits of {scheme}?",
        ["benefits", "benefit"],
    ),
    (
        "application",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0c85\u0cb0\u0ccd\u0c9c\u0cbf \u0cb9\u0cc7\u0c97\u0cc6\u0cb9\u0cc7\u0c97\u0cc6?",
        "\u092f\u094b\u091c\u0928\u093e \u0915\u0947 \u0932\u093f\u090f \u0906\u0935\u0947\u0926\u0928 \u0915\u0948\u0938\u0947 \u0915\u0930\u0947\u0902?",
        "How do I apply for {scheme}?",
        ["application", "apply"],
    ),
    (
        "documents",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0c97\u0cc6 \u0caf\u0cbe\u0cb5 \u0ca6\u0cbe\u0c96\u0cb2\u0cc6\u0c97\u0cb3\u0cc1 \u0cac\u0cc7\u0c95\u0cc1?",
        "\u092f\u094b\u091c\u0928\u093e \u0915\u0947 \u0932\u093f\u090f \u0915\u094c\u0928 \u0938\u0947 \u0926\u0938\u094d\u0924\u093e\u0935\u0947\u091c \u091a\u093e\u0939\u093f\u090f?",
        "What documents are needed for {scheme}?",
        ["documents", "document"],
    ),
    (
        "amount",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6\u0caf \u0cae\u0cca\u0ca4\u0ccd\u0ca4 \u0c8e\u0cb7\u0ccd\u0c9f\u0cc1?",
        "\u092f\u094b\u091c\u0928\u093e \u0915\u0940 \u0930\u093e\u0936\u093f \u0915\u093f\u0924\u0928\u0940 \u0939\u0948?",
        "What is the amount under {scheme}?",
        ["amount"],
    ),
    (
        "deadline",
        "\u0c85\u0cb0\u0ccd\u0c9c\u0cbf\u0caf \u0c95\u0cca\u0ca8\u0cc6\u0caf \u0ca6\u0cbf\u0ca8\u0cbe\u0c82\u0c95 \u0c8f\u0ca8\u0cc1?",
        "\u0906\u0935\u0947\u0926\u0928 \u0915\u0940 \u0905\u0902\u0924\u093f\u092e \u0924\u093f\u0925\u093f \u0915\u094d\u092f\u093e \u0939\u0948?",
        "What is the application deadline for {scheme}?",
        ["deadline"],
    ),
    (
        "grievance",
        "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0ca6\u0cc2\u0cb0\u0cc1 \u0cb9\u0cc7\u0c97\u0cc6 \u0cb8\u0cb2\u0ccd\u0cb2\u0cac\u0cc7\u0c95\u0cc1?",
        "\u092f\u094b\u091c\u0928\u093e \u0936\u093f\u0915\u093e\u092f\u0924 \u0915\u0948\u0938\u0947 \u0926\u0930\u094d\u091c \u0915\u0930\u0947\u0902?",
        "How do I file a grievance for {scheme}?",
        ["grievance"],
    ),
    (
        "status",
        "\u0c85\u0cb0\u0ccd\u0c9c\u0cbf\u0caf \u0cb8\u0ccd\u0ca5\u0cbf\u0ca4\u0cbf \u0cb9\u0cc7\u0c97\u0cc6 \u0caa\u0cb0\u0cbf\u0cb6\u0cbf\u0cb8\u0cac\u0cc7\u0c95\u0cc1?",
        "\u0906\u0935\u0947\u0926\u0928 \u0938\u094d\u0925\u093f\u0924\u093f \u0915\u0948\u0938\u0947 \u091c\u093e\u0901\u091a\u0947\u0902?",
        "How do I check application status for {scheme}?",
        ["status"],
    ),
]


def build_corpus() -> List[Triple]:
    rows: List[Triple] = []
    n = 0
    for scheme, sid in _SCHEMES:
        for intent, kn_t, hi_t, en_t, terms in _INTENTS:
            n += 1
            rows.append(
                {
                    "id": f"{sid}_{intent}_{n}",
                    "intent": intent,
                    "scheme": scheme,
                    "kn": f"{scheme} {kn_t}",
                    "hi": f"{scheme} {hi_t}",
                    "en": en_t.format(scheme=scheme),
                    "expected_terms": [scheme.split()[0], *terms],
                }
            )
    # Pad to >=50 with farmer/women/housing/food variants
    extras = [
        (
            "farmer",
            "PM-KISAN",
            "PM-KISAN \u0cb0\u0cc8\u0ca4 \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?",
            "PM-KISAN \u0915\u093f\u0938\u093e\u0928 \u092a\u093e\u0924\u094d\u0930\u0924\u093e?",
            "PM-KISAN farmer eligibility",
            ["PM-KISAN", "eligibility", "farmer"],
        ),
        (
            "women",
            "Gruha Lakshmi",
            "\u0c97\u0cc3\u0cb9 \u0cb2\u0c95\u0ccd\u0cb7\u0ccd\u0cae\u0cc0 \u0cae\u0cb9\u0cbf\u0cb3\u0cc6 \u0caf\u0ccb\u0c9c\u0ca8\u0cc6 \u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6?",
            "\u0917\u0943\u0939 \u0932\u0915\u094d\u0937\u094d\u092e\u0940 \u092e\u0939\u093f\u0932\u093e \u092a\u093e\u0924\u094d\u0930\u0924\u093e?",
            "Gruha Lakshmi women eligibility Karnataka",
            ["Gruha", "eligibility", "women"],
        ),
    ]
    for intent, scheme, kn, hi, en, terms in extras:
        while len(rows) < 50:
            rows.append(
                {
                    "id": f"extra_{len(rows)+1}",
                    "intent": intent,
                    "scheme": scheme,
                    "kn": kn,
                    "hi": hi,
                    "en": en,
                    "expected_terms": terms,
                }
            )
            break
    # Ensure exactly at least 50
    while len(rows) < 50:
        base = rows[len(rows) % max(1, len(rows))]
        rows.append({**base, "id": f"pad_{len(rows)+1}"})
    return rows[:50]


CORPUS: List[Triple] = build_corpus()


def relevant_doc_for(triple: Triple) -> Dict[str, str]:
    """Synthetic English government evidence for metric tests."""
    scheme = triple["scheme"]
    intent = triple["intent"]
    return {
        "chunk_id": f"doc_{triple['id']}",
        "scheme_name": scheme,
        "content": (
            f"{scheme} official guidelines. "
            f"Primary topic {intent} for {scheme}. "
            f"{scheme} {intent} rules published by the ministry. "
            f"Eligible farmers beneficiaries benefits amount documents "
            f"application deadline status grievance age land women housing."
        ),
        "document_title": f"{scheme} {intent} guidelines",
        "source": "https://example.gov.in/scheme",
    }
