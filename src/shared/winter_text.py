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
