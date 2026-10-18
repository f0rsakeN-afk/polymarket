"""Origin checking: the CSRF defence that survives `SameSite=None`.

## Why this file has to exist

`SameSite=Lax` was the CSRF defence, and it was the whole of it. `COOKIE_SAMESITE`
is now configurable because a cross-site admin deployment cannot use `lax` — the
browser would never send the cookie — and `none` removes that defence as a direct
consequence.

So the defence is asserted at the front door instead, where it does not depend on
a cookie attribute a deployment is *obliged* to change.

## What is being defended

A cross-site state-changing request carrying the victim's cookies. `evil.com`
submits a form to `/api/v1/orders`; without a defence the browser attaches the
session cookie and the order goes through.

Every state-changing endpoint in this API is `POST`/`PATCH`/`PUT`/`DELETE` — there
are no GET mutations — so the unsafe-method set is the whole attack surface.
"""

import pytest

from app.config import settings

ALLOWED = "http://localhost:3000"
ADMIN = "http://localhost:3001"


async def _post(client, path: str, origin: str | None):
    headers = {"Origin": origin} if origin is not None else {}
    return await client.post(path, headers=headers, json={})


@pytest.mark.asyncio
async def test_a_cross_site_state_change_is_refused(client):
    """The attack this replaces `SameSite=Lax` for."""
    resp = await _post(client, "/api/v1/auth/login", "https://evil.example")

    assert resp.status_code == 403
    assert resp.json()["error_code"] == "ORIGIN_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_a_cross_site_delete_is_refused(client):
    """`DELETE` is in the unsafe set too, and is the one a form cannot express -
    so the naive "forms only send GET/POST" assumption would miss it entirely."""
    resp = await client.delete(
        "/api/v1/admin/users/00000000-0000-0000-0000-000000000000",
        headers={"Origin": "https://evil.example"},
    )

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_an_allowed_origin_passes(client):
    """Otherwise this middleware breaks the product rather than protecting it."""
    resp = await _post(client, "/api/v1/auth/login", ALLOWED)

    # 401/422 is fine - the point is that it is not the origin check refusing it.
    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_the_admin_origin_passes(client):
    """The admin app is an allowed origin; refusing it would lock operators out
    of the two endpoints that move money."""
    resp = await _post(client, "/api/v1/auth/login", ADMIN)

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_a_request_without_an_origin_is_allowed(client):
    """Non-browser clients have no `Origin` header.

    Blocking them would break the WebSocket `?token=` fallback, server-to-server
    calls and curl - with no security gain, because every browser that matters
    sends `Origin` on a non-GET request.
    """
    resp = await _post(client, "/api/v1/auth/login", None)

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_a_safelist_bypass_via_null_origin_is_refused(client):
    """`Origin: null` is what a sandboxed iframe or a `data:` document sends.

    It is the one origin an attacker can synthesise, and it is not in any
    allowlist - so it has to be refused explicitly rather than by omission.
    """
    resp = await _post(client, "/api/v1/auth/login", "null")

    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_a_safe_method_is_never_blocked(client):
    """Cross-site GETs are legitimate: embedding, prefetch, link previews.

    There are no GET mutations in this API, so there is nothing for one to change.
    """
    resp = await client.get("/api/v1/auth/me", headers={"Origin": "https://evil.example"})

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_an_options_preflight_is_not_blocked(client):
    """CORS preflight is how the *legitimate* cross-origin request gets to ask.

    Refusing it would mean no browser can ever perform a credentialed request from
    an allowed origin, which is the entire cross-site deployment this work exists
    to enable.
    """
    resp = await client.request(
        "OPTIONS",
        "/api/v1/auth/login",
        headers={"Origin": ALLOWED},
    )

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_the_default_port_does_not_change_the_verdict(client, monkeypatch):
    """`https://x.com` and `https://x.com:443` are the same origin by spec.

    Browsers disagree about whether to include the default port in `Origin`, so a
    plain string comparison refuses a legitimate request from one browser and
    accepts it from another - which is the worst kind of bug: it looks like a
    user-agent problem and it is not.
    """
    monkeypatch.setattr(settings, "cors_origins", "https://admin.example.com")

    resp = await _post(client, "/api/v1/auth/login", "https://admin.example.com:443")

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_a_trailing_slash_does_not_change_the_verdict(client):
    """Same reason: the allowlist is configured by hand in `.env` and a trailing
    slash is an easy, invisible way to lock yourself out."""
    resp = await _post(client, "/api/v1/auth/login", f"{ALLOWED}/")

    assert resp.status_code != 403, resp.text


@pytest.mark.asyncio
async def test_the_allowlist_comes_from_cors_origins_and_nothing_else():
    """One declaration, one list.

    A second copy of the origin list here is the `CORS_ORIGINS` mistake again: two
    lists that agree until someone edits one, after which a legitimate origin is
    refused with a 403 that looks like a CSRF attack.
    """
    from app.api.origin_check import allowed_origins

    configured = {o.strip().rstrip("/") for o in settings.cors_origins.split(",") if o.strip()}

    assert allowed_origins() == configured
    assert ALLOWED in allowed_origins()
    assert ADMIN in allowed_origins()


@pytest.mark.asyncio
async def test_the_refusal_names_what_went_wrong(client):
    """`403 Forbidden` with no explanation is indistinguishable from an
    authorisation failure, and the operator's next move is to ask for permissions
    rather than to look at their `.env`."""
    resp = await _post(client, "/api/v1/auth/login", "https://evil.example")

    body = resp.json()
    assert body["error_code"] == "ORIGIN_NOT_ALLOWED"
    assert body["message"]


@pytest.mark.asyncio
async def test_a_wildcard_allowlist_does_not_disable_the_check(client, monkeypatch):
    """`ALLOWED_ORIGINS=*` was honoured as "allow every origin".

    `app.py` already refuses `*` in `CORS_ORIGINS` because credentials cannot be
    used with a wildcard, so honouring it here was a second and much easier way to
    switch the CSRF defence off - one env var, no warning.
    """
    monkeypatch.setattr(settings, "allowed_origins", "*")

    resp = await _post(client, "/api/v1/auth/login", "https://evil.example")

    assert resp.status_code == 403, "a wildcard must not disable the origin check"


@pytest.mark.asyncio
async def test_the_localhost_bypass_does_not_apply_in_production(
    client, monkeypatch
):
    """Local development conveniences are scoped to local development.

    A browser-based CSRF attack is served from the attacker's own origin, so an
    attacker cannot forge `Origin: http://localhost` - which is why this bypass
    was never a CSRF hole. It is still meaningless in production, and an
    environment-scoped rule is one fewer thing that has to be reasoned about when
    the next one is added.
    """
    monkeypatch.setattr(settings, "app_env", "production")

    resp = await _post(client, "/api/v1/auth/login", "http://localhost:9999")

    assert resp.status_code == 403