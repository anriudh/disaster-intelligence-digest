import hmac
import os

from fastapi import HTTPException
from slowapi import Limiter
from slowapi.util import get_remote_address

# Limits are per client address as the app sees it. Behind Render's proxy that
# may be the proxy's address rather than the caller's; X-Forwarded-For is not
# trusted because callers can set it themselves.
limiter = Limiter(key_func=get_remote_address)

READ_LIMIT = "120/minute"
TRIGGER_LIMIT = "3/hour"


def require_pipeline_token(authorization: str | None):
    """
    Bearer-token check for operator endpoints. Fails closed: when
    PIPELINE_TRIGGER_TOKEN is not configured the endpoints are disabled.
    """
    expected = os.getenv("PIPELINE_TRIGGER_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="Disabled: PIPELINE_TRIGGER_TOKEN is not configured")
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(token.strip().encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Invalid or missing token",
                            headers={"WWW-Authenticate": "Bearer"})
