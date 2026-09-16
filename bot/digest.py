"""Сборка подборки под конкретный профиль."""
import asyncio
import logging

from . import db
from .ranker import diversify, rank
from .sources import wb
from .styles import WB_BRANDS, queries_for

log = logging.getLogger(__name__)

MAX_QUERIES = 14  # на каждый запрос ещё умножается число брендов


async def collect(profile: dict) -> list[tuple[str, str, dict]]:
    styles = profile.get("styles") or []
    cats = profile.get("categories") or []
    brands = [b for b in (profile.get("brands") or WB_BRANDS) if b in WB_BRANDS]
    if not styles or not cats or not brands:
        return []

    plan = queries_for(styles, cats)
    # перемешиваем так, чтобы стили чередовались, и режем хвост
    plan.sort(key=lambda t: styles.index(t[0]) if t[0] in styles else 99)
    plan = plan[:MAX_QUERIES]

    found: list[tuple[str, str, dict]] = []
    async with wb.make_session() as session:
        async def one(style_id: str, cat: str, phrase: str, brand: str):
            items = await wb.search(session, phrase, brand)
            return [(style_id, cat, it) for it in items[:10]]

        tasks = [one(s, c, p, b) for (s, c, p) in plan for b in brands]
        for chunk in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(chunk, Exception):
                log.warning("поиск упал: %s", chunk)
                continue
            found += chunk
    return found


async def build(chat_id: int, profile: dict, n: int,
                only_drops: bool = False) -> list[dict]:
    """Готовая подборка: отфильтрованная, отранжированная, без повторов, с фото."""
    found = await collect(profile)
    if not found:
        return []

    ranked = rank(found, profile)
    if only_drops:
        # для срочных уведомлений — только заметные скидки
        ranked = [i for i in ranked if i.get("discount", 0) >= 40]

    fresh = db.filter_unseen(chat_id, ranked)
    picked = diversify(fresh, n)
    if not picked:
        return []

    async with wb.make_session() as session:
        picked = await wb.attach_images(session, picked)

    db.mark_seen(chat_id, picked)
    return picked
