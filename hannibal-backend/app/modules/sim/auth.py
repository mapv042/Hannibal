"""HTTP Basic auth for the simulator.

The simulator has no dashboard and no Supabase login, but it does sit on a public
URL with a real Google Calendar connection behind it and the ability to move time
and delete data. A browser-native password prompt is the least friction that is
still a lock: a non-engineer opens the URL, types a password once, and is in.

It refuses to serve at all when no password is configured, rather than defaulting
to open. An unset variable is the likeliest way this ends up unprotected, so it
is the case that must fail closed.
"""

from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from app.config import settings

_basic = HTTPBasic(realm="Argos Simulator")


def require_sim_auth(
    credentials: HTTPBasicCredentials = Depends(_basic),
) -> str:
    """Gate a simulator endpoint behind Basic auth.

    Returns:
        The authenticated username.

    Raises:
        HTTPException: 503 when no password is configured (fail closed), 401 when
            the credentials do not match.
    """
    expected_user = settings.sim_basic_auth_user
    expected_password = settings.sim_basic_auth_password

    if not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "the simulator has no SIM_BASIC_AUTH_PASSWORD set and will not "
                "serve unprotected"
            ),
        )

    # compare_digest on both halves, always, so a wrong username and a wrong
    # password take the same time to reject.
    user_ok = secrets.compare_digest(credentials.username, expected_user)
    password_ok = secrets.compare_digest(credentials.password, expected_password)

    if not (user_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid simulator credentials",
            headers={"WWW-Authenticate": 'Basic realm="Argos Simulator"'},
        )

    return credentials.username
