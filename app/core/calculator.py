import math
from typing import Optional, Literal
from pydantic import BaseModel, Field
from app.core.presets import PLATFORMS, TAX_REGIMES


class CalculationRequest(BaseModel):
    cost_original: float = Field(ge=0, description="Цена закупки в валюте закупки")
    currency: str = Field(default="RUB", description="Код валюты закупки (RUB, TRY, USDT и т.д.)")
    currency_rate: float = Field(default=1.0, gt=0, description="Курс валюты к рублю")
    price: float = Field(gt=0, description="Цена продажи на площадке в рублях")
    platform_id: str = Field(default="plati", description="ID площадки")
    
    # Custom overrides (if omitted, platform defaults are used)
    platform_fee_pct: Optional[float] = Field(default=None, ge=0, le=100)
    platform_fee_fixed: Optional[float] = Field(default=None, ge=0)
    payout_fee_pct: Optional[float] = Field(default=None, ge=0, le=100)
    payout_fee_fixed: Optional[float] = Field(default=None, ge=0)
    payout_fee_on_net: Optional[bool] = Field(default=None)
    
    tax_regime: str = Field(default="npd_6", description="ID налогового режима")
    target_margin_pct: float = Field(default=20.0, ge=0, le=95, description="Целевая маржа %")


class CalculationResult(BaseModel):
    # Base numbers
    cost_rub: float
    gross_revenue: float
    platform_fee: float
    payout_fee: float
    tax_amount: float
    total_expenses: float
    net_profit: float
    margin_pct: float
    roi_pct: float
    
    # Limits & safety
    breakeven_price: float
    max_discount_rub: float
    
    # Verdicts
    verdict: Literal["profitable", "borderline", "unprofitable"]
    verdict_title: str
    verdict_badge_class: str
    recommendation: str
    
    # Applied parameters for reference
    platform_fee_pct_applied: float
    payout_fee_pct_applied: float
    tax_rate_pct_applied: float


class ReverseCalculationRequest(BaseModel):
    cost_original: float = Field(ge=0, description="Цена закупки в валюте")
    currency: str = Field(default="RUB")
    currency_rate: float = Field(default=1.0, gt=0)
    mode: Literal["target_profit", "target_margin"] = "target_profit"
    target_value: float = Field(gt=0, description="Желаемая чистая прибыль (₽) или маржинальность (%)")
    
    platform_id: str = Field(default="plati")
    platform_fee_pct: Optional[float] = None
    platform_fee_fixed: Optional[float] = None
    payout_fee_pct: Optional[float] = None
    payout_fee_fixed: Optional[float] = None
    payout_fee_on_net: Optional[bool] = None
    
    tax_regime: str = Field(default="npd_6")
    target_margin_pct: float = Field(default=20.0)


def resolve_platform_params(req: CalculationRequest | ReverseCalculationRequest):
    platform = PLATFORMS.get(req.platform_id, PLATFORMS["custom"])
    plat_fee_pct = req.platform_fee_pct if req.platform_fee_pct is not None else platform.platform_fee_pct
    plat_fee_fixed = req.platform_fee_fixed if req.platform_fee_fixed is not None else platform.platform_fee_fixed
    pay_fee_pct = req.payout_fee_pct if req.payout_fee_pct is not None else platform.payout_fee_pct
    pay_fee_fixed = req.payout_fee_fixed if req.payout_fee_fixed is not None else platform.payout_fee_fixed
    pay_on_net = req.payout_fee_on_net if req.payout_fee_on_net is not None else platform.payout_fee_on_net
    tax_preset = TAX_REGIMES.get(req.tax_regime, TAX_REGIMES["npd_6"])
    return plat_fee_pct, plat_fee_fixed, pay_fee_pct, pay_fee_fixed, pay_on_net, tax_preset


def calculate_deal(req: CalculationRequest) -> CalculationResult:
    plat_pct, plat_fix, pay_pct, pay_fix, pay_on_net, tax_preset = resolve_platform_params(req)

    cost_rub = round(req.cost_original * req.currency_rate, 2)
    price = round(req.price, 2)

    # 1. Platform Fee
    platform_fee = round(price * (plat_pct / 100.0) + plat_fix, 2)

    # 2. Payout Fee
    if pay_on_net:
        net_balance_before_payout = max(0.0, price - platform_fee)
        payout_fee = round(net_balance_before_payout * (pay_pct / 100.0) + pay_fix, 2)
    else:
        payout_fee = round(price * (pay_pct / 100.0) + pay_fix, 2)

    # 3. Tax
    if tax_preset.tax_type == "gross":
        tax_amount = round(price * tax_preset.rate, 2)
    elif tax_preset.tax_type == "net_profit":
        # 15% from income minus expenses
        taxable_profit = max(0.0, price - cost_rub - platform_fee - payout_fee)
        tax_amount = round(taxable_profit * tax_preset.rate, 2)
    else:
        tax_amount = 0.0

    total_expenses = round(platform_fee + payout_fee + tax_amount + cost_rub, 2)
    net_profit = round(price - total_expenses, 2)

    margin_pct = round((net_profit / price) * 100.0, 2) if price > 0 else 0.0
    roi_pct = round((net_profit / cost_rub) * 100.0, 2) if cost_rub > 0 else 0.0

    # 4. Break-even price and discount
    # Linear coefficients: Profit(P) = P * alpha - beta - cost_rub
    p_plat = plat_pct / 100.0
    p_pay = pay_pct / 100.0
    t_rate = tax_preset.rate if tax_preset.tax_type == "gross" else 0.0

    if pay_on_net:
        alpha = (1.0 - p_plat) * (1.0 - p_pay) - t_rate
        beta = plat_fix * (1.0 - p_pay) + pay_fix
    else:
        alpha = 1.0 - p_plat - p_pay - t_rate
        beta = plat_fix + pay_fix

    if alpha > 0.001:
        breakeven_price = round((cost_rub + beta) / alpha, 2)
    else:
        breakeven_price = round(price, 2)

    max_discount_rub = round(max(0.0, price - breakeven_price), 2)

    # 5. Verdict
    target_margin = req.target_margin_pct
    if net_profit <= 0:
        verdict = "unprofitable"
        verdict_title = "Убыток"
        verdict_badge_class = "danger"
        recommendation = f"Сделка в минус ({net_profit:+.0f} ₽). Чтобы выйти в ноль, подними цену минимум до {breakeven_price:,.0f} ₽."
    elif margin_pct < target_margin:
        verdict = "borderline"
        verdict_title = "На грани"
        verdict_badge_class = "warning"
        # Recommended price for target margin
        if (alpha - target_margin / 100.0) > 0.01:
            rec_price = round((cost_rub + beta) / (alpha - target_margin / 100.0), 2)
            recommendation = f"Маржа {margin_pct}% ниже цели {target_margin}%. Чтобы достичь цели, продавай по {rec_price:,.0f} ₽. Не опускай цену ниже {breakeven_price:,.0f} ₽."
        else:
            recommendation = f"Маржа {margin_pct}% ниже целевой {target_margin}%. Макс. допустимая скидка: {max_discount_rub:,.0f} ₽."
    else:
        verdict = "profitable"
        verdict_title = "Выгодно"
        verdict_badge_class = "success"
        recommendation = f"Отличная сделка! Чистая прибыль: {net_profit:,.0f} ₽ (маржа {margin_pct}%). Максимальная скидка без ухода в минус: {max_discount_rub:,.0f} ₽."

    return CalculationResult(
        cost_rub=cost_rub,
        gross_revenue=price,
        platform_fee=platform_fee,
        payout_fee=payout_fee,
        tax_amount=tax_amount,
        total_expenses=total_expenses,
        net_profit=net_profit,
        margin_pct=margin_pct,
        roi_pct=roi_pct,
        breakeven_price=breakeven_price,
        max_discount_rub=max_discount_rub,
        verdict=verdict,
        verdict_title=verdict_title,
        verdict_badge_class=verdict_badge_class,
        recommendation=recommendation,
        platform_fee_pct_applied=plat_pct,
        payout_fee_pct_applied=pay_pct,
        tax_rate_pct_applied=round(tax_preset.rate * 100, 1),
    )


def calculate_reverse(req: ReverseCalculationRequest) -> CalculationResult:
    plat_pct, plat_fix, pay_pct, pay_fix, pay_on_net, tax_preset = resolve_platform_params(req)
    cost_rub = round(req.cost_original * req.currency_rate, 2)

    p_plat = plat_pct / 100.0
    p_pay = pay_pct / 100.0
    t_rate = tax_preset.rate if tax_preset.tax_type == "gross" else 0.0

    if pay_on_net:
        alpha = (1.0 - p_plat) * (1.0 - p_pay) - t_rate
        beta = plat_fix * (1.0 - p_pay) + pay_fix
    else:
        alpha = 1.0 - p_plat - p_pay - t_rate
        beta = plat_fix + pay_fix

    if req.mode == "target_profit":
        target_profit = req.target_value
        if alpha <= 0.001:
            calculated_price = cost_rub + target_profit
        else:
            calculated_price = round((cost_rub + beta + target_profit) / alpha, 2)
    else:
        # target_margin
        target_margin_pct = req.target_value
        m = target_margin_pct / 100.0
        if (alpha - m) <= 0.001:
            calculated_price = round(cost_rub * 2.0, 2)
        else:
            calculated_price = round((cost_rub + beta) / (alpha - m), 2)

    # Now run standard forward calculation with this recommended price
    fwd_req = CalculationRequest(
        cost_original=req.cost_original,
        currency=req.currency,
        currency_rate=req.currency_rate,
        price=max(1.0, calculated_price),
        platform_id=req.platform_id,
        platform_fee_pct=req.platform_fee_pct,
        platform_fee_fixed=req.platform_fee_fixed,
        payout_fee_pct=req.payout_fee_pct,
        payout_fee_fixed=req.payout_fee_fixed,
        payout_fee_on_net=req.payout_fee_on_net,
        tax_regime=req.tax_regime,
        target_margin_pct=req.target_margin_pct
    )
    result = calculate_deal(fwd_req)
    if req.mode == "target_profit":
        result.recommendation = f"Чтобы получить {req.target_value:,.0f} ₽ чистыми, установи цену продажи {calculated_price:,.0f} ₽."
    else:
        result.recommendation = f"Чтобы получить маржу {req.target_value:.1f}%, установи цену продажи {calculated_price:,.0f} ₽."
    return result
