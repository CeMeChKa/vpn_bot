# -*- coding: utf-8 -*-
"""
НЕОБЯЗАТЕЛЬНЫЙ приёмник callback от Platega.
Бот и без него работает: он сам каждые 30 секунд проверяет платежи + есть кнопка
"Я оплатил — проверить". Webhook нужен только для мгновенной выдачи.

Запуск отдельно:  python webhook.py
В личном кабинете Platega укажи Callback URL: https://твой-домен/platega-callback
Platega пришлёт POST {id, amount, currency, status} с заголовками X-MerchantId / X-Secret.
Мы проверяем заголовки, помечаем платёж paid в общей БД, а бот (фоновый процесс проверки)
выдаст подписку в течение 30 секунд.
"""
import os
from flask import Flask, request

import config
import database as db

db.init_db()
app = Flask(__name__)


@app.route("/platega-callback", methods=["POST"])
def platega_callback():
    if (request.headers.get("X-MerchantId") != config.PLATEGA_MERCHANT_ID
            or request.headers.get("X-Secret") != config.PLATEGA_SECRET):
        return "forbidden", 403

    data = request.get_json(silent=True) or {}
    platega_id = str(data.get("id") or "")
    status = str(data.get("status") or "").upper()
    print(f"[webhook] {platega_id} -> {status}")

    payment = db.get_payment_by_platega(platega_id) if platega_id else None
    if not payment and str(data.get("payload", "")).startswith("payment:"):
        try:
            payment = db.get_payment(int(str(data["payload"]).split(":")[1]))
        except Exception:
            payment = None
    if payment:
        if status == "CONFIRMED":
            db.set_payment_status(payment["id"], "paid")
        elif status in ("CANCELED", "CHARGEBACKED"):
            db.set_payment_status(payment["id"], "canceled")
    return "ok", 200


@app.route("/health")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("WEBHOOK_PORT", "8080")))
