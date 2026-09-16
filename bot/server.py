"""Веб-часть: отдаёт мини-апп и принимает от него профиль."""
import logging
import mimetypes

from aiohttp import web

from . import auth, config, db

log = logging.getLogger(__name__)

# На части систем .webp не зарегистрирован, и статика уезжает как octet-stream.
# aiohttp снимает копию таблицы типов при импорте, поэтому правим и её.
mimetypes.add_type("image/webp", ".webp")
try:
    from aiohttp.web_fileresponse import CONTENT_TYPES
    CONTENT_TYPES.add_type("image/webp", ".webp")
except Exception:  # внутренности aiohttp могут переехать — не критично
    pass

ALLOWED = {"styles", "categories", "sizes", "budgetMin", "budgetMax",
           "minDiscount", "veto", "brands"}


def _clean(raw: dict) -> dict:
    """Берём только известные поля и приводим к ожидаемым типам."""
    out: dict = {}
    for k in ALLOWED & set(raw):
        v = raw[k]
        if k in {"styles", "categories", "veto", "brands"} and isinstance(v, list):
            out[k] = [str(x)[:80] for x in v[:40]]
        elif k == "sizes" and isinstance(v, dict):
            out[k] = {str(a)[:16]: str(b)[:16] for a, b in list(v.items())[:10]}
        elif k in {"budgetMin", "budgetMax"} and isinstance(v, (int, float)):
            out[k] = max(0, min(int(v), 1_000_000))
        elif k == "minDiscount":
            out[k] = str(v)[:8]
    if out.get("budgetMin", 0) > out.get("budgetMax", 10 ** 9):
        out["budgetMin"], out["budgetMax"] = out["budgetMax"], out["budgetMin"]
    return out


async def _user_from(request: web.Request) -> tuple[dict | None, dict]:
    try:
        body = await request.json()
    except Exception:
        return None, {}
    user = auth.verify(body.get("initData", ""))
    return user, body


async def profile_get(request: web.Request) -> web.Response:
    user, _ = await _user_from(request)
    if not user:
        return web.json_response({"error": "bad_init_data"}, status=401)
    profile = db.get_profile(user["id"]) or db.DEFAULT_PROFILE
    return web.json_response({"profile": profile})


async def profile_save(request: web.Request) -> web.Response:
    user, body = await _user_from(request)
    if not user:
        return web.json_response({"error": "bad_init_data"}, status=401)

    incoming = body.get("profile")
    if not isinstance(incoming, dict):
        return web.json_response({"error": "bad_profile"}, status=400)

    current = db.get_profile(user["id"]) or dict(db.DEFAULT_PROFILE)
    merged = {**current, **_clean(incoming)}
    if not merged.get("styles"):
        return web.json_response({"error": "no_styles"}, status=400)

    db.save_profile(user["id"], merged,
                    username=user.get("username", "") or "",
                    first_name=user.get("first_name", "") or "")
    log.info("профиль сохранён: chat=%s стилей=%s", user["id"], len(merged["styles"]))
    return web.json_response({"ok": True})


async def health(_: web.Request) -> web.Response:
    return web.Response(text="ok")


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(config.MINIAPP_DIR / "index.html",
                            headers={"Cache-Control": "no-cache"})


def make_app() -> web.Application:
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_post("/api/profile/get", profile_get)
    app.router.add_post("/api/profile", profile_save)
    # каталог сначала, иначе / app/ перехватит статику
    app.router.add_get("/app/", index)
    app.router.add_static("/app/", config.MINIAPP_DIR, show_index=False, name="miniapp")
    return app


async def start_server() -> web.AppRunner:
    runner = web.AppRunner(make_app())
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    log.info("веб-сервер на :%s, мини-апп по %s/app/", config.PORT, config.PUBLIC_URL)
    return runner
