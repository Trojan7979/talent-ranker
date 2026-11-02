"""Microsoft OpenID Connect configuration and ID-token verification."""

import base64
import json
import time

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi import HTTPException

from .recruiter_identity import IdentitySettings


def config(settings: IdentitySettings) -> dict[str, str]:
    tenant = settings.microsoft_tenant
    if not tenant or any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-" for ch in tenant):
        raise HTTPException(503, "Invalid Microsoft tenant configuration")
    root = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0"
    return {
        "client_id": settings.microsoft_client_id,
        "client_secret": settings.microsoft_client_secret.get_secret_value()
        if settings.microsoft_client_secret else "",
        "authorize": root + "/authorize",
        "token": root + "/token",
        "keys": f"https://login.microsoftonline.com/{tenant}/discovery/v2.0/keys",
    }


def _decode(segment: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)))


def verify(token: str, config: dict[str, str], nonce: str) -> dict:
    try:
        header, payload, signature = token.split(".")
        meta, claims = _decode(header), _decode(payload)
        if meta.get("alg") != "RS256":
            raise ValueError("Unexpected signing algorithm")
        response = requests.get(config["keys"], timeout=10)
        response.raise_for_status()
        keys = response.json()["keys"]
        key = next(k for k in keys if k.get("kid") == meta.get("kid") and k.get("kty") == "RSA")
        numbers = rsa.RSAPublicNumbers(
            int.from_bytes(base64.urlsafe_b64decode(key["e"] + "=="), "big"),
            int.from_bytes(base64.urlsafe_b64decode(key["n"] + "=="), "big"),
        )
        numbers.public_key().verify(
            base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)),
            f"{header}.{payload}".encode(), padding.PKCS1v15(), hashes.SHA256(),
        )
        now = time.time()
        if claims.get("aud") != config["client_id"] or claims.get("nonce") != nonce:
            raise ValueError("Audience or nonce mismatch")
        if float(claims.get("exp", 0)) <= now or float(claims.get("iat", 0)) > now + 60:
            raise ValueError("Expired or premature token")
        issuer = claims.get("iss", "")
        if not (claims.get("tid") and issuer ==
                f"https://login.microsoftonline.com/{claims['tid']}/v2.0"):
            raise ValueError("Issuer mismatch")
        if not claims.get("sub"):
            raise ValueError("Missing subject")
        return claims
    except Exception as error:
        raise HTTPException(401, "Identity token verification failed") from error
