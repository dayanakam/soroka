"""Хранение профилей и памяти о том, что уже показывали."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config

DEFAULT_PROFILE: dict[str, Any] = {
    "styles": [],
    "categories": ["tops", "bottoms", "dresses", "outerwear", "knit",
                   "shoes", "bags", "accessories", "lingerie", "swim"],
    "sizes": {"top": "M", "bottom": "46", "jeans": "28", "shoes": "38"},
    "budgetMin": 1500,
    "budgetMax": 25000,
    "minDiscount": "any",
    "veto": [],
    "brands": ["Mango", "Befree", "EKONIKA", "calzedonia"],
    "paused": False,
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    chat_id    INTEGER PRIMARY KEY,
    username   TEXT,
    first_name TEXT,
    profile    TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS seen (
    chat_id    INTEGER NOT NULL,
    item_id    TEXT    NOT NULL,
    price      INTEGER NOT NULL,
    shown_at   REAL    NOT NULL,
    PRIMARY KEY (chat_id, item_id)
);
CREATE INDEX IF NOT EXISTS seen_shown ON seen (shown_at);
CREATE TABLE IF NOT EXISTS wizard (
    chat_id INTEGER PRIMARY KEY,
    state   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS uploads (
    key      TEXT PRIMARY KEY,
    file_id  TEXT NOT NULL
);
"""


def _conn() -> sqlite3.Connection:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(config.DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


def get_profile(chat_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT profile FROM users WHERE chat_id=?", (chat_id,)).fetchone()
    if not row:
        return None
    saved = json.loads(row["profile"])
    return {**DEFAULT_PROFILE, **saved}


def save_profile(chat_id: int, profile: dict[str, Any],
                 username: str = "", first_name: str = "") -> None:
    now = time.time()
    merged = {**DEFAULT_PROFILE, **profile}
    with _conn() as c:
        c.execute(
            """INSERT INTO users (chat_id, username, first_name, profile, created_at, updated_at)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(chat_id) DO UPDATE SET
                 profile=excluded.profile,
                 username=COALESCE(NULLIF(excluded.username,''), users.username),
                 first_name=COALESCE(NULLIF(excluded.first_name,''), users.first_name),
                 updated_at=excluded.updated_at""",
            (chat_id, username, first_name, json.dumps(merged, ensure_ascii=False), now, now),
        )


def all_chats() -> list[int]:
    with _conn() as c:
        return [r["chat_id"] for r in c.execute("SELECT chat_id FROM users")]


def all_active_chats() -> list[int]:
    """Те, у кого заполнен профиль и не стоит пауза."""
    out = []
    with _conn() as c:
        for row in c.execute("SELECT chat_id, profile FROM users"):
            p = json.loads(row["profile"])
            if p.get("styles") and not p.get("paused"):
                out.append(row["chat_id"])
    return out


def set_paused(chat_id: int, paused: bool) -> None:
    p = get_profile(chat_id)
    if p is None:
        return
    p["paused"] = paused
    save_profile(chat_id, p)


def filter_unseen(chat_id: int, items: list[dict]) -> list[dict]:
    """Убирает то, что уже показывали — кроме случая, когда цена заметно упала."""
    if not items:
        return []
    ids = [str(i["id"]) for i in items]
    marks = ",".join("?" * len(ids))
    with _conn() as c:
        rows = c.execute(
            f"SELECT item_id, price FROM seen WHERE chat_id=? AND item_id IN ({marks})",
            (chat_id, *ids),
        ).fetchall()
    before = {r["item_id"]: r["price"] for r in rows}
    fresh = []
    for it in items:
        old = before.get(str(it["id"]))
        if old is None or it["price"] <= old * 0.85:
            fresh.append(it)
    return fresh


def mark_seen(chat_id: int, items: list[dict]) -> None:
    now = time.time()
    with _conn() as c:
        c.executemany(
            """INSERT INTO seen (chat_id, item_id, price, shown_at) VALUES (?,?,?,?)
               ON CONFLICT(chat_id, item_id) DO UPDATE SET
                 price=excluded.price, shown_at=excluded.shown_at""",
            [(chat_id, str(i["id"]), i["price"], now) for i in items],
        )


# --- состояние анкеты: на каком шаге человек и что уже выбрал ---

def get_state(chat_id: int) -> dict[str, Any] | None:
    with _conn() as c:
        row = c.execute("SELECT state FROM wizard WHERE chat_id=?", (chat_id,)).fetchone()
    return json.loads(row["state"]) if row else None


def set_state(chat_id: int, state: dict[str, Any]) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO wizard (chat_id, state) VALUES (?,?)
                     ON CONFLICT(chat_id) DO UPDATE SET state=excluded.state""",
                  (chat_id, json.dumps(state, ensure_ascii=False)))


def clear_state(chat_id: int) -> None:
    with _conn() as c:
        c.execute("DELETE FROM wizard WHERE chat_id=?", (chat_id,))


# --- file_id картинок: Telegram хранит их у себя, второй раз не заливаем ---

def get_file_id(key: str) -> str | None:
    with _conn() as c:
        row = c.execute("SELECT file_id FROM uploads WHERE key=?", (key,)).fetchone()
    return row["file_id"] if row else None


def set_file_id(key: str, file_id: str) -> None:
    with _conn() as c:
        c.execute("""INSERT INTO uploads (key, file_id) VALUES (?,?)
                     ON CONFLICT(key) DO UPDATE SET file_id=excluded.file_id""",
                  (key, file_id))


def prune_seen(days: int = 120) -> None:
    cutoff = time.time() - days * 86400
    with _conn() as c:
        c.execute("DELETE FROM seen WHERE shown_at < ?", (cutoff,))
