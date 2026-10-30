import pytest
import io
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.batch_processor import (
    parse_csv_content,
    audit_batch_items,
    generate_csv_template,
    export_audited_csv,
    SAMPLE_BATCH_ROWS,
)


def test_parse_csv_russian_headers_and_commas():
    csv_raw = """Название лота;Закупка;Валюта;Цена продажи;Площадка;Налог
Telegram Premium 1 год;289,5;TRY;1850;plati;npd_6
Steam Gift Card $20;18,5;USD;2250;plati;npd_6
Убыточный ключ;950;RUB;1000;playerok;npd_6
"""
    items = parse_csv_content(csv_raw.encode("utf-8"))
    assert len(items) == 3
    assert items[0]["title"] == "Telegram Premium 1 год"
    assert items[0]["cost"] == 289.5
    assert items[0]["currency"] == "TRY"
    assert items[0]["price"] == 1850.0

    assert items[1]["cost"] == 18.5
    assert items[1]["currency"] == "USD"

    assert items[2]["platform"] == "playerok"


def test_parse_csv_comma_delimited():
    csv_raw = """name,cost,currency,price,platform
Spotify 12m,400,TRY,2000,funpay
PS Plus,2500,TRY,11000,playerok
"""
    items = parse_csv_content(csv_raw.encode("utf-8"))
    assert len(items) == 2
    assert items[0]["title"] == "Spotify 12m"
    assert items[0]["cost"] == 400.0


@pytest.mark.asyncio
async def test_audit_batch_items():
    res = await audit_batch_items(SAMPLE_BATCH_ROWS)
    assert res.summary.total_items == 5
    assert res.summary.total_revenue > 0
    assert res.summary.total_profit > 0
    assert len(res.items) == 5
    assert any(it.verdict == "unprofitable" or it.verdict == "borderline" for it in res.items)


def test_csv_template_and_export():
    template = generate_csv_template()
    assert "Название лота" in template
    assert "Telegram Premium" in template

    parsed = parse_csv_content(template.encode("utf-8"))
    assert len(parsed) == 5


@pytest.mark.asyncio
async def test_batch_api_endpoints():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 1. Template
        r_temp = await client.get("/api/batch/template")
        assert r_temp.status_code == 200
        assert "text/csv" in r_temp.headers["content-type"]
        assert len(r_temp.content) > 50

        # 2. Demo
        r_demo = await client.post("/api/batch/demo")
        assert r_demo.status_code == 200
        data = r_demo.json()
        assert data["summary"]["total_items"] == 5
        assert len(data["items"]) == 5

        # 3. Upload CSV
        csv_payload = generate_csv_template().encode("utf-8")
        files = {"file": ("test_lots.csv", io.BytesIO(csv_payload), "text/csv")}
        r_up = await client.post("/api/batch/upload-csv", files=files)
        assert r_up.status_code == 200
        up_data = r_up.json()
        assert up_data["summary"]["total_items"] == 5

        # 4. Export CSV
        r_export = await client.post("/api/batch/export-csv", json=up_data["items"])
        assert r_export.status_code == 200
        assert "text/csv" in r_export.headers["content-type"]
        assert "Чистая прибыль ₽" in r_export.text
