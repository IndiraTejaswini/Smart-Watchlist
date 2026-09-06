"""Demo authentication dependency."""

from dataclasses import dataclass

from fastapi import Header, HTTPException

from app.config import get_settings


@dataclass(frozen=True)
class UserContext:
    user_id: str
    roles: tuple[str, ...]
    is_demo: bool


def get_current_user(
    x_demo_user: str | None = Header(None),
    authorization: str | None = Header(None),
) -> UserContext:
    settings = get_settings()
    if settings.DEMO_AUTH_ENABLED:
        if x_demo_user:
            return UserContext(x_demo_user, ("trader",), True)
        if authorization and authorization.startswith("Bearer demo-"):
            return UserContext(authorization.removeprefix("Bearer demo-"), ("trader",), True)
        return UserContext("demo_trader", ("trader",), True)
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    return UserContext(authorization.removeprefix("Bearer "), ("trader",), False)
