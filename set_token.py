#!/usr/bin/env python3
"""Безопасно записывает ключи в .env.

Ключ берётся из буфера обмена: скопируй его и запусти скрипт. Ничего
печатать не нужно. Ключ не появляется на экране, не попадает в историю
команд и никуда не отправляется, кроме самого сервиса — для проверки,
что он рабочий.

    python set_token.py           токен бота от @BotFather
    python set_token.py pexels    ключ Pexels для обложек стилей
"""
import getpass
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

TOKEN_RE = re.compile(r"\d{6,}:[\w-]{30,}")
PEXELS_RE = re.compile(r"[A-Za-z0-9]{40,}")

# Cloudflare у Pexels отбивает запросы без браузерной подписи с ошибкой 1010
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

ENV = Path(__file__).resolve().parent / ".env"
EXAMPLE = Path(__file__).resolve().parent / ".env.example"


def read_lines() -> list[str]:
    src = ENV if ENV.exists() else EXAMPLE
    return src.read_text(encoding="utf-8").splitlines()


def put(lines: list[str], key: str, value: str) -> list[str]:
    """Меняет значение key, сохраняя комментарии. Добавляет строку, если её нет."""
    out, done = [], False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") and not stripped.startswith("#"):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    return out


def from_clipboard(pattern: re.Pattern) -> str | None:
    """Ключ из буфера обмена. Ничего не печатаем — только факт находки."""
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True,
                             timeout=5).stdout
    except Exception:
        return None
    m = pattern.search(out or "")
    return m.group(0) if m else None


def clear_clipboard() -> None:
    try:
        subprocess.run(["pbcopy"], input="", text=True, timeout=5)
    except Exception:
        pass


def check_telegram(token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read())["result"]
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Telegram отверг ключ (HTTP {e.code}). "
            "Скорее всего скопировался не целиком — попробуй ещё раз."
        )
    except Exception as e:
        raise SystemExit(f"Не достучались до Telegram: {type(e).__name__}")


def check_pexels(key: str) -> dict:
    """Поиск у Pexels отвечает и без ключа, поэтому судим по заголовкам лимита:
    их выдают только на запрос с признанным ключом."""
    req = urllib.request.Request(
        "https://api.pexels.com/v1/search?query=coat&per_page=1",
        headers={"Authorization": key, "User-Agent": BROWSER_UA,
                 "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read())
            limit = r.headers.get("X-Ratelimit-Limit")
            left = r.headers.get("X-Ratelimit-Remaining")
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"Pexels отверг ключ (HTTP {e.code}). "
            "Скопировался не целиком или ключ не тот — попробуй ещё раз.")
    except Exception as e:
        raise SystemExit(f"Не достучались до Pexels: {type(e).__name__}")

    out = {"снимков по пробному запросу": data.get("total_results")}
    if limit:
        out["запросов в час"] = limit
        out["осталось сейчас"] = left
    else:
        out["внимание"] = ("Pexels не подтвердил ключ заголовками лимита — "
                           "запишу, но проверь, что скопировала именно ключ")
    return out


SERVICES = {
    "bot": ("BOT_TOKEN", TOKEN_RE, check_telegram,
            "токен бота от @BotFather", "«цифры:буквы»"),
    "pexels": ("PEXELS_API_KEY", PEXELS_RE, check_pexels,
               "ключ Pexels", "длинная строка букв и цифр"),
}


def main() -> None:
    which = (sys.argv[1] if len(sys.argv) > 1 else "bot").lower()
    if which not in SERVICES:
        raise SystemExit(f"Не знаю сервис {which!r}. Доступны: {', '.join(SERVICES)}")
    env_key, pattern, verify, human, shape = SERVICES[which]

    value = from_clipboard(pattern)
    if value:
        print(f"Нашла в буфере обмена {human}, показывать не буду.")
    else:
        print(f"В буфере обмена нет ключа. Скопируй {human} и запусти снова,")
        print("либо вставь сюда вручную — ввод скрыт, на экране ничего не появится.\n")
        value = getpass.getpass("Ключ: ").strip().strip('"').strip("'")

    if not value:
        raise SystemExit("Пусто — ничего не записала.")
    if not pattern.fullmatch(value):
        raise SystemExit(f"Не похоже на ключ: {len(value)} символов. Ожидается {shape}.")

    info = verify(value)

    lines = put(read_lines(), env_key, value)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV.chmod(0o600)

    print("\nПроверено, ключ рабочий:")
    for k, v in info.items():
        print(f"  {k:<12} {v}")
    clear_clipboard()
    print(f"\nЗаписан в {ENV.name} как {env_key}, доступ только для тебя.")
    print("Буфер обмена очищен, чтобы ключ там не болтался.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nОтменено.")
