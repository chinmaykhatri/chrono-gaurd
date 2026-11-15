import hashlib
import hmac
import ipaddress
import json
import re
import secrets
from urllib.parse import urlsplit, urlunsplit

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def key(tenant: str, kind: str, identity: str = "") -> str:
    return f"cg:{digest(tenant)[:24]}:{kind}:{digest(identity)}"


def safe_public_url(url: str) -> str:
    """Validate evidence URLs; this does not perform direct network retrieval."""
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().rstrip(".")
    if parts.scheme != "https" or not host or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError("Evidence requires a public HTTPS URL")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")) or "." not in host:
        raise ValueError("Private host is not evidence")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Private address is not evidence")
    return urlunsplit(("https", host, parts.path or "/", parts.query, ""))


def redact_query(text: str) -> str:
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[redacted]", text)
    return re.sub(r"(?<!\w)(?:\+?\d[\d ()-]{7,}\d)(?!\w)", "[redacted]", text)


async def require_internal(request: Request):
    candidate = request.headers.get("x-cg-internal-key", "")
    if not hmac.compare_digest(candidate.encode(), request.app.state.settings.internal_key.get_secret_value().encode()):
        raise HTTPException(401, "unauthorized")


async def require_session(request: Request):
    session_id = request.cookies.get("cg_session", "")
    if not session_id:
        raise HTTPException(401, "unauthorized")
    session_key = "cg:session:" + digest(session_id)
    raw = await request.app.state.redis.get(session_key)
    if not raw:
        raise HTTPException(401, "unauthorized")
    session = json.loads(raw)
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin") or ""
        valid_origin = (origin == request.app.state.settings.console_origin.rstrip("/")) or (
            request.app.state.settings.environment == "development"
            and (origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"))
        )
        if not valid_origin:
            raise HTTPException(403, "invalid_origin")
        if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf_token"]):
            raise HTTPException(403, "invalid_csrf_token")
    return session


async def login(request: Request, password: str):
    settings = request.app.state.settings
    origin = request.headers.get("origin") or ""
    valid_origin = (origin == settings.console_origin.rstrip("/")) or (
        settings.environment == "development"
        and (origin.startswith("http://localhost:") or origin.startswith("http://127.0.0.1:"))
    )
    if not valid_origin:
        raise HTTPException(403, "invalid_origin")
    # Do not trust forwarding headers. The deployment proxy is the only exposed listener.
    address = request.client.host if request.client else "unknown"
    counter_key = "cg:login:" + digest(address)
    count = await request.app.state.redis.incr(counter_key)
    if count == 1:
        await request.app.state.redis.expire(counter_key, 60)
    if count > 5:
        raise HTTPException(429, "rate_limited")
    try:
        await run_in_threadpool(PasswordHasher().verify, settings.admin_password_hash.get_secret_value(), password)
    except VerificationError:
        raise HTTPException(401, "unauthorized") from None
    session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = {"tenant_id": settings.tenant_id, "csrf_token": csrf, "authenticated": True}
    await request.app.state.redis.set("cg:session:" + digest(session_id), json.dumps(session), ex=settings.session_ttl_seconds)
    return session_id, session
