"""Хранение профилей и памяти о том, что уже показывали."""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from . import config
from .styles import CATEGORIES

DEFAULT_PROFILE: dict[str, Any] = {
    "styles": [],
    "categories": list(CATEGORIES),      # список один, чтобы не разъезжался
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
CREATE TABLE IF NOT EXISTS feedback (
    chat_id    INTEGER NOT NULL,
    item_id    TEXT    NOT NULL,
    style      TEXT    NOT NULL,
    category   TEXT    NOT NULL,
    brand      TEXT    NOT NULL,
    price      INTEGER NOT NULL,
    liked      INTEGER NOT NULL,      -- 1 нравится, 0 мимо
    at         REAL    NOT NULL,
    PRIMARY KEY (chat_id, item_id)
);
CREATE INDEX IF NOT EXISTS feedback_chat ON feedback (chat_id);
CREATE TABLE IF NOT EXISTS digests (
    chat_id   INTEGER NOT NULL,
    digest_id TEXT    NOT NULL,
    payload   TEXT    NOT NULL,
    at        REAL    NOT NULL,
    PRIMARY KEY (chat_id, digest_id)
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
    profile = {**DEFAULT_PROFILE, **saved}
    return _migrate(profile)


def _migrate(profile: dict) -> dict:
    """Старые профили не знают про новые категории.

    Юбки раньше входили в пункт «Брюки, джинсы, юбки» — значит тем, у кого
    выбран низ, юбки тоже были нужны. Выключенные категории не трогаем.
    """
    cats = profile.get("categories") or []
    if "skirts" not in cats and "bottoms" in cats:
        cats = list(cats)
        cats.insert(cats.index("bottoms") + 1, "skirts")
        profile["categories"] = cats
    return profile


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


REPEAT_AFTER = 45 * 86400      # через полтора месяца вещь снова считается новой


def split_seen(chat_id: int, items: list[dict]) -> tuple[list[dict], list[dict]]:
    """Делит на «не показывали» и «показывали», вторые — от самых давних.

    Новым считается и то, что подешевело больше чем на 15 процентов,
    и то, что показывали очень давно: иначе при узких фильтрах пул
    вычерпывается за пару подборок и присылать становится нечего.
    """
    if not items:
        return [], []
    ids = [str(i["id"]) for i in items]
    marks = ",".join("?" * len(ids))
    with _conn() as c:
        rows = c.execute(
            f"SELECT item_id, price, shown_at FROM seen "
            f"WHERE chat_id=? AND item_id IN ({marks})",
            (chat_id, *ids),
        ).fetchall()
    before = {r["item_id"]: (r["price"], r["shown_at"]) for r in rows}

    now = time.time()
    fresh, stale = [], []
    for it in items:
        mark = before.get(str(it["id"]))
        if mark is None:
            fresh.append(it)
            continue
        price, shown_at = mark
        if it["price"] <= price * 0.85 or now - shown_at > REPEAT_AFTER:
            fresh.append(it)
        else:
            stale.append((shown_at, it))

    stale.sort(key=lambda x: x[0])          # сначала то, что видели давнее всего
    return fresh, [it for _, it in stale]


def filter_unseen(chat_id: int, items: list[dict]) -> list[dict]:
    return split_seen(chat_id, items)[0]


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


# ---------------------------------------------------------------- подборки

DIGEST_FIELDS = ("id", "_style", "_category", "brand", "price", "name", "url")


def save_digest(chat_id: int, digest_id: str, items: list[dict]) -> None:
    """Запоминаем состав подборки, чтобы кнопки оценок знали, что оценивают."""
    slim = [{k: it.get(k) for k in DIGEST_FIELDS} for it in items]
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO digests VALUES (?,?,?,?)",
                  (chat_id, digest_id, json.dumps(slim, ensure_ascii=False), time.time()))
        c.execute("DELETE FROM digests WHERE chat_id=? AND at < ?",
                  (chat_id, time.time() - 60 * 86400))


def get_digest(chat_id: int, digest_id: str) -> list[dict]:
    with _conn() as c:
        row = c.execute("SELECT payload FROM digests WHERE chat_id=? AND digest_id=?",
                        (chat_id, digest_id)).fetchone()
    return json.loads(row["payload"]) if row else []


def liked_in(chat_id: int, item_ids: list[str]) -> set[str]:
    if not item_ids:
        return set()
    marks = ",".join("?" * len(item_ids))
    with _conn() as c:
        return {r["item_id"] for r in c.execute(
            f"SELECT item_id FROM feedback WHERE chat_id=? AND liked=1 "
            f"AND item_id IN ({marks})", (chat_id, *item_ids))}


# ---------------------------------------------------------------- оценки

def set_feedback(chat_id: int, item: dict, liked: bool) -> None:
    with _conn() as c:
        c.execute(
            """INSERT INTO feedback (chat_id, item_id, style, category, brand,
                                     price, liked, at)
               VALUES (?,?,?,?,?,?,?,?)
               ON CONFLICT(chat_id, item_id) DO UPDATE SET
                 liked=excluded.liked, at=excluded.at""",
            (chat_id, str(item["id"]), item.get("_style", ""), item.get("_category", ""),
             item.get("brand", ""), int(item.get("price", 0)), int(liked), time.time()))


def disliked_ids(chat_id: int) -> set[str]:
    with _conn() as c:
        return {r["item_id"] for r in c.execute(
            "SELECT item_id FROM feedback WHERE chat_id=? AND liked=0", (chat_id,))}


def get_prefs(chat_id: int) -> dict:
    """Что человек оценил — в виде понятных весов от -1 до 1.

    Без обучения и моделей: доля лайков минус доля дизлайков по каждому
    признаку, приглушённая, если оценок мало. Так вес не улетает от двух
    случайных нажатий и всегда объясним.
    """
    with _conn() as c:
        rows = c.execute(
            "SELECT style, category, brand, price, liked FROM feedback WHERE chat_id=?",
            (chat_id,)).fetchall()
    if not rows:
        return {"styles": {}, "categories": {}, "brands": {}, "liked_prices": [], "total": 0}

    def tally(field):
        pos, neg = {}, {}
        for r in rows:
            key = r[field]
            if not key:
                continue
            (pos if r["liked"] else neg)[key] = (pos if r["liked"] else neg).get(key, 0) + 1
        out = {}
        for key in set(pos) | set(neg):
            p, n = pos.get(key, 0), neg.get(key, 0)
            trust = (p + n) / (p + n + 3)          # три оценки — половина доверия
            out[key] = ((p - n) / (p + n)) * trust
        return out

    return {
        "styles": tally("style"),
        "categories": tally("category"),
        "brands": tally("brand"),
        "liked_prices": sorted(r["price"] for r in rows if r["liked"]),
        "total": len(rows),
    }


def prune_seen(days: int = 120) -> None:
    cutoff = time.time() - days * 86400
    with _conn() as c:
        c.execute("DELETE FROM seen WHERE shown_at < ?", (cutoff,))
