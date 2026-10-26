"""CORS preflight must not consume a client's rate-limit budget.

This is the failure that made the private-feed browser suite intermittently
"fail" with pages that simply never loaded data, and it is a production bug
rather than a test artifact.

The sequence: a browser attaches a preflight to every cross-origin call that
isn't a simple request, which for a JSON API is all of them. The limiter skipped
`GET` but not `OPTIONS`, so a page making N calls spent 2N of its allowance.
Once that ran out, the API answered **429 to the preflight** - and because a
rejected preflight means the browser never sends the real request, every data
call failed while the user had asked for none of them.

The visible result was a page rendering its shell and silently showing nothing:
no client-side error, and a server log full of `OPTIONS ... 429`. That reads as
"the page didn't react to the websocket frame", which sends the investigation
at delivery and parsing - both of which were working correctly.

Preflights are browser-generated, cacheable, idempotent, and the cheapest
requests the API serves. Charging them against an abuse budget protects nothing
and can deny a legitimate client the request it actually wanted.

## Why these tests build their own middleware

`tests/conftest.py` sets `RATE_LIMIT_ENABLED=false` for the whole suite, so a
test hitting the shared `client` fixture would pass whether or not the exemption
exists - it would be asserting nothing. These therefore wrap the real app in an
*enabled* `RateLimitMiddleware` with a deliberately tiny budget, so "not rate
limited" is a claim the test can actually make and a regression can actually
break.
"""

import pytest
from httpx import ASGITransport, AsyncClient

WRITE_PATH = "/api/v1/comments"  # non-GET, non-auth -> STRICT bucket
TINY_LIMIT = 3


@pytest.fixture
def limited_client(monkeypatch):
    """The real app behind a rate limiter with a budget of three requests.

    Both buckets are shrunk because they are reached by different methods:
    `GET` returns before the limiter, so of the methods that survive to it,
    `OPTIONS` lands in GENERAL and a state-changing verb lands in STRICT.
    Shrinking only one would leave the preflight path on the default 60/min
    allowance - large enough that a 30-request burst never trips it, and the
    test would pass with the bug present.
    """
    from app.api.middleware import RateLimitMiddleware
    from app.app import app
    from app.config import settings
    from app.services.rate_limit_service import LimitType, RateLimitService

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setitem(RateLimitService._LIMITS, LimitType.STRICT, (TINY_LIMIT, 60))
    monkeypatch.setitem(RateLimitService._LIMITS, LimitType.GENERAL, (TINY_LIMIT, 60))

    return RateLimitMiddleware(app=app, enabled=True)


async def _call(client: AsyncClient, method: str, path: str) -> int:
    headers = {
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    }
    if method == "OPTIONS":
        return (await client.options(path, headers=headers)).status_code
    return (await client.post(path, json={}, headers={"Origin": "http://localhost:3000"})).status_code


@pytest.mark.asyncio
async def test_preflight_is_never_rate_limited(limited_client):
    """Far more preflights than the budget, all answered.

    The claim under test is that preflights are not counted *at all*, so this
    uses a volume well past the limit. A preflight that eventually 429s is still
    the original bug, however generous the limit that let it through.
    """
    async with AsyncClient(
        transport=ASGITransport(app=limited_client), base_url="http://test"
    ) as client:
        statuses = {(await _call(client, "OPTIONS", WRITE_PATH)) for _ in range(30)}

    assert statuses == {200}, f"preflight was rate limited: {statuses}"


@pytest.mark.asyncio
async def test_preflight_burst_does_not_consume_the_budget(limited_client):
    """A preflight burst must leave the user's next write affordable.

    This is the user-visible half of the bug. Before the fix, preflights were
    the *only* traffic that reached the GENERAL bucket - `GET` returns before the
    limiter, so the bucket's entire 60/minute allowance was spent on requests
    the browser generated and the user never issued. A dashboard, or a couple of
    open tabs, could exhaust it in normal use, and once it was gone every
    cross-origin call in the application failed on a preflight the client never
    meant to send.
    """
    async with AsyncClient(
        transport=ASGITransport(app=limited_client), base_url="http://test"
    ) as client:
        for _ in range(30):
            await _call(client, "OPTIONS", WRITE_PATH)
        status = await _call(client, "POST", WRITE_PATH)

    assert status != 429, (
        "the preflight burst exhausted the client's write budget - the real "
        "request was denied by traffic the client never chose to send"
    )


@pytest.mark.asyncio
async def test_writes_are_still_rate_limited(limited_client):
    """The exemption must not have disabled the limiter.

    A test that only proves the exemption works is satisfied just as well by a
    limiter that is off entirely. This pins the other half: real writes are
    still counted, so the abuse protection the middleware exists for survives.
    """
    async with AsyncClient(
        transport=ASGITransport(app=limited_client), base_url="http://test"
    ) as client:
        statuses = [(await _call(client, "POST", WRITE_PATH)) for _ in range(TINY_LIMIT + 3)]

    assert 429 in statuses, (
        f"writes were never limited ({statuses}) - excluding OPTIONS has taken "
        "rate limiting down with it"
    )
    assert statuses[:TINY_LIMIT] != [429] * TINY_LIMIT, (
        "the limiter rejected requests before exhausting the budget"
    )