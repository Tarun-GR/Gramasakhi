"""Citizen-facing live retrieval failure explanations + verified official sources.

Does not redesign acquisition/RAG — only maps internal outcomes to safe UX.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from app.services.acquisition.reliability import FailureCode
from app.services.live_gov_retrieval_service import (
    discover_seed_urls,
    expand_search_query,
    verify_source,
)

INFORMATION_NOT_FOUND = "information_not_found"
SOURCE_UNAVAILABLE = "source_unavailable"
TIMEOUT = "timeout"
CAPTCHA_BLOCKED = "captcha_blocked"
LOGIN_REQUIRED = "login_required"
AUTHORIZATION_REQUIRED = "authorization_required"
JAVASCRIPT_UNAVAILABLE = "javascript_unavailable"
DOCUMENT_NOT_FOUND = "document_not_found"
DOCUMENT_UNREADABLE = "document_unreadable"
OCR_FAILED = "ocr_failed"
API_UNAVAILABLE = "api_unavailable"
SOURCE_CONFLICT = "source_conflict"
TRUSTED_SOURCES_EXHAUSTED = "trusted_sources_exhausted"
TEMPORARY_FAILURE = "temporary_failure"
SCHEME_CONTENT_UNAVAILABLE = "scheme_content_unavailable"
SCHEME_NOT_IDENTIFIED = "scheme_not_identified"
SCHEME_QUESTION_INSUFFICIENT = "scheme_question_insufficient"

_STATUS_PRIORITY = {
    CAPTCHA_BLOCKED: 100,
    LOGIN_REQUIRED: 95,
    AUTHORIZATION_REQUIRED: 94,
    TIMEOUT: 80,
    SOURCE_UNAVAILABLE: 75,
    JAVASCRIPT_UNAVAILABLE: 70,
    SCHEME_CONTENT_UNAVAILABLE: 68,
    SCHEME_NOT_IDENTIFIED: 66,
    SCHEME_QUESTION_INSUFFICIENT: 64,
    API_UNAVAILABLE: 65,
    DOCUMENT_UNREADABLE: 60,
    OCR_FAILED: 58,
    DOCUMENT_NOT_FOUND: 50,
    SOURCE_CONFLICT: 45,
    TEMPORARY_FAILURE: 30,
    TRUSTED_SOURCES_EXHAUSTED: 20,
    INFORMATION_NOT_FOUND: 10,
}

_FAILURE_TO_STATUS = {
    FailureCode.CAPTCHA_BLOCKED: CAPTCHA_BLOCKED,
    FailureCode.LOGIN_REQUIRED: LOGIN_REQUIRED,
    FailureCode.UNAUTHORIZED: AUTHORIZATION_REQUIRED,
    FailureCode.TIMEOUT: TIMEOUT,
    FailureCode.DNS_ERROR: SOURCE_UNAVAILABLE,
    FailureCode.TLS_ERROR: SOURCE_UNAVAILABLE,
    FailureCode.NETWORK_ERROR: SOURCE_UNAVAILABLE,
    FailureCode.HTTP_5XX: SOURCE_UNAVAILABLE,
    FailureCode.RATE_LIMITED: TEMPORARY_FAILURE,
    FailureCode.JS_RENDER_FAILED: JAVASCRIPT_UNAVAILABLE,
    FailureCode.BROWSER_UNAVAILABLE: JAVASCRIPT_UNAVAILABLE,
    FailureCode.HTML_SHELL: JAVASCRIPT_UNAVAILABLE,
    FailureCode.PDF_NOT_FOUND: DOCUMENT_NOT_FOUND,
    FailureCode.INVALID_PDF: DOCUMENT_UNREADABLE,
    FailureCode.EMPTY_CONTENT: DOCUMENT_NOT_FOUND,
    FailureCode.OCR_FAILED: OCR_FAILED,
    FailureCode.PARSE_FAILED: DOCUMENT_UNREADABLE,
    FailureCode.API_FAILED: API_UNAVAILABLE,
    FailureCode.IRRELEVANT_DOCUMENT: DOCUMENT_NOT_FOUND,
    FailureCode.SUPABASE_FAILED: TEMPORARY_FAILURE,
    FailureCode.INDEX_FAILED: TEMPORARY_FAILURE,
    FailureCode.VALIDATOR_FAILED: INFORMATION_NOT_FOUND,
    FailureCode.COOLDOWN_ACTIVE: TEMPORARY_FAILURE,
    FailureCode.HTTP_4XX: SOURCE_UNAVAILABLE,
    FailureCode.UNTRUSTED_REDIRECT: TEMPORARY_FAILURE,
    FailureCode.SSRF_BLOCKED: TEMPORARY_FAILURE,
    FailureCode.UNKNOWN: TEMPORARY_FAILURE,
}


def _en() -> Dict[str, Dict[str, str]]:
    return {
        CAPTCHA_BLOCKED: {
            "answer": (
                "I found the official government source for this information, "
                "but it requires human verification (CAPTCHA), so I cannot access "
                "that page automatically.\n\n"
                "You can open the official government source directly below."
            ),
            "reason": "The official portal requires human verification (CAPTCHA).",
        },
        LOGIN_REQUIRED: {
            "answer": (
                "I found a relevant official government portal, but the requested "
                "information requires login. I cannot access or bypass login-protected "
                "information.\n\n"
                "You can access the official portal directly below."
            ),
            "reason": "The official portal requires login.",
        },
        AUTHORIZATION_REQUIRED: {
            "answer": (
                "I found a relevant official government source, but access is "
                "restricted. I cannot bypass authorization controls.\n\n"
                "You can try the official source below if it is publicly available to you."
            ),
            "reason": "The official source requires authorization.",
        },
        TIMEOUT: {
            "answer": (
                "I found a relevant official government source, but it did not "
                "respond in time. I could not verify the information from another "
                "trusted source."
            ),
            "reason": "The official website timed out.",
        },
        SOURCE_UNAVAILABLE: {
            "answer": (
                "I found a relevant official government source, but it is currently "
                "unavailable. I could not verify the information from another "
                "trusted source."
            ),
            "reason": "The official website could not be reached right now.",
        },
        JAVASCRIPT_UNAVAILABLE: {
            "answer": (
                "I found the relevant official government website, but its public "
                "content could not be loaded automatically right now."
            ),
            "reason": "The official website's public content could not be loaded.",
        },
        DOCUMENT_NOT_FOUND: {
            "answer": (
                "I could access the official government source, but I could not "
                "find a public document containing enough verified information "
                "to answer this question."
            ),
            "reason": "No relevant public document was found on the official source.",
        },
        DOCUMENT_UNREADABLE: {
            "answer": (
                "I found a relevant government document, but I could not read its "
                "contents reliably enough to give you a verified answer."
            ),
            "reason": "A government document was found but could not be read reliably.",
        },
        OCR_FAILED: {
            "answer": (
                "I found a relevant government document, but I could not read its "
                "scanned contents reliably enough to give you a verified answer."
            ),
            "reason": "The document appears scanned and could not be read reliably.",
        },
        API_UNAVAILABLE: {
            "answer": (
                "I found an official government data source, but it could not be "
                "used to verify an answer right now."
            ),
            "reason": "The official public API was unavailable.",
        },
        SOURCE_CONFLICT: {
            "answer": (
                "I found different information in official government sources, "
                "but I could not reliably determine which version currently applies. "
                "I don't want to give you an incorrect answer."
            ),
            "reason": "Official sources appear to conflict.",
        },
        TRUSTED_SOURCES_EXHAUSTED: {
            "answer": (
                "I checked the available trusted Karnataka and Central Government "
                "sources but could not find enough verified information to answer "
                "this question."
            ),
            "reason": (
                "Trusted government sources were checked without enough verified evidence."
            ),
        },
        TEMPORARY_FAILURE: {
            "answer": (
                "I could not complete verification from trusted government sources "
                "right now due to a temporary problem. Please try again shortly."
            ),
            "reason": "A temporary problem interrupted government source verification.",
        },
        INFORMATION_NOT_FOUND: {
            "answer": (
                "I checked the available trusted government sources but could not "
                "find verified information about this question."
            ),
            "reason": (
                "No verified information was found in the available government sources."
            ),
        },
        SCHEME_CONTENT_UNAVAILABLE: {
            "answer": (
                "I found the official myScheme page, but I could not retrieve its "
                "detailed content right now.\n\n"
                "You can open the verified official source below."
            ),
            "reason": (
                "The official myScheme scheme page was found, but detailed content "
                "could not be retrieved."
            ),
        },
        SCHEME_NOT_IDENTIFIED: {
            "answer": (
                "I couldn't identify the requested scheme from the trusted sources "
                "available right now."
            ),
            "reason": "The requested scheme could not be identified from trusted sources.",
        },
        SCHEME_QUESTION_INSUFFICIENT: {
            "answer": (
                "I found information about the scheme, but the available verified "
                "sources did not contain enough information to answer that specific "
                "question."
            ),
            "reason": (
                "Scheme information was found, but it was insufficient for the "
                "specific question."
            ),
        },
    }


def _hi() -> Dict[str, Dict[str, str]]:
    return {
        CAPTCHA_BLOCKED: {
            "answer": (
                "मुझे इस जानकारी का आधिकारिक सरकारी स्रोत मिला, लेकिन उस पर "
                "मानव सत्यापन (CAPTCHA) आवश्यक है, इसलिए मैं उस पृष्ठ को "
                "स्वचालित रूप से नहीं खोल सकता/सकती।\n\n"
                "आप नीचे दिए गए आधिकारिक स्रोत को सीधे खोल सकते हैं।"
            ),
            "reason": "आधिकारिक पोर्टल पर CAPTCHA आवश्यक है।",
        },
        LOGIN_REQUIRED: {
            "answer": (
                "मुझे एक संबंधित आधिकारिक सरकारी पोर्टल मिला, लेकिन यह जानकारी "
                "लॉगिन के बाद ही उपलब्ध है। मैं लॉगिन-सुरक्षित जानकारी तक पहुँच "
                "या उसे बायपास नहीं कर सकता/सकती।\n\n"
                "आप नीचे आधिकारिक पोर्टल खोल सकते हैं।"
            ),
            "reason": "आधिकारिक पोर्टल पर लॉगिन आवश्यक है।",
        },
        AUTHORIZATION_REQUIRED: {
            "answer": (
                "मुझे एक आधिकारिक स्रोत मिला, लेकिन पहुँच प्रतिबंधित है। "
                "मैं प्राधिकरण नियंत्रणों को बायपास नहीं कर सकता/सकती।"
            ),
            "reason": "आधिकारिक स्रोत पर प्राधिकरण आवश्यक है।",
        },
        TIMEOUT: {
            "answer": (
                "मुझे संबंधित आधिकारिक सरकारी स्रोत मिला, लेकिन उसने समय पर "
                "जवाब नहीं दिया। किसी अन्य विश्वसनीय स्रोत से भी जानकारी "
                "सत्यापित नहीं हो सकी।"
            ),
            "reason": "आधिकारिक वेबसाइट का समय समाप्त हो गया।",
        },
        SOURCE_UNAVAILABLE: {
            "answer": (
                "मुझे संबंधित आधिकारिक सरकारी स्रोत मिला, लेकिन वह अभी उपलब्ध "
                "नहीं है। किसी अन्य विश्वसनीय स्रोत से जानकारी सत्यापित नहीं हो सकी।"
            ),
            "reason": "आधिकारिक वेबसाइट अभी पहुँच योग्य नहीं है।",
        },
        JAVASCRIPT_UNAVAILABLE: {
            "answer": (
                "मुझे संबंधित आधिकारिक सरकारी वेबसाइट मिली, लेकिन उसकी सार्वजनिक "
                "सामग्री अभी स्वचालित रूप से लोड नहीं हो सकी।"
            ),
            "reason": "आधिकारिक वेबसाइट की सार्वजनिक सामग्री लोड नहीं हो सकी।",
        },
        DOCUMENT_NOT_FOUND: {
            "answer": (
                "मैं आधिकारिक सरकारी स्रोत तक पहुँच सका/सकी, लेकिन इस प्रश्न के "
                "लिए पर्याप्त सत्यापित जानकारी वाला सार्वजनिक दस्तावेज़ नहीं मिला।"
            ),
            "reason": "आधिकारिक स्रोत पर प्रासंगिक सार्वजनिक दस्तावेज़ नहीं मिला।",
        },
        DOCUMENT_UNREADABLE: {
            "answer": (
                "मुझे एक संबंधित सरकारी दस्तावेज़ मिला, लेकिन उसकी सामग्री को "
                "इतनी विश्वसनीयता से नहीं पढ़ सका/सकी कि सत्यापित उत्तर दे सकूँ।"
            ),
            "reason": "दस्तावेज़ मिला लेकिन विश्वसनीय रूप से पढ़ा नहीं जा सका।",
        },
        OCR_FAILED: {
            "answer": (
                "मुझे एक संबंधित सरकारी दस्तावेज़ मिला, लेकिन उसकी स्कैन की गई "
                "सामग्री विश्वसनीय रूप से नहीं पढ़ी जा सकी।"
            ),
            "reason": "स्कैन किए गए दस्तावेज़ को विश्वसनीय रूप से नहीं पढ़ा जा सका।",
        },
        API_UNAVAILABLE: {
            "answer": (
                "मुझे एक आधिकारिक सरकारी डेटा स्रोत मिला, लेकिन अभी उससे "
                "उत्तर सत्यापित नहीं किया जा सका।"
            ),
            "reason": "आधिकारिक सार्वजनिक API उपलब्ध नहीं थी।",
        },
        SOURCE_CONFLICT: {
            "answer": (
                "आधिकारिक सरकारी स्रोतों में अलग-अलग जानकारी मिली, लेकिन यह "
                "विश्वसनीय रूप से तय नहीं हो सका कि वर्तमान में कौन-सा संस्करण लागू है। "
                "मैं गलत उत्तर नहीं देना चाहता/चाहती।"
            ),
            "reason": "आधिकारिक स्रोतों में विरोधाभास प्रतीत होता है।",
        },
        TRUSTED_SOURCES_EXHAUSTED: {
            "answer": (
                "मैंने उपलब्ध विश्वसनीय कर्नाटक और केंद्र सरकार के स्रोतों की "
                "जाँच की, लेकिन इस प्रश्न का उत्तर देने के लिए पर्याप्त सत्यापित "
                "जानकारी नहीं मिली।"
            ),
            "reason": "विश्वसनीय सरकारी स्रोतों में पर्याप्त सत्यापित साक्ष्य नहीं मिला।",
        },
        TEMPORARY_FAILURE: {
            "answer": (
                "अस्थायी समस्या के कारण अभी विश्वसनीय सरकारी स्रोतों से "
                "सत्यापन पूरा नहीं हो सका। कृपया थोड़ी देर बाद फिर प्रयास करें।"
            ),
            "reason": "अस्थायी समस्या से सत्यापन बाधित हुआ।",
        },
        INFORMATION_NOT_FOUND: {
            "answer": (
                "मैंने उपलब्ध विश्वसनीय सरकारी स्रोतों की जाँच की, लेकिन इस "
                "प्रश्न के बारे में सत्यापित जानकारी नहीं मिली।"
            ),
            "reason": "उपलब्ध सरकारी स्रोतों में सत्यापित जानकारी नहीं मिली।",
        },
        SCHEME_CONTENT_UNAVAILABLE: {
            "answer": (
                "मुझे इस योजना का आधिकारिक myScheme पृष्ठ मिला, लेकिन अभी "
                "उसकी विस्तृत जानकारी प्राप्त नहीं कर सका/सकी।\n\n"
                "आप नीचे दिए गए सत्यापित आधिकारिक स्रोत को खोल सकते हैं।"
            ),
            "reason": "आधिकारिक myScheme योजना पृष्ठ मिला, पर विस्तृत सामग्री उपलब्ध नहीं हुई।",
        },
        SCHEME_NOT_IDENTIFIED: {
            "answer": (
                "मैं उपलब्ध विश्वसनीय स्रोतों से अनुरोधित योजना की पहचान नहीं "
                "कर सका/सकी।"
            ),
            "reason": "विश्वसनीय स्रोतों से योजना की पहचान नहीं हो सकी।",
        },
        SCHEME_QUESTION_INSUFFICIENT: {
            "answer": (
                "मुझे योजना की जानकारी मिली, लेकिन उपलब्ध सत्यापित स्रोतों में "
                "उस विशिष्ट प्रश्न का उत्तर देने के लिए पर्याप्त जानकारी नहीं थी।"
            ),
            "reason": "योजना मिली, पर विशिष्ट प्रश्न के लिए पर्याप्त जानकारी नहीं।",
        },
    }


def _kn() -> Dict[str, Dict[str, str]]:
    """Full Kannada citizen failure messages (URLs left to official_sources)."""
    return {
        CAPTCHA_BLOCKED: {
            "answer": (
                "\u0c88 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf\u0c97\u0cc6 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0cae\u0cbe\u0ca8\u0cb5 \u0caa\u0cb0\u0cbf\u0cb6\u0cc0\u0cb2\u0ca8\u0cc6 (CAPTCHA) \u0cac\u0cc7\u0c95\u0cc1. "
                "\u0c86 \u0caa\u0cc1\u0c9f\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 \u0cb8\u0ccd\u0cb5\u0caf\u0c82\u0c9a\u0cbe\u0cb2\u0cbf\u0ca4\u0cb5\u0cbe\u0c97\u0cbf \u0ca4\u0cc6\u0cb0\u0cc6\u0caf\u0cb2\u0cc1 \u0cb8\u0cbe\u0ca7\u0ccd\u0caf\u0cb5\u0cbf\u0cb2\u0ccd\u0cb2.\n\n"
                "\u0c95\u0cc6\u0cb3\u0c97\u0cbf\u0ca8 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cae\u0cc2\u0cb2\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cc0\u0cb5\u0cc1 \u0ca4\u0cc6\u0cb0\u0cc6\u0caf\u0cac\u0cb9\u0cc1\u0ca6\u0cc1."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd\u200c\u0c97\u0cc6 CAPTCHA \u0c85\u0c97\u0ca4\u0ccd\u0caf\u0cb5\u0cbf\u0ca6\u0cc6.",
        },
        LOGIN_REQUIRED: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0cb2\u0cbe\u0c97\u0cbf\u0ca8\u0ccd \u0c85\u0c97\u0ca4\u0ccd\u0caf\u0cb5\u0cbf\u0ca6\u0cc6. "
                "\u0cb2\u0cbe\u0c97\u0cbf\u0ca8\u0ccd-\u0cb0\u0c95\u0ccd\u0cb7\u0cbf\u0ca4 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf\u0caf\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cbe\u0ca8\u0cc1 \u0caa\u0ccd\u0cb0\u0cb5\u0cc7\u0cb6\u0cbf\u0cb8\u0cb2\u0cc1 \u0c85\u0ca5\u0cb5\u0cbe "
                "\u0cac\u0cc8\u0caa\u0cbe\u0cb8\u0ccd \u0cae\u0cbe\u0ca1\u0cb2\u0cc1 \u0cb8\u0cbe\u0ca7\u0ccd\u0caf\u0cb5\u0cbf\u0cb2\u0ccd\u0cb2.\n\n"
                "\u0c95\u0cc6\u0cb3\u0c97\u0cbf\u0ca8 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd \u0c85\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cc0\u0cb5\u0cc1 \u0ca4\u0cc6\u0cb0\u0cc6\u0caf\u0cac\u0cb9\u0cc1\u0ca6\u0cc1."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0caa\u0ccb\u0cb0\u0ccd\u0c9f\u0cb2\u0ccd\u200c\u0c97\u0cc6 \u0cb2\u0cbe\u0c97\u0cbf\u0ca8\u0ccd \u0c85\u0c97\u0ca4\u0ccd\u0caf\u0cb5\u0cbf\u0ca6\u0cc6.",
        },
        AUTHORIZATION_REQUIRED: {
            "answer": (
                "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, \u0c86\u0ca6\u0cb0\u0cc6 \u0caa\u0ccd\u0cb0\u0cb5\u0cc7\u0cb6 \u0ca8\u0cbf\u0cb0\u0ccd\u0cac\u0c82\u0ca7\u0cbf\u0ca4\u0cb5\u0cbe\u0c97\u0cbf\u0ca6\u0cc6. "
                "\u0c85\u0ca7\u0cbf\u0c95\u0cbe\u0cb0 \u0ca8\u0cbf\u0caf\u0c82\u0ca4\u0ccd\u0cb0\u0ca3\u0c97\u0cb3\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cbe\u0ca8\u0cc1 \u0cac\u0cc8\u0caa\u0cbe\u0cb8\u0ccd \u0cae\u0cbe\u0ca1\u0cb2\u0cc1 \u0cb8\u0cbe\u0ca7\u0ccd\u0caf\u0cb5\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cae\u0cc2\u0cb2\u0c95\u0ccd\u0c95\u0cc6 \u0c85\u0ca7\u0cbf\u0c95\u0cbe\u0cb0 \u0c85\u0c97\u0ca4\u0ccd\u0caf\u0cb5\u0cbf\u0ca6\u0cc6.",
        },
        TIMEOUT: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c85\u0ca6\u0cc1 \u0cb8\u0cae\u0caf\u0c95\u0ccd\u0c95\u0cc6 \u0caa\u0ccd\u0cb0\u0ca4\u0cbf\u0c95\u0ccd\u0cb0\u0cbf\u0caf\u0cbf\u0cb8\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2. "
                "\u0cac\u0cc7\u0cb0\u0cc6 \u0cb5\u0cbf\u0cb6\u0ccd\u0cb5\u0cbe\u0cb8\u0cbe\u0cb0\u0ccd\u0cb9 \u0cae\u0cc2\u0cb2\u0ca6\u0cbf\u0c82\u0ca6 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cb0\u0cbf\u0cb8\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb5\u0cc6\u0cac\u0ccd\u200c\u0cb8\u0cc8\u0c9f\u0ccd \u0cb8\u0cae\u0caf \u0cae\u0cc0\u0cb0\u0cbf\u0ca6\u0cc6.",
        },
        SOURCE_UNAVAILABLE: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c85\u0ca6\u0cc1 \u0c88\u0c97 \u0cb2\u0cad\u0ccd\u0caf\u0cb5\u0cbf\u0cb2\u0ccd\u0cb2. "
                "\u0cac\u0cc7\u0cb0\u0cc6 \u0cb5\u0cbf\u0cb6\u0ccd\u0cb5\u0cbe\u0cb8\u0cbe\u0cb0\u0ccd\u0cb9 \u0cae\u0cc2\u0cb2\u0ca6\u0cbf\u0c82\u0ca6 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cb0\u0cbf\u0cb8\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb5\u0cc6\u0cac\u0ccd\u200c\u0cb8\u0cc8\u0c9f\u0ccd \u0c88\u0c97 \u0ca4\u0cb2\u0cc1\u0caa\u0cb2\u0cbe\u0c97\u0cc1\u0ca4\u0ccd\u0ca4\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        JAVASCRIPT_UNAVAILABLE: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb5\u0cc6\u0cac\u0ccd\u200c\u0cb8\u0cc8\u0c9f\u0ccd \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c85\u0ca6\u0cb0 \u0cb8\u0cbe\u0cb0\u0ccd\u0cb5\u0c9c\u0ca8\u0cbf\u0c95 \u0cb5\u0cbf\u0cb7\u0caf\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 \u0c88\u0c97 "
                "\u0cb8\u0ccd\u0cb5\u0caf\u0c82\u0c9a\u0cbe\u0cb2\u0cbf\u0ca4\u0cb5\u0cbe\u0c97\u0cbf \u0cb2\u0ccb\u0ca1\u0ccd \u0cae\u0cbe\u0ca1\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb5\u0cc6\u0cac\u0ccd\u200c\u0cb8\u0cc8\u0c9f\u0ccd \u0cb5\u0cbf\u0cb7\u0caf \u0cb2\u0ccb\u0ca1\u0ccd \u0c86\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        DOCUMENT_NOT_FOUND: {
            "answer": (
                "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2\u0c95\u0ccd\u0c95\u0cc6 \u0caa\u0ccd\u0cb0\u0cb5\u0cc7\u0cb6\u0cbf\u0cb8\u0cb2\u0cbe\u0caf\u0cbf\u0ca4\u0cc1, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c88 \u0caa\u0ccd\u0cb0\u0cb6\u0ccd\u0ca8\u0cc6\u0c97\u0cc6 \u0cb8\u0cbe\u0c95\u0cb7\u0ccd\u0c9f\u0cc1 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cc3\u0ca4 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf "
                "\u0c87\u0cb0\u0cc1\u0cb5 \u0cb8\u0cbe\u0cb0\u0ccd\u0cb5\u0c9c\u0ca8\u0cbf\u0c95 \u0ca6\u0cbe\u0c96\u0cb2\u0cc6 \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cae\u0cc2\u0cb2\u0ca6\u0cb2\u0ccd\u0cb2\u0cbf \u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0ca6\u0cbe\u0c96\u0cb2\u0cc6 \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        DOCUMENT_UNREADABLE: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0ca6\u0cbe\u0c96\u0cb2\u0cc6 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c85\u0ca6\u0cb0 \u0cb5\u0cbf\u0cb7\u0caf\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cbf\u0cb0\u0ccd\u0cad\u0cb0\u0cb5\u0cbe\u0c97\u0cbf "
                "\u0c93\u0ca6\u0cb2\u0cc1 \u0cb8\u0cbe\u0ca7\u0ccd\u0caf\u0cb5\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0ca6\u0cbe\u0c96\u0cb2\u0cc6 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca4\u0cc1 \u0ca8\u0cbf\u0cb0\u0ccd\u0cad\u0cb0\u0cb5\u0cbe\u0c97\u0cbf \u0c93\u0ca6\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        OCR_FAILED: {
            "answer": (
                "\u0cb8\u0c82\u0cac\u0c82\u0ca7\u0cbf\u0ca4 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0ca6\u0cbe\u0c96\u0cb2\u0cc6 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0cb8\u0ccd\u0c95\u0cbe\u0ca8\u0ccd \u0cae\u0cbe\u0ca1\u0cbf\u0ca6 \u0cb5\u0cbf\u0cb7\u0caf\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 "
                "\u0ca8\u0cbf\u0cb0\u0ccd\u0cad\u0cb0\u0cb5\u0cbe\u0c97\u0cbf \u0c93\u0ca6\u0cb2\u0cc1 \u0cb8\u0cbe\u0ca7\u0ccd\u0caf\u0cb5\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0cb8\u0ccd\u0c95\u0cbe\u0ca8\u0ccd \u0ca6\u0cbe\u0c96\u0cb2\u0cc6\u0caf\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca8\u0cbf\u0cb0\u0ccd\u0cad\u0cb0\u0cb5\u0cbe\u0c97\u0cbf \u0c93\u0ca6\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        API_UNAVAILABLE: {
            "answer": (
                "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0ca1\u0cc7\u0c9f\u0cbe \u0cae\u0cc2\u0cb2 \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c88\u0c97 \u0c85\u0ca6\u0cb0\u0cbf\u0c82\u0ca6 \u0c89\u0ca4\u0ccd\u0ca4\u0cb0\u0cb5\u0ca8\u0ccd\u0ca8\u0cc1 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cb0\u0cbf\u0cb8\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cb8\u0cbe\u0cb0\u0ccd\u0cb5\u0c9c\u0ca8\u0cbf\u0c95 API \u0cb2\u0cad\u0ccd\u0caf\u0cb5\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        SOURCE_CONFLICT: {
            "answer": (
                "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0cb2\u0ccd\u0cb2\u0cbf \u0cac\u0cc7\u0cb0\u0cc6 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf \u0cb8\u0cbf\u0c95\u0ccd\u0c95\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c88\u0c97 \u0caf\u0cbe\u0cb5\u0cc1\u0ca6\u0cc1 \u0c85\u0ca8\u0ccd\u0cb5\u0caf\u0cbf\u0cb8\u0cc1\u0ca4\u0ccd\u0ca4\u0ca6\u0cc6 "
                "\u0ca8\u0cbf\u0cb0\u0ccd\u0cad\u0cb0\u0cb5\u0cbe\u0c97\u0cbf \u0ca4\u0cbf\u0cb3\u0cbf\u0caf\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2. "
                "\u0ca4\u0caa\u0ccd\u0caa\u0cc1 \u0c89\u0ca4\u0ccd\u0ca4\u0cb0 \u0c95\u0cca\u0ca1\u0cc1\u0cb5\u0cc1\u0ca6\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0c85\u0ca7\u0cbf\u0c95\u0cc3\u0ca4 \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0cb2\u0ccd\u0cb2\u0cbf \u0cb5\u0cbf\u0cb0\u0ccb\u0ca7 \u0c95\u0cbe\u0ca3\u0cc1\u0ca4\u0ccd\u0ca4\u0cbf\u0ca6\u0cc6.",
        },
        TRUSTED_SOURCES_EXHAUSTED: {
            "answer": (
                "\u0cb2\u0cad\u0ccd\u0caf\u0cb5\u0cbf\u0cb0\u0cc1\u0cb5 \u0c95\u0cb0\u0ccd\u0ca8\u0cbe\u0c9f\u0c95 \u0cae\u0ca4\u0ccd\u0ca4\u0cc1 \u0c95\u0cc7\u0c82\u0ca6\u0ccd\u0cb0 "
                "\u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0ca8\u0ccd\u0ca8\u0cc1 \u0caa\u0cb0\u0cbf\u0cb6\u0cc0\u0cb2\u0cbf\u0cb8\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c88 \u0caa\u0ccd\u0cb0\u0cb6\u0ccd\u0ca8\u0cc6\u0c97\u0cc6 \u0cb8\u0cbe\u0c95\u0cb7\u0ccd\u0c9f\u0cc1 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cc3\u0ca4 "
                "\u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0cb5\u0cbf\u0cb6\u0ccd\u0cb5\u0cbe\u0cb8\u0cbe\u0cb0\u0ccd\u0cb9 \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0cb2\u0ccd\u0cb2\u0cbf \u0cb8\u0cbe\u0c95\u0cb7\u0ccd\u0c9f\u0cc1 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cc3\u0ca4 \u0cb8\u0cbe\u0c95\u0ccd\u0cb7\u0ccd\u0caf \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        TEMPORARY_FAILURE: {
            "answer": (
                "\u0ca4\u0cbe\u0ca4\u0ccd\u0c95\u0cbe\u0cb2\u0cbf\u0c95 \u0cb8\u0cae\u0cb8\u0ccd\u0caf\u0cc6\u0caf\u0cbf\u0c82\u0ca6 \u0c88\u0c97 "
                "\u0cb5\u0cbf\u0cb6\u0ccd\u0cb5\u0cbe\u0cb8\u0cbe\u0cb0\u0ccd\u0cb9 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0cbf\u0c82\u0ca6 "
                "\u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cb0\u0ca3 \u0caa\u0cc2\u0cb0\u0ccd\u0ca3\u0c97\u0cca\u0cb3\u0ccd\u0cb3\u0cbf\u0cb8\u0cb2\u0cbe\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2. "
                "\u0ca6\u0caf\u0cb5\u0cbf\u0c9f\u0ccd\u0c9f\u0cc1 \u0cb8\u0ccd\u0cb5\u0cb2\u0ccd\u0caa \u0caa\u0ccd\u0cb0\u0caf\u0ca4\u0ccd\u0ca8\u0cbf\u0cb8\u0cbf."
            ),
            "reason": "\u0ca4\u0cbe\u0ca4\u0ccd\u0c95\u0cbe\u0cb2\u0cbf\u0c95 \u0cb8\u0cae\u0cb8\u0ccd\u0caf\u0cc6\u0caf\u0cbf\u0c82\u0ca6 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cb0\u0ca3 \u0ca4\u0ca1\u0cc6\u0caf\u0cbf\u0ca4\u0cc1.",
        },
        INFORMATION_NOT_FOUND: {
            "answer": (
                "\u0cb2\u0cad\u0ccd\u0caf\u0cb5\u0cbf\u0cb0\u0cc1\u0cb5 \u0cb5\u0cbf\u0cb6\u0ccd\u0cb5\u0cbe\u0cb8\u0cbe\u0cb0\u0ccd\u0cb9 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf "
                "\u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0ca8\u0ccd\u0ca8\u0cc1 \u0caa\u0cb0\u0cbf\u0cb6\u0cc0\u0cb2\u0cbf\u0cb8\u0cbf\u0ca6\u0cc6, "
                "\u0c86\u0ca6\u0cb0\u0cc6 \u0c88 \u0caa\u0ccd\u0cb0\u0cb6\u0ccd\u0ca8\u0cc6\u0c97\u0cc6 \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cc3\u0ca4 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf "
                "\u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2."
            ),
            "reason": "\u0cb2\u0cad\u0ccd\u0caf\u0cb5\u0cbf\u0cb0\u0cc1\u0cb5 \u0cb8\u0cb0\u0ccd\u0c95\u0cbe\u0cb0\u0cbf \u0cae\u0cc2\u0cb2\u0c97\u0cb3\u0cb2\u0ccd\u0cb2\u0cbf \u0ca6\u0cc3\u0ca2\u0cc0\u0c95\u0cc3\u0ca4 \u0cae\u0cbe\u0cb9\u0ca4\u0cbf \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
        },
        SCHEME_CONTENT_UNAVAILABLE: {
            "answer": (
                'ಈ ಯೋಜನೆಯ ಅಧಿಕೃತ myScheme ಪುಟ ಸಿಕ್ಕಿದೆ, ಆದರೆ ಈಗ ಅದರ ವಿವರವಾದ ಮಾಹಿತಿಯನ್ನು ಪಡೆಯಲಾಗಲಿಲ್ಲ.\n\nಕೆಳಗಿನ ಪರಿಶೀಲಿತ ಅಧಿಕೃತ ಮೂಲವನ್ನು ನೀವು ತೆರೆಯಬಹುದು.'
            ),
            "reason": 'ಅಧಿಕೃತ myScheme ಯೋಜನೆ ಪುಟ ಸಿಕ್ಕಿದೆ, ವಿವರ ವಿಷಯ ಲಭ್ಯವಾಗಲಿಲ್ಲ.',
        },
        SCHEME_NOT_IDENTIFIED: {
            "answer": (
                'ಲಭ್ಯವಿರುವ ವಿಶ್ವಾಸಾರ್ಹ ಮೂಲಗಳಿಂದ ಕೋರಿದ ಯೋಜನೆಯನ್ನು ಗುರುತಿಸಲಾಗಲಿಲ್ಲ.'
            ),
            "reason": 'ವಿಶ್ವಾಸಾರ್ಹ ಮೂಲಗಳಿಂದ ಯೋಜನೆ ಗುರುತಿಸಲಾಗಲಿಲ್ಲ.',
        },
        SCHEME_QUESTION_INSUFFICIENT: {
            "answer": (
                'ಯೋಜನೆಯ ಮಾಹಿತಿ ಸಿಕ್ಕಿದೆ, ಆದರೆ ಲಭ್ಯವಿರುವ ಪರಿಶೀಲಿತ ಮೂಲಗಳಲ್ಲಿ ಆ ನಿರ್ದಿಷ್ಟ ಪ್ರಶ್ನೆಗೆ ಉತ್ತರಿಸಲು ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇರಲಿಲ್ಲ.'
            ),
            "reason": 'ಯೋಜನೆ ಸಿಕ್ಕಿದೆ, ನಿರ್ದಿಷ್ಟ ಪ್ರಶ್ನೆಗೆ ಸಾಕಷ್ಟು ಮಾಹಿತಿ ಇಲ್ಲ.',
        },

    }


_MESSAGES = {
    "en": _en(),
    "hi": _hi(),
    "kn": _kn(),
}


def normalize_language(language: Optional[str]) -> str:
    lang = (language or "en").strip().lower()
    if lang.startswith("hi") or lang in ("hindi", "hin"):
        return "hi"
    if lang.startswith("kn") or lang in ("kannada", "kan"):
        return "kn"
    return "en"


def map_failure_code(code: Any) -> str:
    if code is None:
        return INFORMATION_NOT_FOUND
    if isinstance(code, FailureCode):
        return _FAILURE_TO_STATUS.get(code, TEMPORARY_FAILURE)
    raw = str(code).strip()
    if raw in _STATUS_PRIORITY:
        return raw
    upper = raw.upper()
    try:
        fc = FailureCode(upper)
        return _FAILURE_TO_STATUS.get(fc, TEMPORARY_FAILURE)
    except Exception:
        pass
    lower = raw.lower()
    aliases = {
        "captcha_blocked": CAPTCHA_BLOCKED,
        "login_required": LOGIN_REQUIRED,
        "temporarily_unavailable": SOURCE_UNAVAILABLE,
        "js_required": JAVASCRIPT_UNAVAILABLE,
        "js_render_failed": JAVASCRIPT_UNAVAILABLE,
        "timeout": TIMEOUT,
        "html_shell": JAVASCRIPT_UNAVAILABLE,
        "live_fallback_error": TEMPORARY_FAILURE,
        "live_evidence_insufficient": INFORMATION_NOT_FOUND,
        "no_trusted_information_found": TRUSTED_SOURCES_EXHAUSTED,
        "no_trusted_information": TRUSTED_SOURCES_EXHAUSTED,
        "scheme_content_unavailable": SCHEME_CONTENT_UNAVAILABLE,
        "static_shell": SCHEME_CONTENT_UNAVAILABLE,
        "network_error": SCHEME_CONTENT_UNAVAILABLE,
        "content_empty": SCHEME_CONTENT_UNAVAILABLE,
        "scheme_not_resolved": SCHEME_NOT_IDENTIFIED,
        "scheme_not_identified": SCHEME_NOT_IDENTIFIED,
        "scheme_question_insufficient": SCHEME_QUESTION_INSUFFICIENT,
        "live_evidence_insufficient_scheme": SCHEME_QUESTION_INSUFFICIENT,
    }
    return aliases.get(lower, INFORMATION_NOT_FOUND)


def choose_citizen_status(
    failure_codes: Optional[Sequence[Any]] = None,
    *,
    candidates_tried: int = 0,
    ingested_count: int = 0,
    evidence_ready: bool = False,
    fallback: str = INFORMATION_NOT_FOUND,
) -> str:
    if evidence_ready:
        return INFORMATION_NOT_FOUND
    codes = [map_failure_code(c) for c in (failure_codes or []) if c]
    if not codes:
        if candidates_tried > 0 and ingested_count == 0:
            return DOCUMENT_NOT_FOUND
        if candidates_tried > 0:
            return TRUSTED_SOURCES_EXHAUSTED
        return fallback
    return max(codes, key=lambda s: _STATUS_PRIORITY.get(s, 0))


def citizen_messages(status: str, language: Optional[str] = None) -> Dict[str, str]:
    lang = normalize_language(language)
    pack = _MESSAGES.get(lang) or _MESSAGES["en"]
    msg = pack.get(status) or _MESSAGES["en"].get(status) or _MESSAGES["en"][INFORMATION_NOT_FOUND]
    return {"answer": msg["answer"], "live_reason": msg["reason"]}


def _source_reason(language: Optional[str], scheme_name: str) -> str:
    lang = normalize_language(language)
    name = scheme_name or "this scheme"
    if lang == "hi":
        return f"{name} से संबंधित जानकारी के लिए आधिकारिक सरकारी स्रोत।"
    if lang == "kn":
        return f"{name} ಗೆ ಸಂಬಂಧಿಸಿದ ಮಾಹಿತಿಗೆ ಅಧಿಕೃತ ಸರ್ಕಾರಿ ಮೂಲ."
    return f"Official source for information related to {name}."


def _query_overlap_score(query: str, *parts: str) -> int:
    q_tokens = {
        t
        for t in re.findall(r"[a-zA-Z0-9\-]{3,}", (query or "").lower())
        if t
        not in {
            "the",
            "and",
            "for",
            "about",
            "details",
            "scheme",
            "yojana",
            "what",
            "who",
            "how",
        }
    }
    if not q_tokens:
        return 0
    blob = " ".join((p or "").lower() for p in parts)
    return sum(1 for t in q_tokens if t in blob)


def build_official_sources(
    query: str,
    *,
    language: Optional[str] = None,
    limit: int = 3,
    extra_urls: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, str]]:
    """Return at most `limit` verified trusted official source links. Never invent URLs.

    Prefer scheme-specific catalog / candidate URLs over generic portal homepages.
    """
    out: List[Dict[str, str]] = []
    seen = set()
    generic_hosts = {
        "www.myscheme.gov.in",
        "myscheme.gov.in",
        "sevasindhu.karnataka.gov.in",
        "www.karnataka.gov.in",
        "karnataka.gov.in",
        "www.india.gov.in",
        "india.gov.in",
    }

    def _add(url: str, name: str, reason: str, *, score: int = 0, stage: str = "") -> bool:
        if len(out) >= max(0, limit):
            return False
        url = (url or "").strip()
        if not url or url in seen:
            return False
        if not url.lower().startswith("https://"):
            return False
        if not verify_source(url):
            return False
        host = (urlparse(url).hostname or "").lower()
        if host in ("localhost", "127.0.0.1") or host.startswith(("192.168.", "10.", "169.254.")):
            return False
        # Skip bare portal homepages when we already have a better specific link
        path = (urlparse(url).path or "/").rstrip("/") or "/"
        is_generic_home = host in generic_hosts and path in ("", "/")
        if is_generic_home and out and score < 2 and stage in ("", "portal_expand"):
            return False
        seen.add(url)
        out.append(
            {
                "name": (name or host or "Official government source")[:120],
                "url": url,
                "type": "official_government",
                "reason": reason[:200],
            }
        )
        return True

    ranked: List[Tuple[int, Dict[str, Any]]] = []
    for item in extra_urls or []:
        score = 40 + _query_overlap_score(
            query,
            item.get("url") or "",
            item.get("name") or "",
            item.get("scheme_name") or "",
            item.get("link_text") or "",
        )
        ranked.append((score, {**item, "_stage": item.get("stage") or "candidate"}))

    try:
        seeds = discover_seed_urls(expand_search_query(query))
    except Exception:  # noqa: BLE001
        seeds = []
    for seed in seeds:
        stage = (seed.get("stage") or "").lower()
        base = 30 if stage == "catalog" else 18 if stage == "registry_department" else 5
        score = base + _query_overlap_score(
            query,
            seed.get("url") or "",
            seed.get("scheme_name") or "",
            seed.get("link_text") or "",
        )
        ranked.append((score, {**seed, "_stage": stage}))

    ranked.sort(key=lambda x: -x[0])
    specific_added = 0
    for score, item in ranked:
        stage = item.get("_stage") or item.get("stage") or ""
        added = _add(
            item.get("url") or "",
            item.get("name") or item.get("scheme_name") or item.get("link_text") or "",
            item.get("reason")
            or _source_reason(language, item.get("scheme_name") or item.get("name") or ""),
            score=score,
            stage=stage,
        )
        if added and stage in ("catalog", "candidate", "registry_department"):
            specific_added += 1
        if len(out) >= limit:
            break

    # Only pad with generic portals when nothing scheme-specific was found
    if not out:
        for score, item in ranked:
            _add(
                item.get("url") or "",
                item.get("name") or item.get("scheme_name") or "",
                _source_reason(language, item.get("scheme_name") or ""),
                score=score,
                stage="portal_expand",
            )
            if len(out) >= limit:
                break
    _ = specific_added
    return out[:limit]


def build_citizen_live_failure(
    query: str,
    *,
    language: Optional[str] = None,
    failure_codes: Optional[Sequence[Any]] = None,
    candidates_tried: int = 0,
    ingested_count: int = 0,
    evidence_ready: bool = False,
    preferred_status: Optional[str] = None,
    guidance_urls: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    status = preferred_status or choose_citizen_status(
        failure_codes,
        candidates_tried=candidates_tried,
        ingested_count=ingested_count,
        evidence_ready=evidence_ready,
    )
    status = map_failure_code(status)
    msgs = citizen_messages(status, language)
    sources = build_official_sources(
        query, language=language, limit=3, extra_urls=guidance_urls
    )
    return {
        "answer": msgs["answer"],
        "live_status": status,
        "live_reason": msgs["live_reason"],
        "official_sources": sources,
        "knowledge_source": "none",
        "validated": False,
        "llm_invoked": False,
        "confidence": "low",
    }
