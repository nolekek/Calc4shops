import pytest
from app.core.calculator import (
    CalculationRequest,
    ReverseCalculationRequest,
    calculate_deal,
    calculate_reverse,
)


def test_user_spec_example():
    """Тест примера из исходного ТЗ пользователя:

    Ввод: закупка 500 ₽, продажа 1000 ₽, Plati, НПД 6%, вывод 2%.
    Ожидаемый результат:
      - выручка: 1000 ₽
      - комиссия площадки: 100 ₽
      - вывод: 18 ₽
      - налог: 60 ₽
      - себестоимость: 500 ₽
      - чистая прибыль: 322 ₽
      - маржа: 32.2%
      - вердикт: Выгодно
    """
    req = CalculationRequest(
        cost_original=500.0,
        currency="RUB",
        currency_rate=1.0,
        price=1000.0,
        platform_id="plati",
        platform_fee_pct=10.0,
        payout_fee_pct=2.0,
        payout_fee_on_net=True,
        tax_regime="npd_6",
        target_margin_pct=20.0,
    )
    res = calculate_deal(req)

    assert res.gross_revenue == 1000.0
    assert res.cost_rub == 500.0
    assert res.platform_fee == 100.0
    assert res.payout_fee == 18.0
    assert res.tax_amount == 60.0
    assert res.net_profit == 322.0
    assert res.margin_pct == 32.2
    assert res.verdict == "profitable"
    assert res.verdict_title == "Выгодно"
    assert res.breakeven_price == pytest.approx(608.27, 0.1)
    assert res.max_discount_rub == pytest.approx(391.73, 0.1)


def test_unprofitable_deal():
    """Тест убыточной сделки: закупка 900 ₽, продажа 1000 ₽ на Playerok (20% + 3% + 50 ₽)."""
    req = CalculationRequest(
        cost_original=900.0,
        currency="RUB",
        currency_rate=1.0,
        price=1000.0,
        platform_id="playerok",
        tax_regime="npd_6",
    )
    res = calculate_deal(req)
    assert res.net_profit < 0
    assert res.verdict == "unprofitable"
    assert res.verdict_title == "Убыток"
    assert res.breakeven_price > 1000.0


def test_borderline_deal():
    """Тест сделки на грани (маржа 8% при целевой 20%)."""
    req = CalculationRequest(
        cost_original=700.0,
        currency="RUB",
        currency_rate=1.0,
        price=1000.0,
        platform_id="plati",
        tax_regime="none",
        target_margin_pct=20.0,
    )
    res = calculate_deal(req)
    # Price 1000, plat fee 100, payout (900*0.02)=18 -> net balance 882 - 700 = 182 ₽ (18.2% margin)
    assert 0 < res.margin_pct < 20.0
    assert res.verdict == "borderline"


def test_currency_conversion():
    """Тест закупки в валюте (100 TRY по курсу 3.10 ₽)."""
    req = CalculationRequest(
        cost_original=100.0,
        currency="TRY",
        currency_rate=3.10,
        price=600.0,
        platform_id="plati",
        tax_regime="npd_4",
    )
    res = calculate_deal(req)
    assert res.cost_rub == 310.0
    assert res.net_profit > 0


def test_reverse_calculation():
    """Тест обратного подбора цены: хотим чистыми 322 ₽."""
    rev_req = ReverseCalculationRequest(
        cost_original=500.0,
        currency="RUB",
        currency_rate=1.0,
        mode="target_profit",
        target_value=322.0,
        platform_id="plati",
        platform_fee_pct=10.0,
        payout_fee_pct=2.0,
        payout_fee_on_net=True,
        tax_regime="npd_6",
    )
    res = calculate_reverse(rev_req)
    assert res.gross_revenue == pytest.approx(1000.0, 0.5)
    assert res.net_profit == pytest.approx(322.0, 0.5)
