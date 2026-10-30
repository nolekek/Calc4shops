import uuid
import pytest
from datetime import timedelta
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.db.database import init_db, async_session
from app.core.subscription import (
    get_or_create_subscription,
    check_subscription_active,
    generate_activation_keys,
    activate_subscription_key,
    grant_subscription_manual,
    _get_utc_now,
)
from app.config import settings


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_trial_creation_and_activation():
    test_user = f"sub_user_{uuid.uuid4().hex[:8]}"

    async with async_session() as db:
        # 1. New user gets trial
        sub = await get_or_create_subscription(db, test_user)
        assert sub.status == "trial"
        assert sub.expires_at > _get_utc_now()

        # Check active
        is_active, current_sub = await check_subscription_active(db, test_user)
        assert is_active is True
        assert current_sub.status == "trial"

        # 2. Generate key
        keys = await generate_activation_keys(db, count=1, duration_days=30)
        assert len(keys) == 1
        key = keys[0]
        assert key.startswith("AUDIT-")

        # 3. Activate key
        prev_expires = current_sub.expires_at
        success, msg, new_expires = await activate_subscription_key(db, test_user, key)
        assert success is True
        assert "успешно активирован" in msg
        assert new_expires is not None
        # Should extend past previous expires_at by 30 days
        diff = (new_expires - prev_expires).total_seconds()
        assert abs(diff - 30 * 86400) < 10

        # 4. Attempt to reuse key should fail
        reuse_success, reuse_msg, _ = await activate_subscription_key(db, test_user, key)
        assert reuse_success is False
        assert "уже был активирован" in reuse_msg

        # 5. Invalid key should fail
        bad_success, bad_msg, _ = await activate_subscription_key(db, test_user, "INVALID-KEY-1234")
        assert bad_success is False
        assert "не найден" in bad_msg


@pytest.mark.asyncio
async def test_admin_bypass_and_grant():
    admin_id = "admin_super_user"
    settings.ADMIN_IDS = f"{admin_id},other_admin"

    async with async_session() as db:
        # Admin is always active
        is_active, sub = await check_subscription_active(db, admin_id)
        assert is_active is True
        assert sub.status == "admin"

        # Manual grant
        regular_user = f"reg_user_{uuid.uuid4().hex[:8]}"
        granted_sub = await grant_subscription_manual(db, regular_user, days=60)
        assert granted_sub.status == "active"
        assert granted_sub.expires_at > _get_utc_now() + timedelta(days=59)


@pytest.mark.asyncio
async def test_subscription_api_endpoints():
    test_user = f"api_user_{uuid.uuid4().hex[:8]}"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Check initial status (creates trial)
        resp = await client.get(f"/api/subscription/status?user_id={test_user}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["user_id"] == test_user
        assert data["active"] is True
        assert data["status"] == "trial"

        # Generate a key directly in DB
        async with async_session() as db:
            keys = await generate_activation_keys(db, count=1, duration_days=30)
            key = keys[0]

        # Activate via API
        act_resp = await client.post("/api/subscription/activate", json={
            "user_id": test_user,
            "key": key
        })
        assert act_resp.status_code == 200
        act_data = act_resp.json()
        assert act_data["success"] is True

        # Check status again
        status_resp = await client.get(f"/api/subscription/status?user_id={test_user}")
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "active"
