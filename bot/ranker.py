"""Отбор и сортировка: что из найденного вообще годится и что показать первым."""
import datetime as dt
import math
import re
import statistics

from .styles import STYLES, SIZE_FOR, VETO_STEMS

_MIN_DISCOUNT = {"any": 0, "20": 20, "30": 30, "50": 50}

# Сезонность: пуховик в июле и купальник в январе — признак глупого сервиса.
# hi — месяцы, когда категория уместна, lo — когда почти наверняка мимо.
SEASON = {
    "outerwear": {"hi": {10, 11, 12, 1, 2, 3}, "lo": {6, 7, 8}},
    "knit":      {"hi": {10, 11, 12, 1, 2, 3}, "lo": {6, 7}},
    "swim":      {"hi": {5, 6, 7, 8},          "lo": {11, 12, 1, 2, 3}},
    "dresses":   {"hi": {4, 5, 6, 7, 8, 9},    "lo": set()},
    "shoes":     {"hi": set(),                 "lo": set()},
}


def season_bonus(category: str, month: int | None = None) -> float:
    rule = SEASON.get(category)
    if not rule:
        return 0.0
    month = month or dt.date.today().month
    if month in rule["lo"]:
        return -30.0
    if month in rule["hi"]:
        return 14.0
    return 0.0


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def _has_size(item: dict, want: str) -> bool:
    """Есть ли нужный размер в наличии. Терпимо к «42-44» и «M/L»."""
    if not want:
        return True
    want = want.strip().lower()
    for s in item.get("sizes") or []:
        s = s.strip().lower()
        if s == want:
            return True
        if want in re.split(r"[\s/,\-]+", s):
            return True
    return False


def passes(item: dict, profile: dict, category: str,
           disliked: set[str] | None = None) -> bool:
    if disliked and str(item["id"]) in disliked:
        return False                     # отмеченное «мимо» больше не показываем
    price = item["price"]
    if price < profile.get("budgetMin", 0):
        return False
    cap = profile.get("budgetMax") or 10 ** 9
    if price > cap:
        return False

    need = _MIN_DISCOUNT.get(str(profile.get("minDiscount", "any")), 0)
    if item.get("discount", 0) < need:
        return False

    size_key = SIZE_FOR.get(category)
    if size_key:
        want = (profile.get("sizes") or {}).get(size_key, "")
        if not _has_size(item, want):
            return False

    name = _norm(item.get("name", ""))
    for label in profile.get("veto") or []:
        for stem in VETO_STEMS.get(label, []):
            if stem in name:
                return False

    # совсем без отзывов — кот в мешке
    if item.get("feedbacks", 0) < 2:
        return False
    if item.get("rating", 0) and item["rating"] < 3.8:
        return False
    return True


def score(item: dict, style_id: str, prefs: dict | None = None,
          category: str = "") -> float:
    s = STYLES.get(style_id, {})
    name = _norm(item.get("name", ""))

    pts = 0.0
    pts += season_bonus(category)

    if prefs:
        # оценки человека весомее моих догадок о стилях, но не перекрывают их
        pts += 26 * prefs.get("styles", {}).get(style_id, 0.0)
        pts += 20 * prefs.get("categories", {}).get(category, 0.0)
        pts += 14 * prefs.get("brands", {}).get(item.get("brand", ""), 0.0)

        liked = prefs.get("liked_prices") or []
        if len(liked) >= 3:
            # чем дальше цена от той, что человек одобряет, тем хуже
            mid = statistics.median(liked)
            spread = max(mid * 0.6, 1500)
            pts += 12 * max(-1.0, 1 - abs(item["price"] - mid) / spread)
    pts += 12 * sum(1 for stem in s.get("boost", []) if stem in name)
    pts -= 20 * sum(1 for stem in s.get("avoid", []) if stem in name)

    pts += min(item.get("discount", 0), 70) * 0.55
    pts += (item.get("rating", 0) - 4.0) * 14
    pts += math.log1p(item.get("feedbacks", 0)) * 2.5
    pts += min(len(item.get("sizes") or []), 6) * 1.5  # широкая размерная сетка = живой товар
    return pts


def why_thin(found: list[tuple[str, str, dict]], profile: dict) -> str | None:
    """Какой фильтр отрезал больше всего. Нужно, чтобы бот не молчал,
    когда подборка вышла скудной или однообразной."""
    from collections import Counter
    c: Counter = Counter()
    cap = profile.get("budgetMax") or 10 ** 9
    need = _MIN_DISCOUNT.get(str(profile.get("minDiscount", "any")), 0)

    for _, category, item in found:
        if item["price"] < profile.get("budgetMin", 0):
            c["floor"] += 1
        elif item["price"] > cap:
            c["cap"] += 1
        elif item.get("discount", 0) < need:
            c["discount"] += 1
        else:
            size_key = SIZE_FOR.get(category)
            want = (profile.get("sizes") or {}).get(size_key, "") if size_key else ""
            if want and not _has_size(item, want):
                c["size"] += 1

    if not c:
        return None
    reason, count = c.most_common(1)[0]
    if count < len(found) * 0.3:
        return None
    hints = {
        "floor": ("Почти всё дешевле твоей нижней границы "
                  f"{profile.get('budgetMin', 0):,} ₽".replace(",", " ") +
                  " — опусти её, и выбор станет заметно шире."),
        "cap": "Почти всё дороже твоего потолка — подними верхнюю границу.",
        "discount": "Почти всё без нужной скидки — смягчи порог выгоды.",
        "size": "Твоего размера почти нигде нет в наличии — проверь размеры в анкете.",
    }
    return hints.get(reason)


def rank(found: list[tuple[str, str, dict]], profile: dict,
         prefs: dict | None = None, disliked: set[str] | None = None) -> list[dict]:
    """found: (style_id, category, item). Возвращает годные товары по убыванию оценки."""
    best: dict[int, dict] = {}
    for style_id, category, item in found:
        if not passes(item, profile, category, disliked):
            continue
        pts = score(item, style_id, prefs, category)
        prev = best.get(item["id"])
        if prev is None or pts > prev["_score"]:
            best[item["id"]] = {**item, "_score": pts, "_style": style_id, "_category": category}
    return sorted(best.values(), key=lambda x: x["_score"], reverse=True)


def diversify(items: list[dict], n: int) -> list[dict]:
    """Разводит подборку по категориям и стилям.

    Лимит не жёсткий: если с ним не набралось, ослабляем его по шагу,
    а не снимаем совсем — иначе хвост добивается тем, чего больше всего
    в выдаче, и получается восемь пальто подряд.
    """
    base_cat = max(2, n // 4)
    base_style = max(2, n // 3)

    out: list[dict] = []
    chosen: set = set()

    for relax in range(0, 6):
        per_cat: dict[str, int] = {}
        per_style: dict[str, int] = {}
        for it in out:                       # учитываем уже набранное
            per_cat[it["_category"]] = per_cat.get(it["_category"], 0) + 1
            per_style[it["_style"]] = per_style.get(it["_style"], 0) + 1

        for it in items:
            if len(out) >= n:
                break
            if it["id"] in chosen:
                continue
            c, s = it["_category"], it["_style"]
            if per_cat.get(c, 0) >= base_cat + relax:
                continue
            if per_style.get(s, 0) >= base_style + relax:
                continue
            out.append(it)
            chosen.add(it["id"])
            per_cat[c] = per_cat.get(c, 0) + 1
            per_style[s] = per_style.get(s, 0) + 1

        if len(out) >= n:
            break
    return out
