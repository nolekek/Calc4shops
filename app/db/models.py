from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import String, Float, Integer, DateTime, Boolean, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserSetting(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    default_platform: Mapped[str] = mapped_column(String(32), default="plati")
    default_tax_regime: Mapped[str] = mapped_column(String(32), default="npd_6")
    default_currency: Mapped[str] = mapped_column(String(16), default="RUB")
    target_margin_pct: Mapped[float] = mapped_column(Float, default=20.0)
    
    # Custom fee overrides
    custom_platform_fee_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    custom_payout_fee_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    custom_payout_fee_fixed: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)


class CalculationHistory(Base):
    __tablename__ = "calculation_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), index=True)
    platform_id: Mapped[str] = mapped_column(String(32))
    
    cost_original: Mapped[float] = mapped_column(Float)
    currency: Mapped[str] = mapped_column(String(16), default="RUB")
    currency_rate: Mapped[float] = mapped_column(Float, default=1.0)
    cost_rub: Mapped[float] = mapped_column(Float)
    price_rub: Mapped[float] = mapped_column(Float)
    
    platform_fee: Mapped[float] = mapped_column(Float)
    payout_fee: Mapped[float] = mapped_column(Float)
    tax_amount: Mapped[float] = mapped_column(Float)
    net_profit: Mapped[float] = mapped_column(Float)
    margin_pct: Mapped[float] = mapped_column(Float)
    breakeven_price: Mapped[float] = mapped_column(Float)
    
    verdict: Mapped[str] = mapped_column(String(32))
    verdict_title: Mapped[str] = mapped_column(String(32))
    recommendation: Mapped[str] = mapped_column(String(512))
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
