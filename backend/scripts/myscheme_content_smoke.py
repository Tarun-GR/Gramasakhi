"""Optional smoke: package fixture + attempt one live myScheme page (if network)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.live_gov_retrieval_service import verify_source
from app.services.myscheme_service import package_myscheme_evidence


def main() -> int:
    fix = ROOT / "tests" / "fixtures" / "acquisition" / "myscheme_scheme_udyogini.html"
    html = fix.read_text(encoding="utf-8")
    packed = package_myscheme_evidence(
        html=html,
        scheme_name="Udyogini Scheme",
        source_url="https://www.myscheme.gov.in/schemes/us",
        query="Can I get details about Udyogini Scheme?",
    )
    print("FIXTURE_OK", packed.get("ok"), "sections", list((packed.get("sections") or {}).keys()))

    url = "https://www.myscheme.gov.in/schemes/us"
    if not verify_source(url):
        print("LIVE_SKIP untrusted")
        return 0
    try:
        import httpx

        r = httpx.get(url, timeout=20.0, follow_redirects=True)
        live = package_myscheme_evidence(
            html=r.text,
            scheme_name="Udyogini Scheme",
            source_url=url,
            query="Udyogini Scheme details",
        )
        print(
            "LIVE_STATIC",
            "status",
            r.status_code,
            "bytes",
            len(r.content),
            "ok",
            live.get("ok"),
            "reason",
            live.get("reason"),
            "sections",
            list((live.get("sections") or {}).keys()),
        )
    except Exception as e:  # noqa: BLE001
        print("LIVE_STATIC_ERR", type(e).__name__, str(e)[:120])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
