"""Анкета вкуса прямо в чате: карточки стилей и кнопки, без внешнего сайта.

Шаги идут по порядку, состояние лежит в базе — можно закрыть Telegram
и вернуться, ничего не потеряется.
"""
import logging
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, InputMediaPhoto, Message)

from . import db
from .styles import CATEGORIES, STYLES, VETO_STEMS

log = logging.getLogger(__name__)
router = Router()

CARDS = Path(__file__).resolve().parent / "cards"

MAX_STYLES = 5
MIN_STYLES = 1
ORDER = list(STYLES.keys())

SIZE_STEPS = [
    ("top", "Верх", ["XS", "S", "M", "L", "XL", "XXL"]),
    ("bottom", "Низ, российский размер", ["40", "42", "44", "46", "48", "50", "52"]),
    ("jeans", "Джинсы, американский W", ["25", "26", "27", "28", "29", "30", "31", "32"]),
    ("shoes", "Обувь, европейский", ["35", "36", "37", "38", "39", "40", "41"]),
]

BUDGETS = [
    ("До 5 000 ₽", 0, 5000),
    ("5 000 – 15 000 ₽", 5000, 15000),
    ("15 000 – 30 000 ₽", 15000, 30000),
    ("30 000 – 60 000 ₽", 30000, 60000),
    ("Без верхней границы", 1500, 10 ** 9),
]

DISCOUNTS = [
    ("any", "Просто красиво и по цене"),
    ("20", "Скидка от 20%"),
    ("30", "Скидка от 30%"),
    ("50", "Скидка от 50%"),
]

VETO = list(VETO_STEMS.keys())


# ------------------------------------------------------------------ вспомогательное

def _fresh(chat_id: int) -> dict:
    state = {"step": "styles", "idx": 0, "picked": [],
             "cats": list(CATEGORIES.keys()), "sizes": {}, "veto": []}
    db.set_state(chat_id, state)
    return state


def _rows(buttons: list[InlineKeyboardButton], per_row: int) -> InlineKeyboardMarkup:
    grid = [buttons[i:i + per_row] for i in range(0, len(buttons), per_row)]
    return InlineKeyboardMarkup(inline_keyboard=grid)


async def _photo(bot: Bot, style_id: str) -> FSInputFile | str:
    """Отдаём file_id, если Telegram уже хранит эту картинку. Иначе файл."""
    cached = db.get_file_id(f"style:{style_id}")
    return cached or FSInputFile(CARDS / f"{style_id}.jpg")


def _remember_photo(style_id: str, msg: Message) -> None:
    if msg.photo and not db.get_file_id(f"style:{style_id}"):
        db.set_file_id(f"style:{style_id}", msg.photo[-1].file_id)


# ------------------------------------------------------------------ шаг 1: стили

def _style_caption(state: dict) -> str:
    sid = ORDER[state["idx"]]
    s = STYLES[sid]
    n = len(state["picked"])
    chosen = " · ".join(STYLES[x]["name"] for x in state["picked"]) or "пока ничего"
    return (f"<b>{s['name']}</b>\n"
            f"<i>{s['keys']}</i>\n\n"
            f"Стиль {state['idx'] + 1} из {len(ORDER)}\n"
            f"Выбрано {n} из {MAX_STYLES}: {chosen}")


def _style_kb(state: dict) -> InlineKeyboardMarkup:
    sid = ORDER[state["idx"]]
    picked = sid in state["picked"]
    row = [
        InlineKeyboardButton(text="✅ Выбрано" if picked else "🤍 Нравится",
                             callback_data=f"w:like:{state['idx']}"),
        InlineKeyboardButton(text="Дальше →", callback_data=f"w:next:{state['idx']}"),
    ]
    rows = [row]
    if len(state["picked"]) >= MIN_STYLES:
        rows.append([InlineKeyboardButton(text="Хватит, дальше к категориям",
                                          callback_data="w:styles_done")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_style(bot: Bot, chat_id: int, state: dict,
                     edit: Message | None = None) -> None:
    sid = ORDER[state["idx"]]
    media = InputMediaPhoto(media=await _photo(bot, sid), caption=_style_caption(state),
                            parse_mode="HTML")
    if edit is not None:
        try:
            sent = await edit.edit_media(media=media, reply_markup=_style_kb(state))
            if isinstance(sent, Message):
                _remember_photo(sid, sent)
            return
        except Exception as e:
            log.warning("не переписали карточку, шлём новую: %s", e)
    sent = await bot.send_photo(chat_id, await _photo(bot, sid),
                                caption=_style_caption(state),
                                reply_markup=_style_kb(state))
    _remember_photo(sid, sent)


async def start_wizard(bot: Bot, chat_id: int) -> None:
    state = _fresh(chat_id)
    await bot.send_message(
        chat_id,
        "Покажу 16 стилей — по одному, с реальной вещью твоих брендов.\n"
        f"Отмечай те, что откликаются: нужно от {MIN_STYLES} до {MAX_STYLES}.")
    await show_style(bot, chat_id, state)


@router.callback_query(F.data.startswith("w:like:"))
async def on_like(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась, начни заново: /anketa", show_alert=True)
        return

    sid = ORDER[state["idx"]]
    if sid in state["picked"]:
        state["picked"].remove(sid)
        await cb.answer("Убрала")
    elif len(state["picked"]) >= MAX_STYLES:
        await cb.answer(f"Уже {MAX_STYLES} — больше не нужно, сними лишнее",
                        show_alert=True)
        return
    else:
        state["picked"].append(sid)
        await cb.answer("Записала")

    if len(state["picked"]) >= MAX_STYLES:
        db.set_state(cb.message.chat.id, state)
        await ask_categories(cb.bot, cb.message.chat.id, state, cb.message)
        return

    # дальше сам, чтобы не тыкать «Дальше» после каждого выбора
    if sid in state["picked"] and state["idx"] < len(ORDER) - 1:
        state["idx"] += 1
    db.set_state(cb.message.chat.id, state)
    await show_style(cb.bot, cb.message.chat.id, state, edit=cb.message)


@router.callback_query(F.data.startswith("w:next:"))
async def on_next(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась, начни заново: /anketa", show_alert=True)
        return
    await cb.answer()

    if state["idx"] >= len(ORDER) - 1:
        if len(state["picked"]) < MIN_STYLES:
            state["idx"] = 0  # круг закончился, а выбора нет — заходим на второй
            db.set_state(cb.message.chat.id, state)
            await show_style(cb.bot, cb.message.chat.id, state, edit=cb.message)
            return
        db.set_state(cb.message.chat.id, state)
        await ask_categories(cb.bot, cb.message.chat.id, state, cb.message)
        return

    state["idx"] += 1
    db.set_state(cb.message.chat.id, state)
    await show_style(cb.bot, cb.message.chat.id, state, edit=cb.message)


@router.callback_query(F.data == "w:styles_done")
async def on_styles_done(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state or len(state["picked"]) < MIN_STYLES:
        await cb.answer("Отметь хотя бы один стиль", show_alert=True)
        return
    await cb.answer()
    await ask_categories(cb.bot, cb.message.chat.id, state, cb.message)


# ------------------------------------------------------------------ шаг 2: категории

def _cats_kb(state: dict) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(
        text=("✅ " if key in state["cats"] else "⬜️ ") + name,
        callback_data=f"w:cat:{key}") for key, name in CATEGORIES.items()]
    kb = _rows(btns, 1)
    kb.inline_keyboard.append([InlineKeyboardButton(text="Готово →",
                                                    callback_data="w:cats_done")])
    return kb


async def ask_categories(bot: Bot, chat_id: int, state: dict,
                         old: Message | None = None) -> None:
    state["step"] = "cats"
    db.set_state(chat_id, state)
    picked = " · ".join(STYLES[x]["name"] for x in state["picked"])
    if old is not None:
        try:
            await old.edit_caption(caption=f"Стили записала: <b>{picked}</b>",
                                   parse_mode="HTML", reply_markup=None)
        except Exception:
            pass
    await bot.send_message(
        chat_id,
        "Теперь категории. Сейчас включено всё — сними то, что не нужно.",
        reply_markup=_cats_kb(state))


@router.callback_query(F.data.startswith("w:cat:"))
async def on_cat(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    key = cb.data.split(":")[2]
    if key in state["cats"]:
        state["cats"].remove(key)
    else:
        state["cats"].append(key)
    db.set_state(cb.message.chat.id, state)
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=_cats_kb(state))


@router.callback_query(F.data == "w:cats_done")
async def on_cats_done(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    if not state["cats"]:
        await cb.answer("Оставь хотя бы одну категорию", show_alert=True)
        return
    await cb.answer()
    names = ", ".join(CATEGORIES[c] for c in state["cats"])
    await cb.message.edit_text(f"Категории: {names}")
    await ask_size(cb.bot, cb.message.chat.id, state, 0)


# ------------------------------------------------------------------ шаг 3: размеры

async def ask_size(bot: Bot, chat_id: int, state: dict, step: int) -> None:
    state["step"] = f"size:{step}"
    db.set_state(chat_id, state)
    key, title, opts = SIZE_STEPS[step]
    btns = [InlineKeyboardButton(text=o, callback_data=f"w:size:{step}:{o}") for o in opts]
    await bot.send_message(chat_id, f"Размер · {title}", reply_markup=_rows(btns, 4))


@router.callback_query(F.data.startswith("w:size:"))
async def on_size(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    _, _, step_s, value = cb.data.split(":", 3)
    step = int(step_s)
    key, title, _ = SIZE_STEPS[step]
    state["sizes"][key] = value
    db.set_state(cb.message.chat.id, state)
    await cb.answer()
    await cb.message.edit_text(f"{title}: <b>{value}</b>", parse_mode="HTML")

    if step + 1 < len(SIZE_STEPS):
        await ask_size(cb.bot, cb.message.chat.id, state, step + 1)
    else:
        await ask_budget(cb.bot, cb.message.chat.id, state)


# ------------------------------------------------------------------ шаг 4: бюджет

async def ask_budget(bot: Bot, chat_id: int, state: dict) -> None:
    state["step"] = "budget"
    db.set_state(chat_id, state)
    btns = [InlineKeyboardButton(text=label, callback_data=f"w:bud:{i}")
            for i, (label, _, _) in enumerate(BUDGETS)]
    await bot.send_message(chat_id, "Сколько готова отдать за одну вещь?",
                           reply_markup=_rows(btns, 1))


@router.callback_query(F.data.startswith("w:bud:"))
async def on_budget(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    label, lo, hi = BUDGETS[int(cb.data.split(":")[2])]
    state["budgetMin"], state["budgetMax"] = lo, hi
    db.set_state(cb.message.chat.id, state)
    await cb.answer()
    await cb.message.edit_text(f"Бюджет: <b>{label}</b>", parse_mode="HTML")

    btns = [InlineKeyboardButton(text=name, callback_data=f"w:disc:{key}")
            for key, name in DISCOUNTS]
    await cb.bot.send_message(cb.message.chat.id, "Что считать выгодным?",
                              reply_markup=_rows(btns, 1))


@router.callback_query(F.data.startswith("w:disc:"))
async def on_discount(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    key = cb.data.split(":")[2]
    state["minDiscount"] = key
    db.set_state(cb.message.chat.id, state)
    await cb.answer()
    name = dict(DISCOUNTS)[key]
    await cb.message.edit_text(f"Порог выгоды: <b>{name}</b>", parse_mode="HTML")
    await ask_veto(cb.bot, cb.message.chat.id, state)


# ------------------------------------------------------------------ шаг 5: стоп-лист

def _veto_kb(state: dict) -> InlineKeyboardMarkup:
    btns = [InlineKeyboardButton(
        text=("🚫 " if v in state["veto"] else "") + v,
        callback_data=f"w:veto:{i}") for i, v in enumerate(VETO)]
    kb = _rows(btns, 2)
    kb.inline_keyboard.append([InlineKeyboardButton(text="Готово, сохранить",
                                                    callback_data="w:finish")])
    return kb


async def ask_veto(bot: Bot, chat_id: int, state: dict) -> None:
    state["step"] = "veto"
    db.set_state(chat_id, state)
    await bot.send_message(
        chat_id,
        "Последнее. Есть что-то, чего не присылать никогда? "
        "Отметь — или сразу жми «Готово».",
        reply_markup=_veto_kb(state))


@router.callback_query(F.data.startswith("w:veto:"))
async def on_veto(cb: CallbackQuery) -> None:
    state = db.get_state(cb.message.chat.id)
    if not state:
        await cb.answer("Анкета потерялась: /anketa", show_alert=True)
        return
    v = VETO[int(cb.data.split(":")[2])]
    if v in state["veto"]:
        state["veto"].remove(v)
    else:
        state["veto"].append(v)
    db.set_state(cb.message.chat.id, state)
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=_veto_kb(state))


# ------------------------------------------------------------------ финал

@router.callback_query(F.data == "w:finish")
async def on_finish(cb: CallbackQuery) -> None:
    chat_id = cb.message.chat.id
    state = db.get_state(chat_id)
    if not state or not state.get("picked"):
        await cb.answer("Стили не выбраны, начни заново: /anketa", show_alert=True)
        return
    await cb.answer()

    profile = db.get_profile(chat_id) or dict(db.DEFAULT_PROFILE)
    profile.update({
        "styles": state["picked"],
        "categories": state["cats"],
        "veto": state["veto"],
        "sizes": {**profile.get("sizes", {}), **state.get("sizes", {})},
        "budgetMin": state.get("budgetMin", profile.get("budgetMin")),
        "budgetMax": state.get("budgetMax", profile.get("budgetMax")),
        "minDiscount": state.get("minDiscount", profile.get("minDiscount")),
    })
    db.save_profile(chat_id, profile,
                    username=cb.from_user.username or "",
                    first_name=cb.from_user.first_name or "")
    db.clear_state(chat_id)

    styles_txt = " · ".join(STYLES[s]["name"] for s in profile["styles"])
    sz = profile["sizes"]
    cap = ("без верхней границы" if profile["budgetMax"] >= 10 ** 9
           else f"до {profile['budgetMax']:,}".replace(",", " ") + " ₽")
    await cb.message.edit_text(
        "<b>Готово, профиль записан</b>\n\n"
        f"Стили: {styles_txt}\n"
        f"Категорий: {len(profile['categories'])} из {len(CATEGORIES)}\n"
        f"Размеры: {sz.get('top')} / {sz.get('bottom')} / обувь {sz.get('shoes')}\n"
        f"Бюджет: {cap}\n"
        + (f"Стоп-лист: {', '.join(profile['veto'])}\n" if profile["veto"] else "")
        + "\nЖми «✨ Подборка» — слетаю за находками.",
        parse_mode="HTML")
