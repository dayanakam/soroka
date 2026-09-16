"""Картинки для отправки в Telegram.

Telegram перестал скачивать снимки с серверов Wildberries — отвечает
«failed to get HTTP URL content». Поэтому берём файл сами и отдаём байтами.
Заодно переводим в JPEG: webp Telegram принимает не всегда.
"""
import asyncio
import io
import logging

import aiohttp

log = logging.getLogger(__name__)

MAX_SIDE = 1280
JPEG_QUALITY = 82

try:
    from PIL import Image
except ImportError:                       # без Pillow отдаём как есть
    Image = None


def to_jpeg(blob: bytes) -> tuple[bytes, str]:
    if Image is None:
        return blob, "jpg"
    try:
        img = Image.open(io.BytesIO(blob))
        img = img.convert("RGB")
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue(), "jpg"
    except Exception as e:
        log.warning("не сконвертировали картинку: %s", e)
        return blob, "jpg"


async def fetch(session: aiohttp.ClientSession, url: str) -> bytes | None:
    for attempt in range(3):
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=25)) as r:
                if r.status != 200:
                    return None
                blob = await r.read()
            return to_jpeg(blob)[0]
        except Exception as e:
            if attempt == 2:
                log.warning("не скачали %s: %s", url[:60], e)
                return None
            await asyncio.sleep(1.0 * (attempt + 1))
    return None


async def fetch_all(session: aiohttp.ClientSession, urls: list[str]) -> list[bytes | None]:
    sem = asyncio.Semaphore(4)

    async def one(u):
        async with sem:
            return await fetch(session, u)

    return await asyncio.gather(*(one(u) for u in urls))
