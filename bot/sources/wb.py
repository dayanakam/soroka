"""Поиск по Wildberries через публичный search-API + сборка ссылок на фото."""
import asyncio
import json
import logging
from pathlib import Path
from urllib.parse import quote

import aiohttp

from .. import config

log = logging.getLogger(__name__)

# WB отдаёт 429, если запросы идут плотно. Один общий «кран» на процесс.
_gate = asyncio.Semaphore(2)
_last_call = 0.0
_pace = asyncio.Lock()
MIN_GAP = 0.35


async def _throttle() -> None:
    global _last_call
    async with _pace:
        wait = MIN_GAP - (asyncio.get_running_loop().time() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = asyncio.get_running_loop().time()

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

SEARCH = ("https://search.wb.ru/exactmatch/ru/common/v4/search"
          "?appType=1&curr=rub&dest=-1257786&resultset=catalog&sort=popular&spp=30&query={}")

# Поиск умеет фильтровать сразу по нескольким брендам — это один запрос
# на полку вместо одного на каждый бренд.
BRAND_IDS = {"mango": 2513, "befree": 4126, "ekonika": 13293, "calzedonia": 759616}

# Выдача по одному запросу живёт недолго, но за это время человек успевает
# нажать «Подборка» второй раз, а расписание — обойти нескольких людей.
_CACHE_TTL = 1200
_cache: dict[str, tuple[float, list[dict]]] = {}

# WB раскладывает картинки по хостам basket-NN в зависимости от vol = id // 100000.
# Это опубликованные границы; дальше шаг держится на 320 vol'ов.
_BOUNDS = [143, 287, 431, 719, 1007, 1061, 1115, 1169, 1313, 1601, 1655, 1919,
           2045, 2189, 2405, 2621, 2837, 3053, 3269, 3485, 3701, 3917, 4133,
           4349, 4565, 4877, 5189, 5501, 5813, 6125, 6437, 6749, 7061, 7373,
           7685, 7999]

_CACHE_FILE = Path(config.DB_PATH).parent / "baskets.json"
_baskets: dict[str, str] = {}
if _CACHE_FILE.exists():
    try:
        _baskets = json.loads(_CACHE_FILE.read_text())
    except Exception:
        _baskets = {}


def _guess(vol: int) -> int:
    """Для vol до 7999 таблица точна. Дальше — приблизительно: замеры дают
    vol 8321 -> 38, 12075 -> 44, 12672 -> 44, то есть около 600 vol'ов на хост.
    Промах добирается параллельным перебором соседей."""
    for i, hi in enumerate(_BOUNDS):
        if vol <= hi:
            return i + 1
    return len(_BOUNDS) + (vol - _BOUNDS[-1]) // 600


def _tpl(nn: str, vol: int, part: int, pid: int, idx: int) -> str:
    return (f"https://basket-{nn}.wbbasket.ru/vol{vol}/part{part}/{pid}"
            f"/images/c516x688/{idx}.webp")


def _remember(key: str, nn: str) -> None:
    _baskets[key] = nn
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(_baskets))
    except Exception:
        pass


async def _head_ok(session: aiohttp.ClientSession, url: str) -> bool:
    try:
        async with session.head(url, timeout=aiohttp.ClientTimeout(total=5)) as r:
            return r.status == 200
    except Exception:
        return False


async def image_url(session: aiohttp.ClientSession, pid: int, idx: int = 1) -> str | None:
    """Ссылка на фото товара. Хост определяется один раз на vol и кешируется."""
    vol, part = pid // 100000, pid // 1000
    key = str(vol)
    if key in _baskets:
        return _tpl(_baskets[key], vol, part, pid, idx)

    g = _guess(vol)
    # догадке даём две попытки подряд: чаще всего промах — это сетевой сбой
    for attempt in range(2):
        nn = "%02d" % g
        if await _head_ok(session, _tpl(nn, vol, part, pid, 1)):
            _remember(key, nn)
            return _tpl(nn, vol, part, pid, idx)
        await asyncio.sleep(0.3)

    # дальше — перебор пачками по 10 параллельно, иначе таймауты копятся в минуты
    order = [g + d for d in range(1, 9)] + [g - d for d in range(1, 9)]
    order += [n for n in range(1, 63) if n not in order and n != g]
    order = [n for n in order if 1 <= n <= 70]

    for i in range(0, len(order), 10):
        batch = order[i:i + 10]
        oks = await asyncio.gather(
            *(_head_ok(session, _tpl("%02d" % n, vol, part, pid, 1)) for n in batch))
        for n, ok in zip(batch, oks):
            if ok:
                nn = "%02d" % n
                _remember(key, nn)
                return _tpl(nn, vol, part, pid, idx)

    log.warning("не нашли хост картинки для %s (vol %s)", pid, vol)
    return None


async def search(session: aiohttp.ClientSession, query: str,
                 brands: str | list[str], limit: int = 100) -> list[dict]:
    """Товары указанных брендов по запросу — одним запросом на все бренды.

    Бренд сверяется строго и после фильтра: на WB полно «MANGOOFASHION»
    и «XseniyaLime», которые к Mango и Lime отношения не имеют.
    """
    if isinstance(brands, str):
        brands = [brands]
    want = {b.lower() for b in brands}
    ids = [BRAND_IDS[b] for b in want if b in BRAND_IDS]

    url = SEARCH.format(quote(query))
    if ids:
        url += "&fbrand=" + ";".join(str(i) for i in sorted(ids))
    else:  # бренда нет в справочнике — ищем по названию, как раньше
        url = SEARCH.format(quote(f"{brands[0]} {query}"))

    now = asyncio.get_running_loop().time()
    hit = _cache.get(url)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]

    data = None
    for attempt in range(3):
        await _throttle()
        try:
            async with _gate:
                async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                    if r.status == 429:
                        await asyncio.sleep(1.5 * (attempt + 1))
                        continue
                    if r.status != 200:
                        log.warning("WB search %r -> %s", query, r.status)
                        return []
                    data = json.loads(await r.text())
            break
        except Exception as e:
            if attempt == 2:
                log.warning("WB search %r упал: %s", query, e)
                return []
            await asyncio.sleep(1.0 * (attempt + 1))
    if data is None:
        log.warning("WB search %r: не пробились сквозь 429", query)
        return []

    out: list[dict] = []
    for p in (data.get("products") or [])[:limit]:
        if (p.get("brand") or "").strip().lower() not in want:
            continue
        sizes = [s for s in (p.get("sizes") or []) if (s.get("price") or {}).get("product")]
        if not sizes:
            continue
        cur = min(s["price"]["product"] for s in sizes) // 100
        old = max(s["price"].get("basic", 0) for s in sizes) // 100
        avail = sorted({(s.get("origName") or s.get("name") or "").strip() for s in sizes})
        out.append({
            "source": "wb",
            "id": p["id"],
            "brand": (p.get("brand") or "").strip(),
            "name": (p.get("name") or "").strip(),
            "price": cur,
            "old": old if old > cur else None,
            "discount": round((1 - cur / old) * 100) if old > cur else 0,
            "rating": float(p.get("reviewRating") or p.get("rating") or 0),
            "feedbacks": int(p.get("feedbacks") or 0),
            "sizes": [s for s in avail if s],
            "url": f"https://www.wildberries.ru/catalog/{p['id']}/detail.aspx",
        })

    _cache[url] = (now, out)
    if len(_cache) > 400:                      # не копим бесконечно
        for k in [k for k, (t, _) in _cache.items() if now - t > _CACHE_TTL]:
            _cache.pop(k, None)
    return out


async def attach_images(session: aiohttp.ClientSession, items: list[dict]) -> list[dict]:
    """Дотягивает ссылку на фото; товары без картинки выбрасываем."""
    sem = asyncio.Semaphore(3)

    async def one(it):
        async with sem:
            return await image_url(session, it["id"])

    urls = await asyncio.gather(*(one(it) for it in items))
    out = []
    for it, u in zip(items, urls):
        if u:
            it["img"] = u
            out.append(it)
    return out


def make_session() -> aiohttp.ClientSession:
    return aiohttp.ClientSession(
        headers={"User-Agent": UA, "Accept": "*/*"},
        connector=aiohttp.TCPConnector(limit=8, ttl_dns_cache=300),
    )
