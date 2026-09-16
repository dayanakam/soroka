import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    f = ROOT / ".env"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "").rstrip("/")
PORT = int(os.environ.get("PORT", 8080))
DB_PATH = os.environ.get("DB_PATH", str(ROOT / "data" / "outfits.db"))
TZ = os.environ.get("TZ", "Europe/Moscow")

# Папка docs/ — её же раздаёт GitHub Pages
MINIAPP_DIR = ROOT / "docs"

# Публичный адрес анкеты. Страница статическая, поэтому может жить где угодно —
# например на GitHub Pages. Если пусто, берём собственный сервер.
MINIAPP_URL = os.environ.get("MINIAPP_URL", "").rstrip("/")


def app_url() -> str:
    if MINIAPP_URL:
        return MINIAPP_URL
    return f"{PUBLIC_URL}/app/" if PUBLIC_URL else ""

# Понедельник, 10 утра — еженедельный дайджест
DIGEST_DAY = "mon"
DIGEST_HOUR = 10

# Проверка новинок и резких скидок
DROPS_HOURS = 6

ITEMS_PER_DIGEST = 8
