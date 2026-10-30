import csv
import io
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.core.calculator import CalculationRequest, calculate_deal
from app.core.rates import rates_service


class BatchItemResult(BaseModel):
    index: int
    title: str
    cost_original: float
    currency: str
    currency_rate: float
    cost_rub: float
    price_rub: float
    platform_id: str
    tax_regime: str
    
    platform_fee: float
    payout_fee: float
    tax_amount: float
    net_profit: float
    margin_pct: float
    breakeven_price: float
    max_discount_rub: float
    
    verdict: str
    verdict_title: str
    recommendation: str


class BatchSummary(BaseModel):
    total_items: int
    profitable_count: int
    borderline_count: int
    unprofitable_count: int
    total_revenue: float
    total_cost_rub: float
    total_profit: float
    avg_margin_pct: float


class BatchAuditResponse(BaseModel):
    items: List[BatchItemResult]
    summary: BatchSummary


# Column aliases for flexible CSV ingestion
COLUMN_ALIASES = {
    "title": ["название", "наименование", "лот", "товар", "продукт", "title", "name", "item"],
    "cost": ["закупк", "себестоимост", "вход", "buy", "cost"],
    "price": ["продаж", "розниц", "витрин", "price", "sell", "цена"],
    "currency": ["валют", "currency", "curr", "valute"],
    "platform": ["площадк", "маркетплейс", "бирж", "рынок", "platform"],
    "tax": ["налог", "tax"],
}

SAMPLE_BATCH_ROWS = [
    {
        "title": "Telegram Premium 1 год",
        "cost": 289.0,
        "currency": "TRY",
        "price": 1850.0,
        "platform": "plati",
        "tax": "npd_6",
    },
    {
        "title": "PS Plus Deluxe 12 мес (Турция)",
        "cost": 2740.0,
        "currency": "TRY",
        "price": 11500.0,
        "platform": "playerok",
        "tax": "npd_6",
    },
    {
        "title": "Steam Gift Card $20",
        "cost": 18.5,
        "currency": "USD",
        "price": 2250.0,
        "platform": "plati",
        "tax": "npd_6",
    },
    {
        "title": "Spotify Premium 12 мес",
        "cost": 420.0,
        "currency": "TRY",
        "price": 2100.0,
        "platform": "funpay",
        "tax": "npd_6",
    },
    {
        "title": "Windows 11 Pro OEM Key",
        "cost": 240.0,
        "currency": "RUB",
        "price": 320.0,
        "platform": "plati",
        "tax": "npd_6",
    },
]


def detect_delimiter(sample_text: str) -> str:
    for delim in [";", ",", "\t"]:
        if delim in sample_text.splitlines()[0]:
            return delim
    return ";"


def match_column(header_col: str) -> Optional[str]:
    clean = header_col.strip().lower()
    # 1. Exact match
    for field, aliases in COLUMN_ALIASES.items():
        if clean in aliases:
            return field
    # 2. Substring match
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in clean:
                return field
    return None


def parse_csv_content(content_bytes: bytes) -> List[Dict[str, Any]]:
    # Try multiple encodings: utf-8, utf-8-sig, cp1251
    text = None
    for enc in ["utf-8-sig", "utf-8", "cp1251"]:
        try:
            text = content_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if not text:
        text = content_bytes.decode("utf-8", errors="replace")

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    delimiter = detect_delimiter(lines[0])
    reader = csv.reader(lines, delimiter=delimiter)
    headers = next(reader, None)
    if not headers:
        return []

    # Map header positions to known fields
    col_map: Dict[int, str] = {}
    for idx, col in enumerate(headers):
        matched = match_column(col)
        if matched:
            col_map[idx] = matched

    parsed_rows = []
    for line_idx, row in enumerate(reader, start=1):
        if not row or not any(row):
            continue
        row_dict: Dict[str, Any] = {
            "title": f"Лот #{line_idx}",
            "cost": 0.0,
            "currency": "RUB",
            "price": 0.0,
            "platform": "plati",
            "tax": "npd_6",
        }
        for idx, val in enumerate(row):
            if idx in col_map:
                field = col_map[idx]
                val_clean = val.strip()
                if field in ["cost", "price"]:
                    try:
                        # Replace comma with dot for Russian float parsing
                        val_num = float(val_clean.replace(" ", "").replace(",", "."))
                        row_dict[field] = max(0.0, val_num)
                    except ValueError:
                        row_dict[field] = 0.0
                elif field in ["currency", "platform", "tax", "title"]:
                    if val_clean:
                        row_dict[field] = val_clean

        if row_dict["price"] > 0 or row_dict["cost"] > 0:
            parsed_rows.append(row_dict)

    return parsed_rows


async def audit_batch_items(raw_items: List[Dict[str, Any]]) -> BatchAuditResponse:
    results: List[BatchItemResult] = []

    # Pre-fetch exchange rates
    rates = await rates_service.get_rates()

    total_revenue = 0.0
    total_cost_rub = 0.0
    total_profit = 0.0
    profitable_count = 0
    borderline_count = 0
    unprofitable_count = 0

    for idx, item in enumerate(raw_items, start=1):
        title = item.get("title", f"Лот #{idx}")
        cost_orig = float(item.get("cost", 0.0))
        currency = str(item.get("currency", "RUB")).upper()
        price = float(item.get("price", 0.0))
        platform = str(item.get("platform", "plati")).lower()
        tax = str(item.get("tax", "npd_6")).lower()

        # Resolve currency rate
        rate = 1.0
        if currency in rates:
            rate = rates[currency].rate_to_rub

        calc_req = CalculationRequest(
            cost_original=cost_orig,
            currency=currency,
            currency_rate=rate,
            price=max(1.0, price),
            platform_id=platform,
            tax_regime=tax,
            target_margin_pct=20.0
        )
        res = calculate_deal(calc_req)

        # Accumulate stats
        total_revenue += res.gross_revenue
        total_cost_rub += res.cost_rub
        total_profit += res.net_profit

        if res.verdict == "profitable":
            profitable_count += 1
        elif res.verdict == "borderline":
            borderline_count += 1
        else:
            unprofitable_count += 1

        results.append(
            BatchItemResult(
                index=idx,
                title=title,
                cost_original=cost_orig,
                currency=currency,
                currency_rate=rate,
                cost_rub=res.cost_rub,
                price_rub=res.gross_revenue,
                platform_id=platform,
                tax_regime=tax,
                platform_fee=res.platform_fee,
                payout_fee=res.payout_fee,
                tax_amount=res.tax_amount,
                net_profit=res.net_profit,
                margin_pct=res.margin_pct,
                breakeven_price=res.breakeven_price,
                max_discount_rub=res.max_discount_rub,
                verdict=res.verdict,
                verdict_title=res.verdict_title,
                recommendation=res.recommendation,
            )
        )

    avg_margin = round((total_profit / total_revenue) * 100.0, 2) if total_revenue > 0 else 0.0

    summary = BatchSummary(
        total_items=len(results),
        profitable_count=profitable_count,
        borderline_count=borderline_count,
        unprofitable_count=unprofitable_count,
        total_revenue=round(total_revenue, 2),
        total_cost_rub=round(total_cost_rub, 2),
        total_profit=round(total_profit, 2),
        avg_margin_pct=avg_margin,
    )

    return BatchAuditResponse(items=results, summary=summary)


def generate_csv_template() -> str:
    """Генерирует готовый образец CSV с 5 реальными товарами."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Название лота", "Закупка", "Валюта", "Цена продажи (₽)", "Площадка", "Налог"])
    for r in SAMPLE_BATCH_ROWS:
        writer.writerow([r["title"], r["cost"], r["currency"], r["price"], r["platform"], r["tax"]])
    return output.getvalue()


def export_audited_csv(items: List[BatchItemResult]) -> str:
    """Экспортирует проверенный прайс-лист со всеми расчетами в CSV для Excel."""
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "№",
        "Товар",
        "Закупка",
        "Валюта",
        "Курс к ₽",
        "Себестоимость ₽",
        "Цена продажи ₽",
        "Площадка",
        "Ком. площадки ₽",
        "Вывод ₽",
        "Налог ₽",
        "Чистая прибыль ₽",
        "Маржа %",
        "Безубыточность ₽",
        "Макс. скидка ₽",
        "Вердикт",
        "Рекомендация"
    ])
    for it in items:
        writer.writerow([
            it.index,
            it.title,
            it.cost_original,
            it.currency,
            it.currency_rate,
            it.cost_rub,
            it.price_rub,
            it.platform_id.upper(),
            it.platform_fee,
            it.payout_fee,
            it.tax_amount,
            it.net_profit,
            it.margin_pct,
            it.breakeven_price,
            it.max_discount_rub,
            it.verdict_title,
            it.recommendation
        ])
    return output.getvalue()
