# -*- coding: utf-8 -*-
"""
Простая обёртка над Marzban API.
Документация Marzban: панель -> Docs (Swagger) по адресу  {MARZBAN_URL}/docs
Основные методы: получить токен -> создать юзера / продлить юзера -> взять subscription_url
"""
import time
import requests

import config

_token = {"value": None, "exp": 0}


def _get_token():
    if _token["value"] and _token["exp"] > time.time():
        return _token["value"]
    r = requests.post(
        f"{config.MARZBAN_URL}/api/admin/token",
        data={"username": config.MARZBAN_USERNAME, "password": config.MARZBAN_PASSWORD},
        timeout=15,
    )
    r.raise_for_status()
    _token["value"] = r.json()["access_token"]
    _token["exp"] = time.time() + 60 * 60 * 12  # токен Marzban живёт дольше, обновляем с запасом
    return _token["value"]


def _headers():
    return {"Authorization": f"Bearer {_get_token()}", "Content-Type": "application/json"}


def _full_sub_url(user_data: dict) -> str:
    url = user_data.get("subscription_url") or ""
    if url.startswith("/"):
        url = config.MARZBAN_URL + url
    return url


def get_user(username: str):
    r = requests.get(f"{config.MARZBAN_URL}/api/user/{username}", headers=_headers(), timeout=15)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def create_or_extend_user(username: str, inbounds: dict, days: int):
    """
    Создаёт юзера в Marzban или продлевает существующего на `days` дней.
    Возвращает (subscription_url, expire_at_unix).
    Если подписка ещё активна — дни ПЛЮСУЮТСЯ к текущей дате окончания, если истекла — от сегодня.
    """
    now = int(time.time())
    add_seconds = int(days) * 86400
    existing = get_user(username)

    if existing:
        current_expire = int(existing.get("expire") or 0)
        new_expire = (current_expire if current_expire > now else now) + add_seconds
        payload = {
            "proxies": existing.get("proxies") or {config.MARZBAN_PROTOCOL: {}},
            "inbounds": inbounds,
            "expire": new_expire,
            "data_limit": config.DATA_LIMIT_BYTES,
            "status": "active",
        }
        r = requests.put(f"{config.MARZBAN_URL}/api/user/{username}",
                         json=payload, headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()
    else:
        new_expire = now + add_seconds
        payload = {
            "username": username,
            "proxies": {config.MARZBAN_PROTOCOL: {}},
            "inbounds": inbounds,
            "expire": new_expire,
            "data_limit": config.DATA_LIMIT_BYTES,
            "data_limit_reset_strategy": "no_reset",
            "status": "active",
            "note": "created by telegram bot",
        }
        r = requests.post(f"{config.MARZBAN_URL}/api/user",
                          json=payload, headers=_headers(), timeout=15)
        r.raise_for_status()
        data = r.json()

    return _full_sub_url(data), new_expire


def set_user_expire(username: str, new_expire: int, inbounds: dict = None):
    """Точная установка даты окончания (используется для реферального бонуса +7 дней)."""
    existing = get_user(username)
    if not existing:
        return None
    payload = {
        "proxies": existing.get("proxies") or {config.MARZBAN_PROTOCOL: {}},
        "inbounds": inbounds or existing.get("inbounds") or {},
        "expire": int(new_expire),
        "data_limit": config.DATA_LIMIT_BYTES,
        "status": "active",
    }
    r = requests.put(f"{config.MARZBAN_URL}/api/user/{username}",
                     json=payload, headers=_headers(), timeout=15)
    r.raise_for_status()
    return _full_sub_url(r.json())
