"""Проверка initData из Telegram Mini App.

Без неё любой мог бы подменить chat_id и переписать чужой профиль.
Алгоритм описан в документации Telegram (Validating data received via the Mini App).
"""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from . import config

MAX_AGE = 24 * 3600


def verify(init_data: str) -> dict | None:
    """Возвращает объект user, если подпись верна и данные свежие. Иначе None."""
    if not init_data or not config.BOT_TOKEN:
        return None

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return None

    received = pairs.pop("hash", None)
    if not received:
        return None

    check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        return None

    try:
        if time.time() - int(pairs.get("auth_date", 0)) > MAX_AGE:
            return None
    except ValueError:
        return None

    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError:
        return None
    return user if user.get("id") else None
