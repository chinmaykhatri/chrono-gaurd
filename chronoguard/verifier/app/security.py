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


def session_key(settings, token: str) -> str:
    # A new signing key or password invalidates every earlier session.
    material = settings.admin_password_hash.get_secret_value() + ":" + token
    signature = hmac.digest(settings.session_secret.get_secret_value().encode(), material.encode(), "sha256").hex()
    return "cg:operator:v2:" + signature


def require_origin(request: Request):
    if request.headers.get("origin") != request.app.state.settings.console_origin.rstrip("/"):
        raise HTTPException(403, "invalid_origin")


async def require_session(request: Request):
    settings = request.app.state.settings
    token = request.cookies.get("cg_session")
    raw = await request.app.state.redis.get(session_key(settings, token)) if token else None
    session = json.loads(raw) if raw else {}
    if session.get("authenticated") is not True or session.get("tenant_id") != settings.tenant_id:
        raise HTTPException(401, "unauthorized")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_origin(request)
        csrf = request.headers.get("x-csrf-token", "")
        if not csrf or not hmac.compare_digest(csrf.encode(), session["csrf_token"].encode()):
            raise HTTPException(403, "invalid_csrf_token")
    return session


async def login(request: Request, password: str):
    settings = request.app.state.settings
    require_origin(request)
    address = request.client.host if request.client else "unknown"
    counter = "cg:login:" + digest(address)
    async with request.app.state.redis.pipeline(transaction=True) as pipeline:
        count, _ = await pipeline.incr(counter).expire(counter, 60, nx=True).execute()
    if count > 10:
        raise HTTPException(429, "rate_limited")
    try:
        await run_in_threadpool(PasswordHasher().verify, settings.admin_password_hash.get_secret_value(), password)
    except (VerificationError, ValueError):
        raise HTTPException(401, "unauthorized") from None
    token = secrets.token_urlsafe(32)
    session = {"tenant_id": settings.tenant_id, "csrf_token": secrets.token_urlsafe(32), "authenticated": True}
    await request.app.state.redis.set(session_key(settings, token), json.dumps(session), ex=settings.session_ttl_seconds)
    return token, session
