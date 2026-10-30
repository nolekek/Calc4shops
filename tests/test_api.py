import uuid
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db.database import init_db


@pytest.fixture(autouse=True)
async def setup_db():
    await init_db()


@pytest.mark.asyncio
async def test_get_presets():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.json()
        assert "platforms" in data
        assert "tax_regimes" in data
        assert any(p["id"] == "plati" for p in data["platforms"])
        assert any(p["id"] == "playerok" for p in data["platforms"])


@pytest.mark.asyncio
async def test_get_rates():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/rates")
        assert resp.status_code == 200
        rates = resp.json()
        assert "RUB" in rates
        assert "TRY" in rates
        assert "USDT" in rates
        assert rates["RUB"]["rate_to_rub"] == 1.0
        assert rates["TRY"]["rate_to_rub"] > 0


@pytest.mark.asyncio
async def test_post_calculate_and_history():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uid = f"user_{uuid.uuid4().hex[:8]}"
        payload = {
            "user_id": uid,
            "cost_original": 500.0,
            "currency": "RUB",
            "currency_rate": 1.0,
            "price": 1000.0,
            "platform_id": "plati",
            "platform_fee_pct": 10.0,
            "payout_fee_pct": 2.0,
            "payout_fee_on_net": True,
            "tax_regime": "npd_6",
            "target_margin_pct": 20.0,
            "save_to_history": True
        }
        resp = await client.post("/api/calculate", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["net_profit"] == 322.0
        assert data["margin_pct"] == 32.2
        assert data["verdict"] == "profitable"

        # Check history endpoint
        hist_resp = await client.get(f"/api/history/{uid}")
        assert hist_resp.status_code == 200
        hist_data = hist_resp.json()
        assert len(hist_data) >= 1
        assert hist_data[0]["net_profit"] == 322.0


@pytest.mark.asyncio
async def test_reverse_calculate_endpoint():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "cost_original": 500.0,
            "currency": "RUB",
            "currency_rate": 1.0,
            "mode": "target_profit",
            "target_value": 322.0,
            "platform_id": "plati",
            "platform_fee_pct": 10.0,
            "payout_fee_pct": 2.0,
            "payout_fee_on_net": True,
            "tax_regime": "npd_6"
        }
        resp = await client.post("/api/calculate/reverse", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert abs(data["gross_revenue"] - 1000.0) < 1.0


@pytest.mark.asyncio
async def test_user_settings_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        uid = f"user_{uuid.uuid4().hex[:8]}"
        # 1. Get default settings
        resp = await client.get(f"/api/settings/{uid}")
        assert resp.status_code == 200
        assert resp.json()["default_platform"] == "plati"

        # 2. Save new settings
        update_payload = {
            "user_id": uid,
            "default_platform": "playerok",
            "default_tax_regime": "npd_4",
            "default_currency": "TRY",
            "target_margin_pct": 25.0,
            "custom_platform_fee_pct": 18.5,
            "custom_payout_fee_pct": 3.0,
            "custom_payout_fee_fixed": 50.0
        }
        save_resp = await client.post(f"/api/settings/{uid}", json=update_payload)
        assert save_resp.status_code == 200
        assert save_resp.json()["default_platform"] == "playerok"

        # 3. Read back
        read_resp = await client.get(f"/api/settings/{uid}")
        assert read_resp.status_code == 200
        assert read_resp.json()["default_platform"] == "playerok"
        assert read_resp.json()["target_margin_pct"] == 25.0

