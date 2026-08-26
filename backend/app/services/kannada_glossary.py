"""Controlled GramSakhi government terminology (linguistic consistency only).

Glossary NEVER overrides evidence facts. Official scheme names stay as-is.
"""

from __future__ import annotations

from typing import Dict, List, Tuple

# English concept -> preferred Kannada wording (citizen-friendly)
GLOSSARY_KN: Dict[str, str] = {
    "eligibility": "\u0c85\u0cb0\u0ccd\u0cb9\u0ca4\u0cc6",
    "eligible": "\u0c85\u0cb0\u0ccd\u0cb9",
    "beneficiary": "\u0cab\u0cb2\u0cbe\u0ca8\u0cc1\u0cad\u0cb5\u0cbf",
    "application": "\u0c85\u0cb0\u0ccd\u0c9c\u0cbf",
    "apply": "\u0c85\u0cb0\u0ccd\u0c9c\u0cbf \u0cb8\u0cb2\u0ccd\u0cb2\u0cbf\u0cb8\u0cc1",
    "documents": "\u0ca6\u0cbe\u0c96\u0cb2\u0cc6\u0c97\u0cb3\u0cc1",
    "document": "\u0ca6\u0cbe\u0c96\u0cb2\u0cc6",
    "financial assistance": "\u0c86\u0cb0\u0ccd\u0ca5\u0cbf\u0c95 \u0ca8\u0cc6\u0cb0\u0cb5\u0cc1",
    "subsidy": "\u0cb8\u0cac\u0ccd\u0cb8\u0cbf\u0ca1\u0cbf",
    "deadline": "\u0c95\u0cca\u0ca8\u0cc6\u0caf \u0ca6\u0cbf\u0ca8\u0cbe\u0c82\u0c95",
    "installment": "\u0c95\u0c82\u0ca4\u0cc1",
    "installments": "\u0c95\u0c82\u0ca4\u0cc1\u0c97\u0cb3\u0cc1",
    "agriculture": "\u0c95\u0cc3\u0cb7\u0cbf",
    "farmer": "\u0cb0\u0cc8\u0ca4",
    "farmers": "\u0cb0\u0cc8\u0ca4\u0cb0\u0cc1",
    "ministry": "\u0cb8\u0c9a\u0cbf\u0cb5\u0cbe\u0cb2\u0caf",
    "department": "\u0c87\u0cb2\u0cbe\u0c96\u0cc6",
    "scheme": "\u0caf\u0ccb\u0c9c\u0ca8\u0cc6",
    "portal": "\u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd",
    "registration": "\u0ca8\u0ccb\u0c82\u0ca6\u0ca3\u0cbf",
    "benefit": "\u0caa\u0ccd\u0cb0\u0caf\u0ccb\u0c9c\u0ca8",
    "benefits": "\u0caa\u0ccd\u0cb0\u0caf\u0ccb\u0c9c\u0ca8\u0c97\u0cb3\u0cc1",
    "income support": "\u0c86\u0ca6\u0cbe\u0caf \u0cac\u0cc6\u0c82\u0cac\u0cb2",
    "landholding": "\u0cad\u0cc2\u0cae\u0cbe\u0cb2\u0cc0\u0c95\u0ca4\u0ccd\u0cb5",
    "cultivable land": "\u0c95\u0cc3\u0cb7\u0cbf\u0caf\u0ccb\u0c97\u0ccd\u0caf \u0cad\u0cc2\u0cae\u0cbf",
    "grievance": "\u0ca6\u0cc2\u0cb0\u0cc1",
    "renewal": "\u0ca8\u0cb5\u0cc0\u0c95\u0cb0\u0ca3",
}

PRESERVE_ENTITIES: Tuple[str, ...] = (
    "PM-KISAN",
    "PMKISAN",
    "PMFBY",
    "PMAY",
    "PMAY-G",
    "PMSBY",
    "KCC",
    "MGNREGA",
    "MGNREGS",
    "Aadhaar",
    "AADHAAR",
    "OTP",
    "IFSC",
    "Gruha Lakshmi",
    "Gruhalakshmi",
    "Anna Bhagya",
    "Shakti",
    "Pradhan Mantri Kisan Samman Nidhi",
    "Ministry of Agriculture",
    "Ministry of Rural Development",
    "Department of Agriculture",
    "Government of Karnataka",
    "Government of India",
)

ALLOWED_LATIN_TOKENS = {
    "pm-kisan",
    "pmkisan",
    "pmfby",
    "pmay",
    "pmay-g",
    "pmsby",
    "kcc",
    "mgnrega",
    "mgnregs",
    "aadhaar",
    "aadhar",
    "otp",
    "ifsc",
    "gruha",
    "lakshmi",
    "shakti",
    "pmfby",
    "pdf",
    "api",
    "url",
    "rs",
    "inr",
    "captcha",
    "sms",
    "upi",
    "dbt",
    "csc",
    "bank",
    "account",
    "pan",
    "gst",
}


def glossary_prompt_block(language_code: str = "KN") -> str:
    if (language_code or "").upper() != "KN":
        return ""
    lines = ["TERMINOLOGY (use consistently; do not invent facts):"]
    for en, kn in list(GLOSSARY_KN.items())[:18]:
        lines.append(f"- {en} -> {kn}")
    lines.append(
        "Preserve official scheme names and department names in Latin script when given."
    )
    return "\n".join(lines)


def preferred_kannada_terms() -> List[str]:
    return list(GLOSSARY_KN.values())
