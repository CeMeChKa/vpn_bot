# -*- coding: utf-8 -*-
"""
============================================================
  VPN-БОТ: продажа подписок, Marzban, оплата Platega
  Запуск:  python bot.py

  Структура проекта (специально простая):
    config.py    — все настройки и ключи
    database.py  — SQLite: юзеры, локации, подписки, платежи, рефералы
    marzban.py   — создание/продление юзеров в Marzban
    platega.py   — создание/проверка платежей Platega
    bot.py       — этот файл: меню, кнопки, тексты, инструкции, админка
    webhook.py   — (необязательно) приём callback от Platega
============================================================
"""
import json
import os
import re
import threading
import time
from datetime import datetime

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import config
import database as db
import marzban
import platega

db.init_db()
bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode="HTML")

# Временные состояния админа (добавление локации, рассылка и т.п.)
_admin_temp = {}

MONTHS_WORD = {1: "1 месяц", 3: "3 месяца", 6: "6 месяцев", 12: "12 месяцев"}

# ============================================================
#  ТЕКСТЫ ИНСТРУКЦИЙ ПО УСТРОЙСТВАМ (правь прямо здесь)
#  {sub_url} подставится автоматически.
# ============================================================
INSTRUCTIONS = {
    "android": (
        "📱 <b>Подключение на Android</b>\n\n"
        "1️⃣ Установи приложение <b>v2rayNG</b> (Google Play) или <b>Hiddify</b>.\n"
        "2️⃣ Скопируй свою ссылку подписки ниже (нажми на неё).\n"
        "3️⃣ В приложении нажми <b>+</b> → «Импорт из буфера обмена» "
        "(Import config from Clipboard).\n"
        "4️⃣ Выбери появившийся сервер и нажми круглую кнопку подключения.\n\n"
        "🔗 Твоя подписка:\n<code>{sub_url}</code>"
    ),
    "ios": (
        "🍏 <b>Подключение на iPhone / iPad (iOS)</b>\n\n"
        "1️⃣ Установи приложение <b>Streisand</b> или <b>Hiddify</b> из App Store.\n"
        "2️⃣ Скопируй свою ссылку подписки ниже (нажми на неё).\n"
        "3️⃣ В приложении нажми <b>+</b> → «Добавить из буфера обмена» "
        "(Add from Clipboard).\n"
        "4️⃣ Выбери появившийся сервер и нажми «Подключить».\n\n"
        "🔗 Твоя подписка:\n<code>{sub_url}</code>"
    ),
    "windows": (
        "🪟 <b>Подключение на Windows</b>\n\n"
        "1️⃣ Скачай и установи приложение <b>Hiddify</b> (hiddify.com) "
        "или <b>v2rayN</b>.\n"
        "2️⃣ Скопируй свою ссылку подписки ниже.\n"
        "3️⃣ В Hiddify нажми «+ Новый профиль» → «Добавить из буфера обмена».\n"
        "   В v2rayN: «Подписки» → «Настройки подписки» → вставь ссылку и обнови.\n"
        "4️⃣ Нажми большую кнопку подключения.\n\n"
        "🔗 Твоя подписка:\n<code>{sub_url}</code>"
    ),
    "macos": (
        "💻 <b>Подключение на macOS</b>\n\n"
        "1️⃣ Установи приложение <b>Hiddify</b> (hiddify.com) или "
        "<b>Streisand</b> из App Store.\n"
        "2️⃣ Скопируй свою ссылку подписки ниже.\n"
        "3️⃣ В приложении нажми <b>+</b> → «Добавить из буфера обмена».\n"
        "4️⃣ Выбери появившийся сервер и нажми «Подключить».\n\n"
        "🔗 Твоя подписка:\n<code>{sub_url}</code>"
    ),
}
DEVICE_NAMES = {"android": "📱 Android", "ios": "🍏 iOS", "windows": "🪟 Windows", "macos": "💻 macOS"}

PAYMENT_DISABLED_TEXT = "Извините, оплата в данный момент времени недоступна. Попробуйте позже"


# ============================================================
#  МАЛЕНЬКИЕ ХЕЛПЕРЫ
# ============================================================
def is_admin(user_id) -> bool:
    return user_id in config.ADMIN_IDS


def fmt_date(ts) -> str:
    return datetime.fromtimestamp(int(ts)).strftime("%d.%m.%Y %H:%M")


def days_left(ts) -> int:
    return max(0, (int(ts) - int(time.time()) + 86399) // 86400)


def is_subscribed(user_id) -> bool:
    """Подписан ли юзер на канал. Бот должен быть админом канала!"""
    try:
        m = bot.get_chat_member(config.CHANNEL_ID, user_id)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception as e:
        print(f"[channel] не могу проверить подписку {user_id}: {e}")
        return False


def marzban_username(user_id, loc_code) -> str:
    code = re.sub(r"[^a-z0-9_]", "", str(loc_code).lower())
    return f"tg_{user_id}_{code}"


def back_kb():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    return kb


# ============================================================
#  ГЛАВНОЕ МЕНЮ (с баннером)
# ============================================================
def main_kb():
    kb = InlineKeyboardMarkup(row_width=2)
    # Синяя кнопка: style="primary" (Bot API: синий цвет кнопки)
    kb.add(InlineKeyboardButton("🔌 Подключиться", callback_data="connect", style="primary"))
    kb.add(InlineKeyboardButton("🎁 7 дней бесплатно", callback_data="trial"))
    kb.add(
        InlineKeyboardButton("👤 Профиль", callback_data="profile"),
        InlineKeyboardButton("📋 Мои подписки", callback_data="my_subs"),
    )
    kb.add(
        InlineKeyboardButton("🤝 Партнёрам", url=config.OPERATOR_URL),
        InlineKeyboardButton("🆘 Поддержка", callback_data="support"),
    )
    kb.add(
        InlineKeyboardButton("👥 Реферальная система", callback_data="referral"),
        InlineKeyboardButton("ℹ️ Инфо", callback_data="info"),
    )
    return kb


def send_main_menu(chat_id, text="👋 <b>Добро пожаловать в VPN!</b>\n\n"
                                "Быстрый и безопасный VPN по подписке.\nВыбери действие ниже 👇"):
    if os.path.exists(config.BANNER_PATH):
        with open(config.BANNER_PATH, "rb") as photo:
            bot.send_photo(chat_id, photo, caption=text, reply_markup=main_kb())
    else:
        bot.send_message(chat_id, text, reply_markup=main_kb())


# ============================================================
#  КАНАЛ: проверка подписки + реферальный бонус
# ============================================================
def channel_kb(check_callback):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📢 Подписаться на канал", url=config.CHANNEL_URL))
    kb.add(InlineKeyboardButton("✅ Я подписался", callback_data=check_callback))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    return kb


def ask_channel(chat_id, check_callback, why="trial"):
    texts = {
        "trial": "🎁 <b>Пробные 7 дней бесплатно</b>\n\n"
                 "Чтобы получить пробную подписку, подпишись на наш канал — "
                 "там новости и обновления сервиса 👇",
        "referral": "👥 <b>Реферальная система</b>\n\n"
                    "Чтобы пользоваться реферальной системой, подпишись на наш канал 👇",
    }
    bot.send_message(chat_id, texts.get(why, texts["trial"]), reply_markup=channel_kb(check_callback))


def try_reward_referral(referred_id):
    """
    +7 дней пригласившему — ТОЛЬКО когда приглашённый вступил в канал.
    Если у пригласившего есть активная подписка — продлеваем её (и в Marzban),
    если нет — копим дни (bonus_days), они применятся при первой покупке/триале.
    """
    ref = db.get_referral_by_referred(referred_id)
    if not ref or ref["rewarded"]:
        return
    if not is_subscribed(referred_id):
        return
    referrer_id = ref["referrer_id"]
    days = config.REFERRAL_BONUS_DAYS
    sub = db.get_active_subscription(referrer_id)
    note = ""
    if sub:
        new_expire = int(sub["expire_at"]) + days * 86400
        try:
            loc = db.get_location(sub["location_id"])
            inbounds = json.loads(loc["inbounds"]) if loc else {}
            marzban.set_user_expire(sub["marzban_username"], new_expire, inbounds)
            db.extend_subscription_db(sub["id"], new_expire)
            note = f"Твоя подписка ({sub['loc_title']}) продлена на {days} дней, до {fmt_date(new_expire)} 🎉"
        except Exception as e:
            # Marzban недоступен — не теряем бонус, а копим его до следующей покупки
            print(f"[referral] Marzban extend error: {e}")
            db.add_bonus_days(referrer_id, days)
            note = (f"Тебе начислено +{days} бонусных дней! Они применятся автоматически "
                    f"при следующей покупке или продлении 🎉")
    else:
        db.add_bonus_days(referrer_id, days)
        note = (f"Тебе начислено +{days} дней! У тебя пока нет активной подписки, "
                f"поэтому дни применятся автоматически при покупке или пробной подписке 🎉")
    db.mark_referral_rewarded(ref["id"])
    try:
        bot.send_message(referrer_id, f"👥 <b>По твоей реферальной ссылке пришёл новый пользователь "
                                      f"и вступил в канал!</b>\n\n{note}")
    except Exception:
        pass


@bot.chat_member_handler()
def _on_chat_member(update):
    """Автоматически ловим вступление приглашённого в канал (бот — админ канала)."""
    try:
        new = update.new_chat_member
        if new.status in ("member", "administrator", "creator"):
            try_reward_referral(new.user.id)
    except Exception as e:
        print(f"[chat_member] {e}")


# ============================================================
#  ВЫДАЧА ПОДПИСКИ (общая для оплаты и триала) + ИНСТРУКЦИИ
# ============================================================
def give_subscription(user_id, loc, days, is_trial=False):
    """Создаёт/продлевает юзера в Marzban и сохраняет подписку в БД. Возвращает строку подписки из БД."""
    inbounds = json.loads(loc["inbounds"])
    username = marzban_username(user_id, loc["code"])
    # Накопленные реферальные дни применяем только к НЕпробной первой выдаче,
    # и только если активной подписки по этой локации ещё нет в будущем — Marzban сам плюсует срок.
    sub_url, expire_at = marzban.create_or_extend_user(username, inbounds, days)
    return db.save_subscription(user_id, loc["id"], username, sub_url, expire_at, is_trial=is_trial)


def show_device_choice(chat_id, sub_id, header):
    kb = InlineKeyboardMarkup(row_width=2)
    for dev, name in DEVICE_NAMES.items():
        kb.add(InlineKeyboardButton(name, callback_data=f"device:{sub_id}:{dev}"))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(chat_id, header, reply_markup=kb)


def devices_header(sub):
    return (f"✅ <b>Подписка активна!</b>\n\n"
            f"🌍 Сервер: <b>{sub['loc_title']}</b>\n"
            f"📅 Действует до: <b>{fmt_date(sub['expire_at'])}</b> "
            f"(осталось дней: {days_left(sub['expire_at'])})\n\n"
            f"📲 Выбери своё устройство — пришлю инструкцию и ссылку подписки:")


# ============================================================
#  /start И ГЛАВНОЕ МЕНЮ
# ============================================================
@bot.message_handler(commands=["start"])
def cmd_start(message):
    args = message.text.split(maxsplit=1)
    referrer_id = None
    if len(args) > 1 and args[1].startswith("ref_"):
        try:
            referrer_id = int(args[1][4:])
        except ValueError:
            pass
    db.get_or_create_user(message.from_user.id, message.from_user.username,
                          message.from_user.first_name, referrer_id)
    send_main_menu(message.chat.id)
    if is_admin(message.from_user.id):
        bot.send_message(message.chat.id,
                         "🛠 Ты админ. Команды: /admin — список админ-команд.")


@bot.callback_query_handler(func=lambda c: c.data == "menu")
def cb_menu(call):
    bot.answer_callback_query(call.id)
    send_main_menu(call.message.chat.id)


# ============================================================
#  ПРОФИЛЬ / МОИ ПОДПИСКИ / ПОДДЕРЖКА / ИНФО
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "profile")
def cb_profile(call):
    bot.answer_callback_query(call.id)
    user = db.get_user(call.from_user.id)
    subs = db.get_user_subscriptions(call.from_user.id)
    active = [s for s in subs if s["expire_at"] > time.time()]
    total_ref, rewarded_ref = db.referral_stats(call.from_user.id)
    text = (
        f"👤 <b>Профиль</b>\n\n"
        f"🆔 ID: <code>{call.from_user.id}</code>\n"
        f"👤 Username: @{call.from_user.username or '—'}\n"
        f"📅 С нами с: {fmt_date(user['created_at']) if user else '—'}\n\n"
        f"📋 Активных подписок: <b>{len(active)}</b>\n"
        f"🎁 Пробный период: <b>{'использован' if user and user['trial_used'] else 'доступен'}</b>\n"
        f"👥 Приглашено друзей: <b>{total_ref}</b> (бонус получен за {rewarded_ref})\n"
        f"⭐️ Накоплено бонусных дней: <b>{user['bonus_days'] if user else 0}</b>"
    )
    bot.send_message(call.message.chat.id, text, reply_markup=back_kb())


@bot.callback_query_handler(func=lambda c: c.data == "my_subs")
def cb_my_subs(call):
    bot.answer_callback_query(call.id)
    subs = db.get_user_subscriptions(call.from_user.id)
    if not subs:
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("🔌 Подключиться", callback_data="connect", style="primary"))
        kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
        bot.send_message(call.message.chat.id,
                         "📋 <b>Мои подписки</b>\n\nУ тебя пока нет подписок. "
                         "Нажми «Подключиться», чтобы выбрать сервер и тариф 👇",
                         reply_markup=kb)
        return
    for sub in subs:
        active = sub["expire_at"] > time.time()
        text = (f"{'🟢' if active else '🔴'} <b>{sub['loc_title']}</b>"
                f"{' (пробная)' if sub['is_trial'] else ''}\n"
                f"📅 До: <b>{fmt_date(sub['expire_at'])}</b> "
                f"({'осталось дней: ' + str(days_left(sub['expire_at'])) if active else 'истекла'})\n"
                f"🔗 <code>{sub['sub_url']}</code>")
        kb = InlineKeyboardMarkup()
        if active:
            kb.add(InlineKeyboardButton("📲 Инструкция по подключению",
                                        callback_data=f"devices:{sub['id']}"))
        kb.add(InlineKeyboardButton("🔄 Продлить эту локацию",
                                    callback_data=f"buy_loc:{sub['location_id']}"))
        kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
        bot.send_message(call.message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "support")
def cb_support(call):
    bot.answer_callback_query(call.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"✍️ Написать оператору {config.OPERATOR_USERNAME}", url=config.OPERATOR_URL))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(call.message.chat.id,
                     "🆘 <b>Поддержка</b>\n\nПо любым вопросам напиши оператору — "
                     "ответим и поможем с подключением 👇", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "info")
def cb_info(call):
    bot.answer_callback_query(call.id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📄 Пользовательское соглашение", url=config.INFO_AGREEMENT_URL))
    kb.add(InlineKeyboardButton("🔒 Политика конфиденциальности", url=config.INFO_PRIVACY_URL))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(call.message.chat.id, "ℹ️ <b>Информация</b>\n\nОфициальные документы сервиса:",
                     reply_markup=kb)


# ============================================================
#  ПОДКЛЮЧИТЬСЯ: выбор сервера -> тариф -> оплата Platega
# ============================================================
def locations_kb(prefix, only_active=True):
    kb = InlineKeyboardMarkup()
    locs = db.get_locations(only_active=only_active)
    if not locs:
        kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
        return kb
    for loc in locs:
        kb.add(InlineKeyboardButton(loc["title"], callback_data=f"{prefix}:{loc['id']}"))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    return kb


@bot.callback_query_handler(func=lambda c: c.data == "connect")
def cb_connect(call):
    bot.answer_callback_query(call.id)
    if not db.get_locations():
        bot.send_message(call.message.chat.id,
                         "😔 Сейчас нет доступных серверов. Загляни позже.", reply_markup=back_kb())
        return
    bot.send_message(call.message.chat.id, "🌍 <b>Выбери сервер:</b>",
                     reply_markup=locations_kb("buy_loc"))


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy_loc:"))
def cb_buy_loc(call):
    bot.answer_callback_query(call.id)
    loc = db.get_location(int(call.data.split(":")[1]))
    if not loc:
        return
    kb = InlineKeyboardMarkup()
    for months in (1, 3, 6, 12):
        price = db.location_price(loc, months)
        per_month = round(price / months)
        kb.add(InlineKeyboardButton(
            f"{MONTHS_WORD[months]} — {price} ₽  (≈{per_month} ₽/мес)",
            callback_data=f"buy:{loc['id']}:{months}"))
    kb.add(InlineKeyboardButton("⬅️ К выбору сервера", callback_data="connect"))
    bot.send_message(call.message.chat.id,
                     f"🌍 Сервер: <b>{loc['title']}</b>\n\n"
                     f"💳 Выбери срок подписки — чем дольше, тем выгоднее цена за месяц 👇",
                     reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("buy:"))
def cb_buy(call):
    _, loc_id, months = call.data.split(":")
    loc, months = db.get_location(int(loc_id)), int(months)

    # --- ЗАГЛУШКА ОПЛАТЫ ---
    if not db.payment_enabled():
        bot.answer_callback_query(call.id, PAYMENT_DISABLED_TEXT, show_alert=True)
        bot.send_message(call.message.chat.id, f"⚠️ {PAYMENT_DISABLED_TEXT}", reply_markup=back_kb())
        return
    bot.answer_callback_query(call.id)

    price = db.location_price(loc, months)
    days = db.TARIFF_DAYS[months]
    payment_id = db.create_payment(call.from_user.id, loc["id"], months, days, price)
    try:
        platega_id, pay_url = platega.create_payment(
            amount_rub=price,
            description=f"VPN подписка {loc['title']}, {MONTHS_WORD[months]}",
            payload=f"payment:{payment_id}",
            user_id=call.from_user.id,
            username=call.from_user.username,
        )
        db.set_payment_platega_id(payment_id, platega_id)
    except Exception as e:
        print(f"[platega] create error: {e}")
        bot.send_message(call.message.chat.id, f"⚠️ {PAYMENT_DISABLED_TEXT}", reply_markup=back_kb())
        return

    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"💳 Оплатить {price} ₽", url=pay_url))
    kb.add(InlineKeyboardButton("✅ Я оплатил — проверить", callback_data=f"check_pay:{payment_id}"))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(call.message.chat.id,
                     f"🧾 <b>Оплата подписки</b>\n\n"
                     f"🌍 Сервер: <b>{loc['title']}</b>\n"
                     f"📅 Срок: <b>{MONTHS_WORD[months]}</b>\n"
                     f"💰 Сумма: <b>{price} ₽</b>\n\n"
                     f"Нажми кнопку оплаты, оплати удобным способом на странице Platega, "
                     f"затем вернись сюда и нажми «Я оплатил — проверить». "
                     f"Подписка также выдастся автоматически в течение минуты после оплаты.",
                     reply_markup=kb)


def issue_payment(payment) -> bool:
    """Выдаёт подписку по оплаченному платежу. True = выдано."""
    loc = db.get_location(payment["location_id"])
    user_id = payment["user_id"]
    days = int(payment["days"])
    # Накопленные реферальные бонусные дни добавляем к покупке
    user = db.get_user(user_id)
    bonus = int(user["bonus_days"]) if user else 0
    sub = give_subscription(user_id, loc, days + bonus, is_trial=False)
    if bonus:
        db.add_bonus_days(user_id, -bonus)
    db.mark_payment_issued(payment["id"])
    try:
        bot.send_message(user_id,
                         f"🎉 <b>Оплата прошла успешно!</b>\n\n"
                         f"🌍 Сервер: <b>{loc['title']}</b>\n"
                         f"📅 Подписка до: <b>{fmt_date(sub['expire_at'])}</b>"
                         + (f"\n⭐️ Применено бонусных дней: +{bonus}" if bonus else ""))
        show_device_choice(user_id, sub["id"], devices_header(sub))
    except Exception as e:
        print(f"[issue] notify error: {e}")
    return True


_process_lock = threading.Lock()  # чтобы кнопка и фоновый процесс не выдали подписку дважды


def process_payment(payment_id) -> str:
    """Проверяет статус в Platega и выдаёт подписку, если оплачено. Возвращает статус для юзера."""
    with _process_lock:
        return _process_payment_locked(payment_id)


def _process_payment_locked(payment_id) -> str:
    payment = db.get_payment(payment_id)
    if not payment:
        return "not_found"
    if payment["issued"]:
        return "issued"
    if payment["status"] != "paid":
        try:
            status = platega.check_payment(payment["platega_id"])
        except Exception as e:
            print(f"[platega] check error: {e}")
            return "error"
        if status == "CONFIRMED":
            db.set_payment_status(payment_id, "paid")
        elif status == "CANCELED":
            db.set_payment_status(payment_id, "canceled")
            return "canceled"
        else:
            return "pending"
    # сюда попадаем, если status == paid (по проверке выше, по callback или webhook.py)
    try:
        issue_payment(db.get_payment(payment_id))
        return "issued"
    except Exception as e:
        print(f"[issue] Marzban error: {e}")
        return "error"


@bot.callback_query_handler(func=lambda c: c.data.startswith("check_pay:"))
def cb_check_pay(call):
    payment_id = int(call.data.split(":")[1])
    payment = db.get_payment(payment_id)
    if not payment or payment["user_id"] != call.from_user.id:
        bot.answer_callback_query(call.id, "Платёж не найден", show_alert=True)
        return
    result = process_payment(payment_id)
    answers = {
        "issued": "✅ Оплата подтверждена! Подписка выдана — смотри сообщение выше 👆",
        "pending": "⏳ Оплата пока не поступила. Если ты уже оплатил — подожди минуту и нажми ещё раз.",
        "canceled": "❌ Платёж отменён. Попробуй оформить заново.",
        "error": "⚠️ Оплата, возможно, прошла, но возникла ошибка выдачи. Подписка выдастся автоматически, либо напиши в поддержку.",
    }
    bot.answer_callback_query(call.id, answers.get(result, ""), show_alert=True)


def payment_checker_loop():
    """Фон: каждые 30 сек проверяем pending-платежи и выдаём оплаченные (страховка к webhook)."""
    while True:
        try:
            for payment in db.get_unissued_payments():
                process_payment(payment["id"])
        except Exception as e:
            print(f"[checker] {e}")
        time.sleep(30)


# ============================================================
#  ВЫБОР УСТРОЙСТВА И ИНСТРУКЦИИ
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data.startswith("devices:"))
def cb_devices(call):
    bot.answer_callback_query(call.id)
    sub = _get_sub_for_user(int(call.data.split(":")[1]), call.from_user.id)
    if not sub:
        bot.send_message(call.message.chat.id, "Подписка не найдена.", reply_markup=back_kb())
        return
    show_device_choice(call.message.chat.id, sub["id"], devices_header(sub))


@bot.callback_query_handler(func=lambda c: c.data.startswith("device:"))
def cb_device(call):
    bot.answer_callback_query(call.id)
    _, sub_id, device = call.data.split(":")
    sub = _get_sub_for_user(int(sub_id), call.from_user.id)
    if not sub:
        bot.send_message(call.message.chat.id, "Подписка не найдена.", reply_markup=back_kb())
        return
    text = INSTRUCTIONS[device].format(sub_url=sub["sub_url"])
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🔗 Открыть ссылку подписки", url=sub["sub_url"]))
    kb.add(InlineKeyboardButton("⬅️ К выбору устройства", callback_data=f"devices:{sub['id']}"))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(call.message.chat.id, text, reply_markup=kb, disable_web_page_preview=True)


def _get_sub_for_user(sub_id, user_id):
    for s in db.get_user_subscriptions(user_id):
        if s["id"] == sub_id:
            return s
    return None


# ============================================================
#  ПРОБНАЯ ПОДПИСКА (7 ДНЕЙ) — только после подписки на канал
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "trial")
def cb_trial(call):
    bot.answer_callback_query(call.id)
    user = db.get_user(call.from_user.id)
    if user and user["trial_used"]:
        bot.send_message(call.message.chat.id,
                         "🎁 Пробный период уже был использован.\n"
                         "Оформи полную подписку — от 100 ₽ 👇", reply_markup=back_kb())
        # сразу покажем локации для покупки
        bot.send_message(call.message.chat.id, "🌍 <b>Выбери сервер:</b>",
                         reply_markup=locations_kb("buy_loc"))
        return
    if not is_subscribed(call.from_user.id):
        ask_channel(call.message.chat.id, "check_trial", why="trial")
        return
    _show_trial_locations(call.message.chat.id)


def _show_trial_locations(chat_id):
    bot.send_message(chat_id,
                     "🎁 <b>Пробная подписка на 7 дней</b>\n\n🌍 Выбери сервер:",
                     reply_markup=locations_kb("trial_loc"))


@bot.callback_query_handler(func=lambda c: c.data == "check_trial")
def cb_check_trial(call):
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Ты пока не подписан на канал. Подпишись и нажми ещё раз.",
                                  show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ Подписка на канал подтверждена!")
    try_reward_referral(call.from_user.id)  # если этого юзера кто-то пригласил — начислим бонус пригласившему
    _show_trial_locations(call.message.chat.id)


@bot.callback_query_handler(func=lambda c: c.data.startswith("trial_loc:"))
def cb_trial_loc(call):
    user = db.get_user(call.from_user.id)
    if user and user["trial_used"]:
        bot.answer_callback_query(call.id, "Пробный период уже использован", show_alert=True)
        return
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "Сначала подпишись на канал", show_alert=True)
        ask_channel(call.message.chat.id, "check_trial", why="trial")
        return
    bot.answer_callback_query(call.id)
    loc = db.get_location(int(call.data.split(":")[1]))
    try:
        # реферальные бонусные дни нового юзера тоже можно применить к триалу
        bonus = int(user["bonus_days"]) if user else 0
        sub = give_subscription(call.from_user.id, loc, config.TRIAL_DAYS + bonus, is_trial=True)
        if bonus:
            db.add_bonus_days(call.from_user.id, -bonus)
        db.mark_trial_used(call.from_user.id)
    except Exception as e:
        print(f"[trial] Marzban error: {e}")
        bot.send_message(call.message.chat.id,
                         "⚠️ Не удалось создать пробную подписку (сервер недоступен). "
                         "Попробуй позже или напиши в поддержку.", reply_markup=back_kb())
        return
    try_reward_referral(call.from_user.id)
    show_device_choice(call.message.chat.id, sub["id"],
                       f"🎁 <b>Пробная подписка активирована на {config.TRIAL_DAYS} дней!</b>\n\n"
                       + devices_header(sub))


# ============================================================
#  РЕФЕРАЛЬНАЯ СИСТЕМА (+7 дней) — только после подписки на канал
# ============================================================
@bot.callback_query_handler(func=lambda c: c.data == "referral")
def cb_referral(call):
    bot.answer_callback_query(call.id)
    if not is_subscribed(call.from_user.id):
        ask_channel(call.message.chat.id, "check_referral", why="referral")
        return
    _show_referral(call.message.chat.id, call.from_user.id)


@bot.callback_query_handler(func=lambda c: c.data == "check_referral")
def cb_check_referral(call):
    if not is_subscribed(call.from_user.id):
        bot.answer_callback_query(call.id, "❌ Ты пока не подписан на канал. Подпишись и нажми ещё раз.",
                                  show_alert=True)
        return
    bot.answer_callback_query(call.id, "✅ Подписка на канал подтверждена!")
    try_reward_referral(call.from_user.id)
    _show_referral(call.message.chat.id, call.from_user.id)


def _show_referral(chat_id, user_id):
    me = bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user_id}"
    total, rewarded = db.referral_stats(user_id)
    user = db.get_user(user_id)
    text = (
        f"👥 <b>Реферальная система</b>\n\n"
        f"Приглашай друзей и получай <b>+{config.REFERRAL_BONUS_DAYS} дней</b> к подписке "
        f"за каждого друга!\n\n"
        f"⚠️ Бонус начисляется, только когда приглашённый друг "
        f"<b>зайдёт в бот по твоей ссылке И вступит в наш канал</b>.\n\n"
        f"🔗 Твоя ссылка (нажми, чтобы скопировать):\n<code>{link}</code>\n\n"
        f"📊 Приглашено: <b>{total}</b> · бонус получен за: <b>{rewarded}</b>\n"
        f"⭐️ Накоплено бонусных дней: <b>{user['bonus_days'] if user else 0}</b>\n\n"
        f"Бонусные дни автоматически продлят активную подписку, а если её нет — "
        f"прибавится к первой покупке или пробной подписке."
    )
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("📢 Наш канал", url=config.CHANNEL_URL))
    kb.add(InlineKeyboardButton("⬅️ В главное меню", callback_data="menu"))
    bot.send_message(chat_id, text, reply_markup=kb)


# ============================================================
#  АДМИНКА
# ============================================================
def _admin_only(message) -> bool:
    if not is_admin(message.from_user.id):
        bot.reply_to(message, "⛔️ Нет доступа.")
        return False
    return True


@bot.message_handler(commands=["admin"])
def cmd_admin(message):
    if not _admin_only(message):
        return
    bot.send_message(message.chat.id,
                     "🛠 <b>Админ-команды:</b>\n\n"
                     "/add_location — добавить новый сервер (секцию)\n"
                     "/locations — список серверов: вкл/выкл, удалить\n"
                     "/edit_price — изменить цены сервера\n"
                     "/broadcast — рассылка всем пользователям\n"
                     "/payment_toggle — вкл/выкл заглушку оплаты\n"
                     "/stats — статистика\n"
                     "/cancel — отменить текущее действие")


@bot.message_handler(commands=["cancel"])
def cmd_cancel(message):
    _admin_temp.pop(message.from_user.id, None)
    bot.send_message(message.chat.id, "❌ Действие отменено.")


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not _admin_only(message):
        return
    s = db.stats()
    bot.send_message(message.chat.id,
                     f"📊 <b>Статистика</b>\n\n"
                     f"👥 Пользователей: <b>{s['users']}</b>\n"
                     f"🟢 Активных подписок: <b>{s['active_subs']}</b>\n"
                     f"💳 Оплаченных платежей: <b>{s['paid_payments']}</b>\n"
                     f"💰 Выручка: <b>{s['revenue']} ₽</b>\n"
                     f"💸 Оплата сейчас: <b>{'включена ✅' if db.payment_enabled() else 'ВЫКЛЮЧЕНА (заглушка) ⛔️'}</b>")


@bot.message_handler(commands=["payment_toggle"])
def cmd_payment_toggle(message):
    if not _admin_only(message):
        return
    new_val = "0" if db.payment_enabled() else "1"
    db.set_setting("payment_enabled", new_val)
    bot.send_message(message.chat.id,
                     "💸 Оплата <b>ВКЛЮЧЕНА</b> ✅" if new_val == "1" else
                     f"💸 Оплата <b>ВЫКЛЮЧЕНА</b> ⛔️\nТеперь при оплате бот пишет: «{PAYMENT_DISABLED_TEXT}»")


# ---------- Добавление локации ----------
@bot.message_handler(commands=["add_location"])
def cmd_add_location(message):
    if not _admin_only(message):
        return
    _admin_temp[message.from_user.id] = {}
    msg = bot.send_message(message.chat.id,
                           "➕ <b>Добавление сервера</b>\n\nШаг 1/4. Пришли название для кнопки, "
                           "например: <code>🇩🇪 Германия</code>\n(/cancel — отмена)")
    bot.register_next_step_handler(msg, _add_loc_step_title)


def _add_loc_step_title(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    _admin_temp[message.from_user.id]["title"] = message.text.strip()
    msg = bot.send_message(message.chat.id,
                           "Шаг 2/4. Пришли <b>код латиницей</b> (для имени юзера в Marzban), "
                           "например: <code>de</code>")
    bot.register_next_step_handler(msg, _add_loc_step_code)


def _add_loc_step_code(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    code = message.text.strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{2,10}", code):
        msg = bot.send_message(message.chat.id, "❌ Код: только латиница/цифры/_ , 2–10 символов. Ещё раз:")
        return bot.register_next_step_handler(msg, _add_loc_step_code)
    if db.get_location_by_code(code):
        msg = bot.send_message(message.chat.id, "❌ Такой код уже есть. Пришли другой:")
        return bot.register_next_step_handler(msg, _add_loc_step_code)
    _admin_temp[message.from_user.id]["code"] = code
    msg = bot.send_message(message.chat.id,
                           f"Шаг 3/4. Пришли <b>тег инбаунда</b> из Marzban для протокола "
                           f"<b>{config.MARZBAN_PROTOCOL}</b> (точное название из панели Marzban → Inbounds), "
                           f"например: <code>VLESS-TCP-DE</code>")
    bot.register_next_step_handler(msg, _add_loc_step_inbound)


def _add_loc_step_inbound(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    _admin_temp[message.from_user.id]["inbounds"] = {config.MARZBAN_PROTOCOL: [message.text.strip()]}
    msg = bot.send_message(message.chat.id,
                           "Шаг 4/4. Пришли <b>4 цены в рублях через пробел</b>: "
                           "за 1, 3, 6 и 12 месяцев.\nНапример: <code>100 270 480 840</code>")
    bot.register_next_step_handler(msg, _add_loc_step_prices)


def _add_loc_step_prices(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    try:
        prices = [int(x) for x in message.text.split()]
        assert len(prices) == 4 and all(p > 0 for p in prices)
    except Exception:
        msg = bot.send_message(message.chat.id, "❌ Нужно ровно 4 числа через пробел. Ещё раз:")
        return bot.register_next_step_handler(msg, _add_loc_step_prices)
    data = _admin_temp.pop(message.from_user.id, {})
    loc = db.add_location(data["code"], data["title"], data["inbounds"], *prices)
    bot.send_message(message.chat.id,
                     f"✅ Сервер добавлен и уже виден в «Подключиться»:\n\n"
                     f"<b>{loc['title']}</b> (код: <code>{loc['code']}</code>)\n"
                     f"Цены: 1 мес — {prices[0]} ₽ · 3 мес — {prices[1]} ₽ · "
                     f"6 мес — {prices[2]} ₽ · 12 мес — {prices[3]} ₽")


# ---------- Список локаций: вкл/выкл, удаление ----------
@bot.message_handler(commands=["locations"])
def cmd_locations(message):
    if not _admin_only(message):
        return
    locs = db.get_locations(only_active=False)
    if not locs:
        return bot.send_message(message.chat.id, "Локаций нет.")
    kb = InlineKeyboardMarkup()
    text = "🌍 <b>Все серверы:</b>\n\n"
    for loc in locs:
        status = "✅ активен" if loc["is_active"] else "⛔️ скрыт"
        text += (f"<b>{loc['title']}</b> (<code>{loc['code']}</code>) — {status}\n"
                 f"Цены: {loc['price_1']} / {loc['price_3']} / {loc['price_6']} / {loc['price_12']} ₽\n\n")
        kb.add(
            InlineKeyboardButton(f"{'⛔️ Выкл' if loc['is_active'] else '✅ Вкл'} {loc['title']}",
                                 callback_data=f"ltgl:{loc['id']}"),
            InlineKeyboardButton(f"🗑 {loc['title']}", callback_data=f"ldel:{loc['id']}"),
        )
    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ltgl:"))
def cb_loc_toggle(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    loc = db.get_location(int(call.data.split(":")[1]))
    db.set_location_active(loc["id"], not loc["is_active"])
    bot.answer_callback_query(call.id, f"{loc['title']}: {'скрыт' if loc['is_active'] else 'активен'}")
    bot.send_message(call.message.chat.id, "Обнови список: /locations")


@bot.callback_query_handler(func=lambda c: c.data.startswith("ldel:"))
def cb_loc_delete(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    loc_id = int(call.data.split(":")[1])
    loc = db.get_location(loc_id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("🗑 Да, скрыть сервер", callback_data=f"ldelc:{loc_id}"),
           InlineKeyboardButton("Отмена", callback_data="menu"))
    # Удаление делаем "мягким" (is_active=0), чтобы не ломать уже выданные подписки и историю платежей
    bot.send_message(call.message.chat.id,
                     f"Скрыть сервер <b>{loc['title']}</b> из продажи? "
                     f"Уже выданные подписки продолжат работать.", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ldelc:"))
def cb_loc_delete_confirm(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    db.set_location_active(int(call.data.split(":")[1]), False)
    bot.answer_callback_query(call.id, "Сервер скрыт")
    bot.send_message(call.message.chat.id, "✅ Сервер скрыт из продажи. "
                                           "Вернуть обратно: /locations → «Вкл».")


# ---------- Изменение цен ----------
@bot.message_handler(commands=["edit_price"])
def cmd_edit_price(message):
    if not _admin_only(message):
        return
    bot.send_message(message.chat.id, "💰 <b>Изменение цен.</b> Выбери сервер:",
                     reply_markup=locations_kb("eploc", only_active=False))


@bot.callback_query_handler(func=lambda c: c.data.startswith("eploc:"))
def cb_edit_price_loc(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    bot.answer_callback_query(call.id)
    loc = db.get_location(int(call.data.split(":")[1]))
    kb = InlineKeyboardMarkup()
    for months in (1, 3, 6, 12):
        kb.add(InlineKeyboardButton(
            f"{MONTHS_WORD[months]} — сейчас {db.location_price(loc, months)} ₽",
            callback_data=f"ep:{loc['id']}:{months}"))
    bot.send_message(call.message.chat.id, f"💰 <b>{loc['title']}</b>. Какой тариф изменить?",
                     reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data.startswith("ep:"))
def cb_edit_price_period(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    bot.answer_callback_query(call.id)
    _, loc_id, months = call.data.split(":")
    _admin_temp[call.from_user.id] = {"price_loc": int(loc_id), "price_months": int(months)}
    msg = bot.send_message(call.message.chat.id,
                           f"Пришли новую цену в рублях за {MONTHS_WORD[int(months)]} "
                           f"(только число). /cancel — отмена")
    bot.register_next_step_handler(msg, _edit_price_input)


def _edit_price_input(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    data = _admin_temp.pop(message.from_user.id, {})
    try:
        price = int(message.text.strip())
        assert price > 0
    except Exception:
        msg = bot.send_message(message.chat.id, "❌ Нужно целое число больше 0. Ещё раз:")
        _admin_temp[message.from_user.id] = data
        return bot.register_next_step_handler(msg, _edit_price_input)
    db.set_location_price(data["price_loc"], data["price_months"], price)
    loc = db.get_location(data["price_loc"])
    bot.send_message(message.chat.id,
                     f"✅ Цена обновлена: <b>{loc['title']}</b>, "
                     f"{MONTHS_WORD[data['price_months']]} — теперь <b>{price} ₽</b>.\n"
                     f"Все цены сервера: {loc['price_1']} / {loc['price_3']} / "
                     f"{loc['price_6']} / {loc['price_12']} ₽ "
                     f"(уже обновлённая цена подтянется при следующем открытии — проверь /locations)")


# ---------- Рассылка ----------
@bot.message_handler(commands=["broadcast"])
def cmd_broadcast(message):
    if not _admin_only(message):
        return
    msg = bot.send_message(message.chat.id,
                           "📣 <b>Рассылка</b>\n\nПришли сообщение для рассылки всем пользователям: "
                           "текст, фото, видео — что угодно. Я покажу предпросмотр перед отправкой.\n"
                           "/cancel — отмена")
    bot.register_next_step_handler(msg, _broadcast_preview)


def _broadcast_preview(message):
    if message.text and message.text.strip() == "/cancel":
        return cmd_cancel(message)
    _admin_temp[message.from_user.id] = {"bcast_chat": message.chat.id, "bcast_msg": message.message_id}
    bot.copy_message(message.chat.id, message.chat.id, message.message_id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(f"📣 Разослать всем ({len(db.all_user_ids())} чел.)",
                                callback_data="bcast_go"),
           InlineKeyboardButton("❌ Отмена", callback_data="bcast_cancel"))
    bot.send_message(message.chat.id, "☝️ Так будет выглядеть рассылка. Отправляем?", reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data in ("bcast_go", "bcast_cancel"))
def cb_broadcast(call):
    if not is_admin(call.from_user.id):
        return bot.answer_callback_query(call.id, "⛔️ Нет доступа", show_alert=True)
    data = _admin_temp.pop(call.from_user.id, {})
    if call.data == "bcast_cancel" or not data:
        bot.answer_callback_query(call.id, "Рассылка отменена")
        return bot.send_message(call.message.chat.id, "❌ Рассылка отменена.")
    bot.answer_callback_query(call.id, "Рассылка началась…")
    ok = fail = 0
    for user_id in db.all_user_ids():
        try:
            bot.copy_message(user_id, data["bcast_chat"], data["bcast_msg"])
            ok += 1
        except Exception:
            fail += 1  # юзер заблокировал бота и т.п.
        time.sleep(0.05)  # не упираемся в лимиты Telegram
    bot.send_message(call.message.chat.id,
                     f"📣 <b>Рассылка завершена</b>\n✅ Доставлено: {ok}\n❌ Не доставлено: {fail}")


# ============================================================
#  ЗАПУСК
# ============================================================
if __name__ == "__main__":
    threading.Thread(target=payment_checker_loop, daemon=True).start()
    try:
        bot.set_my_commands([
            telebot.types.BotCommand("start", "Главное меню"),
            telebot.types.BotCommand("admin", "Админка (только для админов)"),
        ])
    except Exception:
        pass
    print("🤖 Бот запущен")
    # chat_member нужен, чтобы ловить вступление приглашённых в канал для реферального бонуса
    bot.infinity_polling(skip_pending=True,
                         allowed_updates=["message", "callback_query", "chat_member"])
