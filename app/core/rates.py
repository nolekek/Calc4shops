import time
import logging
from typing import Dict, Optional
import httpx
from pydantic import BaseModel
from app.config import settings

logger = logging.getLogger(__name__)


class CurrencyRate(BaseModel):
    code: str
    name: str
    symbol: str
    rate_to_rub: float
    updated_at: float
    is_fallback: bool = False


# Default realistic fallback rates in case of network unavailability
FALLBACK_RATES: Dict[str, float] = {
    "RUB": 1.0,
    "TRY": 3.10,     # Турецкая лира
    "USDT": 94.50,   # P2P USDT
    "USD": 92.50,    # Доллар США (ЦБ)
    "EUR": 100.20,   # Евро (ЦБ)
    "KZT": 0.19,     # Казахский тенге (19 коп / 1 тенге)
}

CURRENCY_INFO: Dict[str, Dict[str, str]] = {
    "RUB": {"name": "Российский рубль", "symbol": "₽"},
    "TRY": {"name": "Турецкая лира", "symbol": "₺"},
    "USDT": {"name": "Tether USDT", "symbol": "₮"},
    "USD": {"name": "Доллар США", "symbol": "$"},
    "EUR": {"name": "Евро", "symbol": "€"},
    "KZT": {"name": "Казахский тенге", "symbol": "₸"},
}


class RatesService:
    def __init__(self):
        self._cache: Dict[str, CurrencyRate] = {}
        self._last_fetch: float = 0.0
        self._ttl: int = settings.RATES_CACHE_TTL_SECONDS
        self._init_defaults()

    def _init_defaults(self):
        now = time.time()
        for code, rate in FALLBACK_RATES.items():
            info = CURRENCY_INFO.get(code, {"name": code, "symbol": code})
            self._cache[code] = CurrencyRate(
                code=code,
                name=info["name"],
                symbol=info["symbol"],
                rate_to_rub=rate,
                updated_at=now,
                is_fallback=True
            )

    async def get_rates(self, force_refresh: bool = False) -> Dict[str, CurrencyRate]:
        now = time.time()
        if not force_refresh and (now - self._last_fetch) < self._ttl and self._cache:
            return self._cache

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(settings.CBR_API_URL)
                if resp.status_code == 200:
                    data = resp.json()
                    valutes = data.get("Valute", {})

                    # Parse CBR currencies
                    for code in ["USD", "EUR", "TRY", "KZT"]:
                        if code in valutes:
                            item = valutes[code]
                            nominal = float(item.get("Nominal", 1))
                            value = float(item.get("Value", 0))
                            if nominal > 0 and value > 0:
                                rate = round(value / nominal, 4)
                                info = CURRENCY_INFO.get(code, {"name": code, "symbol": code})
                                self._cache[code] = CurrencyRate(
                                    code=code,
                                    name=info["name"],
                                    symbol=info["symbol"],
                                    rate_to_rub=rate,
                                    updated_at=now,
                                    is_fallback=False
                                )

                    # Derive USDT with standard P2P exchange margin (~1.02 of USD)
                    usd_rate = self._cache.get("USD")
                    if usd_rate:
                        usdt_rate = round(usd_rate.rate_to_rub * 1.02, 2)
                        self._cache["USDT"] = CurrencyRate(
                            code="USDT",
                            name=CURRENCY_INFO["USDT"]["name"],
                            symbol=CURRENCY_INFO["USDT"]["symbol"],
                            rate_to_rub=usdt_rate,
                            updated_at=now,
                            is_fallback=False
                        )

                    self._last_fetch = now
                    logger.info("Successfully refreshed currency rates from CBR")
        except Exception as e:
            logger.warning(f"Could not refresh rates from CBR ({e}), using cached fallback")

        return self._cache

    async def get_rate_to_rub(self, currency_code: str) -> float:
        code = currency_code.upper()
        if code == "RUB":
            return 1.0
        rates = await self.get_rates()
        if code in rates:
            return rates[code].rate_to_rub
        return FALLBACK_RATES.get(code, 1.0)


rates_service = RatesService()
