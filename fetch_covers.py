#!/usr/bin/env python3
"""Скачивает обложки стилей с Pexels и раскладывает по местам.

Зачем: обложка должна показывать направление в одежде, а не конкретный товар.
Снимки с Wildberries умирают вместе с товаром, а лицензия Pexels прямо
разрешает хранить копии у себя — значит обложки перестают отваливаться.

    .venv/bin/python fetch_covers.py            все стили
    .venv/bin/python fetch_covers.py boho glam  только названные

Кладёт файлы в docs/img/, пишет bot/covers.py и список авторов
в brand/PHOTO-CREDITS.md, подставляет пути в docs/index.html.
"""
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bot import config          # noqa: E402
from bot.styles import STYLES   # noqa: E402

ROOT = Path(__file__).resolve().parent
IMG_DIR = ROOT / "docs" / "img"
COVERS_PY = ROOT / "bot" / "covers.py"
CREDITS = ROOT / "brand" / "PHOTO-CREDITS.md"
PAGE = ROOT / "docs" / "index.html"

API = "https://api.pexels.com/v1/search"

# Cloudflare у Pexels отбивает запросы без браузерной подписи с ошибкой 1010
BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/122.0 Safari/537.36")

# Запросы подобраны так, чтобы в кадр попадал образ целиком, а не лицо крупным
# планом: лицензия покрывает права фотографа, но не права людей на снимке.
QUERIES = {
    "minimal":    ["minimal fashion studio beige background", "neutral outfit studio model"],
    "quiet":      ["beige coat studio fashion model", "camel coat lookbook studio"],
    "office":     ["woman suit studio fashion editorial", "tailored blazer studio model"],
    "smart":      ["blazer studio fashion model neutral", "smart casual lookbook studio"],
    "casual":     ["jeans studio fashion model white background", "casual lookbook studio model"],
    "street":     ["oversized streetwear studio fashion", "streetwear lookbook studio model"],
    "athleisure": ["sportswear studio fashion model", "activewear lookbook studio"],
    "romantic":   ["silk dress studio fashion model", "flowing dress lookbook studio"],
    "ballet":     ["ballet flats studio fashion", "ballet core lookbook studio"],
    "black":      ["black outfit studio fashion model", "black dress lookbook studio"],
    "grunge":     ["leather jacket studio fashion model", "denim lookbook studio grunge"],
    "boho":       ["maxi dress studio fashion model", "linen dress lookbook studio"],
    "preppy":     ["knit cardigan studio fashion model", "preppy lookbook studio"],
    "denim":      ["denim jacket studio fashion model", "denim lookbook studio"],
    "utility":    ["cargo pants studio fashion model", "utility jacket lookbook studio"],
    "glam":       ["evening dress studio fashion", "satin dress lookbook studio"],
}


def api(query: str, key: str) -> list[dict]:
    url = API + "?" + urllib.parse.urlencode(
        {"query": query, "orientation": "portrait", "per_page": 30, "size": "medium"})
    req = urllib.request.Request(url, headers={"Authorization": key,
                                               "User-Agent": BROWSER_UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read()).get("photos", [])
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise SystemExit("Pexels: превышен лимит запросов, попробуй через час.")
        raise SystemExit(f"Pexels ответил HTTP {e.code}")
    except Exception as e:
        raise SystemExit(f"Не достучались до Pexels: {type(e).__name__}")


def best(photos: list[dict], used: set[int]) -> dict | None:
    """Ближе всего к 3:4 — именно в такой рамке карточка в анкете."""
    def score(p):
        w, h = p.get("width") or 1, p.get("height") or 1
        return abs(w / h - 0.75)
    for p in sorted(photos, key=score):
        if p["id"] not in used and (p.get("src") or {}).get("portrait"):
            return p
    return None


def download(url: str, dest: Path) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        blob = r.read()
    dest.write_bytes(blob)
    return len(blob)


def main() -> None:
    key = getattr(config, "PEXELS_API_KEY", "")
    if not key:
        raise SystemExit(
            "Нет ключа Pexels. Получи его на https://www.pexels.com/api/ и впиши:\n"
            "    .venv/bin/python set_token.py pexels")

    only = set(sys.argv[1:])
    IMG_DIR.mkdir(parents=True, exist_ok=True)
    CREDITS.parent.mkdir(parents=True, exist_ok=True)

    covers: dict[str, dict] = {}
    if COVERS_PY.exists():
        ns: dict = {}
        exec(COVERS_PY.read_text(encoding="utf-8"), ns)
        covers = ns.get("COVERS", {})

    used = {c["photo_id"] for c in covers.values() if c.get("photo_id")}

    for sid in STYLES:
        if only and sid not in only:
            continue
        if not only and (IMG_DIR / f"{sid}.jpg").exists() and sid in covers:
            print(f"  {sid:<11} уже есть")
            continue

        photo = None
        for query in QUERIES.get(sid, [sid]):
            photo = best(api(query, key), used)
            if photo:
                break
        if not photo:
            print(f"  {sid:<11} НЕ НАЙДЕНО")
            continue

        size = download(photo["src"]["portrait"], IMG_DIR / f"{sid}.jpg")
        used.add(photo["id"])
        covers[sid] = {
            "photo_id": photo["id"],
            "author": photo.get("photographer", ""),
            "author_url": photo.get("photographer_url", ""),
            "page": photo.get("url", ""),
            "file": f"img/{sid}.jpg",
        }
        print(f"  {sid:<11} {photo.get('photographer', '?'):<24} {size // 1024} KB")

    COVERS_PY.write_text(
        '"""Обложки стилей: файлы в docs/img и авторы снимков.\n\n'
        "Создаётся fetch_covers.py. Снимки взяты на Pexels — их лицензия\n"
        'разрешает хранить и использовать копии, в том числе коммерчески.\n"""\n\n'
        f"COVERS = {json.dumps(covers, ensure_ascii=False, indent=1)}\n",
        encoding="utf-8")

    rows = "\n".join(
        f"| {STYLES[s]['name']} | [{c['author']}]({c['author_url']}) | [снимок]({c['page']}) |"
        for s, c in covers.items() if s in STYLES)
    CREDITS.write_text(
        "# Авторы снимков\n\n"
        "Обложки стилей взяты на [Pexels](https://www.pexels.com/license/). "
        "Лицензия не требует указания автора, но указать честнее.\n\n"
        "| Стиль | Автор | Оригинал |\n|---|---|---|\n" + rows + "\n",
        encoding="utf-8")

    if PAGE.exists():
        html = PAGE.read_text(encoding="utf-8")
        m = re.search(r"const STYLES = (\[[\s\S]*?\n\]);", html)
        data = json.loads(m.group(1))
        for entry in data:
            c = covers.get(entry["id"])
            if c:
                entry["img"] = c["file"]
        html = html[:m.start(1)] + json.dumps(data, ensure_ascii=False, indent=1) + html[m.end(1):]
        PAGE.write_text(html, encoding="utf-8")

    print(f"\nобложек: {len(covers)} · docs/img, bot/covers.py, "
          f"brand/PHOTO-CREDITS.md, анкета обновлены")


if __name__ == "__main__":
    main()
