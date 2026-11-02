"""Нормализация текстов seed сезонных точек (TASK-343): телефоны, адреса, имена. Чистые функции."""
from __future__ import annotations

import re

_SCHOOL_RE = re.compile(r"(школ|гимнази|лице[йя]|\bгуо\b|\bсош\b)", re.IGNORECASE)
_INDOOR_NAME_RE = re.compile(r"(закрыт|крыт|минск[\s-]*арена|чижовка[\s-]*арена)", re.IGNORECASE)


def normalize_phones(raw: str | None) -> list[str]:
    """«8 0152 68 98 06; +375 (17) 371-04-53» -> [«+375152689806», «+375173710453»].

    Белорусские номера приводим к E.164. Непонятное не выдумываем: возвращаем как есть
    (цифры и плюс), если не похоже на белорусский номер.
    """
    out: list[str] = []
    for part in re.split(r"[;,/]|\bи\b", raw or ""):
        digits = re.sub(r"\D", "", part)
        if not digits:
            continue
        if digits.startswith("375") and len(digits) == 12:
            num = "+" + digits
        elif digits.startswith("80") and len(digits) == 11:
            num = "+375" + digits[2:]
        elif len(digits) == 9 and not digits.startswith("0"):
            num = "+375" + digits
        else:
            num = part.strip()
        if num not in out:
            out.append(num)
    return out


def phone_field(raw: str | None) -> str | None:
    """Строка для колонки phone (до 64 символов): номера через запятую."""
    nums = normalize_phones(raw)
    return ", ".join(nums)[:64] if nums else None


_ADDR_REPLACEMENTS = (
    (r"\bг\.?\s*п\.?\s", " "),
    (r"\bгп\.?\s", " "),
    (r"\bг\.\s", " "),
    (r"\bагрогородок\b|\bа/г\b|\bагр\.\s", " "),
    (r"\bпр[-.]?\s*(?:т|кт)?\.?\s", " проспект "),
    (r"\bпросп\.?\s", " проспект "),
    (r"\bпер\.?\s", " переулок "),
    (r"\bпр-д\.?\s", " проезд "),
    (r"\bул\.?\s", " улица "),
    (r"\bвул\.?\s", " улица "),
    (r"\bпл\.?\s", " площадь "),
    (r"\bд\.\s", " "),
)


def normalize_address(address: str | None, city: str | None = None) -> str:
    """Ключ сравнения адресов: без города, «ул.» -> «улица», без знаков и регистра."""
    text = (address or "").lower().replace("ё", "е")
    if city:
        text = re.sub(re.escape(city.lower().replace("ё", "е")), " ", text)
    text = " " + text + " "
    for pat, rep in _ADDR_REPLACEMENTS:
        text = re.sub(pat, rep, text)
    text = re.sub(r"[.,;:«»\"'()]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def first_address(address: str | None) -> str:
    """Два объекта в одной ячейке («ул. Мицкевича, 9; стадион «Колос»») — берём первый."""
    return (address or "").split(";")[0].strip()


def is_school_name(name: str | None) -> bool:
    return bool(_SCHOOL_RE.search(name or ""))


def is_indoor_name(name: str | None) -> bool:
    """Закрытый / крытый каток и известные крытые арены: не сезонные."""
    return bool(_INDOOR_NAME_RE.search(name or ""))


def kind_noun(kind: str) -> str:
    return "Коробка" if kind == "hockey_box" else "Каток"


def generated_name(kind: str, address: str | None, district: str | None, city: str) -> str:
    """«Коробка, ул. Соломовой 155» / «Каток, <район>» / «Каток, <город>»."""
    addr = first_address(address)
    addr = re.sub(r"^(г\.?|гп\.?|аг\.?)\s*[^,]+,\s*", "", addr, flags=re.IGNORECASE).strip()
    tail = addr or (f"{district} район" if district and "район" not in district.lower() else district) or city
    return f"{kind_noun(kind)}, {tail}"[:128]


def phone_links(raw: str | None) -> list[tuple[str, str]]:
    """«+375173647551, +375291112233» -> [(«+375 17 364-75-51», «+375173647551»), …]: (как показать, для tel:)."""
    from src.shared.phone_guard import tel_href
    from src.shared.public_display import format_phone_display

    out: list[tuple[str, str]] = []
    for part in re.split(r"[;,]", raw or ""):
        part = part.strip()
        if not part:
            continue
        out.append((format_phone_display(part), tel_href(part) or re.sub(r"[^\d+]", "", part)))
    return out


# --- официальные названия -------------------------------------------------------------
# Юр. формы и аббревиатуры учреждений, которые ничего не говорят человеку на карточке катка.
_LEGAL_FORMS = r"(?:ГУО|ГКСУ|ГУСК|ГУФК|КУПП|КУП|РУП|ГУ|УО|УП|ООО|ЗАО|ОАО|ОДО|ЧУП|МКСК)"
_INSTITUTION_ABBR = r"(?:РЦОП(?:\s+по\s+[а-яё]+\s+видам\s+спорта)?|ЦФОР|ЦФК|СДЮШОР|ДЮСШ|НОК\s+РБ|РЦОПсф)"
_LEGAL_WITH_QUOTE_RE = re.compile(rf"(?<![А-ЯЁа-яё]){_LEGAL_FORMS}\s*«")
_LEGAL_RE = re.compile(rf"(?<![А-ЯЁа-яё]){_LEGAL_FORMS}(?![А-ЯЁа-яё])")
_ABBR_RE = re.compile(rf"(?<![А-ЯЁа-яё]){_INSTITUTION_ABBR}(?![А-ЯЁа-яё])")
_LEGAL_PAREN_RE = re.compile(rf"\s*\([^)]*(?<![А-ЯЁа-яё]){_LEGAL_FORMS}(?![А-ЯЁа-яё])[^)]*\)")
_TOWN_RE = re.compile(r"\s*\bг\.\s?[А-ЯЁ][А-ЯЁа-яёіўІЎ\-]+")
_GENERIC_ONLY_RE = re.compile(r"^(?:мобильный\s+)?(?:каток|коробка|хоккейная\s+коробка|ледовая\s+площадка)$", re.IGNORECASE)


def clean_official_name(name: str | None) -> str | None:
    """«Мобильный каток ГУ «ЦФОР Заводского района г.Минска»» -> «Мобильный каток Заводского района».

    Убирает юр. формы (ГУ, ГУО, ГКСУ, УО, УП…), аббревиатуры учреждений (ЦФОР, РЦОП, СДЮШОР…) и «г.Минска».
    Кавычки-обёртки организации снимаются, кавычки бренда («Динамо», «Замок») остаются.
    ``None`` — осмысленного имени не осталось (вызывающий строит «Каток/Коробка, <адрес>»).
    """
    raw = " ".join((name or "").split())
    if not raw:
        return None
    s = _LEGAL_PAREN_RE.sub("", raw)
    had_wrapper = bool(_LEGAL_WITH_QUOTE_RE.search(s))
    s = _LEGAL_WITH_QUOTE_RE.sub("", s, count=1)
    if had_wrapper and s.count("»") > s.count("«"):
        i = s.rfind("»")
        s = s[:i] + s[i + 1:]
    s = _LEGAL_RE.sub("", s)
    s = _ABBR_RE.sub("", s)
    s = _TOWN_RE.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" ,;-–—")
    if s.startswith("«") and s.endswith("»") and s.count("«") == 1:  # вся строка в кавычках бренда
        s = s[1:-1].strip()
    s = re.sub(r"«\s+", "«", s)
    s = re.sub(r"\s+»", "»", s)
    s = re.sub(r"\s+\)", ")", s)
    letters = re.sub(r"[^A-Za-zА-Яа-яЁёІіЎў]", "", s)
    if len(letters) < 4 or not (s[0].isupper() or s[0] in "«№0123456789"):
        return None  # «по фигурному катанию» — не имя
    if _GENERIC_ONLY_RE.match(s):
        return None
    return s[:128]
