"""Хендлеры бота «Сорока»."""
import asyncio
import html
import json
import logging
import re
import time

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery
from aiogram.types import (BotCommand, BufferedInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, InputMediaPhoto, KeyboardButton,
                           MenuButtonCommands, MenuButtonWebApp, Message,
                           ReplyKeyboardMarkup, WebAppInfo)

from . import config, db, digest, images, server, wizard
from .sources import wb
from .styles import CATEGORIES, STYLES, VETO_STEMS

VETO_ORDER = list(VETO_STEMS)

log = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(wizard.router)

BTN_DIGEST = "✨ Подборка"
BTN_TASTE = "🎨 Мой вкус"
BTN_MENU = "Мой вкус"


def _app_link(chat_id: int) -> str:
    """Адрес анкеты с текущим профилем в якоре.

    Telegram обрезает адрес мини-аппа на 256 символах, поэтому профиль
    кодируем коротко: категории и стоп-лист — битовыми масками по порядку
    списков из styles.py, которые повторены в docs/index.html.
    Якорь браузер на сервер не шлёт, так что страница остаётся статической.
    """
    base = config.app_url()
    if not base:
        return ""
    p = db.get_profile(chat_id) or {}

    def mask(values, order):
        got = set(values or [])
        return sum(1 << i for i, key in enumerate(order) if key in got)

    sizes = p.get("sizes") or {}
    parts = []
    if p.get("styles"):
        parts.append("s=" + ",".join(p["styles"]))
    parts.append("c=%d" % mask(p.get("categories"), list(CATEGORIES)))
    parts.append("z=%s-%s-%s-%s" % (sizes.get("top", ""), sizes.get("bottom", ""),
                                    sizes.get("jeans", ""), sizes.get("shoes", "")))
    hi = p.get("budgetMax") or 0
    parts.append("b=%s-%s" % (p.get("budgetMin", 0), "max" if hi >= 10 ** 9 else hi))
    parts.append("d=%s" % p.get("minDiscount", "any"))
    parts.append("v=%d" % mask(p.get("veto"), VETO_ORDER))

    link = base + "#" + "&".join(parts)
    if len(link) > 256:  # профиль не влез — пусть откроется с настройками по умолчанию
        log.warning("ссылка анкеты %s символов, открываем без профиля", len(link))
        return base
    return link


async def refresh_menu(bot: Bot, chat_id: int) -> None:
    """Кнопка меню слева от поля ввода — отдельная от клавиатуры, и Telegram
    помнит её, пока не перезапишешь. Ставим на неё анкету с уже проставленным
    профилем и обновляем всякий раз, когда профиль меняется."""
    link = _app_link(chat_id)
    try:
        if link:
            await bot.set_chat_menu_button(
                chat_id=chat_id,
                menu_button=MenuButtonWebApp(text=BTN_MENU,
                                             web_app=WebAppInfo(url=link)))
        else:
            await bot.set_chat_menu_button(chat_id=chat_id,
                                           menu_button=MenuButtonCommands())
    except Exception as e:
        log.warning("не обновили кнопку меню для %s: %s", chat_id, e)


def keyboard(chat_id: int | None = None) -> ReplyKeyboardMarkup:
    """Кнопка анкеты открывает мини-апп, если адрес задан. Иначе — опрос в чате."""
    taste = KeyboardButton(text=BTN_TASTE)
    if chat_id is not None:
        link = _app_link(chat_id)
        if link:
            taste = KeyboardButton(text=BTN_TASTE, web_app=WebAppInfo(url=link))
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=BTN_DIGEST)], [taste]],
        resize_keyboard=True,
    )


def rub(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


def caption(item: dict) -> str:
    style = STYLES.get(item.get("_style"), {}).get("name", "")
    cat = CATEGORIES.get(item.get("_category"), "")

    price = f"<b>{rub(item['price'])}</b>"
    if item.get("old"):
        price += f"  <s>{rub(item['old'])}</s>  −{item['discount']}%"

    lines = [f"<b>{item['brand']}</b> · {item['name']}", price]
    sizes = [s for s in item.get("sizes", []) if s and s != "0"]
    if sizes:                      # у сумок и аксессуаров размера нет
        lines.append(f"Размеры: {', '.join(sizes[:8])}")
    if item.get("rating"):
        stars = f"★ {item['rating']:.1f}"
        if item.get("feedbacks"):
            stars += f" ({item['feedbacks']})"
        lines.append(stars)
    tail = " · ".join(x for x in (style, cat) if x)
    if tail:
        lines.append(f"<i>{tail}</i>")
    return "\n".join(lines)


def buy_button(item: dict) -> InlineKeyboardMarkup:
    label = "Открыть на Wildberries" if item.get("source") == "wb" else "Открыть"
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text=label, url=item["url"])]])


MAX_ALBUM = 10          # ограничение Telegram на альбом
CAPTION_LIMIT = 1024


def _short(text: str, limit: int = 38) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip(" ,.-") + "…"


def album_caption(items: list[dict], head: str) -> str:
    """Список под альбомом: строка на вещь, вся строка — ссылка на товар.

    Адреса внутри тегов в лимит подписи не входят, считается видимый текст.
    """
    lines = [f"<b>{head}</b>", ""]
    for i, it in enumerate(items, 1):
        price = rub(it["price"])
        if it.get("discount"):
            price += f" <s>{rub(it['old'])}</s> −{it['discount']}%"
        name = html.escape(_short(it["name"]))
        brand = html.escape(it["brand"])
        lines.append(f'{i}. <a href="{it["url"]}">{brand} · {name}</a> — {price}')
    lines.append("")
    lines.append("<i>Номера по порядку фотографий</i>")

    text = "\n".join(lines)
    while len(_visible(text)) > CAPTION_LIMIT and len(lines) > 4:
        del lines[-3]                       # режем хвост списка, если не влезло
        text = "\n".join(lines)
    return text


def _visible(html_text: str) -> str:
    """Длину подписи Telegram считает по видимому тексту, без разметки."""
    return re.sub(r"<[^>]+>", "", html_text)


async def photo_inputs(items: list[dict]) -> list:
    """Telegram не может скачать снимки с Wildberries — качаем сами и отдаём
    байтами. Что Telegram уже видел, отправляем по file_id: это бесплатно."""
    out: list = [None] * len(items)
    need: list[int] = []
    for i, it in enumerate(items):
        cached = db.get_file_id(f"item:{it['id']}")
        if cached:
            out[i] = cached
        else:
            need.append(i)

    if need:
        async with wb.make_session() as session:
            blobs = await images.fetch_all(session, [items[i]["img"] for i in need])
        for i, blob in zip(need, blobs):
            if blob:
                out[i] = BufferedInputFile(blob, filename=f"{items[i]['id']}.jpg")
    return out


def _remember_item(item: dict, msg: Message) -> None:
    if msg and msg.photo:
        db.set_file_id(f"item:{item['id']}", msg.photo[-1].file_id)


async def send_album(bot: Bot, chat_id: int, items: list[dict], head: str) -> bool:
    """Одним постом. Возвращает False, если Telegram не принял альбом."""
    chunk = items[:MAX_ALBUM]
    photos = await photo_inputs(chunk)
    pairs = [(it, ph) for it, ph in zip(chunk, photos) if ph is not None]
    if len(pairs) < 2:                       # альбом — это минимум две картинки
        return False

    caption = album_caption([it for it, _ in pairs], head)
    media = [InputMediaPhoto(media=ph, caption=caption if i == 0 else None,
                             parse_mode=ParseMode.HTML)
             for i, (_, ph) in enumerate(pairs)]
    try:
        sent = await bot.send_media_group(chat_id, media)
    except Exception as e:
        log.warning("альбом не ушёл (%s), отправляю по одной", e)
        return False

    for (it, _), msg in zip(pairs, sent):
        _remember_item(it, msg)
    return True


async def send_items(bot: Bot, chat_id: int, items: list[dict]) -> None:
    photos = await photo_inputs(items)
    for it, ph in zip(items, photos):
        try:
            if ph is None:
                await bot.send_message(chat_id, caption(it), reply_markup=buy_button(it))
            else:
                msg = await bot.send_photo(chat_id, ph, caption=caption(it),
                                           reply_markup=buy_button(it))
                _remember_item(it, msg)
        except Exception as e:
            log.warning("не отправили %s: %s", it.get("id"), e)
        await asyncio.sleep(0.4)  # бережём лимиты Telegram


async def send_digest(bot: Bot, chat_id: int, n: int | None = None,
                      only_drops: bool = False) -> int:
    profile = db.get_profile(chat_id)
    if not profile or not profile.get("styles"):
        return 0
    items, hint = await digest.build(chat_id, profile, n or config.ITEMS_PER_DIGEST,
                                     only_drops=only_drops)
    if not items:
        if hint and not only_drops:
            await bot.send_message(chat_id, hint)
        return 0
    head = (f"Резко подешевело — {len(items)} шт." if only_drops
            else f"Натаскала {len(items)} вещей под твой вкус")
    if not await send_album(bot, chat_id, items, head):
        await bot.send_message(chat_id, head)
        await send_items(bot, chat_id, items)
    await ask_feedback(bot, chat_id, items)
    if hint:
        await bot.send_message(chat_id, hint)
    return len(items)


# ---------------------------------------------------------------- запуск подборки

BUSY: set[int] = set()          # чтобы двойное нажатие не запускало два поиска


def go_button(text: str = "✨ Собрать подборку") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=text, callback_data="go:digest")]])


async def run_digest(bot: Bot, chat_id: int, note_to: Message | None = None) -> None:
    if chat_id in BUSY:
        return
    BUSY.add(chat_id)
    note = None
    try:
        note = await bot.send_message(chat_id, "Улетела за находками…")
        sent = await send_digest(bot, chat_id)
        if not sent:
            await bot.send_message(
                chat_id,
                "Вернулась с пустым клювом: либо всё уже показывала, либо фильтры "
                "слишком узкие. Попробуй расширить бюджет или включить больше "
                "категорий — «🎨 Мой вкус».")
    finally:
        BUSY.discard(chat_id)
        if note:
            try:
                await note.delete()
            except Exception:
                pass


@dp.callback_query(F.data == "go:digest")
async def on_go(cb: CallbackQuery) -> None:
    if cb.message.chat.id in BUSY:
        await cb.answer("Уже ищу, подожди немного")
        return
    await cb.answer("Полетела")
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    await run_digest(cb.bot, cb.message.chat.id)


# ---------------------------------------------------------------- оценки

def feedback_kb(items: list[dict], did: str, liked: set[str]) -> InlineKeyboardMarkup:
    row, rows = [], []
    for i, it in enumerate(items, 1):
        mark = "✓" if str(it["id"]) in liked else ""
        row.append(InlineKeyboardButton(text=f"{mark}{i}", callback_data=f"fb:l:{did}:{i - 1}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="Всё мимо", callback_data=f"fb:none:{did}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def ask_feedback(bot: Bot, chat_id: int, items: list[dict]) -> None:
    did = str(int(time.time()))
    db.save_digest(chat_id, did, items)
    await bot.send_message(
        chat_id,
        "Отметь номера, которые понравились — так я быстрее пойму твой вкус.\n"
        "<i>Номера совпадают с порядком фотографий.</i>",
        reply_markup=feedback_kb(items, did, set()))


@dp.callback_query(F.data.startswith("fb:l:"))
async def on_like(cb: CallbackQuery) -> None:
    _, _, did, idx = cb.data.split(":")
    items = db.get_digest(cb.message.chat.id, did)
    if not items or int(idx) >= len(items):
        await cb.answer("Эта подборка уже старая", show_alert=True)
        return

    item = items[int(idx)]
    liked = db.liked_in(cb.message.chat.id, [str(i["id"]) for i in items])
    now_liked = str(item["id"]) not in liked
    db.set_feedback(cb.message.chat.id, item, now_liked)
    await cb.answer("Запомнила" if now_liked else "Убрала")

    liked = db.liked_in(cb.message.chat.id, [str(i["id"]) for i in items])
    try:
        await cb.message.edit_reply_markup(reply_markup=feedback_kb(items, did, liked))
    except Exception:
        pass


@dp.callback_query(F.data.startswith("fb:none:"))
async def on_none(cb: CallbackQuery) -> None:
    did = cb.data.split(":")[2]
    items = db.get_digest(cb.message.chat.id, did)
    if not items:
        await cb.answer("Эта подборка уже старая", show_alert=True)
        return
    for it in items:
        db.set_feedback(cb.message.chat.id, it, False)
    await cb.answer("Поняла, не буду такое присылать")
    try:
        await cb.message.edit_text("Записала: вся подборка мимо. Учту в следующей.")
    except Exception:
        pass


# ---------------------------------------------------------------- handlers

@dp.message(CommandStart())
async def start(msg: Message) -> None:
    await refresh_menu(msg.bot, msg.chat.id)
    profile = db.get_profile(msg.chat.id)
    if profile and profile.get("styles"):
        picked = " · ".join(STYLES[s]["name"] for s in profile["styles"] if s in STYLES)
        await msg.answer(
            f"С возвращением. Твой вкус: <b>{picked}</b>.\n"
            "Жми «Подборка» — слетаю за свежим прямо сейчас.",
            reply_markup=keyboard(msg.chat.id))
        return

    db.save_profile(msg.chat.id, db.DEFAULT_PROFILE,
                    username=msg.from_user.username or "",
                    first_name=msg.from_user.first_name or "")
    await msg.answer(
        "Привет, я Сорока. Таскаю в гнездо всё красивое, что найду "
        "у Mango, Befree, EKONIKA и Calzedonia — и приношу тебе.\n\n"
        "Сейчас разберёмся, что для тебя красивое.",
        reply_markup=keyboard(msg.chat.id))
    await wizard.start_wizard(msg.bot, msg.chat.id)


@dp.message(Command("anketa"))
@dp.message(F.text == BTN_TASTE)
async def anketa(msg: Message) -> None:
    """Текстом сюда попадают, только если мини-апп недоступен — тогда опрос в чате."""
    await wizard.start_wizard(msg.bot, msg.chat.id)


@dp.message(Command("chat_anketa"))
async def anketa_in_chat(msg: Message) -> None:
    await wizard.start_wizard(msg.bot, msg.chat.id)


@dp.message(Command("podborka"))
@dp.message(F.text == BTN_DIGEST)
async def now(msg: Message) -> None:
    profile = db.get_profile(msg.chat.id)
    if not profile or not profile.get("styles"):
        await msg.answer("Сначала анкета — иначе я не знаю, что искать. Жми «🎨 Мой вкус».",
                         reply_markup=keyboard(msg.chat.id))
        return
    if msg.chat.id in BUSY:
        await msg.answer("Уже ищу, подожди немного")
        return
    await run_digest(msg.bot, msg.chat.id)


@dp.message(Command("proverka"))
async def proverka(msg: Message) -> None:
    """Какие хостинги вообще открываются с этого телефона."""
    await msg.answer(
        "Открой по очереди — просто тапни. Неважно, что покажет страница, "
        "важно только открылась она или нет.\n\n"
        "1) https://octocat.github.io\n"
        "2) https://render.com\n"
        "3) https://netlify.app\n\n"
        "Потом скажи, какие загрузились. Туда и положим анкету.",
        disable_web_page_preview=True)


@dp.message(Command("pause"))
async def pause(msg: Message) -> None:
    db.set_paused(msg.chat.id, True)
    await msg.answer("Поставила на паузу. Вернуть — /resume")


@dp.message(Command("resume"))
async def resume(msg: Message) -> None:
    db.set_paused(msg.chat.id, False)
    await msg.answer("Снова приношу подборки.", reply_markup=keyboard(msg.chat.id))


@dp.message(Command("help"))
async def help_(msg: Message) -> None:
    await msg.answer(
        "<b>Что я умею</b>\n"
        "✨ Подборка — собрать свежее прямо сейчас\n"
        "🎨 Мой вкус — переписать анкету\n"
        "/pause и /resume — остановить и вернуть рассылку\n\n"
        "Раз в неделю приношу подборку сама, а между делом проверяю, "
        "не подешевело ли что-то из твоего вкуса.",
        reply_markup=keyboard(msg.chat.id))


@dp.message(F.web_app_data)
async def from_miniapp(msg: Message) -> None:
    """Ответы из анкеты приходят через Telegram, а не по сети — подделать нельзя."""
    try:
        incoming = json.loads(msg.web_app_data.data)
    except Exception as e:
        log.warning("мини-апп прислал мусор: %s", e)
        await msg.answer("Не разобрала ответ анкеты. Попробуй ещё раз.")
        return

    profile = db.get_profile(msg.chat.id) or dict(db.DEFAULT_PROFILE)
    cleaned = server._clean(incoming) if hasattr(server, "_clean") else incoming
    profile.update(cleaned)
    if not profile.get("styles"):
        await msg.answer("Стили не выбраны — открой анкету ещё раз.")
        return

    db.save_profile(msg.chat.id, profile,
                    username=msg.from_user.username or "",
                    first_name=msg.from_user.first_name or "")
    db.clear_state(msg.chat.id)
    await refresh_menu(msg.bot, msg.chat.id)

    names = " · ".join(STYLES[s]["name"] for s in profile["styles"] if s in STYLES)
    sz = profile.get("sizes", {})
    cap = ("без верхней границы" if profile.get("budgetMax", 0) >= 10 ** 9
           else rub(profile.get("budgetMax", 0)))
    await msg.answer(
        f"<b>Записала</b>\n\nСтили: {names}\n"
        f"Категорий: {len(profile.get('categories') or [])} из {len(CATEGORIES)}\n"
        f"Размеры: {sz.get('top')} / {sz.get('bottom')} / обувь {sz.get('shoes')}\n"
        f"Бюджет: до {cap}",
        reply_markup=keyboard(msg.chat.id))
    await msg.answer("Готова искать под этот вкус.", reply_markup=go_button())


@dp.message()
async def fallback(msg: Message) -> None:
    log.info("не разобрала сообщение: chat=%s %r", msg.chat.id, (msg.text or "")[:60])
    await msg.answer("Не поняла. Жми кнопки внизу или /help.", reply_markup=keyboard(msg.chat.id))


async def make_bot() -> Bot:
    bot = Bot(config.BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await bot.set_my_commands([
        BotCommand(command="podborka", description="Собрать подборку сейчас"),
        BotCommand(command="anketa", description="Заполнить анкету заново"),
        BotCommand(command="pause", description="Остановить рассылку"),
        BotCommand(command="resume", description="Вернуть рассылку"),
        BotCommand(command="help", description="Что я умею"),
    ])
    if config.app_url():
        try:
            await bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(
                    text=BTN_MENU, web_app=WebAppInfo(url=config.app_url())))
        except Exception as e:
            log.warning("не выставили кнопку меню по умолчанию: %s", e)
    return bot
