from typing import Dict, Any, List
from pydantic import BaseModel


class PlatformPreset(BaseModel):
    id: str
    name: str
    short_name: str
    platform_fee_pct: float
    platform_fee_fixed: float = 0.0
    payout_fee_pct: float
    payout_fee_fixed: float = 0.0
    payout_fee_on_net: bool = True
    description: str
    popular_currencies: List[str] = ["RUB", "TRY", "USDT", "USD"]


class TaxPreset(BaseModel):
    id: str
    name: str
    rate: float
    tax_type: str  # 'gross' (from selling price), 'net_profit' (from profit), 'none'
    description: str


PLATFORMS: Dict[str, PlatformPreset] = {
    "plati": PlatformPreset(
        id="plati",
        name="Plati.market / Digiseller",
        short_name="Plati",
        platform_fee_pct=10.0,
        platform_fee_fixed=0.0,
        payout_fee_pct=2.0,
        payout_fee_fixed=0.0,
        payout_fee_on_net=True,
        description="Комиссия Digiseller ~10%, вывод на СБП/USDT 2%",
        popular_currencies=["RUB", "TRY", "USDT", "USD", "KZT"],
    ),
    "playerok": PlatformPreset(
        id="playerok",
        name="Playerok",
        short_name="Playerok",
        platform_fee_pct=20.0,
        platform_fee_fixed=0.0,
        payout_fee_pct=3.0,
        payout_fee_fixed=50.0,
        payout_fee_on_net=True,
        description="Комиссия маркетплейса ~20% + вывод 3% (мин. 50 ₽)",
        popular_currencies=["RUB", "TRY", "USDT"],
    ),
    "funpay": PlatformPreset(
        id="funpay",
        name="FunPay",
        short_name="FunPay",
        platform_fee_pct=10.0,
        platform_fee_fixed=0.0,
        payout_fee_pct=3.0,
        payout_fee_fixed=30.0,
        payout_fee_on_net=True,
        description="Комиссия биржи ~10% (зависит от раздела) + вывод 3%",
        popular_currencies=["RUB", "TRY", "USDT", "EUR"],
    ),
    "custom": PlatformPreset(
        id="custom",
        name="Пользовательская площадка",
        short_name="Своя",
        platform_fee_pct=0.0,
        platform_fee_fixed=0.0,
        payout_fee_pct=0.0,
        payout_fee_fixed=0.0,
        payout_fee_on_net=True,
        description="Ручной ввод параметров комиссий",
        popular_currencies=["RUB", "TRY", "USDT", "USD", "EUR", "KZT"],
    ),
}


TAX_REGIMES: Dict[str, TaxPreset] = {
    "npd_4": TaxPreset(
        id="npd_4",
        name="НПД 4% (Физлица)",
        rate=0.04,
        tax_type="gross",
        description="Самозанятый при продаже физическим лицам",
    ),
    "npd_6": TaxPreset(
        id="npd_6",
        name="НПД 6% (Юрлица)",
        rate=0.06,
        tax_type="gross",
        description="Самозанятый при получении выплат через юрлицо/агента",
    ),
    "usn_6": TaxPreset(
        id="usn_6",
        name="УСН Доходы 6%",
        rate=0.06,
        tax_type="gross",
        description="Упрощенная система налогообложения (доходы)",
    ),
    "usn_15": TaxPreset(
        id="usn_15",
        name="УСН Доходы-Расходы 15%",
        rate=0.15,
        tax_type="net_profit",
        description="15% от разницы между доходами и подтвержденными расходами",
    ),
    "none": TaxPreset(
        id="none",
        name="Без налога (0%)",
        rate=0.0,
        tax_type="none",
        description="Расчет без учета налогов",
    ),
}
