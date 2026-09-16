"""Хендлеры бота «Сорока»."""
import asyncio
import json
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (BotCommand, InlineKeyboardButton, InlineKeyboardMarkup,
                           KeyboardButton, Message, ReplyKeyboardMarkup, WebAppInfo)

from . import config, db, digest, server, wizard
from .styles import CATEGORIES, STYLES, VETO_STEMS

VETO_ORDER = list(VETO_STEMS)

log = logging.getLogger(__name__)

dp = Dispatcher()
dp.include_router(wizard.router)

BTN_DIGEST = "✨ Подборка"
BTN_TASTE = "🎨 Мой вкус"


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

    lines = [f"<b>{item['brand']}</b> · {item['name']}", price,
             f"Размеры: {', '.join(item.get('sizes', [])[:8]) or '—'}"]
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


async def send_items(bot: Bot, chat_id: int, items: list[dict]) -> None:
    for it in items:
        try:
            await bot.send_photo(chat_id, it["img"], caption=caption(it),
                                 reply_markup=buy_button(it))
        except Exception as e:
            log.warning("не отправили %s: %s", it.get("id"), e)
        await asyncio.sleep(0.4)  # бережём лимиты Telegram


async def send_digest(bot: Bot, chat_id: int, n: int | None = None,
                      only_drops: bool = False) -> int:
    profile = db.get_profile(chat_id)
    if not profile or not profile.get("styles"):
        return 0
    items = await digest.build(chat_id, profile, n or config.ITEMS_PER_DIGEST,
                               only_drops=only_drops)
    if not items:
        return 0
    head = (f"🔥 Резко подешевело — {len(items)} шт." if only_drops
            else f"Натаскала за неделю · {len(items)} вещей под твой вкус")
    await bot.send_message(chat_id, head)
    await send_items(bot, chat_id, items)
    return len(items)


# ---------------------------------------------------------------- handlers

@dp.message(CommandStart())
async def start(msg: Message) -> None:
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
    note = await msg.answer("Улетела за находками…")
    sent = await send_digest(msg.bot, msg.chat.id)
    try:
        await note.delete()
    except Exception:
        pass
    if not sent:
        await msg.answer(
            "Вернулась с пустым клювом: либо всё уже показывала, либо фильтры слишком узкие.\n"
            "Попробуй расширить бюджет или включить больше категорий — «🎨 Мой вкус».")


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

    names = " · ".join(STYLES[s]["name"] for s in profile["styles"] if s in STYLES)
    sz = profile.get("sizes", {})
    cap = ("без верхней границы" if profile.get("budgetMax", 0) >= 10 ** 9
           else rub(profile.get("budgetMax", 0)))
    await msg.answer(
        f"<b>Записала</b>\n\nСтили: {names}\n"
        f"Категорий: {len(profile.get('categories') or [])} из {len(CATEGORIES)}\n"
        f"Размеры: {sz.get('top')} / {sz.get('bottom')} / обувь {sz.get('shoes')}\n"
        f"Бюджет: до {cap}\n\nЖми «✨ Подборка».",
        reply_markup=keyboard(msg.chat.id))


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
    return bot
