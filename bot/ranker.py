"""Отбор и сортировка: что из найденного вообще годится и что показать первым."""
import math
import re

from .styles import STYLES, SIZE_FOR, VETO_STEMS

_MIN_DISCOUNT = {"any": 0, "20": 20, "30": 30, "50": 50}


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


def passes(item: dict, profile: dict, category: str) -> bool:
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


def score(item: dict, style_id: str) -> float:
    s = STYLES.get(style_id, {})
    name = _norm(item.get("name", ""))

    pts = 0.0
    pts += 12 * sum(1 for stem in s.get("boost", []) if stem in name)
    pts -= 20 * sum(1 for stem in s.get("avoid", []) if stem in name)

    pts += min(item.get("discount", 0), 70) * 0.55
    pts += (item.get("rating", 0) - 4.0) * 14
    pts += math.log1p(item.get("feedbacks", 0)) * 2.5
    pts += min(len(item.get("sizes") or []), 6) * 1.5  # широкая размерная сетка = живой товар
    return pts


def rank(found: list[tuple[str, str, dict]], profile: dict) -> list[dict]:
    """found: (style_id, category, item). Возвращает годные товары по убыванию оценки."""
    best: dict[int, dict] = {}
    for style_id, category, item in found:
        if not passes(item, profile, category):
            continue
        pts = score(item, style_id)
        prev = best.get(item["id"])
        if prev is None or pts > prev["_score"]:
            best[item["id"]] = {**item, "_score": pts, "_style": style_id, "_category": category}
    return sorted(best.values(), key=lambda x: x["_score"], reverse=True)


def diversify(items: list[dict], n: int) -> list[dict]:
    """Не больше двух вещей одной категории подряд и по возможности разные стили."""
    out: list[dict] = []
    per_cat: dict[str, int] = {}
    per_style: dict[str, int] = {}
    cap_cat = max(2, n // 3)
    cap_style = max(2, n // 2)

    for it in items:
        if len(out) >= n:
            break
        c, s = it["_category"], it["_style"]
        if per_cat.get(c, 0) >= cap_cat or per_style.get(s, 0) >= cap_style:
            continue
        out.append(it)
        per_cat[c] = per_cat.get(c, 0) + 1
        per_style[s] = per_style.get(s, 0) + 1

    # добиваем, если из-за лимитов не набрали
    if len(out) < n:
        chosen = {i["id"] for i in out}
        for it in items:
            if len(out) >= n:
                break
            if it["id"] not in chosen:
                out.append(it)
    return out
