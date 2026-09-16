"""Сборка подборки под конкретный профиль."""
import asyncio
import logging

from . import db
from .ranker import diversify, rank, why_thin
from .sources import wb
from .styles import WB_BRANDS, queries_for

log = logging.getLogger(__name__)

MAX_QUERIES = 18  # один запрос на полку — бренды фильтруются на стороне WB


async def collect(profile: dict) -> list[tuple[str, str, dict]]:
    styles = profile.get("styles") or []
    cats = profile.get("categories") or []
    brands = [b for b in (profile.get("brands") or WB_BRANDS) if b in WB_BRANDS]
    if not styles or not cats or not brands:
        return []

    # чередуем и стили, и категории: иначе первые стили занимают весь лимит
    # своими верхними категориями, и подборка выходит из одних пальто
    plan = queries_for(styles, cats)
    buckets: dict[tuple[str, str], list] = {}
    for style_id, cat, phrase in plan:
        buckets.setdefault((style_id, cat), []).append((style_id, cat, phrase))

    order = sorted(buckets, key=lambda k: (styles.index(k[0]) if k[0] in styles else 99,
                                           cats.index(k[1]) if k[1] in cats else 99))
    plan, round_no = [], 0
    while len(plan) < MAX_QUERIES and any(buckets.values()):
        for key in order:
            if len(plan) >= MAX_QUERIES:
                break
            if buckets[key]:
                plan.append(buckets[key].pop(0))
        round_no += 1
        if round_no > 8:
            break

    found: list[tuple[str, str, dict]] = []
    async with wb.make_session() as session:
        async def one(style_id: str, cat: str, phrase: str):
            items = await wb.search(session, phrase, brands)
            return [(style_id, cat, it) for it in items[:16]]

        tasks = [one(s, c, p) for (s, c, p) in plan]
        for chunk in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(chunk, Exception):
                log.warning("поиск упал: %s", chunk)
                continue
            found += chunk
    return found


async def build(chat_id: int, profile: dict, n: int,
                only_drops: bool = False) -> tuple[list[dict], str | None]:
    """Готовая подборка и, если она вышла скудной, подсказка почему."""
    found = await collect(profile)
    if not found:
        return [], None

    ranked = rank(found, profile)
    if only_drops:
        # для срочных уведомлений — только заметные скидки
        ranked = [i for i in ranked if i.get("discount", 0) >= 40]

    fresh, stale = db.split_seen(chat_id, ranked)
    picked = diversify(fresh, n)

    # добираем уже показанным, начиная с самого давнего: пустой пост хуже повтора
    repeated = 0
    if len(picked) < n and stale and not only_drops:
        taken = {i["id"] for i in picked}
        extra = diversify([s for s in stale if s["id"] not in taken], n - len(picked))
        picked += extra
        repeated = len(extra)
    # подсказка нужна не только когда вещей мало, но и когда они все из одной
    # категории: восемь пальто подряд — тоже признак слишком узких фильтров
    from collections import Counter
    top = Counter(i["_category"] for i in picked).most_common(1)
    monotone = bool(picked) and top and top[0][1] >= max(3, len(picked) * 0.6)
    hint = why_thin(found, profile) if (len(picked) < n or monotone) else None
    if repeated:
        note = f"Из них {repeated} уже показывала — нового под твои фильтры мало."
        hint = f"{note} {hint}" if hint else note
    if not picked:
        return [], hint

    async with wb.make_session() as session:
        picked = await wb.attach_images(session, picked)

    db.mark_seen(chat_id, picked)
    return picked, hint
