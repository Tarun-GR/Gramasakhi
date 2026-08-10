"""
Optional periodic government web ingestion (safe threshold).

Disabled by default. Enable with WEB_INGEST_SCHEDULER_ENABLED=true.
Does not modify retrieval — only calls WebIngestionService → existing ingest.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("gramsakhi.web_ingest_scheduler")

_stop = threading.Event()
_thread: Optional[threading.Thread] = None

STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "web_ingest_last_run.json"


def _load_last_run() -> Optional[datetime]:
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        ts = data.get("last_run_at")
        if not ts:
            return None
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def _save_last_run(when: datetime) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps({"last_run_at": when.astimezone(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


def should_run(interval_hours: float) -> bool:
    """Skip if last successful run is still within the threshold window."""
    last = _load_last_run()
    if last is None:
        return True
    now = datetime.now(timezone.utc)
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed_hours = (now - last).total_seconds() / 3600.0
    if elapsed_hours < interval_hours:
        logger.info(
            "Scheduler skip: last_run=%.2fh ago < threshold=%.2fh",
            elapsed_hours,
            interval_hours,
        )
        return False
    return True


def _run_loop(interval_hours: float, source: str, max_docs: int) -> None:
    from app.database.session import SessionLocal
    from app.services.web_ingestion_service import WebIngestionService

    logger.info(
        "Web ingest scheduler started source=%s interval_hours=%s",
        source,
        interval_hours,
    )
    # Initial delay uses same interval; first wake checks threshold
    while not _stop.wait(timeout=max(60.0, min(3600.0, interval_hours * 3600 / 4))):
        if not should_run(interval_hours):
            continue
        db = SessionLocal()
        try:
            service = WebIngestionService(db=db, uploaded_by=None)
            result = service.ingest_source(source=source, max_docs=max_docs)
            _save_last_run(datetime.now(timezone.utc))
            logger.info("Scheduled web ingest summary: %s", result.get("summary"))
        except Exception as e:
            logger.exception("Scheduled web ingest failed: %s", e)
        finally:
            db.close()


def start_web_ingest_scheduler_if_enabled() -> None:
    global _thread
    enabled = os.getenv("WEB_INGEST_SCHEDULER_ENABLED", "false").lower() in (
        "1",
        "true",
        "yes",
    )
    if not enabled:
        return
    if _thread and _thread.is_alive():
        return

    interval_hours = float(os.getenv("WEB_INGEST_INTERVAL_HOURS", "168"))  # weekly
    source = os.getenv("WEB_INGEST_SOURCE", "central")
    max_docs = int(os.getenv("WEB_INGEST_MAX_DOCS", "3"))

    _stop.clear()
    _thread = threading.Thread(
        target=_run_loop,
        args=(interval_hours, source, max_docs),
        name="web-ingest-scheduler",
        daemon=True,
    )
    _thread.start()


def stop_web_ingest_scheduler() -> None:
    _stop.set()
