# -*- coding: utf-8 -*-
"""
============================================================
  ЕДИНСТВЕННОЕ МЕСТО, ГДЕ НУЖНО ВПИСЫВАТЬ СВОИ ДАННЫЕ
  Все секреты можно либо вписать прямо сюда, либо (лучше)
  положить в файл .env рядом — см. .env.example
============================================================
"""
import os

# --- .env (необязательно) ---
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
except Exception:
    pass


def _env(name, default=""):
    return os.getenv(name, default)


# ---------------- TELEGRAM BOT ----------------
BOT_TOKEN = _env("BOT_TOKEN", "ВСТАВЬ_ТОКЕН_БОТА_ОТ_BotFather")

# Telegram ID админов через запятую: ADMIN_IDS=111111111,222222222
ADMIN_IDS = [int(x) for x in _env("ADMIN_IDS", "123456789").split(",") if x.strip().isdigit()]

# Канал, на который нужна подписка (для триала и рефералки).
# Бот ОБЯЗАТЕЛЬНО должен быть АДМИНОМ этого канала, иначе не сможет проверить подписку.
# Можно указать "@username_канала" или числовой ID вида -1001234567890
CHANNEL_ID = _env("CHANNEL_ID", "@your_vpn_channel")
CHANNEL_URL = _env("CHANNEL_URL", "https://t.me/your_vpn_channel")

# Оператор: партнёрство и поддержка
OPERATOR_USERNAME = "@theeveryesha"
OPERATOR_URL = "https://t.me/theeveryesha"

# ---------------- MARZBAN ----------------
MARZBAN_URL = _env("MARZBAN_URL", "https://panel.example.com").rstrip("/")  # без слэша в конце
MARZBAN_USERNAME = _env("MARZBAN_USERNAME", "admin")
MARZBAN_PASSWORD = _env("MARZBAN_PASSWORD", "admin_password")

# Протокол и лимит трафика для новых пользователей Marzban
MARZBAN_PROTOCOL = "vless"          # если у тебя другой протокол - поменяй здесь и теги при добавлении локации
DATA_LIMIT_BYTES = 0                # 0 = безлимит. Например 100 ГБ = 100 * 1024 * 1024 * 1024

# ---------------- PLATEGA ----------------
# Выдаются в личном кабинете Platega: Настройки -> MerchantId и API ключ (X-Secret)
PLATEGA_MERCHANT_ID = _env("PLATEGA_MERCHANT_ID", "")
PLATEGA_SECRET = _env("PLATEGA_SECRET", "")
PLATEGA_API_URL = "https://app.platega.io"
# Куда Platega вернёт пользователя после оплаты / при неудаче (можно ссылку на бота)
PLATEGA_RETURN_URL = _env("PLATEGA_RETURN_URL", OPERATOR_URL)
PLATEGA_FAILED_URL = _env("PLATEGA_FAILED_URL", OPERATOR_URL)

# ---------------- ЗАГЛУШКА ОПЛАТЫ ----------------
# True  = оплата работает
# False = при нажатии оплаты бот отвечает: "Извините, оплата в данный момент времени недоступна. Попробуйте позже"
# Админ также может переключать это на лету командой /payment_toggle (значение хранится в БД и важнее этого)
PAYMENT_ENABLED = _env("PAYMENT_ENABLED", "true").lower() in ("1", "true", "yes")

# ---------------- ОСТАЛЬНОЕ ----------------
TRIAL_DAYS = 7                 # дней в пробной подписке
REFERRAL_BONUS_DAYS = 7        # +дней пригласившему за каждого друга, вступившего в канал
BANNER_PATH = os.path.join(os.path.dirname(__file__), "banner.jpg")  # <-- СЮДА положи свой баннер главного меню
DB_PATH = os.path.join(os.path.dirname(__file__), "bot.db")

INFO_AGREEMENT_URL = "https://telegra.ph/Polzovatelskoe-soglashenie-10-12-97"
INFO_PRIVACY_URL = "https://telegra.ph/Politika-konfidencialnosti-10-12-146"
