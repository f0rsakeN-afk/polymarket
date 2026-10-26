"""A benign refresh must not read as a stolen token.

## The bug this fixes

`POST /auth/refresh` treated *any* presentation of a revoked token as theft:
`_revoke_chain` — every session, every device — and 401. That is the correct
response to a real stolen token, and it has no way to distinguish one from a
legitimate client that refreshed twice.

It is not a theoretical race. Cookies are keyed by domain and path, **not by
port**, so `localhost:3000` and `localhost:3001` — the storefront and the admin
panel — share one `refresh_token`. Whichever refreshes first rotates it; the other
then presents the revoked one on a routine navigation, and the operator is logged
out of both. Two browser tabs of the same app do the same thing.

## The fix

A grace window. A revoked token presented within `refresh_reuse_grace_seconds`
of being revoked, **with a matching device fingerprint**, is treated as the
duplicate it almost always is: the caller is issued a fresh pair and nothing is
revoked.

Outside the window, or from a different device, behaviour is unchanged — the
chain still dies. That is the part that matters: the window is measured in
seconds and the theft case is exactly the case it does not cover.

The device check is not decoration. Without it, an attacker holding a stolen
token could present it inside the window and be handed a live session, which would
turn a defence into a hole. The window only forgives a token that is being used
by the client that owns it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import text

UA = "Mozilla/5.0 (X11; Linux x86_64) GraceTest/1.0"


@pytest.fixture
async def account(db_session):
    """A signed-in account, returned as `(user_id, email)` plain values.

    Strings rather than the ORM object on purpose: `commit()` expires the
    instance, and reading an attribute afterwards is a lazy load in whatever
    context happens to run next.
    """
    from conftest import create_login_session

    from app.deps import hash_password
    from app.models.user import User

    user = User(
        email=f"grace_{uuid.uuid4().hex[:8]}@example.com",
        username=f"grace_{uuid.uuid4().hex[:8]}",
        password_hash=hash_password("Grace!Pass1"),
        is_active=True,
        is_email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    await create_login_session(db_session, user)
    user_id, email = str(user.id), user.email
    await db_session.commit()
    return user_id, email


@pytest.fixture
async def refresh_token(client: AsyncClient, account) -> str:
    """Sign in the way a browser does, and return the refresh token it got."""
    _user_id, email = account
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Grace!Pass1"},
        headers={"User-Agent": UA},
    )
    assert resp.status_code == 200, resp.text
    # The cookie jar is the source of truth, exactly as it is in a browser.
    return client.cookies.get("refresh_token") or ""


async def _refresh(client: AsyncClient, token: str, ua: str = UA):
    return await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": token},
        headers={"User-Agent": ua},
    )


# ── The duplicate that was logging people out ─────────────────────────────────


@pytest.mark.asyncio
async def test_a_replayed_refresh_inside_the_window_is_not_treated_as_theft(
    client: AsyncClient, refresh_token: str
):
    """The reported bug: the second app presenting the token the first just rotated.

    The old behaviour revoked the whole chain here, which logged the user out of
    every device because two pages happened to refresh within a second of each
    other.
    """
    first = await _refresh(client, refresh_token)
    assert first.status_code == 200, first.text

    # The other app still holds the pre-rotation cookie.
    second = await _refresh(client, refresh_token)

    assert second.status_code == 200, (
        "a benign duplicate refresh logged the user out: " + second.text
    )


@pytest.mark.asyncio
async def test_a_duplicated_refresh_leaves_the_session_usable(
    client: AsyncClient, refresh_token: str
):
    """Not just "the replay succeeded" — the session must survive it.

    A 200 while the chain is nonetheless revoked hands back a token that works
    once and then fails, which is the same bug in a different expression.
    """
    await _refresh(client, refresh_token)
    await _refresh(client, refresh_token)  # the duplicate

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200, me.text
    assert me.json()["data"]["email"]


@pytest.mark.asyncio
async def test_repeated_duplicates_keep_working_within_the_window(
    client: AsyncClient, refresh_token: str
):
    """Three tabs refreshing in a burst is three tabs, not three attackers."""
    for _ in range(3):
        resp = await _refresh(client, refresh_token)
        assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_the_duplicate_gets_a_working_pair_not_an_error(
    client: AsyncClient, refresh_token: str
):
    """The response must carry cookies, or the caller retries with the same dead
    token forever."""
    await _refresh(client, refresh_token)

    resp = await _refresh(client, refresh_token)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "refreshed"
    assert client.cookies.get("access_token"), "no access token was set"
    assert client.cookies.get("refresh_token"), "no refresh token was set"


# ── The window must not become a hole ────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_replay_from_a_different_device_is_still_theft(
    client: AsyncClient, refresh_token: str
):
    """The grace window forgives a *duplicate*, not an unknown client.

    Without this, anyone holding a stolen token could present it inside the window
    and be handed a working session — turning a theft defence into the way in.
    """
    await _refresh(client, refresh_token)  # rotates it; the token is now revoked

    attacker = await _refresh(
        client, refresh_token, ua="Mozilla/5.0 (Windows NT 10.0) Attacker/9.9"
    )

    assert attacker.status_code == 401, attacker.text


@pytest.mark.asyncio
async def test_a_replay_outside_the_window_is_still_theft(
    client: AsyncClient, db_session, refresh_token: str
):
    """The window is measured in seconds, and theft is the case it excludes.

    The revocation is rewound rather than slept through: the boundary is what is
    under test, and waiting out a real window would only make the suite slow.
    """
    await _refresh(client, refresh_token)

    await db_session.execute(
        text("UPDATE refresh_tokens SET revoked_at = :old WHERE revoked = true"),
        {"old": datetime.now(UTC) - timedelta(hours=1)},
    )
    await db_session.commit()

    replayed = await _refresh(client, refresh_token)

    assert replayed.status_code == 401, replayed.text


@pytest.mark.asyncio
async def test_a_never_revoked_token_rotates_normally(
    client: AsyncClient, refresh_token: str
):
    """The grace path is only for `revoked=True`; a live token is unaffected."""
    resp = await _refresh(client, refresh_token)

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["status"] == "refreshed"