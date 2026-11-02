"""Recruiter sign-in HTTP flow shared by Google and Microsoft."""

import base64
import hashlib
import secrets
from urllib.parse import urlencode, urlsplit

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from . import recruiter_google, recruiter_microsoft
from .recruiter_identity import COOKIE, IdentitySettings, digest

router = APIRouter(prefix="/api/auth", tags=["recruiter sign-in"])
STATE_COOKIE = "sieve_login_state"


def _provider(settings: IdentitySettings, name: str) -> dict[str, str]:
    if name == "google":
        return recruiter_google.config(settings)
    if name == "microsoft":
        return recruiter_microsoft.config(settings)
    raise HTTPException(404, "Unknown sign-in provider")


def _verified_claims(token: str, provider: str, config: dict[str, str], nonce: str) -> dict:
    if provider == "google":
        return recruiter_google.verify(token, config["client_id"], nonce)
    return recruiter_microsoft.verify(token, config, nonce)


def _configured_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return (url.scheme == "https" or
                (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1"))) \
            and bool(url.hostname) and not (url.username or url.password or url.query or url.fragment)
    except ValueError:
        return False


def _callback_uri(settings: IdentitySettings, provider: str) -> str:
    return settings.public_base_url.rstrip("/") + "/api/auth/callback/" + provider


@router.get("/providers")
def providers(request: Request):
    settings = request.app.state.recruiter_identity.settings
    choices = (("google", settings.google_client_id, settings.google_client_secret),
               ("microsoft", settings.microsoft_client_id, settings.microsoft_client_secret))
    configured = (_configured_url(settings.public_base_url)
                  and _configured_url(settings.frontend_base_url))
    names = [name for name, client, secret in choices
             if configured and client and secret and secret.get_secret_value()]
    base = settings.public_base_url.rstrip("/")
    return {"providers": names,
            "login_urls": {name: f"{base}/api/auth/login/{name}" for name in names}}


@router.get("/login/{provider}")
def login(provider: str, request: Request):
    identity = request.app.state.recruiter_identity
    settings = identity.settings
    config = _provider(settings, provider)
    if (not config["client_id"] or not config["client_secret"]
            or not _configured_url(settings.public_base_url)
            or not _configured_url(settings.frontend_base_url)):
        raise HTTPException(503, f"{provider.title()} sign-in is not configured")
    state, verifier, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(48), secrets.token_urlsafe(32)
    identity.save_login_state(state, provider, verifier, nonce)
    query = urlencode({"client_id": config["client_id"],
                       "redirect_uri": _callback_uri(settings, provider),
                       "response_type": "code", "scope": "openid email profile", "state": state,
                       "nonce": nonce,
                       "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
                       .rstrip(b"=").decode(),
                       "code_challenge_method": "S256", "prompt": "select_account"})
    result = RedirectResponse(config["authorize"] + "?" + query)
    result.set_cookie(STATE_COOKIE, digest(state), max_age=600, httponly=True,
                      secure=settings.secure_cookies, samesite="lax", path="/api/auth")
    return result


@router.get("/callback/{provider}")
def callback(provider: str, request: Request, state: str = "", code: str = ""):
    identity = request.app.state.recruiter_identity
    settings = identity.settings
    config = _provider(settings, provider)
    if (not state or not code or not secrets.compare_digest(
            request.cookies.get(STATE_COOKIE, ""), digest(state))):
        raise HTTPException(400, "Sign-in was cancelled or incomplete")
    saved = identity.consume_login_state(state, provider)
    if saved is None:
        raise HTTPException(400, "Sign-in state expired")
    try:
        response = requests.post(config["token"], data={"client_id": config["client_id"],
            "client_secret": config["client_secret"], "code": code, "grant_type": "authorization_code",
            "redirect_uri": _callback_uri(settings, provider), "code_verifier": saved[0]}, timeout=15)
        response.raise_for_status()
        claims = _verified_claims(response.json()["id_token"], provider, config, saved[1])
    except (requests.RequestException, KeyError) as error:
        raise HTTPException(401, "Could not complete account sign-in") from error
    session = secrets.token_urlsafe(48)
    identity.finish_login(provider, claims, session)
    result = RedirectResponse(settings.frontend_base_url.rstrip("/") + "/agents/recruitment",
                              status_code=303)
    result.set_cookie(COOKIE, session, max_age=8 * 3600, httponly=True,
                      secure=settings.secure_cookies, samesite="lax", path="/")
    result.delete_cookie(STATE_COOKIE, path="/api/auth")
    return result


@router.get("/me")
def me(request: Request, response: Response):
    identity = request.app.state.recruiter_identity
    actor = identity.actor(request)
    provider, email = identity.account(actor)
    response.headers["Cache-Control"] = "no-store"
    return {"recruiter_id": actor, "provider": provider, "email": email}


@router.post("/logout")
def logout(request: Request):
    request.app.state.recruiter_identity.logout(request.cookies.get(COOKIE))
    result = Response(status_code=204)
    result.delete_cookie(COOKIE, path="/")
    return result
