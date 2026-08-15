"""Tests for trades, comments, alerts, notifications, referrals, disputes, flags."""
import pytest

from httpx import AsyncClient


def _token(user_id: str) -> str:
    from app.deps import create_access_token
    t, _ = create_access_token(str(user_id))
    return t


# ── Trades ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_trades(client: AsyncClient, test_market):
    resp = await client.get("/api/v1/trades")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "trades" in data["data"]


@pytest.mark.asyncio
async def test_list_trades_by_market(client: AsyncClient, test_market):
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/trades")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Comments ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_comment(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "This is a test comment!"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["data"]["content"] == "This is a test comment!"


@pytest.mark.asyncio
async def test_create_comment_unauthenticated(client: AsyncClient, test_market):
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Unauthorized comment"},
    )
    assert resp.status_code == 401
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_list_comments(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    # Create a comment first
    await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "First comment"},
    )
    resp = await client.get(f"/api/v1/markets/{test_market.slug}/comments")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert len(data["data"]["comments"]) >= 1


@pytest.mark.asyncio
async def test_edit_comment(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    create_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Original content"},
    )
    comment_id = create_resp.json()["data"]["id"]

    resp = await client.patch(
        f"/api/v1/markets/{test_market.slug}/comments/{comment_id}",
        json={"content": "Edited content"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == "Edited content"


@pytest.mark.asyncio
async def test_delete_comment(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    create_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "To be deleted"},
    )
    comment_id = create_resp.json()["data"]["id"]

    resp = await client.delete(
        f"/api/v1/markets/{test_market.slug}/comments/{comment_id}",
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_comment_not_found_market(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        "/api/v1/markets/nonexistent/comments",
        json={"content": "Comment on nothing"},
    )
    assert resp.status_code == 404
    assert resp.json()["success"] is False


# ── Alerts ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_alert(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/alerts/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "condition": "above",
        "trigger_price": 0.7,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


@pytest.mark.asyncio
async def test_create_alert_invalid_price(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/alerts/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "condition": "above",
        "trigger_price": 1.5,  # Out of range
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_list_alerts(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/alerts/")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_delete_alert(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    # Create alert
    create_resp = await client.post("/api/v1/alerts/", json={
        "market_id": str(test_market.id),
        "outcome": "yes",
        "condition": "above",
        "trigger_price": 0.7,
    })
    alert_id = create_resp.json()["data"]["id"]

    # Delete it
    resp = await client.delete(f"/api/v1/alerts/{alert_id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Notifications ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_notification_preferences(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/notifications/preferences")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_update_notification_preferences(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.put("/api/v1/notifications/preferences", json={
        "email_alerts": False,
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_list_notifications(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_mark_notification_read(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        "/api/v1/notifications/00000000-0000-0000-0000-000000000000/read",
    )
    # Should return success even if not found (idempotent behavior) OR not found error
    assert resp.status_code in (200, 404)


# ── Referrals ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_referral_code(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/referrals/code")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "referral_code" in data["data"]


@pytest.mark.asyncio
async def test_get_referral_stats(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/referrals/stats")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Flags ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flag_market(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Inappropriate content",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_flag_market_duplicate(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Duplicate flag",
    })

    resp = await client.post("/api/v1/flags", json={
        "market_id": str(test_market.id),
        "reason": "Second flag",
    })
    assert resp.status_code == 422
    assert resp.json()["success"] is False


# ── Disputes ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_propose_resolution(client: AsyncClient, admin_user, test_market, db_session):
    """Admin can propose resolution, opening a dispute window."""
    client.cookies.set("access_token", _token(admin_user.id))
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")

    resp = await client.post("/api/v1/disputes/propose-resolution", json={
        "market_id": str(test_market.id),
        "outcome_id": str(outcome.id),
        "resolution_source": "https://example.com/result",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_create_dispute(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """User can file a dispute on resolved market."""
    # First resolve the market
    outcome = next(o for o in test_market.outcomes if o.name == "Yes")
    client.cookies.set("access_token", _token(admin_user.id))
    await client.post(f"/api/v1/markets/{test_market.slug}/resolve", json={
        "winning_outcome_id": str(outcome.id),
    })

    # Then file dispute
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/disputes", json={
        "market_id": str(test_market.id),
        "evidence": "The resolution was incorrect",
        "evidence_url": "https://example.com/proof",
    })
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_disputes_for_market(client: AsyncClient, test_user, test_market):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/disputes/market/{test_market.id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


# ── Nested comments ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_reply_to_comment(client: AsyncClient, admin_user, test_market):
    """User can reply to a top-level comment (depth=1)."""
    client.cookies.set("access_token", _token(admin_user.id))
    # First create a top-level comment
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Top level comment"},
    )
    assert c_resp.status_code == 200
    comment_id = c_resp.json()["data"]["id"]

    # Post a reply
    r_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "A reply", "parent_id": comment_id},
    )
    assert r_resp.status_code == 200
    data = r_resp.json()["data"]
    assert data["parent_id"] == comment_id
    assert data["depth"] == 1


@pytest.mark.asyncio
async def test_create_nested_reply_depth_2(client: AsyncClient, admin_user, test_market):
    """Replies can be nested up to MAX_DEPTH=3."""
    client.cookies.set("access_token", _token(admin_user.id))
    # Create chain: comment -> reply (depth 1) -> reply (depth 2)
    c1 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L0"})).json()["data"]
    c2 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L1", "parent_id": c1["id"]})).json()["data"]
    c3 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L2", "parent_id": c2["id"]})).json()["data"]
    assert c3["depth"] == 2


@pytest.mark.asyncio
async def test_create_reply_depth_limit_exceeded(client: AsyncClient, admin_user, test_market):
    """Replies beyond MAX_DEPTH=3 are rejected."""
    client.cookies.set("access_token", _token(admin_user.id))
    c1 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L0"})).json()["data"]
    c2 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L1", "parent_id": c1["id"]})).json()["data"]
    c3 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L2", "parent_id": c2["id"]})).json()["data"]
    c4 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L3", "parent_id": c3["id"]})).json()["data"]
    # c4 is depth=3 (MAX_DEPTH) — the deepest allowed reply
    assert c4["depth"] == 3
    # r5 is depth=4 — exceeds limit, must be rejected
    r5 = await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L4", "parent_id": c4["id"]})
    assert r5.status_code == 422


@pytest.mark.asyncio
async def test_get_replies(client: AsyncClient, admin_user, test_market):
    """get_replies endpoint returns paginated replies to a comment."""
    client.cookies.set("access_token", _token(admin_user.id))
    c1 = (await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "L0"})).json()["data"]
    await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "R1", "parent_id": c1["id"]})
    await client.post(f"/api/v1/markets/{test_market.slug}/comments", json={"content": "R2", "parent_id": c1["id"]})

    r = await client.get(f"/api/v1/markets/{test_market.slug}/comments/{c1['id']}/replies")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["replies"][0]["content"] == "R1"
    assert data["replies"][1]["content"] == "R2"


@pytest.mark.asyncio
async def test_get_replies_not_found(client: AsyncClient, test_market):
    """get_replies returns empty list for non-existent comment (no validation)."""
    import uuid
    r = await client.get(f"/api/v1/markets/{test_market.slug}/comments/{uuid.uuid4()}/replies")
    assert r.status_code == 200
    assert r.json()["data"]["replies"] == []


# ── Treasury ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_treasury(client: AsyncClient):
    resp = await client.get("/api/v1/treasury")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_get_treasury_logs(client: AsyncClient, test_user):
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get("/api/v1/treasury/logs")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


@pytest.mark.asyncio
async def test_distribute_fees_admin_only(client: AsyncClient, admin_user, test_user):
    """Only admins can distribute fees."""
    # Non-admin should be forbidden
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/treasury/distribute?amount=10")
    assert resp.status_code == 403
    assert resp.json()["success"] is False

    # Admin should succeed (or fail on insufficient balance)
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post("/api/v1/treasury/distribute?amount=10")
    # Success or validation error due to balance
    assert resp.status_code in (200, 422)


# ── Comment edge cases ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_comment_parent_on_different_market(client: AsyncClient, admin_user, test_market, db_session):
    """parent_id referencing a comment on a different market is rejected."""
    import uuid
    from app.models.comment import Comment
    from app.models.market import Market, Outcome
    from datetime import datetime, timezone

    # Create a comment on a second market
    m2 = Market(
        slug=f"other-{uuid.uuid4().hex[:8]}",
        question="Other market",
        description="Other",
        category="test",
        status="active",
        created_by=admin_user.id,
        closes_at=datetime(2099, 12, 31, tzinfo=timezone.utc),
    )
    db_session.add(m2)
    await db_session.flush()
    Outcome(market_id=m2.id, name="Yes", outcome_index=0)
    Outcome(market_id=m2.id, name="No", outcome_index=1)
    await db_session.commit()

    # Comment on the OTHER market
    other_comment = Comment(
        market_id=m2.id,
        user_id=admin_user.id,
        content="On other market",
        depth=0,
    )
    db_session.add(other_comment)
    await db_session.commit()
    await db_session.refresh(other_comment)

    # Try to reply to it from test_market
    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Reply to other market's comment", "parent_id": str(other_comment.id)},
    )
    assert resp.status_code == 422
    assert resp.json()["success"] is False


@pytest.mark.asyncio
async def test_create_comment_empty_content(client: AsyncClient, test_user, test_market):
    """Empty content is rejected by schema validation."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": ""},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_comment_content_too_long(client: AsyncClient, test_user, test_market):
    """Content exceeding max length is rejected."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "x" * 10000},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_edit_comment_by_non_owner(client: AsyncClient, test_user, admin_user, test_market, db_session):
    """Editing someone else's comment returns 403."""
    from app.models.comment import Comment

    # admin creates a comment
    client.cookies.set("access_token", _token(admin_user.id))
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Original"},
    )
    comment_id = c_resp.json()["data"]["id"]

    # test_user tries to edit it
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.patch(
        f"/api/v1/markets/{test_market.slug}/comments/{comment_id}",
        json={"content": "Hacked!"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_edit_comment_already_deleted(client: AsyncClient, test_user, test_market):
    """Editing a soft-deleted comment is rejected."""
    client.cookies.set("access_token", _token(test_user.id))
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "To be deleted"},
    )
    comment_id = c_resp.json()["data"]["id"]

    # Soft-delete it
    await client.delete(f"/api/v1/markets/{test_market.slug}/comments/{comment_id}")

    # Try to edit
    resp = await client.patch(
        f"/api/v1/markets/{test_market.slug}/comments/{comment_id}",
        json={"content": "Should fail"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_comment_soft_delete_flag(client: AsyncClient, test_user, test_market, db_session):
    """Soft-delete sets is_deleted=True and hides content from list."""
    from app.models.comment import Comment
    from sqlalchemy import select

    client.cookies.set("access_token", _token(test_user.id))
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Will be soft-deleted"},
    )
    comment_id = c_resp.json()["data"]["id"]

    resp = await client.delete(f"/api/v1/markets/{test_market.slug}/comments/{comment_id}")
    assert resp.status_code == 200

    # Verify is_deleted flag in DB
    result = await db_session.execute(select(Comment).where(Comment.id == comment_id))
    comment = result.scalar_one()
    assert comment.is_deleted is True

    # Verify it's still returned in list with is_deleted=True (soft-delete, not hard-delete)
    list_resp = await client.get(f"/api/v1/markets/{test_market.slug}/comments")
    comments = list_resp.json()["data"]["comments"]
    deleted = next((c for c in comments if c["id"] == comment_id), None)
    assert deleted is not None, "Deleted comment should still be in list"
    assert deleted["is_deleted"] is True


@pytest.mark.asyncio
async def test_delete_comment_by_non_owner(client: AsyncClient, test_user, admin_user, test_market):
    """Deleting someone else's comment returns 403."""
    client.cookies.set("access_token", _token(admin_user.id))
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Admin comment"},
    )
    comment_id = c_resp.json()["data"]["id"]

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.delete(f"/api/v1/markets/{test_market.slug}/comments/{comment_id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_delete_comment_already_deleted(client: AsyncClient, test_user, test_market):
    """Deleting an already-deleted comment handles gracefully."""
    client.cookies.set("access_token", _token(test_user.id))
    c_resp = await client.post(
        f"/api/v1/markets/{test_market.slug}/comments",
        json={"content": "Delete me twice"},
    )
    comment_id = c_resp.json()["data"]["id"]

    await client.delete(f"/api/v1/markets/{test_market.slug}/comments/{comment_id}")
    # Soft-delete is idempotent — second delete returns 200 (comment found but already deleted)
    resp = await client.delete(f"/api/v1/markets/{test_market.slug}/comments/{comment_id}")
    assert resp.status_code == 200


# ── Flags edge cases ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_market_flags_admin(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """GET /flags/market/{market_id} returns flags for a market (admin only)."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.get(f"/api/v1/flags/market/{test_market.id}")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_get_market_flags_non_admin_forbidden(client: AsyncClient, test_user, test_market):
    """Non-admin cannot view flags."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.get(f"/api/v1/flags/market/{test_market.id}")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_resolve_flag_admin(client: AsyncClient, admin_user, test_user, test_market, db_session):
    """PATCH /flags/{flag_id}/resolve allows admin to resolve a flag."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(admin_user.id))
    resp = await client.patch(
        f"/api/v1/flags/{flag.id}/resolve",
        json={"status": "dismissed"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "dismissed"


@pytest.mark.asyncio
async def test_resolve_flag_non_admin_forbidden(client: AsyncClient, test_user, test_market, db_session):
    """Non-admin cannot resolve flags."""
    from app.models.flag import MarketFlag

    flag = MarketFlag(market_id=test_market.id, user_id=test_user.id, reason="Spam")
    db_session.add(flag)
    await db_session.commit()
    await db_session.refresh(flag)

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.patch(
        f"/api/v1/flags/{flag.id}/resolve",
        json={"status": "dismissed"},
    )
    assert resp.status_code == 403


# ── Disputes edge cases ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_adjudicate_dispute_admin_only(client: AsyncClient, test_user, test_market, db_session):
    """Adjudicating a dispute requires admin_user (non-admin gets 403)."""
    from app.models.dispute import Dispute

    dispute = Dispute(
        market_id=test_market.id,
        user_id=test_user.id,
        evidence="Test evidence",
    )
    db_session.add(dispute)
    await db_session.commit()
    await db_session.refresh(dispute)

    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post(
        f"/api/v1/disputes/{dispute.id}/adjudicate",
        json={"ruling": "dismissed"},
    )
    assert resp.status_code == 403


# ── Notifications edge cases ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mark_all_notifications_read(client: AsyncClient, test_user):
    """POST /notifications/read-all marks all notifications as read."""
    client.cookies.set("access_token", _token(test_user.id))
    resp = await client.post("/api/v1/notifications/read-all")
    assert resp.status_code == 200
    assert resp.json()["success"] is True
