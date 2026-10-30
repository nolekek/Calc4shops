import re
import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from sqlalchemy import select, desc

from app.config import settings
from app.db.database import async_session
from app.db.models import UserSetting, CalculationHistory
from app.core.presets import PLATFORMS, TAX_REGIMES
from app.core.rates import rates_service
from app.core.calculator import CalculationRequest, calculate_deal
from app.core.batch_processor import (
    parse_csv_content,
    audit_batch_items,
    export_audited_csv,
    generate_csv_template,
)
from aiogram.types import BufferedInputFile
from app.bot.keyboards import (
    get_main_reply_keyboard,
    get_start_inline_keyboard,
    get_platforms_inline_keyboard,
    get_sub_inline_keyboard,
)
from app.core.subscription import (
    check_subscription_active,
    activate_subscription_key,
    generate_activation_keys,
    grant_subscription_manual,
    _get_utc_now,
)

logger = logging.getLogger(__name__)
router = Router(name="bot_handlers")


def format_deal_message(res, platform_name: str, currency: str, cost_orig: float, rate: float) -> str:
    """Форматирует красивый Telegram-вердикт сделки."""
    if res.verdict == "profitable":
        status_icon = "🟢"
    elif res.verdict == "borderline":
        status_icon = "🟡"
    else:
        status_icon = "🔴"

    curr_note = f" ({cost_orig:,.0f} {currency} × {rate:.2f} ₽)" if currency != "RUB" else ""

    text = (
        f"{status_icon} <b>Вердикт: {res.verdict_title.upper()}</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🏷️ <b>Выручка (цена продажи):</b> <code>{res.gross_revenue:,.0f} ₽</code>\n"
        f"📦 <b>Себестоимость закупки:</b> <code>{res.cost_rub:,.0f} ₽</code>{curr_note}\n"
        f"🏛️ <b>Площадка ({platform_name}):</b> <code>{res.platform_fee:,.0f} ₽</code> ({res.platform_fee_pct_applied}%)\n"
        f"💳 <b>Вывод средств:</b> <code>{res.payout_fee:,.0f} ₽</code> ({res.payout_fee_pct_applied}%)\n"
        f"📑 <b>Налог:</b> <code>{res.tax_amount:,.0f} ₽</code> ({res.tax_rate_pct_applied}%)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Чистая прибыль:</b> <b>{res.net_profit:+,.0f} ₽</b>\n"
        f"📊 <b>Маржинальность:</b> <b>{res.margin_pct:.1f}%</b> | <b>ROI:</b> <b>{res.roi_pct:.1f}%</b>\n"
        f"🎯 <b>Точка безубыточности:</b> <code>{res.breakeven_price:,.0f} ₽</code>\n"
        f"🛡️ <b>Максимальная скидка:</b> <code>{res.max_discount_rub:,.0f} ₽</code>\n\n"
        f"💡 <i>{res.recommendation}</i>"
    )
    return text


@router.message(CommandStart())
async def handle_start(message: Message):
    user_name = message.from_user.first_name if message.from_user else "Продавец"
    user_id = str(message.from_user.id) if message.from_user else "anon"

    async with async_session() as db:
        is_active, sub = await check_subscription_active(db, user_id)

    now = _get_utc_now()
    if sub.status == "admin":
        sub_status_text = "👑 <b>Статус:</b> Администратор (бессрочный доступ)"
    elif sub.status == "trial":
        days_left = max(0, (sub.expires_at - now).days + 1)
        sub_status_text = f"🎁 <b>Пробный доступ:</b> активен (осталось {days_left} дн.)"
    elif is_active:
        days_left = max(0, (sub.expires_at - now).days)
        sub_status_text = f"💎 <b>Подписка:</b> активна до {sub.expires_at.strftime('%d.%m.%Y')} ({days_left} дн.)"
    else:
        sub_status_text = "🔒 <b>Подписка:</b> не активна (активируйте ключ: <code>/activate КЛЮЧ</code>)"

    text = (
        f"👋 Привет, <b>{user_name}</b>!\n\n"
        f"Я <b>«Аудитор сделок»</b> — твой персональный финансовый калькулятор для продаж цифровых товаров на "
        f"<b>Plati.market, Playerok, FunPay и Digiseller</b>.\n\n"
        f"⚡ <b>Что я умею:</b>\n"
        f"• Считать реальную <b>чистую прибыль</b> за 3 секунды с учетом комиссий шлюзов и налогов.\n"
        f"• Автоматически пересчитывать <b>закупки в TRY, USDT, USD, KZT</b> по курсу.\n"
        f"• Находить <b>точку безубыточности</b> и максимальную безопасную скидку.\n"
        f"• Подбирать цену лота под желаемую прибыль.\n\n"
        f"{sub_status_text}\n\n"
        f"👇 <i>Нажми кнопку ниже, чтобы открыть калькулятор на весь экран:</i>"
    )
    await message.answer(
        text,
        reply_markup=get_main_reply_keyboard(),
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь и комиссии")
async def handle_help(message: Message):
    text = (
        "📚 <b>Справка и комиссии площадок</b>\n\n"
        "🔹 <b>Plati.market / Digiseller:</b>\n"
        "• Базовая комиссия сервиса: ~10% (может варьироваться от 7% до 15%).\n"
        "• Вывод средств: СБП / USDT ~2%, карты РФ ~2.5% + 50 ₽.\n\n"
        "🔹 <b>Playerok:</b>\n"
        "• Комиссия маркетплейса: 20–25% (зависит от категории товара).\n"
        "• Вывод средств: 3% (минимальная комиссия 50 ₽).\n\n"
        "🔹 <b>FunPay:</b>\n"
        "• Комиссия биржи: 3–15% (по умолчанию заложена в цену покупателя).\n"
        "• Вывод средств: ~3%.\n\n"
        "💡 <b>Команда быстрого расчета:</b>\n"
        "<code>/calc [закупка] [продажа] [площадка] [валюта]</code>\n"
        "<i>Пример:</i> <code>/calc 500 1000 plati</code>\n"
        "<i>С валютой:</i> <code>/calc 100 500 plati try</code> (100 лир закупка)"
    )
    await message.answer(text)


@router.message(Command("calc"))
@router.message(F.text == "⚡ Быстрый расчет")
async def handle_calc_command(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        is_active, _ = await check_subscription_active(db, user_id)
    if not is_active:
        await message.answer(
            "🔒 <b>Доступ ограничен по подписке</b>\n\n"
            "Срок вашей подписки или пробного периода истёк.\n"
            "Продлите доступ на <b>Playerok</b> и активируйте полученный ключ:\n"
            "<code>/activate ВАШ_КЛЮЧ</code>\n\n"
            "💎 <i>Узнать статус: /sub</i>"
        )
        return

    # Check if arguments provided
    text_content = message.text.strip()
    parts = text_content.split()

    if len(parts) >= 3 and parts[0] == "/calc":
        # Fast one-line command: /calc 500 1000 [platform] [currency]
        try:
            cost_val = float(parts[1].replace(",", "."))
            price_val = float(parts[2].replace(",", "."))
            platform_id = parts[3].lower() if len(parts) >= 4 else "plati"
            currency = parts[4].upper() if len(parts) >= 5 else "RUB"

            if platform_id not in PLATFORMS:
                platform_id = "plati"

            rate = await rates_service.get_rate_to_rub(currency)

            req = CalculationRequest(
                cost_original=cost_val,
                currency=currency,
                currency_rate=rate,
                price=price_val,
                platform_id=platform_id,
            )
            res = calculate_deal(req)

            # Save to history
            user_id = str(message.from_user.id) if message.from_user else "anon"
            async with async_session() as db:
                record = CalculationHistory(
                    user_id=user_id,
                    platform_id=platform_id,
                    cost_original=cost_val,
                    currency=currency,
                    currency_rate=rate,
                    cost_rub=res.cost_rub,
                    price_rub=res.gross_revenue,
                    platform_fee=res.platform_fee,
                    payout_fee=res.payout_fee,
                    tax_amount=res.tax_amount,
                    net_profit=res.net_profit,
                    margin_pct=res.margin_pct,
                    breakeven_price=res.breakeven_price,
                    verdict=res.verdict,
                    verdict_title=res.verdict_title,
                    recommendation=res.recommendation,
                )
                db.add(record)
                await db.commit()

            plat_name = PLATFORMS[platform_id].name
            reply_msg = format_deal_message(res, plat_name, currency, cost_val, rate)
            await message.answer(reply_msg)
            return

        except ValueError:
            pass

    # If no parameters or button clicked, show quick guide
    guide_text = (
        "⚡ <b>Быстрый расчёт сделки</b>\n\n"
        "Отправь команду в одну строку:\n"
        "<code>/calc 500 1000 plati</code>\n\n"
        "Где:\n"
        "• <code>500</code> — цена закупки\n"
        "• <code>1000</code> — цена продажи\n"
        "• <code>plati</code> — площадка (plati / playerok / funpay)\n"
        "• Опционально валюта закупки: <code>/calc 150 900 plati try</code>\n\n"
        "Или открой интерактивный Mini App с удобными ползунками: 👇"
    )
    await message.answer(
        guide_text,
        reply_markup=get_start_inline_keyboard()
    )


@router.message(Command("history"))
@router.message(F.text == "📊 Моя история")
async def handle_history(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        stmt = (
            select(CalculationHistory)
            .where(CalculationHistory.user_id == user_id)
            .order_by(desc(CalculationHistory.created_at))
            .limit(5)
        )
        res = await db.execute(stmt)
        records = res.scalars().all()

    if not records:
        await message.answer(
            "📊 У вас пока нет сохраненных расчетов сделок.\n"
            "Сделайте первый расчет через команду <code>/calc 500 1000</code> или в Mini App!"
        )
        return

    text = "📊 <b>Последние рассчитанные сделки:</b>\n━━━━━━━━━━━━━━━━━━\n"
    for idx, r in enumerate(records, 1):
        icon = "🟢" if r.verdict == "profitable" else ("🟡" if r.verdict == "borderline" else "🔴")
        text += (
            f"{idx}. {icon} <b>{r.platform_id.upper()}</b> | Продажа: {r.price_rub:,.0f} ₽\n"
            f"   Прибыль: <b>{r.net_profit:+,.0f} ₽</b> (маржа {r.margin_pct:.1f}%)\n"
            f"   <i>{r.created_at.strftime('%d.%m %H:%M')}</i>\n"
        )
    text += "━━━━━━━━━━━━━━━━━━\n💡 Полную историю можно просмотреть в Mini App."
    await message.answer(text)


@router.message(Command("settings"))
@router.message(F.text == "⚙️ Настройки")
async def handle_settings(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        stmt = select(UserSetting).where(UserSetting.user_id == user_id)
        res = await db.execute(stmt)
        setting = res.scalar_one_or_none()

    plat = setting.default_platform if setting else "plati"
    tax = setting.default_tax_regime if setting else "npd_6"
    margin = setting.target_margin_pct if setting else 20.0

    text = (
        f"⚙️ <b>Ваши персональные настройки:</b>\n\n"
        f"• Основная площадка: <b>{PLATFORMS.get(plat, PLATFORMS['plati']).name}</b>\n"
        f"• Налоговый режим: <b>{TAX_REGIMES.get(tax, TAX_REGIMES['npd_6']).name}</b>\n"
        f"• Целевая маржинальность: <b>{margin:.0f}%</b>\n\n"
        f"💡 Все параметры и индивидуальные комиссии можно изменить прямо в Mini App:"
    )
    await message.answer(text, reply_markup=get_start_inline_keyboard())


@router.message(Command("batch"))
@router.message(F.text == "📁 Массовый расчёт (CSV)")
async def handle_batch_command(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        is_active, _ = await check_subscription_active(db, user_id)
    if not is_active:
        await message.answer(
            "🔒 <b>Доступ ограничен по подписке</b>\n\n"
            "Массовый аудит прайс-листов доступен только пользователям с активной подпиской.\n"
            "Активируйте ключ доступа:\n"
            "<code>/activate ВАШ_КЛЮЧ</code>\n\n"
            "💎 <i>Узнать статус: /sub</i>"
        )
        return

    text = (
        "📁 <b>Массовый расчёт лотов из CSV</b>\n\n"
        "Вы можете отправить боту файл <b>.csv</b> со списком ваших товаров, и я мгновенно рассчитаю маржинальность всего прайс-листа!\n\n"
        "📋 <b>Формат колонок в CSV:</b>\n"
        "<code>Название;Закупка;Валюта;Цена продажи;Площадка;Налог</code>\n\n"
        "👇 <i>Отправьте CSV-файл прямо в этот диалог или скачайте готовый шаблон:</i>"
    )
    template_csv = ("\ufeff" + generate_csv_template()).encode("utf-8")
    doc = BufferedInputFile(template_csv, filename="шаблон_товаров.csv")
    await message.answer_document(
        document=doc,
        caption=text
    )


@router.message(F.document)
async def handle_csv_document(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        is_active, _ = await check_subscription_active(db, user_id)
    if not is_active:
        await message.answer(
            "🔒 <b>Доступ ограничен по подписке</b>\n\n"
            "Пакетный анализ файлов CSV доступен только по активной подписке.\n"
            "Активируйте ключ доступа:\n"
            "<code>/activate ВАШ_КЛЮЧ</code>\n\n"
            "💎 <i>Узнать статус: /sub</i>"
        )
        return

    doc = message.document
    if not doc or not doc.file_name or not doc.file_name.lower().endswith(".csv"):
        await message.answer("⚠️ Пожалуйста, отправьте файл в формате <b>.csv</b>.")
        return

    wait_msg = await message.answer("⏳ Анализирую прайс-лист и считаю комиссии всех площадок...")

    try:
        from app.bot.bot_instance import get_bot
        b = get_bot()
        if not b:
            await wait_msg.edit_text("Ошибка: бот не инициализирован.")
            return

        file_obj = await b.get_file(doc.file_id)
        if not file_obj.file_path:
            await wait_msg.edit_text("Не удалось загрузить файл из Telegram.")
            return

        file_stream = await b.download_file(file_obj.file_path)
        content_bytes = file_stream.read()

        parsed_items = parse_csv_content(content_bytes)
        if not parsed_items:
            await wait_msg.edit_text(
                "❌ Не удалось найти строки с товарами. Убедитесь, что в файле есть колонки 'Закупка' и 'Цена продажи'."
            )
            return

        audit_res = await audit_batch_items(parsed_items)
        s = audit_res.summary

        # Format briefing message
        report_text = (
            f"📊 <b>Результат аудита прайс-листа ({s.total_items} лотов):</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"🟢 <b>Прибыльных:</b> {s.profitable_count}\n"
            f"🟡 <b>На грани:</b> {s.borderline_count}\n"
            f"🔴 <b>В УБЫТОК:</b> {s.unprofitable_count}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 <b>Суммарная чистая прибыль:</b> <b>{s.total_profit:+,.0f} ₽</b>\n"
            f"📈 <b>Средняя маржа портфеля:</b> <b>{s.avg_margin_pct:.1f}%</b>\n\n"
        )

        # Highlight unprofitable lots
        unprofitable_items = [it for it in audit_res.items if it.verdict == "unprofitable"]
        if unprofitable_items:
            report_text += "🚨 <b>Внимание! Товары с отрицательной прибылью:</b>\n"
            for it in unprofitable_items[:5]:
                report_text += (
                    f"• <b>{it.title}</b>: <code>{it.net_profit:,.0f} ₽</code> "
                    f"(подними цену с {it.price_rub:,.0f} ₽ до <b>{it.breakeven_price:,.0f} ₽</b>)\n"
                )
            if len(unprofitable_items) > 5:
                report_text += f"<i>...и ещё {len(unprofitable_items) - 5} лотов в отчёте ниже.</i>\n\n"
            report_text += "\n"

        report_text += "📎 <i>Полный детальный расчёт с рекомендациями прикреплен в файле:</i>"

        # Generate output CSV
        out_csv = ("\ufeff" + export_audited_csv(audit_res.items)).encode("utf-8")
        out_doc = BufferedInputFile(out_csv, filename=f"аудит_{doc.file_name}")

        await wait_msg.delete()
        await message.answer_document(
            document=out_doc,
            caption=report_text
        )

    except Exception as e:
        logger.error(f"Error processing CSV: {e}")
        await wait_msg.edit_text(f"❌ Произошла ошибка при обработке файла: {e}")


@router.callback_query(F.data == "btn_history")
async def callback_history(query: CallbackQuery):
    await query.answer()
    if query.message:
        await handle_history(query.message)


@router.callback_query(F.data == "btn_settings")
async def callback_settings(query: CallbackQuery):
    await query.answer()
    if query.message:
        await handle_settings(query.message)


@router.message(Command("sub"))
@router.message(Command("subscription"))
@router.message(F.text == "💎 Подписка")
async def handle_subscription_info(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    async with async_session() as db:
        is_active, sub = await check_subscription_active(db, user_id)

    now = _get_utc_now()
    if sub.status == "admin":
        msg = (
            "👑 <b>Управление подпиской</b>\n━━━━━━━━━━━━━━━━━━\n"
            "Статус: <b>Администратор системы</b>\n"
            "Доступ: <b>Бессрочный / Неограниченный</b>\n\n"
            "🛠️ <b>Команды администратора:</b>\n"
            "• <code>/genkey [кол-во] [дней]</code> — сгенерировать ключи для Playerok\n"
            "• <code>/grant [telegram_id] [дней]</code> — выдать подписку пользователю вручную"
        )
    elif is_active:
        days_left = max(0, (sub.expires_at - now).days)
        tag = "🎁 <b>Пробный доступ:</b>" if sub.status == "trial" else "💎 <b>Активная подписка:</b>"
        msg = (
            f"{tag}\n━━━━━━━━━━━━━━━━━━\n"
            f"• Статус: <b>Активна ✅</b>\n"
            f"• Действует до: <b>{sub.expires_at.strftime('%d.%m.%Y %H:%M UTC')}</b>\n"
            f"• Осталось: <b>{days_left} дн.</b>\n\n"
            f"💡 Для продления приобретите ключ на Playerok и введите:\n"
            f"<code>/activate ВАШ_КЛЮЧ</code>"
        )
    else:
        msg = (
            "❌ <b>Подписка неактивна</b>\n━━━━━━━━━━━━━━━━━━\n"
            "Срок действия вашего доступа истёк.\n\n"
            "🛒 <b>Как получить доступ:</b>\n"
            "1. Приобретите ключ подписки на 30 дней на <b>Playerok</b>.\n"
            "2. Отправьте полученный ключ сюда командой:\n"
            "<code>/activate ВАШ_КЛЮЧ</code>\n\n"
            "После активации вам мгновенно откроется полный доступ к калькулятору и пакетному анализу CSV."
        )

    await message.answer(msg, reply_markup=get_sub_inline_keyboard())


@router.message(Command("activate"))
async def handle_activate_key(message: Message):
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "🔑 <b>Активация подписки</b>\n\n"
            "Пожалуйста, укажите ключ после команды, например:\n"
            "<code>/activate AUDIT-XXXX-XXXX-XXXX</code>"
        )
        return

    key_input = parts[1].strip()
    user_id = str(message.from_user.id) if message.from_user else "anon"

    async with async_session() as db:
        success, text, new_expires = await activate_subscription_key(db, user_id, key_input)

    if success and new_expires:
        text += f"\n\n📅 Подписка активна до: <b>{new_expires.strftime('%d.%m.%Y %H:%M UTC')}</b>"

    await message.answer(text)


@router.message(Command("genkey"))
async def handle_genkey(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    if user_id not in settings.get_admin_ids():
        await message.answer("⛔ Данная команда доступна только администраторам.")
        return

    parts = message.text.strip().split()
    count = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else 1
    days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 30

    if count > 100:
        count = 100

    async with async_session() as db:
        keys = await generate_activation_keys(db, count=count, duration_days=days)

    keys_str = "\n".join(keys)
    reply_text = (
        f"🔑 <b>Сгенерировано {len(keys)} ключей на {days} дней:</b>\n\n"
        f"<code>{keys_str}</code>\n\n"
        f"📋 <i>Скопируйте их в раздел «Автоматическая выдача» на Playerok.</i>"
    )
    await message.answer(reply_text)


@router.message(Command("grant"))
async def handle_grant(message: Message):
    user_id = str(message.from_user.id) if message.from_user else "anon"
    if user_id not in settings.get_admin_ids():
        await message.answer("⛔ Данная команда доступна только администраторам.")
        return

    parts = message.text.strip().split()
    if len(parts) < 2:
        await message.answer("Использование: <code>/grant [user_id] [days]</code>")
        return

    target_user_id = parts[1]
    days = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 30

    async with async_session() as db:
        sub = await grant_subscription_manual(db, target_user_id, days=days)

    await message.answer(
        f"✅ Пользователю <code>{target_user_id}</code> начислено {days} дней подписки.\n"
        f"Срок действия: <b>{sub.expires_at.strftime('%d.%m.%Y %H:%M UTC')}</b>"
    )


@router.callback_query(F.data == "btn_sub")
async def callback_sub(query: CallbackQuery):
    await query.answer()
    if query.message:
        await handle_subscription_info(query.message)


@router.callback_query(F.data == "btn_sub_help")
async def callback_sub_help(query: CallbackQuery):
    await query.answer()
    if query.message:
        await query.message.answer(
            "📖 <b>Как активировать подписку:</b>\n\n"
            "1. Купите товар на Playerok.\n"
            "2. В чате заказа или автовыдаче вы получите ключ формата:\n"
            "   <code>AUDIT-XXXX-XXXX-XXXX</code>\n"
            "3. Скопируйте ключ и отправьте его сюда сообщением:\n"
            "   <code>/activate ВАШ_КЛЮЧ</code>\n\n"
            "Бот мгновенно продлит ваш доступ на 30 дней!"
        )
