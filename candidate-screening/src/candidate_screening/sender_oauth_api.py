"""Recruiter-controlled Gmail connection with a one-time server-side callback."""

import hashlib
import json
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from .auth import recruiter_actor

router = APIRouter(prefix="/screening", tags=["screening sender"])
Actor = Annotated[str, Depends(recruiter_actor)]


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
    return ConnectResponse(authorization_url=url)


@router.get("/oauth/gmail/callback")
def gmail_callback(request: Request, state: str, code: str | None = None,
                   error: str | None = None):
    saved = request.app.state.repo.consume_oauth_state(_digest(state))
    if saved is None:
        raise HTTPException(status_code=400, detail="Gmail connection request expired or reused")
    if error or not code:
        raise HTTPException(status_code=400, detail="Gmail connection was not completed")
    try:
        request.app.state.gmail_web_oauth.complete(
            state, saved["code_verifier"], saved["nonce"], code
        )
    except (ValueError, ImportError, OSError) as failure:
        raise HTTPException(status_code=400, detail=str(failure)) from failure
    base = request.app.state.settings.frontend_base_url.rstrip("/")
    campaign_id = saved["campaign_id"]
    path = f"/screening/campaigns/{campaign_id}" if campaign_id else "/ranking"
    return RedirectResponse(
        url=f"{base}{path}?gmail=connected", status_code=303,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )
