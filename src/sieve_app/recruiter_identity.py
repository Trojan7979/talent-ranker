"""Shared recruiter identity, job grants, and server-side sessions."""

import hashlib

import psycopg
from fastapi import HTTPException, Request
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

COOKIE = "sieve_recruiter_session"


class IdentitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SIEVE_IDENTITY_", env_file=".env", extra="ignore")
    database_url: str = ""
    public_base_url: str = ""
    frontend_base_url: str = ""
    google_client_id: str = ""
    google_client_secret: SecretStr | None = None
    microsoft_client_id: str = ""
    microsoft_client_secret: SecretStr | None = None
    microsoft_tenant: str = "common"
    secure_cookies: bool = True


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class RecruiterIdentity:
    def __init__(self, settings: IdentitySettings):
        self.settings = settings

    def connect(self):
        if not self.settings.database_url:
            raise HTTPException(503, "Recruiter identity database is not configured")
        return psycopg.connect(self.settings.database_url)

    def actor(self, request: Request) -> str:
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Sign in with Google or Microsoft")
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT recruiter_id::text FROM recruiter_sessions "
                        "WHERE token_hash=%s AND expires_at>now()", (digest(token),))
            row = cur.fetchone()
        if not row:
            raise HTTPException(401, "Recruiter session expired; sign in again")
        return row[0]

    def jobs(self, actor: str, workspace_id: str) -> frozenset[str]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT job_id FROM recruiter_job_grants "
                        "WHERE workspace_id=%s AND recruiter_id=%s", (workspace_id, actor))
            return frozenset(row[0] for row in cur.fetchall())

    def save_login_state(self, state: str, provider: str, verifier: str, nonce: str) -> None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM recruiter_login_states WHERE expires_at<now()")
            cur.execute("INSERT INTO recruiter_login_states"
                        "(state_hash,provider,verifier,nonce,expires_at) "
                        "VALUES (%s,%s,%s,%s,now()+interval '10 minutes')",
                        (digest(state), provider, verifier, nonce))

    def consume_login_state(self, state: str, provider: str) -> tuple[str, str] | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM recruiter_login_states "
                        "WHERE state_hash=%s AND provider=%s AND expires_at>now() "
                        "RETURNING verifier,nonce", (digest(state), provider))
            return cur.fetchone()

    def finish_login(self, provider: str, claims: dict, session: str) -> str:
        issuer = "https://accounts.google.com" if provider == "google" else claims["iss"]
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("INSERT INTO recruiter_identities(provider,issuer,subject,email) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT(provider,issuer,subject) "
                        "DO UPDATE SET email=excluded.email,last_login_at=now() "
                        "RETURNING recruiter_id::text",
                        (provider, issuer, claims["sub"], claims.get("email")))
            recruiter_id = cur.fetchone()[0]
            cur.execute("INSERT INTO recruiter_sessions(token_hash,recruiter_id,expires_at) "
                        "VALUES (%s,%s,now()+interval '8 hours')", (digest(session), recruiter_id))
        return recruiter_id

    def account(self, actor: str) -> tuple[str, str | None]:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT provider,email FROM recruiter_identities WHERE recruiter_id=%s", (actor,))
            return cur.fetchone()

    def logout(self, token: str | None) -> None:
        if token:
            with self.connect() as conn, conn.cursor() as cur:
                cur.execute("DELETE FROM recruiter_sessions WHERE token_hash=%s", (digest(token),))


def actor_for(request: Request) -> str:
    identity = getattr(request.app.state, "recruiter_identity", None)
    if identity is None:
        raise HTTPException(503, "Recruiter sign-in is not configured")
    return identity.actor(request)
