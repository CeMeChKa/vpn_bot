# -*- coding: utf-8 -*-
"""
Оплата через Platega. Документация: https://docs.platega.io
Авторизация: заголовки X-MerchantId и X-Secret.
Создание платежа без заданного метода: POST https://app.platega.io/v2/transaction/process
Проверка статуса:                      GET  https://app.platega.io/transaction/{id}
Статусы: CONFIRMED = оплачено, CANCELED = отменено, PENDING = ожидается.
Callback (если настроишь webhook.py): Platega шлёт POST {id, amount, currency, status, paymentMethod}
с теми же заголовками X-MerchantId / X-Secret.
"""
import requests

import config


def _headers():
    return {
        "X-MerchantId": config.PLATEGA_MERCHANT_ID,
        "X-Secret": config.PLATEGA_SECRET,
        "Content-Type": "application/json",
    }


def create_payment(amount_rub: int, description: str, payload: str, user_id=None, username=None):
    """
    Создаёт платёж. Возвращает (transaction_id, pay_url).
    payload — наша внутренняя метка (например "payment:123"), Platega вернёт её в callback и в статусе.
    """
    body = {
        "paymentDetails": {"amount": int(amount_rub), "currency": "RUB"},
        "description": description,
        "return": config.PLATEGA_RETURN_URL,
        "failedUrl": config.PLATEGA_FAILED_URL,
        "payload": str(payload),
        "metadata": {"userId": str(user_id or ""), "userName": str(username or "")},
    }
    r = requests.post(f"{config.PLATEGA_API_URL}/v2/transaction/process",
                      json=body, headers=_headers(), timeout=20)
    r.raise_for_status()
    data = r.json()
    transaction_id = data.get("transactionId") or data.get("id")
    pay_url = data.get("redirect") or data.get("url")  # в разных ответах поле называется по-разному
    return transaction_id, pay_url


def check_payment(transaction_id: str) -> str:
    """Возвращает статус строкой: CONFIRMED / CANCELED / PENDING / ..."""
    r = requests.get(f"{config.PLATEGA_API_URL}/transaction/{transaction_id}",
                     headers=_headers(), timeout=20)
    r.raise_for_status()
    return (r.json().get("status") or "").upper()
