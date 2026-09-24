from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(auto_error=False)


def recruiter_actor(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> str:
    """Resolve an authenticated actor; production deployments replace this dependency."""
    if credentials is None:
        raise HTTPException(status_code=401, detail="recruiter bearer token required")
    actor = request.app.state.settings.recruiter_tokens.get(credentials.credentials)
    if not actor:
        raise HTTPException(status_code=403, detail="recruiter token not authorized")
    return actor
