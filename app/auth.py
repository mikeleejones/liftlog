import hashlib
import hmac

from fastapi import Request

from .config import SECRET

COOKIE_NAME = "liftlog_auth"
COOKIE_MAX_AGE = 365 * 24 * 3600


def cookie_value() -> str:
    return hashlib.sha256(SECRET.encode()).hexdigest()


def is_authed(request: Request) -> bool:
    got = request.cookies.get(COOKIE_NAME, "")
    return bool(SECRET) and hmac.compare_digest(got, cookie_value())


def secret_matches(candidate: str) -> bool:
    return bool(SECRET) and hmac.compare_digest(candidate, SECRET)


def bearer_token(request: Request) -> str:
    """The token from an 'Authorization: Bearer <token>' header, or '' if absent.
    Used only by endpoints that opt into token auth; the cookie flow above is
    untouched."""
    header = request.headers.get("authorization", "")
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""
