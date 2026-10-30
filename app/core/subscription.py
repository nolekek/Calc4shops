import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import UserSubscription, ActivationKey, utc_now


def _get_utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_or_create_subscription(db: AsyncSession, user_id: str) -> UserSubscription:
    """Получает или создает подписку пользователя (с триалом при первом входе, если включен)."""
    stmt = select(UserSubscription).where(UserSubscription.user_id == user_id)
    res = await db.execute(stmt)
    sub = res.scalar_one_or_none()

    now = _get_utc_now()

    if not sub:
        trial_days = getattr(settings, "TRIAL_DAYS", 3)
        if trial_days > 0:
            expires_at = now + timedelta(days=trial_days)
            status = "trial"
        else:
            expires_at = now
            status = "expired"

        sub = UserSubscription(
            user_id=user_id,
            status=status,
            expires_at=expires_at,
            plan_name="trial" if status == "trial" else "monthly",
            created_at=now,
            updated_at=now,
        )
        db.add(sub)
        await db.commit()
        await db.refresh(sub)

    return sub


async def check_subscription_active(db: AsyncSession, user_id: str) -> Tuple[bool, UserSubscription]:
    """
    Проверяет, активна ли подписка пользователя.
    Возвращает (is_active, subscription_object).
    Администраторы всегда имеют активный статус.
    """
    # Проверка админа
    if user_id in settings.get_admin_ids():
        fake_admin_sub = UserSubscription(
            user_id=user_id,
            status="admin",
            expires_at=_get_utc_now() + timedelta(days=3650),
            plan_name="admin_lifetime",
        )
        return True, fake_admin_sub

    sub = await get_or_create_subscription(db, user_id)
    now = _get_utc_now()

    if sub.expires_at > now:
        return True, sub

    # Подписка истекла
    if sub.status != "expired":
        sub.status = "expired"
        await db.commit()
        await db.refresh(sub)

    return False, sub


async def generate_activation_keys(
    db: AsyncSession,
    count: int = 1,
    duration_days: int = 30
) -> List[str]:
    """Генерирует уникальные ключи активации вида AUDIT-XXXX-XXXX-XXXX."""
    keys_created = []
    now = _get_utc_now()

    for _ in range(count):
        while True:
            part1 = secrets.token_hex(2).upper()
            part2 = secrets.token_hex(2).upper()
            part3 = secrets.token_hex(2).upper()
            raw_key = f"AUDIT-{part1}-{part2}-{part3}"

            # Check if exists
            stmt = select(ActivationKey).where(ActivationKey.key == raw_key)
            existing = (await db.execute(stmt)).scalar_one_or_none()
            if not existing:
                break

        key_obj = ActivationKey(
            key=raw_key,
            duration_days=duration_days,
            is_used=False,
            created_at=now,
        )
        db.add(key_obj)
        keys_created.append(raw_key)

    await db.commit()
    return keys_created


async def activate_subscription_key(
    db: AsyncSession,
    user_id: str,
    key_input: str
) -> Tuple[bool, str, Optional[datetime]]:
    """
    Активирует ключ подписки для пользователя.
    Если у пользователя уже была активная подписка, дни суммируются.
    Возвращает (success, message, new_expires_at).
    """
    cleaned_key = key_input.strip().upper()

    stmt = select(ActivationKey).where(ActivationKey.key == cleaned_key)
    res = await db.execute(stmt)
    key_obj = res.scalar_one_or_none()

    if not key_obj:
        return False, "❌ Ключ не найден. Проверьте правильность ввода кода.", None

    if key_obj.is_used:
        used_date = key_obj.used_at.strftime("%d.%m.%Y") if key_obj.used_at else "ранее"
        return False, f"⚠️ Этот ключ уже был активирован ({used_date}).", None

    sub = await get_or_create_subscription(db, user_id)
    now = _get_utc_now()

    # Если текущая подписка еще действует — продлеваем от даты окончания
    if sub.expires_at > now:
        new_expires = sub.expires_at + timedelta(days=key_obj.duration_days)
    else:
        new_expires = now + timedelta(days=key_obj.duration_days)

    sub.expires_at = new_expires
    sub.status = "active"
    sub.plan_name = f"{key_obj.duration_days}_days"
    sub.updated_at = now

    key_obj.is_used = True
    key_obj.used_by_user_id = user_id
    key_obj.used_at = now

    await db.commit()
    await db.refresh(sub)

    return True, f"✅ Ключ успешно активирован на {key_obj.duration_days} дней!", new_expires


async def grant_subscription_manual(
    db: AsyncSession,
    user_id: str,
    days: int = 30
) -> UserSubscription:
    """Вручную начисляет дни подписки пользователю (для админ-панели)."""
    sub = await get_or_create_subscription(db, user_id)
    now = _get_utc_now()

    if sub.expires_at > now:
        sub.expires_at = sub.expires_at + timedelta(days=days)
    else:
        sub.expires_at = now + timedelta(days=days)

    sub.status = "active"
    sub.updated_at = now
    await db.commit()
    await db.refresh(sub)
    return sub
