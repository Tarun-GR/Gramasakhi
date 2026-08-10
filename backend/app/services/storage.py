import json
import urllib.request
import urllib.error
from typing import Optional
from app.core.config import settings


def supabase_configured() -> bool:
    return bool(settings.SUPABASE_URL and get_supabase_key())


def get_supabase_key(*, require_secret: bool = False) -> Optional[str]:
    """
    Prefer service-role/secret for privileged Storage ops.
    Fall back to publishable/anon only for read-ish checks when allowed.
    """
    secret = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
    publishable = (settings.SUPABASE_PUBLISHABLE_KEY or "").strip()
    if require_secret:
        return secret or None
    return secret or publishable or None


def _auth_headers(content_type: Optional[str] = None, *, require_secret: bool = False) -> dict:
    key = get_supabase_key(require_secret=require_secret)
    if not key:
        raise ValueError(
            "Supabase key missing. Set SUPABASE_SERVICE_ROLE_KEY (secret) for storage writes, "
            "or SUPABASE_PUBLISHABLE_KEY for limited public access."
        )
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
    }
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def ensure_bucket_exists():
    """
    Attempts to create the configured Supabase storage bucket if it doesn't already exist.
    Requires secret/service_role key (publishable is blocked by RLS).
    """
    if not settings.SUPABASE_URL or not get_supabase_key(require_secret=True):
        return

    url = f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/bucket"
    payload = json.dumps(
        {
            "id": settings.SUPABASE_STORAGE_BUCKET,
            "name": settings.SUPABASE_STORAGE_BUCKET,
            "public": False,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers=_auth_headers("application/json", require_secret=True),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10.0) as response:
            print(
                f"[STORAGE SERVICE] Created missing bucket: {settings.SUPABASE_STORAGE_BUCKET}",
                flush=True,
            )
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        # 409 Conflict indicates the bucket already exists, which is safe to ignore
        if e.code not in (409, 422):
            print(
                f"[STORAGE SERVICE] Attempted to create bucket '{settings.SUPABASE_STORAGE_BUCKET}', "
                f"server returned status {e.code}: {body}",
                flush=True,
            )
    except Exception as e:
        print(f"[STORAGE SERVICE] Failed to verify/create bucket: {str(e)}", flush=True)


def upload_rag_document(path: str, content: bytes, content_type: str) -> str:
    """
    Uploads raw document bytes to Supabase Storage when configured.
    Falls back to local static/uploads so web/manual ingest works offline.
    Returns a stable storage path / URL used by RagDocument.file_url.
    """
    import os

    if not settings.SUPABASE_URL or not get_supabase_key(require_secret=True):
        # Local fallback when secret key is absent (publishable cannot write private buckets)
        safe_name = path.replace("\\", "/").replace("/", "__")
        local_dir = os.path.join("static", "uploads")
        os.makedirs(local_dir, exist_ok=True)
        local_path = os.path.join(local_dir, safe_name)
        with open(local_path, "wb") as f:
            f.write(content)
        return f"/static/uploads/{safe_name}"

    url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{path}"
    )

    def _do_upload():
        req = urllib.request.Request(
            url,
            data=content,
            headers=_auth_headers(content_type, require_secret=True),
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15.0) as response:
            pass

    try:
        _do_upload()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        # Check if bucket is missing (HTTP 404 or 400 with "Bucket not found" error)
        is_bucket_missing = (e.code == 404) or (e.code == 400 and "Bucket not found" in body)
        if is_bucket_missing:
            ensure_bucket_exists()
            try:
                _do_upload()
                return path
            except Exception as retry_err:
                raise ValueError(
                    f"Supabase upload retry failed after creating bucket: {str(retry_err)}"
                )
        raise ValueError(f"Supabase upload failed with status {e.code}: {body}")
    except Exception as e:
        raise ValueError(f"Supabase Storage connection failed: {str(e)}")

    return path


def delete_rag_document(path: str):
    """
    Deletes the document object from Supabase Storage, or local static uploads.
    """
    import os

    if path.startswith("/static/uploads/"):
        local_path = os.path.join("static", "uploads", path.split("/")[-1])
        if os.path.exists(local_path):
            try:
                os.remove(local_path)
            except Exception as e:
                print(f"[STORAGE SERVICE] Local delete failed: {e}")
        return

    if not settings.SUPABASE_URL or not get_supabase_key(require_secret=True):
        return

    url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{path}"
    )

    req = urllib.request.Request(
        url,
        headers=_auth_headers(require_secret=True),
        method="DELETE",
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as response:
            pass
    except urllib.error.HTTPError as e:
        if e.code not in (200, 404):
            body = e.read().decode("utf-8", errors="ignore")
            print(f"[STORAGE SERVICE] Supabase delete warning (status {e.code}): {body}")
    except Exception as e:
        print(f"[STORAGE SERVICE] Supabase delete failed: {str(e)}")


def create_signed_url(path: str, expires_in: int = 60) -> str:
    """
    Generates a short-lived signed URL for reading private storage objects.
    """
    if not settings.SUPABASE_URL or not get_supabase_key(require_secret=True):
        raise ValueError(
            "Supabase secret key required for signed URLs. "
            "Set SUPABASE_SERVICE_ROLE_KEY in backend/.env."
        )

    url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/sign/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{path}"
    )

    req = urllib.request.Request(
        url,
        data=json.dumps({"expiresIn": expires_in}).encode("utf-8"),
        headers=_auth_headers("application/json", require_secret=True),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15.0) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Failed to create signed URL from Supabase (status {e.code}): {body}")
    except Exception as e:
        raise ValueError(f"Supabase connection for signed URL failed: {str(e)}")

    signed_url = data.get("signedURL") or data.get("signedUrl")
    if not signed_url:
        raise ValueError("Supabase response did not contain a valid signed URL key.")

    if signed_url.startswith("/"):
        signed_url = f"{settings.SUPABASE_URL.rstrip('/')}{signed_url}"

    return signed_url


def download_rag_document(path: str) -> bytes:
    """
    Downloads the raw file bytes directly from private Supabase Storage.
    """
    if not settings.SUPABASE_URL or not get_supabase_key(require_secret=True):
        raise ValueError(
            "Supabase secret key required for private downloads. "
            "Set SUPABASE_SERVICE_ROLE_KEY in backend/.env."
        )

    url = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/authenticated/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{path}"
    )

    req = urllib.request.Request(
        url,
        headers=_auth_headers(require_secret=True),
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=30.0) as response:
            return response.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise ValueError(f"Direct storage download failed with status {e.code}: {body}")
    except Exception as e:
        raise ValueError(f"Supabase Storage download connection failed: {str(e)}")


def check_supabase_connection() -> dict:
    """
    Lightweight connectivity probe for diagnostics (no secrets printed).
    """
    result = {
        "url_configured": bool(settings.SUPABASE_URL),
        "publishable_configured": bool((settings.SUPABASE_PUBLISHABLE_KEY or "").strip()),
        "service_role_configured": bool((settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()),
        "bucket": settings.SUPABASE_STORAGE_BUCKET,
        "auth_reachable": False,
        "storage_reachable": False,
        "can_write_storage": False,
        "detail": "",
    }
    if not settings.SUPABASE_URL:
        result["detail"] = "SUPABASE_URL is empty"
        return result

    key = get_supabase_key()
    if not key:
        result["detail"] = "No Supabase key configured"
        return result

    headers = {"Authorization": f"Bearer {key}", "apikey": key}
    try:
        req = urllib.request.Request(
            f"{settings.SUPABASE_URL.rstrip('/')}/auth/v1/health",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            result["auth_reachable"] = resp.status == 200
    except Exception as e:
        result["detail"] = f"auth health failed: {e}"

    try:
        req = urllib.request.Request(
            f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/bucket",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            result["storage_reachable"] = resp.status == 200
            buckets = json.loads(resp.read().decode("utf-8"))
            names = [b.get("name") or b.get("id") for b in (buckets or [])]
            result["buckets"] = names
            result["bucket_exists"] = settings.SUPABASE_STORAGE_BUCKET in names
    except Exception as e:
        result["detail"] = f"storage list failed: {e}"

    result["can_write_storage"] = bool((settings.SUPABASE_SERVICE_ROLE_KEY or "").strip())
    if result["auth_reachable"] and result["storage_reachable"] and not result["can_write_storage"]:
        result["detail"] = (
            "Connected with publishable key. Add SUPABASE_SERVICE_ROLE_KEY "
            "(secret / service_role) to enable private bucket create/upload."
        )
    elif result["auth_reachable"] and result["storage_reachable"]:
        result["detail"] = "Supabase reachable; storage writes enabled"
    return result
