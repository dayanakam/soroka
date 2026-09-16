#!/usr/bin/env python3
"""Безопасно записывает токен бота в .env.

Ключ берётся из буфера обмена: скопируй его в Telegram и запусти скрипт.
Ничего печатать не нужно. Токен не появляется на экране, не попадает
в историю команд и никуда не отправляется, кроме самого Telegram —
для проверки, что ключ рабочий.

    python set_token.py
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


def from_clipboard() -> str | None:
    """Токен из буфера обмена. Ничего не печатаем — только факт находки."""
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True,
                             timeout=5).stdout
    except Exception:
        return None
    m = TOKEN_RE.search(out or "")
    return m.group(0) if m else None


def clear_clipboard() -> None:
    try:
        subprocess.run(["pbcopy"], input="", text=True, timeout=5)
    except Exception:
        pass


def check(token: str) -> dict:
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


def main() -> None:
    token = from_clipboard()
    if token:
        print(f"Нашла токен в буфере обмена: бот №{token.split(':')[0]}, "
              f"секретная часть скрыта.")
    else:
        print("В буфере обмена токена нет. Скопируй его в Telegram и запусти снова,")
        print("либо вставь сюда вручную — ввод скрыт, на экране ничего не появится.\n")
        token = getpass.getpass("Токен: ").strip().strip('"').strip("'")

    if not token:
        raise SystemExit("Пусто — ничего не записала.")
    if not TOKEN_RE.fullmatch(token):
        raise SystemExit(
            f"Не похоже на токен: {len(token)} символов, "
            f"двоеточие {'есть' if ':' in token else 'отсутствует'}. "
            "Ожидается «цифры:буквы»."
        )

    me = check(token)

    lines = put(read_lines(), "BOT_TOKEN", token)
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    ENV.chmod(0o600)  # читать может только владелец

    print(f"\nГотово. Telegram подтвердил бота:")
    print(f"  имя       {me.get('first_name')}")
    print(f"  username  @{me.get('username')}")
    print(f"  id        {me.get('id')}")
    clear_clipboard()
    print(f"\nКлюч записан в {ENV.name}, доступ только для тебя.")
    print("Буфер обмена очищен, чтобы ключ там не болтался.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nОтменено.")
