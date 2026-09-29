"""Recruiter-controlled Gmail connection with a one-time server-side callback."""

import hashlib
import json
import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .auth import recruiter_actor

router = APIRouter(prefix="/screening", tags=["screening sender"])
Actor = Annotated[str, Depends(recruiter_actor)]
logger = logging.getLogger("uvicorn.error")


class ConnectRequest(BaseModel):
    campaign_id: UUID | None = None


class ConnectResponse(BaseModel):
    authorization_url: str


class SenderStatus(BaseModel):
    backend: str
    sender_email: str | None
    connected: bool


def _digest(state: str) -> str:
    return hashlib.sha256(state.encode("ascii")).hexdigest()


@router.get("/sender/gmail/status", response_model=SenderStatus)
def sender_status(actor: Actor, request: Request) -> SenderStatus:
    settings = request.app.state.settings
    try:
        saved = json.loads(settings.gmail_token_file.read_text(encoding="utf-8"))
        connected = bool(saved.get("refresh_token"))
    except (OSError, ValueError, AttributeError):
        connected = False
    return SenderStatus(
        backend=settings.sender_backend,
        sender_email=settings.gmail_sender_email,
        connected=settings.sender_backend == "gmail_api" and connected,
    )


@router.post("/sender/gmail/connect", response_model=ConnectResponse)
def connect_gmail(details: ConnectRequest, actor: Actor, request: Request) -> ConnectResponse:
    settings = request.app.state.settings
    if settings.sender_backend != "gmail_api" or not settings.gmail_sender_email:
        raise HTTPException(status_code=503, detail="Gmail sender is not configured")
    if details.campaign_id and request.app.state.repo.get_campaign(details.campaign_id) is None:
        raise HTTPException(status_code=404, detail="campaign not found")
    state, verifier, nonce = (secrets.token_urlsafe(size) for size in (32, 64, 32))
    try:
        url = request.app.state.gmail_web_oauth.authorization_url(state, verifier, nonce)
    except (ValueError, ImportError) as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    request.app.state.repo.save_oauth_state(
        _digest(state), actor, verifier, nonce, details.campaign_id
    )
    logger.info("Gmail OAuth started state_hash_prefix=%s", _digest(state)[:12])
    return ConnectResponse(authorization_url=url)


@router.get("/oauth/gmail/callback")
def gmail_callback(request: Request, state: str, code: str | None = None,
                   error: str | None = None):
    state_hash = _digest(state)
    saved = request.app.state.repo.consume_oauth_state(state_hash)
    request.app.state.repo.record_oauth_event(
        state_hash, "callback_found" if saved else "callback_missing"
    )
    logger.info(
        "Gmail OAuth callback state_hash_prefix=%s state_found=%s provider_error=%s",
        state_hash[:12], saved is not None, bool(error),
    )
    if saved is None:
        raise HTTPException(
            status_code=400,
            detail="Gmail connection expired or was already attempted. Return to the campaign and click Connect Gmail again.",
        )
    if error or not code:
        request.app.state.repo.record_oauth_event(state_hash, "cancelled")
        raise HTTPException(status_code=400, detail="Gmail connection was not completed")
    try:
        request.app.state.gmail_web_oauth.complete(
            state, saved["code_verifier"], saved["nonce"], code
        )
    except (ValueError, ImportError, OSError) as failure:
        request.app.state.repo.record_oauth_event(state_hash, "failed", str(failure))
        logger.warning("Gmail OAuth completion failed: %s", failure)
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    except Exception as failure:
        request.app.state.repo.record_oauth_event(
            state_hash, "unexpected_failure", type(failure).__name__
        )
        logger.error("Gmail OAuth unexpected failure: %s", type(failure).__name__)
        raise HTTPException(
            status_code=502, detail="Google authorization failed; start a new connection"
        ) from failure
    request.app.state.repo.record_oauth_event(state_hash, "completed")
    logger.info("Gmail OAuth completed state_hash_prefix=%s", state_hash[:12])
    base = request.app.state.settings.frontend_base_url.rstrip("/")
    campaign_id = saved["campaign_id"]
    path = f"/screening/campaigns/{campaign_id}" if campaign_id else "/ranking"
    return RedirectResponse(
        url=f"{base}{path}?gmail=connected", status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
