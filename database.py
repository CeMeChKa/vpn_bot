# -*- coding: utf-8 -*-
"""
Работа с SQLite. Все таблицы и все запросы — только здесь.
Тарифы: months -> (дней, подпись). Сами ЦЕНЫ хранятся у каждой локации (сервера),
потому что админ может менять цены для каждого сервера отдельно.
"""
import sqlite3
import threading
import time
import json

import config

_lock = threading.Lock()
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row

# Сколько дней даёт каждый тариф
TARIFF_DAYS = {1: 30, 3: 90, 6: 180, 12: 365}


def _exec(sql, params=(), commit=True):
    with _lock:
        cur = _conn.execute(sql, params)
        if commit:
            _conn.commit()
        return cur


def _one(sql, params=()):
    with _lock:
        return _conn.execute(sql, params).fetchone()


def _all(sql, params=()):
    with _lock:
        return _conn.execute(sql, params).fetchall()


def init_db():
    with _lock:
        _conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       INTEGER PRIMARY KEY,   -- telegram id
            username      TEXT,
            first_name    TEXT,
            referrer_id   INTEGER,               -- кто пригласил (или NULL)
            trial_used    INTEGER DEFAULT 0,     -- 1 = пробник уже брал
            bonus_days    INTEGER DEFAULT 0,     -- накопленные реферальные дни без активной подписки
            created_at    INTEGER
        );

        CREATE TABLE IF NOT EXISTS locations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            code        TEXT UNIQUE,             -- латиницей, напр. pl, de, nl (используется в имени юзера Marzban)
            title       TEXT,                    -- напр. 🇵🇱 Польша
            inbounds    TEXT,                    -- JSON для Marzban, напр. {"vless": ["VLESS-TCP"]}
            price_1     INTEGER,                 -- 1 месяц, руб.
            price_3     INTEGER,                 -- 3 месяца, руб.
            price_6     INTEGER,                 -- 6 месяцев, руб.
            price_12    INTEGER,                 -- 12 месяцев, руб.
            is_active   INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS subscriptions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            location_id      INTEGER,
            marzban_username TEXT,
            sub_url          TEXT,
            expire_at        INTEGER,            -- unix time
            is_trial         INTEGER DEFAULT 0,
            created_at       INTEGER
        );

        CREATE TABLE IF NOT EXISTS payments (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER,
            location_id INTEGER,
            months      INTEGER,
            days        INTEGER,
            amount      INTEGER,
            platega_id  TEXT,
            status      TEXT DEFAULT 'pending',  -- pending / paid / canceled
            issued      INTEGER DEFAULT 0,       -- 1 = подписка уже выдана
            created_at  INTEGER
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,                 -- кто пригласил
            referred_id INTEGER UNIQUE,          -- кого пригласили
            rewarded    INTEGER DEFAULT 0,       -- 1 = бонус +7 дней уже начислен
            created_at  INTEGER
        );

        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        """)
        _conn.commit()

    # Первая локация — Польша. Цены: чем дольше срок, тем дешевле месяц:
    # 100 ₽/мес | 270 ₽ (90 ₽/мес, -10%) | 480 ₽ (80 ₽/мес, -20%) | 840 ₽ (70 ₽/мес, -30%)
    if not get_location_by_code("pl"):
        add_location(
            code="pl",
            title="🇵🇱 Польша",
            inbounds={config.MARZBAN_PROTOCOL: ["VLESS-TCP"]},  # <-- ЗАМЕНИ "VLESS-TCP" на тег своего инбаунда из Marzban!
            price_1=100, price_3=270, price_6=480, price_12=840,
        )
    # Заглушка оплаты: начальное значение из config.py
    if get_setting("payment_enabled") is None:
        set_setting("payment_enabled", "1" if config.PAYMENT_ENABLED else "0")


# ---------------- НАСТРОЙКИ ----------------

def get_setting(key):
    row = _one("SELECT value FROM settings WHERE key=?", (key,))
    return row["value"] if row else None


def set_setting(key, value):
    _exec("INSERT INTO settings(key,value) VALUES(?,?) "
          "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def payment_enabled() -> bool:
    return get_setting("payment_enabled") == "1"


# ---------------- ПОЛЬЗОВАТЕЛИ ----------------

def get_or_create_user(user_id, username=None, first_name=None, referrer_id=None):
    """Создаёт юзера при первом /start. referrer_id засчитывается ТОЛЬКО новому юзеру и не самому себе."""
    user = _one("SELECT * FROM users WHERE user_id=?", (user_id,))
    if user:
        return user, False
    ref = referrer_id if (referrer_id and referrer_id != user_id) else None
    _exec("INSERT INTO users(user_id, username, first_name, referrer_id, created_at) VALUES(?,?,?,?,?)",
          (user_id, username, first_name, ref, int(time.time())))
    if ref:
        _exec("INSERT OR IGNORE INTO referrals(referrer_id, referred_id, created_at) VALUES(?,?,?)",
              (ref, user_id, int(time.time())))
    return _one("SELECT * FROM users WHERE user_id=?", (user_id,)), True


def get_user(user_id):
    return _one("SELECT * FROM users WHERE user_id=?", (user_id,))


def all_user_ids():
    return [r["user_id"] for r in _all("SELECT user_id FROM users")]


def mark_trial_used(user_id):
    _exec("UPDATE users SET trial_used=1 WHERE user_id=?", (user_id,))


def add_bonus_days(user_id, days):
    _exec("UPDATE users SET bonus_days = bonus_days + ? WHERE user_id=?", (days, user_id))


def take_bonus_days(user_id) -> int:
    user = get_user(user_id)
    days = user["bonus_days"] if user else 0
    if days:
        _exec("UPDATE users SET bonus_days=0 WHERE user_id=?", (user_id,))
    return days


# ---------------- ЛОКАЦИИ (СЕРВЕРЫ) ----------------

def add_location(code, title, inbounds: dict, price_1, price_3, price_6, price_12):
    _exec("INSERT INTO locations(code,title,inbounds,price_1,price_3,price_6,price_12) VALUES(?,?,?,?,?,?,?)",
          (code.lower().strip(), title, json.dumps(inbounds, ensure_ascii=False),
           int(price_1), int(price_3), int(price_6), int(price_12)))
    return get_location_by_code(code)


def get_locations(only_active=True):
    sql = "SELECT * FROM locations" + (" WHERE is_active=1" if only_active else "") + " ORDER BY id"
    return _all(sql)


def get_location(location_id):
    return _one("SELECT * FROM locations WHERE id=?", (location_id,))


def get_location_by_code(code):
    return _one("SELECT * FROM locations WHERE code=?", (str(code).lower().strip(),))


def set_location_price(location_id, months, price):
    col = {1: "price_1", 3: "price_3", 6: "price_6", 12: "price_12"}[int(months)]
    _exec(f"UPDATE locations SET {col}=? WHERE id=?", (int(price), location_id))


def set_location_active(location_id, active: bool):
    _exec("UPDATE locations SET is_active=? WHERE id=?", (1 if active else 0, location_id))


def location_price(location, months) -> int:
    return location[{1: "price_1", 3: "price_3", 6: "price_6", 12: "price_12"}[int(months)]]


# ---------------- ПОДПИСКИ ----------------

def get_subscription(user_id, location_id):
    return _one("SELECT * FROM subscriptions WHERE user_id=? AND location_id=? "
                "ORDER BY expire_at DESC LIMIT 1", (user_id, location_id))


def get_user_subscriptions(user_id):
    return _all("""SELECT s.*, l.title AS loc_title, l.code AS loc_code
                   FROM subscriptions s JOIN locations l ON l.id = s.location_id
                   WHERE s.user_id=? ORDER BY s.expire_at DESC""", (user_id,))


def get_active_subscription(user_id):
    """Самая свежая НЕистёкшая подписка юзера (для реферального бонуса)."""
    return _one("""SELECT s.*, l.title AS loc_title FROM subscriptions s
                   JOIN locations l ON l.id = s.location_id
                   WHERE s.user_id=? AND s.expire_at > ? ORDER BY s.expire_at DESC LIMIT 1""",
                (user_id, int(time.time())))


def save_subscription(user_id, location_id, marzban_username, sub_url, expire_at, is_trial=False):
    old = get_subscription(user_id, location_id)
    if old:
        _exec("UPDATE subscriptions SET sub_url=?, expire_at=?, is_trial=? WHERE id=?",
              (sub_url, int(expire_at), 1 if is_trial else 0, old["id"]))
        return get_subscription(user_id, location_id)
    _exec("INSERT INTO subscriptions(user_id,location_id,marzban_username,sub_url,expire_at,is_trial,created_at)"
          " VALUES(?,?,?,?,?,?,?)",
          (user_id, location_id, marzban_username, sub_url, int(expire_at),
           1 if is_trial else 0, int(time.time())))
    return get_subscription(user_id, location_id)


def extend_subscription_db(sub_id, new_expire_at):
    _exec("UPDATE subscriptions SET expire_at=? WHERE id=?", (int(new_expire_at), sub_id))


# ---------------- ПЛАТЕЖИ ----------------

def create_payment(user_id, location_id, months, days, amount):
    cur = _exec("INSERT INTO payments(user_id,location_id,months,days,amount,created_at) VALUES(?,?,?,?,?,?)",
                (user_id, location_id, months, days, amount, int(time.time())))
    return cur.lastrowid


def set_payment_platega_id(payment_id, platega_id):
    _exec("UPDATE payments SET platega_id=? WHERE id=?", (platega_id, payment_id))


def get_payment(payment_id):
    return _one("SELECT * FROM payments WHERE id=?", (payment_id,))


def get_payment_by_platega(platega_id):
    return _one("SELECT * FROM payments WHERE platega_id=?", (platega_id,))


def set_payment_status(payment_id, status):
    _exec("UPDATE payments SET status=? WHERE id=?", (status, payment_id))


def mark_payment_issued(payment_id):
    _exec("UPDATE payments SET status='paid', issued=1 WHERE id=?", (payment_id,))


def get_unissued_payments():
    """Оплаченные, но ещё не выданные + pending (их надо перепроверять в Platega)."""
    return _all("SELECT * FROM payments WHERE issued=0 AND status IN ('pending','paid') ORDER BY id")


# ---------------- РЕФЕРАЛЫ ----------------

def get_referral_by_referred(referred_id):
    return _one("SELECT * FROM referrals WHERE referred_id=?", (referred_id,))


def mark_referral_rewarded(ref_id):
    _exec("UPDATE referrals SET rewarded=1 WHERE id=?", (ref_id,))


def referral_stats(user_id):
    total = _one("SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=?", (user_id,))["c"]
    rewarded = _one("SELECT COUNT(*) AS c FROM referrals WHERE referrer_id=? AND rewarded=1",
                    (user_id,))["c"]
    return total, rewarded


# ---------------- СТАТИСТИКА ----------------

def stats():
    now = int(time.time())
    return {
        "users": _one("SELECT COUNT(*) AS c FROM users")["c"],
        "active_subs": _one("SELECT COUNT(*) AS c FROM subscriptions WHERE expire_at > ?", (now,))["c"],
        "paid_payments": _one("SELECT COUNT(*) AS c FROM payments WHERE status='paid'")["c"],
        "revenue": _one("SELECT COALESCE(SUM(amount),0) AS c FROM payments WHERE status='paid'")["c"],
    }
