"""Cloud runtime profile and embedding provider tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from app.core.config import settings
from app.services.runtime_profile import cloud_config_errors, is_cloud_runtime


class TestCloudRuntime(unittest.TestCase):
    def test_cloud_requires_gemini_llm_and_embeddings(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "LLM_PROVIDER", "ollama"):
                with patch.object(settings, "EMBEDDING_PROVIDER", "ollama"):
                    with patch.object(settings, "GEMINI_API_KEY", ""):
                        with patch.object(settings, "LLM_FALLBACK_TO_OLLAMA", True):
                            errors = cloud_config_errors()
        self.assertTrue(any("LLM_PROVIDER" in e for e in errors))
        self.assertTrue(any("EMBEDDING_PROVIDER" in e for e in errors))
        self.assertTrue(any("GEMINI_API_KEY" in e for e in errors))
        self.assertTrue(any("FALLBACK" in e for e in errors))

    def test_cloud_config_ok_when_aligned(self):
        with patch.object(settings, "RUNTIME_PROFILE", "cloud"):
            with patch.object(settings, "APP_ENV", "production"):
                with patch.object(settings, "LLM_PROVIDER", "gemini"):
                    with patch.object(settings, "EMBEDDING_PROVIDER", "gemini"):
                        with patch.object(settings, "GEMINI_API_KEY", "test-key"):
                            with patch.object(settings, "LLM_FALLBACK_TO_OLLAMA", False):
                                with patch.object(settings, "OTP_DELIVERY_MODE", "sms"):
                                    with patch.object(settings, "OTP_DEV_POPUP_ENABLED", False):
                                        self.assertEqual(cloud_config_errors(), [])

    def test_gemini_embed_routing_mocked(self):
        with patch("app.services.gemini_embedding.embed_text", return_value=[0.1] * 768):
            with patch.object(settings, "EMBEDDING_PROVIDER", "gemini"):
                from app.services.rag import get_embeddings

                vec = get_embeddings("PM-KISAN benefits")
        self.assertEqual(len(vec), 768)


if __name__ == "__main__":
    unittest.main()
