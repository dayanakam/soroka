#!/usr/bin/env python3
"""Обновляет карточки-обложки стилей по живым данным Wildberries.

Мы не храним копии чужих фотографий: и бот, и анкета показывают снимки
прямо с серверов WB по ссылке. Товары со временем пропадают из продажи,
и ссылка перестаёт работать — тогда достаточно запустить этот скрипт:

    .venv/bin/python refresh_examples.py

Он пишет bot/examples.py и подставляет свежие адреса в docs/index.html.
"""
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot.sources import wb                     # noqa: E402
from bot.styles import STYLES, WB_BRANDS       # noqa: E402

ROOT = Path(__file__).resolve().parent
OUT_PY = ROOT / "bot" / "examples.py"
PAGE = ROOT / "docs" / "index.html"

# бренд, который лучше всего показывает стиль — пробуем его первым
PREFERRED = {
    "ballet": "EKONIKA", "black": "EKONIKA", "office": "Mango",
    "athleisure": "calzedonia", "quiet": "Mango", "minimal": "Mango",
}


async def pick(session, style_id: str, style: dict) -> dict | None:
    brands = ([PREFERRED[style_id]] if style_id in PREFERRED else []) + \
             [b for b in WB_BRANDS if b != PREFERRED.get(style_id)]

    for cat, phrases in style["q"].items():
        for phrase in phrases:
            for brand in brands:
                items = await wb.search(session, phrase, brand)
                good = [i for i in items if i["feedbacks"] >= 5 and i["rating"] >= 4.3]
                for item in (good or items)[:4]:
                    img = await wb.image_url(session, item["id"])
                    if img:
                        return {"id": item["id"], "brand": item["brand"],
                                "name": item["name"], "price": item["price"],
                                "url": item["url"], "img": img}
    return None


async def main() -> None:
    only = set(sys.argv[1:])
    current = {}
    if OUT_PY.exists():
        ns: dict = {}
        exec(OUT_PY.read_text(encoding="utf-8"), ns)
        current = ns.get("EXAMPLES", {})

    async with wb.make_session() as session:
        for sid, style in STYLES.items():
            if only and sid not in only:
                continue
            if not only and current.get(sid, {}).get("img"):
                continue                        # уже есть — не трогаем
            found = await pick(session, sid, style)
            if found:
                current[sid] = found
                print(f"  {sid:<11} {found['brand']:<11} {found['name'][:40]}")
            else:
                print(f"  {sid:<11} НЕ НАЙДЕНО")

    body = json.dumps(current, ensure_ascii=False, indent=1)
    OUT_PY.write_text(
        '"""Обложки стилей: примеры товаров с Wildberries.\n\n'
        "Файл создаётся refresh_examples.py. Копий фотографий у нас нет —\n"
        'только ссылки на снимки WB.\n"""\n\n'
        f"EXAMPLES = {body}\n", encoding="utf-8")
    print(f"\nbot/examples.py: {len(current)} стилей")

    # подставляем свежие адреса в анкету
    if PAGE.exists():
        html = PAGE.read_text(encoding="utf-8")
        m = re.search(r"const STYLES = (\[[\s\S]*?\n\]);", html)
        data = json.loads(m.group(1))
        for entry in data:
            ex = current.get(entry["id"])
            if ex and ex.get("img"):
                entry["img"] = ex["img"]
        html = html[:m.start(1)] + json.dumps(data, ensure_ascii=False, indent=1) + html[m.end(1):]
        PAGE.write_text(html, encoding="utf-8")
        print("docs/index.html обновлён")


if __name__ == "__main__":
    asyncio.run(main())
