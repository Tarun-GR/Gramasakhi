"""Government information acquisition providers (additive layer)."""

from app.services.providers.base import (
    ChainRunResult,
    ExtractedEvidence,
    GovernmentInformationProvider,
    IdentityCheckResult,
    ProbeResult,
    ProviderContext,
    ProviderPhaseStatus,
    ProviderRunResult,
    SchemeCandidate,
    extracted_evidence_is_usable,
    log_provider_event,
    merge_provider_ingested,
)
from app.services.providers.data_gov_provider import DataGovProvider
from app.services.providers.india_gov_provider import IndiaGovProvider
from app.services.providers.live_integration import (
    build_default_registry,
    search_via_provider_registry,
)
from app.services.providers.myscheme_provider import MySchemeProvider
from app.services.providers.registry import ProviderRegistry, default_provider_registry
from app.services.providers.registry_government_provider import RegistryGovernmentProvider

__all__ = [
    "ChainRunResult",
    "ExtractedEvidence",
    "GovernmentInformationProvider",
    "IdentityCheckResult",
    "DataGovProvider",
    "IndiaGovProvider",
    "MySchemeProvider",
    "ProbeResult",
    "ProviderContext",
    "ProviderPhaseStatus",
    "ProviderRegistry",
    "ProviderRunResult",
    "RegistryGovernmentProvider",
    "SchemeCandidate",
    "build_default_registry",
    "default_provider_registry",
    "extracted_evidence_is_usable",
    "log_provider_event",
    "merge_provider_ingested",
    "search_via_provider_registry",
]
