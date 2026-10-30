from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel

from app.db.database import get_db
from app.db.models import UserSetting, CalculationHistory
from app.core.presets import PLATFORMS, TAX_REGIMES
from app.core.rates import rates_service
from app.core.calculator import (
    CalculationRequest,
    CalculationResult,
    ReverseCalculationRequest,
    calculate_deal,
    calculate_reverse,
)
from app.core.batch_processor import (
    parse_csv_content,
    audit_batch_items,
    generate_csv_template,
    export_audited_csv,
    BatchAuditResponse,
    BatchItemResult,
    SAMPLE_BATCH_ROWS,
)
from app.core.subscription import (
    check_subscription_active,
    activate_subscription_key,
    _get_utc_now,
)
from app.config import settings
import httpx
from fastapi import UploadFile, File
from fastapi.responses import Response

router = APIRouter(prefix="/api", tags=["Calculator & Settings"])


class UserSettingsDTO(BaseModel):
    user_id: str
    default_platform: str = "plati"
    default_tax_regime: str = "npd_6"
    default_currency: str = "RUB"
    target_margin_pct: float = 20.0
    custom_platform_fee_pct: Optional[float] = None
    custom_payout_fee_pct: Optional[float] = None
    custom_payout_fee_fixed: Optional[float] = None


class CalculateDealPayload(CalculationRequest):
    user_id: Optional[str] = "web_guest"
    save_to_history: bool = True


class HistoryItemDTO(BaseModel):
    id: int
    platform_id: str
    cost_original: float
    currency: str
    currency_rate: float
    cost_rub: float
    price_rub: float
    net_profit: float
    margin_pct: float
    breakeven_price: float
    verdict: str
    verdict_title: str
    recommendation: str
    created_at: str


@router.get("/presets")
async def get_presets():
    """Возвращает предустановленные комиссии площадок и налоговые режимы."""
    return {
        "platforms": list(PLATFORMS.values()),
        "tax_regimes": list(TAX_REGIMES.values()),
    }


@router.get("/rates")
async def get_rates(force: bool = False):
    """Возвращает актуальные курсы валют к рублю (ЦБ РФ + USDT P2P)."""
    rates = await rates_service.get_rates(force_refresh=force)
    return rates


@router.post("/calculate", response_model=CalculationResult)
async def calculate_endpoint(
    payload: CalculateDealPayload,
    db: AsyncSession = Depends(get_db)
):
    """Мгновенный расчет сделки и сохранение в историю."""
    result = calculate_deal(payload)

    if payload.save_to_history and payload.user_id:
        record = CalculationHistory(
            user_id=payload.user_id,
            platform_id=payload.platform_id,
            cost_original=payload.cost_original,
            currency=payload.currency,
            currency_rate=payload.currency_rate,
            cost_rub=result.cost_rub,
            price_rub=result.gross_revenue,
            platform_fee=result.platform_fee,
            payout_fee=result.payout_fee,
            tax_amount=result.tax_amount,
            net_profit=result.net_profit,
            margin_pct=result.margin_pct,
            breakeven_price=result.breakeven_price,
            verdict=result.verdict,
            verdict_title=result.verdict_title,
            recommendation=result.recommendation,
        )
        db.add(record)
        await db.commit()

    return result


@router.post("/calculate/reverse", response_model=CalculationResult)
async def reverse_calculate_endpoint(
    payload: ReverseCalculationRequest,
):
    """Подбор цены продажи под желаемую чистую прибыль или маржинальность."""
    return calculate_reverse(payload)


@router.get("/settings/{user_id}", response_model=UserSettingsDTO)
async def get_user_settings(
    user_id: str,
    db: AsyncSession = Depends(get_db)
):
    """Получение сохраненных настроек пользователя."""
    stmt = select(UserSetting).where(UserSetting.user_id == user_id)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()

    if not setting:
        # Default settings
        return UserSettingsDTO(user_id=user_id)

    return UserSettingsDTO(
        user_id=setting.user_id,
        default_platform=setting.default_platform,
        default_tax_regime=setting.default_tax_regime,
        default_currency=setting.default_currency,
        target_margin_pct=setting.target_margin_pct,
        custom_platform_fee_pct=setting.custom_platform_fee_pct,
        custom_payout_fee_pct=setting.custom_payout_fee_pct,
        custom_payout_fee_fixed=setting.custom_payout_fee_fixed,
    )


@router.post("/settings/{user_id}", response_model=UserSettingsDTO)
async def save_user_settings(
    user_id: str,
    payload: UserSettingsDTO,
    db: AsyncSession = Depends(get_db)
):
    """Сохранение индивидуальных настроек комиссий и налогов пользователя."""
    stmt = select(UserSetting).where(UserSetting.user_id == user_id)
    res = await db.execute(stmt)
    setting = res.scalar_one_or_none()

    if not setting:
        setting = UserSetting(user_id=user_id)
        db.add(setting)

    setting.default_platform = payload.default_platform
    setting.default_tax_regime = payload.default_tax_regime
    setting.default_currency = payload.default_currency
    setting.target_margin_pct = payload.target_margin_pct
    setting.custom_platform_fee_pct = payload.custom_platform_fee_pct
    setting.custom_payout_fee_pct = payload.custom_payout_fee_pct
    setting.custom_payout_fee_fixed = payload.custom_payout_fee_fixed

    await db.commit()
    await db.refresh(setting)
    return payload


@router.get("/history/{user_id}", response_model=List[HistoryItemDTO])
async def get_user_history(
    user_id: str,
    limit: int = Query(default=10, le=50),
    db: AsyncSession = Depends(get_db)
):
    """Получение последних расчетов пользователя."""
    stmt = (
        select(CalculationHistory)
        .where(CalculationHistory.user_id == user_id)
        .order_by(desc(CalculationHistory.created_at))
        .limit(limit)
    )
    res = await db.execute(stmt)
    records = res.scalars().all()

    return [
        HistoryItemDTO(
            id=r.id,
            platform_id=r.platform_id,
            cost_original=r.cost_original,
            currency=r.currency,
            currency_rate=r.currency_rate,
            cost_rub=r.cost_rub,
            price_rub=r.price_rub,
            net_profit=r.net_profit,
            margin_pct=r.margin_pct,
            breakeven_price=r.breakeven_price,
            verdict=r.verdict,
            verdict_title=r.verdict_title,
            recommendation=r.recommendation,
            created_at=r.created_at.strftime("%d.%m %H:%M"),
        )
        for r in records
    ]


# --- BATCH / CSV PROCESSING ENDPOINTS ---

@router.get("/batch/template")
async def download_csv_template():
    """Скачать готовый CSV-шаблон для заполнения своих товаров."""
    csv_text = generate_csv_template()
    # Excel requires UTF-8 BOM (\ufeff) to display Cyrillic properly
    content = ("\ufeff" + csv_text).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=deal_auditor_template.csv"}
    )


@router.post("/batch/demo", response_model=BatchAuditResponse)
async def run_batch_demo():
    """Мгновенный аудит 5 демо-товаров без необходимости загружать файл."""
    return await audit_batch_items(SAMPLE_BATCH_ROWS)


@router.post("/batch/upload-csv", response_model=BatchAuditResponse)
async def upload_csv_batch(file: UploadFile = File(...)):
    """Загрузка CSV-файла с товарами и полный пакетный финансовый аудит."""
    contents = await file.read()
    items = parse_csv_content(contents)
    if not items:
        raise HTTPException(
            status_code=400,
            detail="Не удалось распознать строки товаров в файле. Скачайте шаблон для примера структуры."
        )
    return await audit_batch_items(items)


@router.post("/batch/export-csv")
async def export_batch_csv(items: List[BatchItemResult]):
    """Выгрузка рассчитанного аудита обратно в CSV-файл."""
    csv_text = export_audited_csv(items)
    content = ("\ufeff" + csv_text).encode("utf-8")
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=deal_auditor_report.csv"}
    )


class SubscriptionStatusDTO(BaseModel):
    user_id: str
    active: bool
    status: str
    plan_name: str
    expires_at: Optional[str]
    days_left: int


class ActivateKeyRequest(BaseModel):
    user_id: str
    key: str


@router.get("/subscription/status", response_model=SubscriptionStatusDTO)
async def get_subscription_status_endpoint(
    user_id: str = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db)
):
    """Возвращает статус активности подписки и количество оставшихся дней."""
    is_active, sub = await check_subscription_active(db, user_id)
    now = _get_utc_now()
    days_left = max(0, (sub.expires_at - now).days) if sub.expires_at else 0
    return SubscriptionStatusDTO(
        user_id=user_id,
        active=is_active,
        status=sub.status,
        plan_name=sub.plan_name,
        expires_at=sub.expires_at.isoformat() if sub.expires_at else None,
        days_left=days_left
    )


@router.post("/subscription/activate")
async def activate_subscription_key_endpoint(
    payload: ActivateKeyRequest,
    db: AsyncSession = Depends(get_db)
):
    """Активация разового промокода/ключа подписки."""
    success, message, new_expires = await activate_subscription_key(db, payload.user_id, payload.key)
    if not success:
        raise HTTPException(status_code=400, detail=message)

    return {
        "success": True,
        "message": message,
        "expires_at": new_expires.isoformat() if new_expires else None
    }


@router.get("/system/status")
async def get_system_status(db: AsyncSession = Depends(get_db)):
    """Диагностика состояния системы, токена бота и доступности Telegram API."""
    token_set = bool(settings.BOT_TOKEN)
    masked_token = (
        f"{settings.BOT_TOKEN[:6]}...{settings.BOT_TOKEN[-4:]}"
        if token_set and len(settings.BOT_TOKEN) > 10
        else (settings.BOT_TOKEN if token_set else None)
    )

    telegram_api_reachable = False
    telegram_api_error = None
    bot_info = None

    proxy = settings.get_telegram_proxy()
    transport = None

    try:
        async with httpx.AsyncClient(proxy=proxy, timeout=5.0) as client:
            if token_set:
                r = await client.get(f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getMe")
                if r.status_code == 200:
                    telegram_api_reachable = True
                    bot_info = r.json().get("result", {})
                else:
                    telegram_api_error = f"HTTP {r.status_code}: {r.text[:120]}"
            else:
                r = await client.get("https://api.telegram.org")
                telegram_api_reachable = r.status_code in (200, 302, 404)
    except Exception as e:
        telegram_api_error = str(e)

    # Check DB
    db_ok = False
    try:
        await db.execute(select(UserSetting).limit(1))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok",
        "bot_token_configured": token_set,
        "bot_token_masked": masked_token,
        "bot_authorized": bot_info is not None,
        "bot_info": bot_info,
        "telegram_api_reachable": telegram_api_reachable,
        "telegram_api_error": telegram_api_error,
        "proxy_configured": bool(proxy),
        "proxy_url": proxy,
        "webapp_url": settings.WEBAPP_URL,
        "database_connected": db_ok,
    }


