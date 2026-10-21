"""SameSite is the setting nobody can reproduce locally.

## The trap

`SameSite` ignores ports. To a cookie, `localhost:3000` and `localhost:3001` are
one site, so `lax` works perfectly in development - for both apps.

In production the admin app is usually on its own host (`admin.example.com`) and
the API on another (`api.example.com`). Those are *different sites*, and `lax`
means the browser withholds the cookie from `fetch()` entirely. So:

- login returns 200 and `Set-Cookie` arrives;
- every subsequent request goes out unauthenticated;
- `/auth/me` 401s forever;
- nothing is logged, nothing is redirected, and the operator is simply and
  permanently signed out.

Every check that can be run locally passes. This file is what stands in for the
deploy that cannot be.

## The mirror-image failure

The opposite mistake is just as silent: `SameSite=None` without `Secure` is
discarded by every current browser, so asking for it in a non-production
environment produces the same unauthenticated-everything state by a different
route. Both are refused - at boot in `app.py`, and again at cookie-issue time in
`deps.py` for a settings object mutated after startup.
"""

import pytest
from fastapi import Response

from app.config import settings
from app.deps import clear_auth_cookies, set_auth_cookies


def _cookie(response: Response, name: str) -> str:
    for header in response.headers.getlist("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    raise AssertionError(f"{name} was not set")


# ── The default ─────────────────────────────────────────────────────────────


async def test_default_is_lax():
    """`lax` is correct for single-site deployments and for local dev."""
    response = Response()
    set_auth_cookies(response, access_token="a", refresh_token="r")

    assert "SameSite=lax" in _cookie(response, "access_token")
    assert "SameSite=lax" in _cookie(response, "refresh_token")


async def test_the_default_survives_being_left_out_of_the_environment():
    """A deployment that sets nothing must still work for a single-site setup.

    The setting is optional on purpose. Making it required would mean the first
    deploy after adding this check fails on a value nobody was told they needed.
    """
    assert settings.cookie_samesite.strip().lower() == "lax"


# ── Cross-site: the deployment that cannot be reproduced locally ────────────


async def test_none_is_honoured_in_production(monkeypatch):
    """The configuration that makes a cross-site admin app work at all.

    `api.example.com` serving `admin.example.com` has no other option: with
    `lax` the browser never sends the cookie back, and the app is permanently
    signed out.
    """
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    response = Response()
    set_auth_cookies(response, access_token="a", refresh_token="r")

    assert "SameSite=none" in _cookie(response, "access_token")
    assert "SameSite=none" in _cookie(response, "refresh_token")


async def test_none_always_pairs_with_secure(monkeypatch):
    """Not a preference. A `SameSite=None` cookie without `Secure` is discarded.

    Asserted explicitly because the pairing is invisible in the response: a test
    that only checked for `SameSite=none` would pass on a cookie the browser
    throws away, which is the whole failure mode.
    """
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    response = Response()
    set_auth_cookies(response, access_token="a")

    assert "Secure" in _cookie(response, "access_token")


async def test_secure_is_still_off_in_development(monkeypatch):
    """`lax` in development must stay non-Secure, or nothing works over http."""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "cookie_samesite", "lax")

    response = Response()
    set_auth_cookies(response, access_token="a")

    assert "Secure" not in _cookie(response, "access_token")


# ── The pair that cannot work ───────────────────────────────────────────────


async def test_none_outside_production_is_refused(monkeypatch):
    """The mirror failure: asking for `none` on plain http.

    Browsers discard the cookie, so login succeeds and nothing else ever does -
    the same symptom as the `lax` bug, reached from the opposite direction. A
    warning would not help, because the symptom looks like an unrelated bug.
    """
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    response = Response()
    with pytest.raises(ValueError, match="requires APP_ENV=production"):
        set_auth_cookies(response, access_token="a")


async def test_the_refusal_names_both_settings(monkeypatch):
    """An error that does not say what to change is an error someone files."""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    with pytest.raises(ValueError) as exc:
        set_auth_cookies(Response(), access_token="a")

    message = str(exc.value)
    assert "COOKIE_SAMESITE" in message
    assert "APP_ENV" in message
    # And says what to do instead, rather than only what is wrong.
    assert "lax" in message


@pytest.mark.parametrize("value", ["LAX-ish", "None;", "off", "lax,none", "true"])
async def test_an_unrecognised_value_is_refused(monkeypatch, value):
    """Typos must not fall through to a default.

    Falling back to `lax` on a typo is the `CORS_ORIGINS` mistake again: a second
    value, silently different from the one configured, discovered in production.
    """
    monkeypatch.setattr(settings, "cookie_samesite", value)

    with pytest.raises(ValueError):
        set_auth_cookies(Response(), access_token="a")


async def test_an_empty_value_falls_back_to_the_default(monkeypatch):
    """`COOKIE_SAMESITE=` in a `.env` means "unset", not "invalid".

    Refusing to boot on an empty value would make the first deploy after this
    check fail over a line an operator had no reason to add. The distinction from
    a typo is deliberate: empty is a complete absence, `"lax-ish"` is a mistake.
    """
    monkeypatch.setattr(settings, "cookie_samesite", "   ")

    response = Response()
    set_auth_cookies(response, access_token="a")
    assert "SameSite=lax" in _cookie(response, "access_token")


@pytest.mark.parametrize(
    "value,expected",
    [("LAX", "lax"), ("Strict", "strict"), (" NONE ", "none")],
)
async def test_values_are_case_insensitive(monkeypatch, value, expected):
    """Configuration is written by hand in a `.env`; `Lax` is a reasonable typo
    of nothing and should not be a reason to refuse to boot."""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cookie_samesite", value)

    response = Response()
    set_auth_cookies(response, access_token="a")
    assert f"SameSite={expected}" in _cookie(response, "access_token")


# ── Logout has to match ─────────────────────────────────────────────────────


async def test_logout_deletes_with_the_same_samesite(monkeypatch):
    """A delete that does not mirror the set does not remove the cookie.

    The existing comment warned about `Domain` and `Path`; `SameSite` belongs on
    that list. A browser that stored a `SameSite=None` cookie will not match a
    deletion that omits the attribute, and the result is a logout that appears to
    work while the cookie is still there to be sent.
    """
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "cookie_samesite", "none")

    response = Response()
    clear_auth_cookies(response)

    for name in ("access_token", "refresh_token"):
        header = _cookie(response, name)
        assert "Max-Age=0" in header or "expires" in header.lower()
        assert "SameSite=none" in header


async def test_logout_matches_in_the_default_configuration():
    response = Response()
    clear_auth_cookies(response)

    for name in ("access_token", "refresh_token"):
        assert "SameSite=lax" in _cookie(response, name)


# ── What this means for a deployment ────────────────────────────────────────


def test_the_localhost_case_is_a_single_site():
    """Why none of this is reproducible in development, stated as a test.

    SameSite compares *registrable domains* and ignores the port. Both front ends
    and the API share `localhost` here, so they are one site, so `lax` is correct,
    so every local check passes. The bug only exists once the hostnames differ.
    """
    from urllib.parse import urlparse

    def site(url: str) -> str:
        # The registrable domain, which is the whole of what SameSite compares.
        return urlparse(url).hostname or ""

    assert site("http://localhost:3000") == site("http://localhost:3001")
    assert site("https://api.example.com") != site("https://admin.example.com")