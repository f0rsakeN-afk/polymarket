"""Tests for the admin user list: state filter, ordering, and stable pagination.

Separated from `test_admin.py` because the concerns are distinct: the basic list
endpoint is covered there, and what follows is the behaviour that lets an
operator answer a question rather than just read a list.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from conftest import token_for
from httpx import AsyncClient

from app.deps import hash_password
from app.models.user import User


async def _make_user(
    db_session,
    *,
    email: str | None = None,
    username: str | None = None,
    is_admin: bool = False,
    is_active: bool = True,
    is_email_verified: bool = True,
    banned: bool = False,
    created_at: datetime | None = None,
) -> str:
    """Create a user and return its id as a string.

    The id is stringified before the commit on purpose: after `commit()` the
    instance is expired, and reading `.id` re-emits a SELECT per attribute -
    which is how a test ends up asserting against a detached instance.
    """
    uid = uuid4().hex[:8]
    user = User(
        email=email or f"user_{uid}@example.com",
        username=username or f"user_{uid}",
        password_hash=hash_password("User!Pass1"),
        is_active=is_active,
        is_admin=is_admin,
        is_email_verified=is_email_verified,
    )
    if banned:
        # `banned_at` rather than `is_active`: the list filter distinguishes a
        # banned account from a merely deactivated one, and so must the fixture.
        user.banned_at = datetime.now(UTC)
        user.ban_reason = "Test fixture"
        user.is_active = False
    if created_at is not None:
        user.created_at = created_at
    db_session.add(user)
    await db_session.flush()
    return str(user.id)


# ── Status filter ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_status_banned_returns_only_banned(
    client: AsyncClient, db_session, admin_user, test_user
):
    banned_id = await _make_user(db_session, banned=True)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=banned&page_size=100")

    assert resp.status_code == 200
    emails = {u["email"] for u in resp.json()["data"]}
    assert banned_id  # the fixture really created something
    assert len(emails) >= 1
    assert test_user.email not in emails


@pytest.mark.asyncio
async def test_status_banned_excludes_active_users(
    client: AsyncClient, db_session, admin_user, test_user
):
    """The filter must be a filter, not a hint.

    A response that quietly included everyone would still let an operator find
    the banned account, and would fail silently at exactly the moment it was
    needed.
    """
    await _make_user(db_session, banned=True)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=banned&page_size=100")

    returned = {u["id"] for u in resp.json()["data"]}
    assert str(test_user.id) not in returned
    assert str(admin_user.id) not in returned


@pytest.mark.asyncio
async def test_status_active_excludes_banned(
    client: AsyncClient, db_session, admin_user, test_user
):
    banned_id = await _make_user(db_session, banned=True)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=active&page_size=100")

    returned = {u["id"] for u in resp.json()["data"]}
    assert banned_id not in returned
    assert str(test_user.id) in returned


@pytest.mark.asyncio
async def test_status_admins(client: AsyncClient, db_session, admin_user, test_user):
    other_admin = await _make_user(db_session, is_admin=True)
    await _make_user(db_session)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=admins&page_size=100")

    returned = {u["id"] for u in resp.json()["data"]}
    assert other_admin in returned
    assert str(admin_user.id) in returned
    assert str(test_user.id) not in returned


@pytest.mark.asyncio
async def test_status_unverified(client: AsyncClient, db_session, admin_user, test_user):
    unverified = await _make_user(db_session, is_email_verified=False)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=unverified&page_size=100")

    returned = {u["id"] for u in resp.json()["data"]}
    assert unverified in returned
    assert str(test_user.id) not in returned


@pytest.mark.asyncio
async def test_status_default_is_all(client: AsyncClient, db_session, admin_user, test_user):
    await _make_user(db_session, banned=True)

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?page_size=100")

    returned = {u["id"] for u in resp.json()["data"]}
    assert str(test_user.id) in returned
    assert str(admin_user.id) in returned


@pytest.mark.asyncio
async def test_status_rejects_unknown_value(client: AsyncClient, admin_user):
    """An unrecognised filter is refused, not silently treated as `all`.

    Falling back to "everyone" would turn a typo in a bookmarked URL into a list
    that looks filtered and is not.
    """
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?status=nonsense")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_sort_rejects_unknown_value(client: AsyncClient, admin_user):
    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?sort=nonsense")
    assert resp.status_code == 422


# ── Counts follow the filter ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_total_reflects_the_filter_not_the_whole_table(
    client: AsyncClient, db_session, admin_user, test_user
):
    """`total` drives the pagination, so a filter-blind count is a lie.

    The operator is told page 1 of 3 while holding 3 rows, and has no way to
    learn that the other 200 accounts exist.
    """
    await _make_user(db_session, banned=True)

    client.cookies.set("access_token", token_for(admin_user.id))
    filtered = await client.get("/api/v1/admin/users?status=banned&page_size=100")
    unfiltered = await client.get("/api/v1/admin/users?page_size=100")

    filtered_total = filtered.json()["total"]
    unfiltered_total = unfiltered.json()["total"]

    assert filtered_total == len(filtered.json()["data"])
    assert unfiltered_total > filtered_total


# ── Ordering ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sort_by_email(client: AsyncClient, db_session, admin_user):
    await _make_user(db_session, email="zzz_sort@example.com")
    await _make_user(db_session, email="aaa_sort@example.com")

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get("/api/v1/admin/users?sort=email&page_size=100")

    emails = [u["email"] for u in resp.json()["data"]]
    assert emails == sorted(emails)


@pytest.mark.asyncio
async def test_sort_newest_and_oldest_are_opposites(
    client: AsyncClient, db_session, admin_user
):
    now = datetime.now(UTC)
    await _make_user(db_session, created_at=now - timedelta(days=2))
    await _make_user(db_session, created_at=now - timedelta(days=1))

    client.cookies.set("access_token", token_for(admin_user.id))
    newest = await client.get("/api/v1/admin/users?sort=newest&page_size=100")
    oldest = await client.get("/api/v1/admin/users?sort=oldest&page_size=100")

    assert [u["id"] for u in newest.json()["data"]] == [
        u["id"] for u in reversed(oldest.json()["data"])
    ]


# ── Pagination stability ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pagination_is_stable_when_created_at_ties(
    client: AsyncClient, db_session, admin_user
):
    """Rows sharing a `created_at` must not be repeated or dropped across pages.

    Bulk imports and seed data produce identical timestamps. Without a tiebreak
    the database is free to return the same row on page 1 and page 2 and skip
    another entirely, so the list looks correct while quietly losing accounts -
    and an operator paging through a queue never sees some of them.
    """
    stamp = datetime.now(UTC)
    created = {
        await _make_user(db_session, created_at=stamp) for _ in range(7)
    }

    client.cookies.set("access_token", token_for(admin_user.id))
    seen: list[str] = []
    for page in (1, 2, 3, 4):
        resp = await client.get(f"/api/v1/admin/users?sort=newest&page={page}&page_size=2")
        seen.extend(u["id"] for u in resp.json()["data"])

    # No duplicates, and nothing lost.
    assert len(seen) == len(set(seen)), "a row was repeated across pages"
    assert set(created) <= set(seen), "a tied row never appeared"


@pytest.mark.asyncio
async def test_filter_and_pagination_agree(
    client: AsyncClient, db_session, admin_user, test_user
):
    """Page 2 of a filtered list must stay inside the filter.

    Off-by-one scope leaks here show a banned account inside an "active" result,
    which is how an operator ends up acting on the wrong row.
    """
    banned_ids = {await _make_user(db_session, banned=True) for _ in range(3)}
    await _make_user(db_session)

    client.cookies.set("access_token", token_for(admin_user.id))
    for page in (1, 2):
        resp = await client.get(f"/api/v1/admin/users?status=banned&page={page}&page_size=2")
        returned = {u["id"] for u in resp.json()["data"]}
        assert returned <= banned_ids


@pytest.mark.asyncio
async def test_search_and_filter_combine(
    client: AsyncClient, db_session, admin_user
):
    await _make_user(
        db_session, email="needle_banned@example.com", banned=True
    )
    await _make_user(db_session, email="needle_active@example.com")

    client.cookies.set("access_token", token_for(admin_user.id))
    resp = await client.get(
        "/api/v1/admin/users?search=needle&status=banned&page_size=100"
    )

    emails = {u["email"] for u in resp.json()["data"]}
    assert emails == {"needle_banned@example.com"}


@pytest.mark.asyncio
async def test_filters_require_admin(client: AsyncClient, test_user):
    """The filters must not become an enumeration oracle for ordinary users.

    Authenticated as a non-admin on purpose. An unauthenticated request proves
    nothing here - it would be refused at the door before the filter was ever
    read, which is the same answer for every query string.
    """
    client.cookies.set("access_token", token_for(test_user.id))
    for query in ("status=banned", "status=admins", "status=unverified", "sort=email"):
        resp = await client.get(f"/api/v1/admin/users?{query}")
        assert resp.status_code == 403, f"{query} was reachable by a non-admin"
