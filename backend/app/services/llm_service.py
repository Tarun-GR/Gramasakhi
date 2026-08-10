"""Grounded Ollama LLM generation for GramSakhi (Phase 5).

Call ONLY after Evidence Sufficiency Validator PASS. This module does not
retrieve documents or talk to the database — it receives validated evidence.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.services.prompt_builder import build_prompt, detect_language

logger = logging.getLogger(__name__)

LLM_UNAVAILABLE = "LLM service unavailable"
LLM_TIMEOUT = "LLM service timeout"
LLM_EMPTY = "LLM returned an empty response"


def get_ollama_base_url() -> str:
    """Prefer OLLAMA_BASE_URL; fall back to existing OLLAMA_API_URL."""
    base = (settings.OLLAMA_BASE_URL or settings.OLLAMA_API_URL or "").strip()
    return base.rstrip("/")


def get_llm_model() -> str:
    return (settings.OLLAMA_LLM_MODEL or settings.OLLAMA_MODEL or "llama3.2:3b").strip()


def clean_llm_response(text: str) -> str:
    """Strip obvious protocol artifacts; do not rewrite factual content."""
    if not text:
        return ""
    cleaned = text.strip()
    # Common chat wrappers some models emit
    for marker in ("Assistant:", "GramSakhi:", "Answer:"):
        if cleaned.startswith(marker):
            cleaned = cleaned[len(marker) :].lstrip()
    return cleaned.strip()


def _post_generate(prompt: str) -> Dict[str, Any]:
    """Low-level Ollama /api/generate call. Not for use outside this module."""
    url = f"{get_ollama_base_url()}/api/generate"
    model = get_llm_model()
    options: Dict[str, Any] = {
        "temperature": float(settings.OLLAMA_LLM_TEMPERATURE),
    }
    if settings.OLLAMA_LLM_NUM_PREDICT and int(settings.OLLAMA_LLM_NUM_PREDICT) > 0:
        options["num_predict"] = int(settings.OLLAMA_LLM_NUM_PREDICT)

    payload = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = float(settings.OLLAMA_LLM_TIMEOUT_SECONDS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return json.loads(body) if body else {}


def check_ollama_llm() -> Dict[str, Any]:
    """Health helper: reachable + whether configured generation model is listed."""
    base = get_ollama_base_url()
    model = get_llm_model()
    result = {
        "ollama_available": False,
        "model_available": False,
        "base_url": base,
        "model": model,
        "detail": None,
    }
    if not base:
        result["detail"] = "OLLAMA_BASE_URL / OLLAMA_API_URL not configured"
        return result
    try:
        req = urllib.request.Request(f"{base}/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=5.0) as response:
            data = json.loads(response.read().decode("utf-8"))
        result["ollama_available"] = True
        names = []
        for m in data.get("models") or []:
            name = m.get("name") or m.get("model") or ""
            if name:
                names.append(name)
        # Accept exact match or same model:tag prefix
        result["model_available"] = any(
            name == model or name.startswith(f"{model}") for name in names
        )
        if not result["model_available"]:
            result["detail"] = f"Model '{model}' not found in ollama list"
        else:
            result["detail"] = "ok"
    except Exception as e:  # noqa: BLE001
        result["detail"] = f"{type(e).__name__}: {e}"
    return result


def generate_answer(
    query: str,
    evidence: List[Dict[str, Any]],
    language: Optional[str] = None,
    conversation_context: Any = None,
) -> Dict[str, Any]:
    """
    Generate a grounded GramSakhi answer via Ollama.

    Returns:
        {"success": True, "answer": "...", "model": "...", "latency_ms": N, "language": "..."}
        or
        {"success": False, "error": "...", "model": "...", "latency_ms": N}
    """
    model = get_llm_model()
    lang = detect_language(query, language)
    started = time.perf_counter()

    if not (query or "").strip():
        return {
            "success": False,
            "error": "Empty query",
            "model": model,
            "language": lang,
            "latency_ms": 0,
        }
    if not evidence:
        return {
            "success": False,
            "error": "No evidence provided",
            "model": model,
            "language": lang,
            "latency_ms": 0,
        }

    prompt = build_prompt(
        query,
        evidence,
        language=language,
        conversation_context=conversation_context,
    )

    logger.info(
        "LLM request started model=%s evidence_chunks=%s language=%s",
        model,
        len(evidence),
        lang,
    )

    try:
        raw = _post_generate(prompt)
    except TimeoutError:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "LLM generation timeout model=%s latency_ms=%s", model, latency_ms
        )
        return {
            "success": False,
            "error": LLM_TIMEOUT,
            "model": model,
            "language": lang,
            "latency_ms": latency_ms,
        }
    except urllib.error.HTTPError as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "LLM generation HTTP error model=%s status=%s latency_ms=%s",
            model,
            e.code,
            latency_ms,
        )
        return {
            "success": False,
            "error": LLM_UNAVAILABLE,
            "model": model,
            "language": lang,
            "latency_ms": latency_ms,
        }
    except (urllib.error.URLError, ConnectionError, OSError) as e:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "LLM generation connection failure model=%s err=%s latency_ms=%s",
            model,
            type(e).__name__,
            latency_ms,
        )
        return {
            "success": False,
            "error": LLM_UNAVAILABLE,
            "model": model,
            "language": lang,
            "latency_ms": latency_ms,
        }
    except Exception as e:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.warning(
            "LLM generation unexpected error model=%s err=%s latency_ms=%s",
            model,
            type(e).__name__,
            latency_ms,
        )
        return {
            "success": False,
            "error": LLM_UNAVAILABLE,
            "model": model,
            "language": lang,
            "latency_ms": latency_ms,
        }

    latency_ms = int((time.perf_counter() - started) * 1000)
    answer = clean_llm_response(raw.get("response") or "")
    if not answer:
        logger.warning(
            "LLM generation empty response model=%s latency_ms=%s", model, latency_ms
        )
        return {
            "success": False,
            "error": LLM_EMPTY,
            "model": model,
            "language": lang,
            "latency_ms": latency_ms,
        }

    logger.info(
        "LLM generation completed model=%s latency_ms=%s", model, latency_ms
    )
    return {
        "success": True,
        "answer": answer,
        "model": model,
        "language": lang,
        "latency_ms": latency_ms,
    }
