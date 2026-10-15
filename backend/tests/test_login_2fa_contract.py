"""Login has to say *which* step it wants, not just that it is not done.

## The gap

`POST /auth/login` answered "2FA code required" and "Invalid 2FA code" with the
same 401 and no `error_code`. The step-up endpoint already answered this way
(`STEP_UP_2FA_REQUIRED` / `STEP_UP_2FA_INVALID`), so login was the odd one out —
and the only signal separating "your password is wrong" from "now type your code"
was an English sentence.

## Why that matters rather than being pedantry

A client that cannot tell those apart does one of two wrong things, and both are
shippable-looking:

- It always shows the 2FA field, which asks every password-only admin for a code
  they do not have, and leaves them stuck on a six-box input.
- It shows nothing until an error, and then shows the *same* thing for both cases,
  so a correct password appears rejected and the operator retypes it forever.

String-matching an error message is the kind of coupling that survives review,
because it works. It breaks when someone rewords the sentence or adds a
translation, and it fails silently: the field still appears, just at the wrong
moment.

So the codes are asserted here as part of the API's contract, not as an
implementation detail of one client.
"""

import pyotp
import pytest

from app.services.totp_service import TOTPService


async def _user_with_2fa(db_session, user):
    """Give the user a working 2FA secret, and return it.

    The secret is encrypted exactly the way the setup endpoint stores it, so the
    test exercises the real decrypt-and-verify path. Generating a *valid* code
    through pyotp rather than stubbing `verify_code` matters for the same reason:
    a stub would keep this passing if the encryption handling broke, which is the
    half of 2FA that actually breaks.
    """
    secret = TOTPService.generate_secret()
    user.totp_secret_encrypted = TOTPService.encrypt_secret(secret)
    user.is_2fa_enabled = True
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return secret


@pytest.mark.asyncio
async def test_login_asks_for_a_code_with_a_machine_readable_code(
    client, db_session, test_user
):
    """The state a client needs to act on, as data rather than prose."""
    await _user_with_2fa(db_session, test_user)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "User!Pass1"},
    )

    assert resp.status_code == 401
    assert resp.json()["error_code"] == "LOGIN_2FA_REQUIRED"


@pytest.mark.asyncio
async def test_a_wrong_code_is_distinguishable_from_a_wrong_password(
    client, db_session, test_user
):
    """The two are different states and must not share an answer.

    A client that cannot tell them apart either re-prompts a password the server
    just accepted, or shows a code field to someone whose password is simply
    mistyped.
    """
    await _user_with_2fa(db_session, test_user)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "User!Pass1", "totp_code": "000000"},
    )

    assert resp.status_code == 401
    assert resp.json()["error_code"] == "LOGIN_2FA_INVALID"


@pytest.mark.asyncio
async def test_a_wrong_password_is_not_reported_as_a_2fa_problem(
    client, db_session, test_user
):
    """The distinction the client is relying on has to actually hold.

    Asserting only that `LOGIN_2FA_REQUIRED` exists would pass even if the
    endpoint also emitted it for an ordinary bad password — which is precisely the
    ambiguity this change exists to remove.
    """
    await _user_with_2fa(db_session, test_user)

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "not-the-password"},
    )

    assert resp.status_code == 401
    assert resp.json()["error_code"] != "LOGIN_2FA_REQUIRED"


@pytest.mark.asyncio
async def test_a_correct_code_signs_in(client, db_session, test_user):
    """The codes must not be a way of refusing everything.

    A guard that blocks every 2FA login is indistinguishable from a working one
    until somebody tries to use it.
    """
    secret = await _user_with_2fa(db_session, test_user)

    resp = await client.post(
        "/api/v1/auth/login",
        json={
            "email": test_user.email,
            "password": "User!Pass1",
            "totp_code": pyotp.TOTP(secret).now(),
        },
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["data"]["email"] == test_user.email


@pytest.mark.asyncio
async def test_a_password_only_account_is_never_asked_for_a_code(client, test_user):
    """The negative case: the code must not leak into the ordinary path.

    Without this, "always show the 2FA field" would pass every test above.
    """
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": test_user.email, "password": "User!Pass1"},
    )

    assert resp.status_code == 200, resp.text