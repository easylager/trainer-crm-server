"""TASK-063: load verified Minsk MK dossiers into arena_profiles (ops, not research).

Default is dry-run. ``--apply`` writes to a local test DB only — never production.

Usage:
  PYTHONPATH=. python scripts/load_minsk_arena_cards.py
  PYTHONPATH=. python scripts/load_minsk_arena_cards.py --apply
  PYTHONPATH=. python scripts/load_minsk_arena_cards.py --apply --report .ai/data/arena-cards/TASK-063-load-report.md

Photos: official rink site/socials and local dossier files are would-upload / uploaded on
``--apply`` for demo (EPIC3 2026-09-06: verbal OK is enough). ``license`` must be
own|operator|permitted; Google/gstatic/stock never. Grant notes do not block official frames.
DiaMond ``photos/minsk-diamond/bannerled.png`` is loaded. Cap 6 photos per arena (TASK-049).
Manual ice_sessions: optional 7-day public_skate/open_ice from fixture expected.json
(source_id=etalon_073). Skip empty / 403-only fixtures. TASK-061 adapters are not used.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib import error as urllib_error
from urllib import request as urllib_request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SOURCE_ETALON = "etalon_073"
TARGET_ARENA_IDS = (2, 3, 6, 5, 7, 8, 4)
DEFAULT_TZ = "Europe/Minsk"
PHONE_MAX_LEN = 32
SESSION_HORIZON_DAYS = 7
CLIENT_SESSION_KINDS = frozenset({"public_skate", "open_ice"})
AMENITY_KEYS = frozenset(
    {
        "skate_rental",
        "skate_sharpening",
        "parking",
        "locker_rooms",
        "cafe",
        "accessibility",
    }
)
UNKNOWN_TOKENS = frozenset({"", "unknown", "—", "-", "–", "нет"})
GOOGLE_IMAGE_RE = re.compile(r"google\.(?:com|by)|gstatic\.com|googleapis\.com", re.I)
STOCK_OR_AGGREGATOR_RE = re.compile(
    r"unsplash\.com|shutterstock\.com|gettyimages\.|pinterest\.|yandex\.(?:ru|by|com)/images",
    re.I,
)
SOCIAL_PROFILE_RE = re.compile(
    r"(?:instagram\.com|facebook\.com|fb\.com|vk\.com|t\.me|telegram\.me)/",
    re.I,
)
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif"})
ARENA_MEDIA_MAX = 6
BY_BLOCKER_RE = re.compile(r"403|BY-egress|BY-blocker|nginx/1\.10", re.I)
SEASON_START_RE = re.compile(r"season_start_month\s*=\s*(\d{1,2})", re.I)
SEASON_END_RE = re.compile(r"season_end_month\s*=\s*(\d{1,2})", re.I)
YEAR_ROUND_RE = re.compile(r"круглый год", re.I)
DAILY_HOURS_RE = re.compile(
    r"ежедневно\s+(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})",
    re.I,
)
AMENITY_PAIR_RE = re.compile(
    r"(skate_rental|skate_sharpening|parking|locker_rooms|cafe|accessibility)"
    r"\s*[:=]\s*(true|false|unknown)",
    re.I,
)
PHONE_RE = re.compile(r"\+375[\d\s().-]{7,}")
HEADER_ARENA_ID_RE = re.compile(r"^-\s*arena_id:\s*(\d+)\s*$", re.M)
HEADER_SLUG_RE = re.compile(r"^-\s*slug:\s*(\S+)\s*$", re.M)
HEADER_VERIFIED_RE = re.compile(r"^-\s*verified_at:\s*(\S+)\s*$", re.M)
SOCIAL_SPECS = (
    ("instagram", re.compile(r"https?://(?:www\.)?instagram\.com/[^\s;]+", re.I)),
    ("facebook", re.compile(r"https?://(?:www\.|web\.)?facebook\.com/[^\s;]+", re.I)),
    ("vk", re.compile(r"https?://(?:www\.)?vk\.com/[^\s;]+", re.I)),
    ("youtube", re.compile(r"https?://(?:www\.)?youtube\.com/[^\s;]+", re.I)),
    ("telegram", re.compile(r"https?://(?:t\.me|telegram\.me)/[^\s;]+", re.I)),
)
SLUG_FIXTURE_DIRS = {
    "zamok": ("minsk-zamok",),
    "minskarena": ("minsk-arena", "minsk-minskarena"),
    "chizhovka": ("minsk-chizhovka",),
    "ledby": ("minsk-ledby",),
    "minsk-diamond": ("minsk-diamond",),
    "minsk-junost": ("minsk-junost",),
    "minsk-ledlife": ("minsk-ledlife",),
}
LOCAL_DB_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "db", "host.docker.internal"}
)
CLOUD_DB_MARKERS = (
    "railway",
    "supabase",
    "neon.tech",
    "amazonaws.com",
    "azure",
    "render.com",
    "onrender.com",
    "planetscale",
    "digitalocean",
    "prod.",
    "production",
)


class ProdDatabaseError(RuntimeError):
    """Refuses writes (and apply) against a non-local / production-looking URL."""


@dataclass
class PhotoDecision:
    url_or_file: str
    license: str | None
    attribution: str | None
    note: str
    action: str
    reason: str


@dataclass
class SessionPlan:
    fixture_path: Path | None
    seed: bool
    reason: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    horizon_start: date | None = None
    horizon_end: date | None = None
    valid_until: datetime | None = None
    clipped: int = 0
    skipped_kind: int = 0
    skipped_duration: int = 0


@dataclass
class ArenaCard:
    path: Path
    arena_id: int
    slug: str
    verified_at: date | None
    district: str | None
    phone: str | None
    website_url: str | None
    opening_hours: dict[str, Any] | None
    season_start_month: int | None
    season_end_month: int | None
    amenities: dict[str, bool]
    short_description: str | None
    social_urls: dict[str, str]
    photo_decisions: list[PhotoDecision]
    field_sources: dict[str, str]
    blockers: list[str]
    enough_facts: bool
    status: str
    parse_ms: float = 0.0

    @property
    def publishable_photo_count(self) -> int:
        return sum(1 for p in self.photo_decisions if p.action == "upload")


@dataclass
class ArenaLoadResult:
    card: ArenaCard
    profile: str
    sessions_seeded: int = 0
    sessions_skipped: int = 0
    sessions_reason: str = ""
    photo_summary: str = ""
    photos_uploaded: int = 0
    apply_ms: float = 0.0
    error: str | None = None


def is_unknown(value: str | None) -> bool:
    if value is None:
        return True
    return value.strip().lower() in UNKNOWN_TOKENS


def _cell(raw: str) -> str:
    return (raw or "").strip().strip("`").strip()


def _split_md_row(stripped: str) -> list[str]:
    inner = stripped.strip().strip("|").replace("\\|", "\x00")
    return [_cell(c.replace("\x00", "|")) for c in inner.split("|")]


def _parse_md_table(section: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if header is not None and rows:
                break
            continue
        cells = _split_md_row(stripped)
        if not cells or all(set(c) <= {"-", ":"} and c for c in cells):
            continue
        if header is None:
            header = [c.lower() for c in cells]
            continue
        padded = cells + [""] * (len(header) - len(cells))
        rows.append({header[i]: padded[i] for i in range(len(header))})
    return rows


def _section_after(md: str, prefix: str) -> str:
    lines = md.splitlines()
    capturing = False
    out: list[str] = []
    for line in lines:
        if line.startswith("## "):
            if capturing:
                break
            if line[3:].lower().startswith(prefix.lower()):
                capturing = True
                continue
        if capturing:
            out.append(line)
    return "\n".join(out)


def _known_text(value: str | None) -> str | None:
    if is_unknown(value):
        return None
    text = (value or "").strip()
    return text or None


def compact_phone(raw: str | None) -> str | None:
    """Store a verified number that fits arena_profiles.phone (32 chars). Never invent digits."""
    if is_unknown(raw):
        return None
    text = (raw or "").strip()
    found = PHONE_RE.findall(text)
    compact: list[str] = []
    for chunk in found:
        digits = re.sub(r"[^\d+]", "", chunk)
        if not digits.startswith("+"):
            digits = "+" + digits.lstrip("+")
        # BY: +375 + 9 digits
        if re.fullmatch(r"\+375\d{9}", digits) and digits not in compact:
            compact.append(digits)
    if compact:
        joined = "; ".join(compact)
        if len(joined) <= PHONE_MAX_LEN:
            return joined
        return compact[0]
    if len(text) <= PHONE_MAX_LEN:
        return text
    return None


def parse_social_urls(raw: str | None) -> dict[str, str]:
    if is_unknown(raw):
        return {}
    text = raw or ""
    out: dict[str, str] = {}
    for key, pattern in SOCIAL_SPECS:
        match = pattern.search(text)
        if not match:
            continue
        url = match.group(0).rstrip(").,;")
        out[key] = url
    return out


def parse_amenities(raw: str | None) -> dict[str, bool]:
    if is_unknown(raw):
        return {}
    out: dict[str, bool] = {}
    for match in AMENITY_PAIR_RE.finditer(raw or ""):
        key = match.group(1).lower()
        token = match.group(2).lower()
        if key not in AMENITY_KEYS or token == "unknown":
            continue
        out[key] = token == "true"
    return out


def parse_season(raw: str | None) -> tuple[int | None, int | None]:
    if is_unknown(raw):
        return None, None
    text = raw or ""
    start_m = SEASON_START_RE.search(text)
    end_m = SEASON_END_RE.search(text)
    start = int(start_m.group(1)) if start_m else None
    end = int(end_m.group(1)) if end_m else None
    if start is None and end is None and YEAR_ROUND_RE.search(text):
        return 1, 12
    if start is not None and not (1 <= start <= 12):
        start = None
    if end is not None and not (1 <= end <= 12):
        end = None
    return start, end


def _norm_hhmm(raw: str) -> str:
    hours, minutes = raw.split(":")
    return f"{int(hours):02d}:{int(minutes):02d}"


def parse_opening_hours(raw: str | None) -> dict[str, Any] | None:
    if is_unknown(raw):
        return None
    text = (raw or "").strip()
    payload: dict[str, Any] = {"note": text}
    daily = DAILY_HOURS_RE.search(text)
    if daily:
        payload["daily"] = {"open": _norm_hhmm(daily.group(1)), "close": _norm_hhmm(daily.group(2))}
        return payload
    # Lift a bare range only when it is the leading fact (DiaMond). Do not pick the
    # first weekday fragment out of a mixed admin/rink note (Минск-Арена).
    leading = re.match(r"^(\d{1,2}:\d{2})\s*[–-]\s*(\d{1,2}:\d{2})\b", text)
    if leading:
        payload["hours"] = {"open": _norm_hhmm(leading.group(1)), "close": _norm_hhmm(leading.group(2))}
    return payload


def _asset_path(value: str) -> str:
    if "://" in value:
        return urlparse(value).path
    return value.split("?", 1)[0]


def _looks_like_image_ref(value: str) -> bool:
    if is_unknown(value):
        return False
    suffix = Path(_asset_path(value)).suffix.lower()
    return suffix in IMAGE_SUFFIXES


def _first_http_url(text: str | None) -> str | None:
    if not text:
        return None
    match = re.search(r"https?://[^\s)>\]]+", text)
    if not match:
        return None
    return match.group(0).rstrip(").,;")


def photo_source_url(decision: PhotoDecision) -> str | None:
    """HTTP origin for media.source_url (TASK-049). Local files use attribution URL."""
    ref = decision.url_or_file
    if ref.startswith(("http://", "https://")):
        return ref
    return _first_http_url(decision.attribution)


def _cap_arena_media(photos: list[PhotoDecision]) -> list[PhotoDecision]:
    kept = 0
    out: list[PhotoDecision] = []
    for photo in photos:
        if photo.action != "upload":
            out.append(photo)
            continue
        if kept >= ARENA_MEDIA_MAX:
            out.append(
                PhotoDecision(
                    photo.url_or_file,
                    photo.license,
                    photo.attribution,
                    photo.note,
                    "skip",
                    f"arena media limit {ARENA_MEDIA_MAX}",
                )
            )
            continue
        kept += 1
        out.append(photo)
    return out


def _decide_photo(row: Mapping[str, str], *, slug: str) -> PhotoDecision | None:
    _ = slug  # call-site compatibility; decisions are URL/license based
    url = _cell(row.get("file or url") or row.get("file") or row.get("url") or "")
    license_raw = _cell(row.get("license (own|operator|permitted)") or row.get("license") or "")
    attribution = _cell(row.get("attribution") or "") or None
    note = _cell(row.get("note") or "")
    if is_unknown(url) and is_unknown(license_raw) and not note:
        return None
    license_val = None if is_unknown(license_raw) else license_raw.lower()
    haystack = f"{url} {note} {attribution or ''}"
    if GOOGLE_IMAGE_RE.search(haystack):
        return PhotoDecision(url, license_val, attribution, note, "skip", "google/search image — never download")
    if STOCK_OR_AGGREGATOR_RE.search(haystack):
        return PhotoDecision(url, license_val, attribution, note, "skip", "stock/aggregator image — never download")
    if is_unknown(url):
        return PhotoDecision(url or "—", license_val, attribution, note, "skip", "no photo / waiting")
    if SOCIAL_PROFILE_RE.search(url) and not _looks_like_image_ref(url):
        return PhotoDecision(url, license_val, attribution, note, "skip", "instagram/social — never scrape")
    if not _looks_like_image_ref(url):
        reason = "origin 403 — no file" if "403" in haystack else "not an image file"
        return PhotoDecision(url, license_val, attribution, note, "skip", reason)
    if license_val not in {"own", "operator", "permitted"}:
        return PhotoDecision(url, license_val, attribution, note, "skip", "license not explicit")
    # EPIC3 2026-09-06: verbal OK is enough. Grant notes do not block official rink frames.
    return PhotoDecision(
        url,
        license_val,
        attribution,
        note,
        "upload",
        "official operator source — presentation (verbal OK 2026-09-06)",
    )


def _collect_blockers(md: str, slug: str) -> list[str]:
    if not BY_BLOCKER_RE.search(md):
        return []
    if slug in {"minsk-junost", "junost"}:
        return ["junost.by origin 403 (needs BY-egress)"]
    if slug in {"minsk-ledlife", "ledlife"}:
        return ["ledlife.by origin 403 (needs BY-egress)"]
    return ["403 / BY-egress blocker noted in dossier"]


def enough_profile_facts(
    *,
    district: str | None,
    phone: str | None,
    website_url: str | None,
    short_description: str | None,
    amenities: Mapping[str, bool],
) -> bool:
    n = sum(
        1
        for value in (district, phone, website_url, short_description)
        if value
    )
    if amenities:
        n += 1
    return n >= 2


def parse_dossier(path: Path) -> ArenaCard:
    started = time.perf_counter()
    md = path.read_text(encoding="utf-8")
    id_match = HEADER_ARENA_ID_RE.search(md)
    slug_match = HEADER_SLUG_RE.search(md)
    if not id_match:
        raise ValueError(f"{path.name}: missing arena_id — refuse to invent")
    if not slug_match:
        raise ValueError(f"{path.name}: missing slug")
    arena_id = int(id_match.group(1))
    slug = slug_match.group(1).strip()
    verified_raw = HEADER_VERIFIED_RE.search(md)
    verified_at = None
    if verified_raw:
        try:
            verified_at = date.fromisoformat(verified_raw.group(1)[:10])
        except ValueError:
            verified_at = None

    profile_rows = _parse_md_table(_section_after(md, "profile"))
    fields = {row.get("field", "").strip(): row for row in profile_rows if row.get("field")}

    def value_of(key: str) -> str | None:
        row = fields.get(key)
        if not row:
            return None
        return row.get("value")

    district = _known_text(value_of("district"))
    phone = compact_phone(value_of("phone"))
    website_url = _known_text(value_of("website_url"))
    opening_hours = parse_opening_hours(value_of("opening_hours"))
    season_start, season_end = parse_season(value_of("season"))
    amenities = parse_amenities(value_of("amenities"))
    short_description = _known_text(value_of("short_description"))
    social_urls = parse_social_urls(value_of("socials"))
    field_sources = {
        key: (fields[key].get("source") or "").strip()
        for key in fields
        if not is_unknown(fields[key].get("value"))
    }
    photos = _cap_arena_media(
        [
            decision
            for row in _parse_md_table(_section_after(md, "photos"))
            if (decision := _decide_photo(row, slug=slug)) is not None
        ]
    )
    enough = enough_profile_facts(
        district=district,
        phone=phone,
        website_url=website_url,
        short_description=short_description,
        amenities=amenities,
    )
    return ArenaCard(
        path=path,
        arena_id=arena_id,
        slug=slug,
        verified_at=verified_at,
        district=district,
        phone=phone,
        website_url=website_url,
        opening_hours=opening_hours,
        season_start_month=season_start,
        season_end_month=season_end,
        amenities=amenities,
        short_description=short_description,
        social_urls=social_urls,
        photo_decisions=photos,
        field_sources=field_sources,
        blockers=_collect_blockers(md, slug),
        enough_facts=enough,
        status="published" if enough else "draft",
        parse_ms=(time.perf_counter() - started) * 1000,
    )


def discover_dossiers(cards_dir: Path) -> list[Path]:
    paths = []
    for path in sorted(cards_dir.glob("minsk-*.md")):
        name = path.name.lower()
        if "load-report" in name or "stand-report" in name or name == "readme.md":
            continue
        paths.append(path)
    return paths


def parse_only_arena_ids(raw: str | None) -> frozenset[int] | None:
    """Comma-separated arena_ids for a local apply subset. None = all dossiers."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return frozenset()
    out: set[int] = set()
    for chunk in text.split(","):
        piece = chunk.strip()
        if not piece:
            continue
        out.add(int(piece))
    return frozenset(out)


def fixture_expected_path(slug: str, fixtures_dir: Path) -> Path | None:
    names: list[str] = []
    names.extend(SLUG_FIXTURE_DIRS.get(slug, ()))
    names.append(slug)
    if not slug.startswith("minsk-"):
        names.append(f"minsk-{slug}")
    seen: set[str] = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        candidate = fixtures_dir / name / "expected.json"
        if candidate.is_file():
            return candidate
    return None


def _duration_minutes(start: dt_time, end: dt_time) -> int:
    dummy = date(2026, 1, 1)
    started = datetime.combine(dummy, start)
    ended = datetime.combine(dummy, end)
    if ended <= started:
        ended += timedelta(days=1)
    return int((ended - started).total_seconds() // 60)


def plan_sessions(card: ArenaCard, fixtures_dir: Path) -> SessionPlan:
    path = fixture_expected_path(card.slug, fixtures_dir)
    if path is None:
        return SessionPlan(None, False, "no expected.json on this train")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("blocked_without_by_egress") or payload.get("http_status") == 403:
        return SessionPlan(path, False, "403-only / BY-egress — skip")
    sessions = payload.get("sessions") or []
    if not sessions:
        return SessionPlan(path, False, "empty sessions")
    skipped_kind = 0
    usable: list[dict[str, Any]] = []
    for row in sessions:
        kind = (row.get("kind") or "").strip()
        if kind not in CLIENT_SESSION_KINDS:
            skipped_kind += 1
            continue
        usable.append(row)
    if not usable:
        return SessionPlan(path, False, "no public_skate/open_ice rows", skipped_kind=skipped_kind)
    dates = sorted({date.fromisoformat(str(row["local_date"])) for row in usable})
    horizon_start = dates[0]
    horizon_end = horizon_start + timedelta(days=SESSION_HORIZON_DAYS - 1)
    windowed = [
        row
        for row in usable
        if horizon_start <= date.fromisoformat(str(row["local_date"])) <= horizon_end
    ]
    clipped = len(usable) - len(windowed)
    kept: list[dict[str, Any]] = []
    skipped_duration = 0
    for row in windowed:
        start = _parse_hhmm(row["starts_at_local"])
        end = _parse_hhmm(row["ends_at_local"])
        minutes = _duration_minutes(start, end)
        if minutes < 30 or minutes > 120:
            skipped_duration += 1
            continue
        kept.append(row)
    valid_until = datetime.combine(horizon_end, dt_time(23, 59, 59), tzinfo=ZoneInfo(DEFAULT_TZ))
    return SessionPlan(
        path,
        True,
        "seed ≤7 days from expected.json",
        rows=kept,
        horizon_start=horizon_start,
        horizon_end=horizon_end,
        valid_until=valid_until,
        clipped=clipped,
        skipped_kind=skipped_kind,
        skipped_duration=skipped_duration,
    )


def _parse_hhmm(value: str) -> dt_time:
    from src.application.ice_session_use_cases import parse_hhmm

    return parse_hhmm(value)


def _normalize_db_url(url: str) -> str:
    raw = url.strip()
    for prefix in ("postgresql+asyncpg://", "postgresql+psycopg://", "postgresql+psycopg2://"):
        if raw.startswith(prefix):
            return "postgresql://" + raw[len(prefix) :]
    return raw


def assert_local_database_url(url: str, *, apply: bool, allow_local_dev: bool = False) -> None:
    parsed = urlparse(_normalize_db_url(url))
    host = (parsed.hostname or "").lower()
    dbname = (parsed.path or "").lstrip("/").split("?")[0]
    haystack = f"{host} {url.lower()}"
    if any(marker in haystack for marker in CLOUD_DB_MARKERS):
        raise ProdDatabaseError(
            f"refusing DATABASE_URL host that looks like production/cloud ({host!r})"
        )
    local_ok = host in LOCAL_DB_HOSTS or (host.startswith("127.") and host.count(".") == 3)
    if not local_ok:
        raise ProdDatabaseError(f"refusing non-local DATABASE_URL host {host!r}")
    if not apply:
        return
    if dbname == "trainer_crm_test":
        return
    if dbname == "trainer_crm" and allow_local_dev:
        return
    raise ProdDatabaseError(
        f"apply requires database trainer_crm_test (got {dbname!r}). "
        "Pass --allow-local-dev-db only for a clearly local trainer_crm, never prod."
    )


def resolve_database_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_SYNC") or "").strip()
    if raw:
        return raw
    from src.shared.config import Settings

    return Settings().database_url


def async_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _content_type_for(ref: str) -> str:
    suffix = Path(_asset_path(ref)).suffix.lower()
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(suffix, "image/jpeg")


def resolve_local_photo_path(ref: str, *, root: Path) -> Path | None:
    if is_unknown(ref) or ref.startswith(("http://", "https://")):
        return None
    cleaned = ref.strip().lstrip("./")
    candidates = [
        Path(ref) if os.path.isabs(ref) else None,
        root / cleaned,
        root / ".ai" / "data" / "arena-cards" / cleaned,
        root / ".ai" / "data" / cleaned,
    ]
    for path in candidates:
        if path is not None and path.is_file():
            return path
    return None


def fetch_remote_photo_bytes(url: str, *, timeout: float = 8.0) -> bytes | None:
    """GET a dossier URL. Never follow search/stock/social profile pages."""
    if not url.startswith(("http://", "https://")):
        return None
    if GOOGLE_IMAGE_RE.search(url) or STOCK_OR_AGGREGATOR_RE.search(url):
        return None
    if SOCIAL_PROFILE_RE.search(url) and not _looks_like_image_ref(url):
        return None
    req = urllib_request.Request(
        url,
        headers={"User-Agent": "IceProCare-TASK-063/1.0 (arena card loader; operator demo)"},
    )
    try:
        with urllib_request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(15 * 1024 * 1024 + 1)
    except (urllib_error.URLError, TimeoutError, OSError, ValueError):
        return None
    if not data or len(data) > 15 * 1024 * 1024:
        return None
    return data


def resolve_photo_bytes(
    decision: PhotoDecision,
    *,
    root: Path,
    fetch: Callable[[str], bytes | None] | None = None,
) -> tuple[bytes | None, str]:
    """Local dossier file first; else HTTP URL already listed in the dossier."""
    fetcher = fetch or fetch_remote_photo_bytes
    local = resolve_local_photo_path(decision.url_or_file, root=root)
    if local is not None:
        return local.read_bytes(), _content_type_for(local.name)
    if decision.url_or_file.startswith(("http://", "https://")) and _looks_like_image_ref(
        decision.url_or_file
    ):
        body = fetcher(decision.url_or_file)
        if body:
            return body, _content_type_for(decision.url_or_file)
    source = photo_source_url(decision)
    if source and _looks_like_image_ref(source):
        body = fetcher(source)
        if body:
            return body, _content_type_for(source)
    return None, _content_type_for(decision.url_or_file)


def profile_patch(card: ArenaCard) -> dict[str, Any]:
    return {
        "district": card.district,
        "phone": card.phone,
        "website_url": card.website_url,
        "opening_hours": card.opening_hours,
        "season_start_month": card.season_start_month,
        "season_end_month": card.season_end_month,
        "amenities": card.amenities,
        "short_description": card.short_description,
        "social_urls": card.social_urls,
        "status": card.status,
    }


async def apply_card(
    session: Any,
    card: ArenaCard,
    *,
    fixtures_dir: Path,
    seed_sessions: bool = True,
    arena_id: int | None = None,
    repo_root: Path | None = None,
    fetch_photo: Callable[[str], bytes | None] | None = None,
) -> ArenaLoadResult:
    from sqlalchemy import text

    from src.application.arena_media import (
        ArenaMediaLimitError,
        InvalidMediaLicenseError,
        upload_arena_media_from_bytes,
    )
    from src.application.arena_profile import apply_admin_arena_profile_patch
    from src.application.ice_session_use_cases import (
        IceSessionDurationError,
        IceSessionOverlapError,
        IceSessionValidationError,
        compute_price_minor,
        compute_session_datetimes,
        parse_hhmm,
        validate_duration_minutes,
        validate_kind,
        validate_no_overlap,
        validate_prices,
    )

    target_id = int(arena_id if arena_id is not None else card.arena_id)
    started = time.perf_counter()
    photo_summary = "; ".join(
        f"{p.action}:{p.reason}" for p in card.photo_decisions[:3]
    ) or "no photo rows"
    plan = plan_sessions(card, fixtures_dir) if seed_sessions else SessionPlan(
        None, False, "sessions disabled"
    )
    try:
        await apply_admin_arena_profile_patch(session, target_id, profile_patch(card))
        if card.verified_at is not None:
            verified_ts = datetime(
                card.verified_at.year,
                card.verified_at.month,
                card.verified_at.day,
                tzinfo=timezone.utc,
            )
            await session.execute(
                text("UPDATE arena_profiles SET verified_at = :ts WHERE arena_id = :id"),
                {"ts": verified_ts, "id": target_id},
            )
    except LookupError:
        return ArenaLoadResult(
            card,
            profile="skipped (arena_id not in DB)",
            photo_summary=photo_summary,
            sessions_reason=plan.reason,
            error=f"arena_id {target_id} not in DB",
            apply_ms=(time.perf_counter() - started) * 1000,
        )

    photos_uploaded = 0
    root = repo_root or ROOT
    fetcher = fetch_photo or fetch_remote_photo_bytes
    for photo in card.photo_decisions:
        if photo.action != "upload":
            continue
        body, content_type = resolve_photo_bytes(photo, root=root, fetch=fetcher)
        if not body:
            continue
        try:
            await upload_arena_media_from_bytes(
                session,
                target_id,
                body,
                content_type,
                license_key=photo.license,
                source_url=photo_source_url(photo),
                attribution=photo.attribution,
            )
        except (ArenaMediaLimitError, InvalidMediaLicenseError, LookupError, ValueError):
            continue
        photos_uploaded += 1
    if photos_uploaded:
        photo_summary = f"uploaded {photos_uploaded}; {photo_summary}"

    seeded = 0
    skipped = 0
    sessions_reason = plan.reason
    if plan.seed and plan.rows:
        existing_rows = (
            await session.execute(
                text(
                    """
                    SELECT id, status, starts_at_utc, ends_at_utc
                    FROM ice_sessions WHERE arena_id = :aid
                    """
                ),
                {"aid": target_id},
            )
        ).fetchall()
        existing = [
            {
                "id": int(row[0]),
                "status": row[1],
                "starts_at_utc": row[2],
                "ends_at_utc": row[3],
            }
            for row in existing_rows
        ]
        captured = datetime.now(timezone.utc)
        for row in plan.rows:
            try:
                kind = validate_kind(str(row["kind"]))
                start_local = parse_hhmm(row["starts_at_local"])
                end_local = parse_hhmm(row["ends_at_local"])
                minutes = validate_duration_minutes(_duration_minutes(start_local, end_local))
                adult = row.get("price_adult_minor")
                child = row.get("price_child_minor")
                rental = row.get("price_rental_minor")
                validate_prices(
                    price_adult_minor=adult,
                    price_child_minor=child,
                    price_rental_minor=rental,
                )
                local_day = date.fromisoformat(str(row["local_date"]))
                parts = compute_session_datetimes(
                    local_date=local_day,
                    starts_at_local=start_local,
                    duration_minutes=minutes,
                    tz_name=DEFAULT_TZ,
                )
                already = (
                    await session.execute(
                        text(
                            """
                            SELECT 1 FROM ice_sessions
                            WHERE arena_id = :aid
                              AND source_id = :src
                              AND starts_at_utc = :start
                            """
                        ),
                        {
                            "aid": target_id,
                            "src": SOURCE_ETALON,
                            "start": parts.starts_at_utc,
                        },
                    )
                ).fetchone()
                if already:
                    skipped += 1
                    continue
                validate_no_overlap(
                    existing,
                    starts_at_utc=parts.starts_at_utc,
                    ends_at_utc=parts.ends_at_utc,
                )
            except (IceSessionDurationError, IceSessionOverlapError, IceSessionValidationError, KeyError, ValueError):
                skipped += 1
                continue
            price_minor = compute_price_minor(adult, child, rental)
            label = row.get("session_label")
            age_note = row.get("age_note")
            currency = (row.get("currency_code") or "BYN")[:3]
            await session.execute(
                text(
                    """
                    INSERT INTO ice_sessions (
                        arena_id, kind, starts_at_utc, ends_at_utc, local_date,
                        starts_at_local, ends_at_local,
                        price_adult_minor, price_child_minor, price_rental_minor, price_minor,
                        currency_code, session_label, age_note, status, source_id,
                        observed_at, valid_until, confidence
                    ) VALUES (
                        :arena_id, :kind, :starts_at_utc, :ends_at_utc, :local_date,
                        :starts_at_local, :ends_at_local,
                        :price_adult_minor, :price_child_minor, :price_rental_minor, :price_minor,
                        :currency_code, :session_label, :age_note, 'active', :source_id,
                        :observed_at, :valid_until, :confidence
                    )
                    """
                ),
                {
                    "arena_id": target_id,
                    "kind": kind,
                    "starts_at_utc": parts.starts_at_utc,
                    "ends_at_utc": parts.ends_at_utc,
                    "local_date": parts.local_date,
                    "starts_at_local": parts.starts_at_local,
                    "ends_at_local": parts.ends_at_local,
                    "price_adult_minor": adult,
                    "price_child_minor": child,
                    "price_rental_minor": rental,
                    "price_minor": price_minor,
                    "currency_code": currency,
                    "session_label": (str(label)[:128] if label else None),
                    "age_note": (str(age_note)[:128] if age_note else None),
                    "source_id": SOURCE_ETALON,
                    "observed_at": captured,
                    "valid_until": plan.valid_until,
                    "confidence": 1.0,
                },
            )
            existing.append(
                {
                    "id": 0,
                    "status": "active",
                    "starts_at_utc": parts.starts_at_utc,
                    "ends_at_utc": parts.ends_at_utc,
                }
            )
            seeded += 1
        sessions_reason = (
            f"seeded {seeded} (clipped {plan.clipped}, skipped {skipped}, "
            f"horizon {plan.horizon_start}…{plan.horizon_end}, source_id={SOURCE_ETALON})"
        )
    return ArenaLoadResult(
        card,
        profile=f"{'published' if card.enough_facts else 'draft'} upsert arena_id={target_id}",
        sessions_seeded=seeded,
        sessions_skipped=skipped,
        sessions_reason=sessions_reason,
        photo_summary=photo_summary,
        photos_uploaded=photos_uploaded,
        apply_ms=(time.perf_counter() - started) * 1000,
    )


def render_report(results: list[ArenaLoadResult], *, applied: bool, total_ms: float) -> str:
    lines = [
        "# TASK-063 load report — Minsk MK cards",
        "",
        f"- mode: {'apply' if applied else 'dry-run'}",
        f"- generated_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"- wall_ms: {total_ms:.1f}",
        f"- source_id for manual slots: `{SOURCE_ETALON}`",
        "- media: official operator frames would-upload / upload on --apply "
        "(verbal OK 2026-09-06; Google/stock never; grant notes do not block)",
        "",
        "| arena_id | slug | profile | photos | sessions | parse_ms | notes |",
        "|---|---|---|---|---|---|---|",
    ]
    parse_times: list[float] = []
    for item in results:
        card = item.card
        parse_times.append(card.parse_ms)
        photo_actions = {}
        for photo in card.photo_decisions:
            photo_actions[photo.action] = photo_actions.get(photo.action, 0) + 1
        photo_cell = ", ".join(f"{k}={v}" for k, v in sorted(photo_actions.items())) or "none"
        if applied:
            session_cell = f"{item.sessions_seeded} seeded; {item.sessions_reason}"
        else:
            session_cell = item.sessions_reason
        notes = "; ".join(card.blockers) or item.error or ""
        lines.append(
            f"| {card.arena_id} | {card.slug} | {item.profile} | {photo_cell} | "
            f"{session_cell} | {card.parse_ms:.1f} | {notes} |"
        )
    avg_parse = (sum(parse_times) / len(parse_times)) if parse_times else 0.0
    lines += [
        "",
        "## Photo decisions",
        "",
    ]
    for item in results:
        lines.append(f"### {item.card.slug} (arena_id={item.card.arena_id})")
        if not item.card.photo_decisions:
            lines.append("- no photo rows")
            lines.append("")
            continue
        for photo in item.card.photo_decisions:
            lines.append(f"- `{photo.url_or_file}` → **{photo.action}** ({photo.reason})")
        lines.append("")
    lines += [
        "## AC-003 timing",
        "",
        f"- parser wall-clock mean: **{avg_parse:.1f} ms** per dossier "
        f"({len(parse_times)} arenas; script, not research).",
        "- Estimated operator time from a *ready* TASK-073 dossier (read card, dry-run, confirm): "
        "**2–4 minutes per arena**. First-pass research is TASK-073, not this loader.",
        f"- Full batch dry-run wall: **{total_ms / 1000:.2f} s** for {len(results)} arenas.",
        "",
        "## Blockers",
        "",
        "- junost.by / ledlife.by: origin **403** without BY-egress — hours/phone/amenities stay unknown where the dossier said so; sessions not invented.",
        "- Fixture `expected.json` files live on the SPEC lane; if absent here, session seed is skipped until those files are on the train.",
        "",
    ]
    return "\n".join(lines) + "\n"


def _session_reason_for_report(card: ArenaCard, fixtures_dir: Path) -> str:
    plan = plan_sessions(card, fixtures_dir)
    if not plan.seed:
        return plan.reason
    return f"would seed {len(plan.rows)} slots ({plan.horizon_start}…{plan.horizon_end})"


async def run_load(
    *,
    cards_dir: Path,
    fixtures_dir: Path,
    apply: bool,
    seed_sessions: bool,
    report_path: Path | None,
    allow_local_dev: bool = False,
    only_arena_ids: frozenset[int] | None = None,
) -> list[ArenaLoadResult]:
    started = time.perf_counter()
    dossiers = discover_dossiers(cards_dir)
    if not dossiers:
        raise SystemExit(f"no minsk-*.md dossiers in {cards_dir}")
    cards = [parse_dossier(path) for path in dossiers]
    missing_ids = [c.arena_id for c in cards if c.arena_id not in TARGET_ARENA_IDS]
    if missing_ids:
        raise SystemExit(f"unexpected arena_id values (refusing to invent/remap): {missing_ids}")
    if only_arena_ids is not None:
        unknown = sorted(only_arena_ids - set(TARGET_ARENA_IDS))
        if unknown:
            raise SystemExit(f"unknown --only-arena-ids (not in TARGET_ARENA_IDS): {unknown}")
        cards = [c for c in cards if c.arena_id in only_arena_ids]
        if not cards:
            raise SystemExit("no dossiers left after --only-arena-ids filter")

    results: list[ArenaLoadResult] = []
    if apply:
        db_url = resolve_database_url()
        assert_local_database_url(db_url, apply=True, allow_local_dev=allow_local_dev)
        from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

        engine = create_async_engine(async_database_url(db_url), pool_pre_ping=True)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session:
                for card in cards:
                    results.append(
                        await apply_card(
                            session,
                            card,
                            fixtures_dir=fixtures_dir,
                            seed_sessions=seed_sessions,
                        )
                    )
                await session.commit()
        finally:
            await engine.dispose()
    else:
        for card in cards:
            plan_reason = (
                _session_reason_for_report(card, fixtures_dir) if seed_sessions else "sessions disabled"
            )
            results.append(
                ArenaLoadResult(
                    card,
                    profile=f"dry-run {card.status} arena_id={card.arena_id}",
                    sessions_reason=plan_reason,
                    photo_summary="; ".join(p.reason for p in card.photo_decisions[:2]) or "none",
                )
            )
    total_ms = (time.perf_counter() - started) * 1000
    text_report = render_report(results, applied=apply, total_ms=total_ms)
    print(text_report)
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(text_report, encoding="utf-8")
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Load Minsk MK dossiers into arena_profiles (TASK-063).")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write to local trainer_crm_test / local trainer_crm. Default is dry-run.",
    )
    parser.add_argument(
        "--cards-dir",
        type=Path,
        default=ROOT / ".ai" / "data" / "arena-cards",
    )
    parser.add_argument(
        "--fixtures-dir",
        type=Path,
        default=ROOT / ".ai" / "data" / "fixtures",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / ".ai" / "data" / "arena-cards" / "TASK-063-load-report.md",
    )
    parser.add_argument(
        "--no-report",
        action="store_true",
        help="Do not write the markdown load report.",
    )
    parser.add_argument(
        "--no-seed-sessions",
        action="store_true",
        help="Do not plan/insert ice_sessions from expected.json.",
    )
    parser.add_argument(
        "--allow-local-dev-db",
        action="store_true",
        help="Allow --apply against local database name trainer_crm (still refuses cloud/prod hosts).",
    )
    parser.add_argument(
        "--only-arena-ids",
        default=None,
        help="Comma-separated arena_ids to load (skip others). Local DB may not match prod CSV ids.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply:
        db_url = resolve_database_url()
        assert_local_database_url(db_url, apply=True, allow_local_dev=args.allow_local_dev_db)
    report_path = None if args.no_report else args.report
    asyncio.run(
        run_load(
            cards_dir=args.cards_dir,
            fixtures_dir=args.fixtures_dir,
            apply=args.apply,
            seed_sessions=not args.no_seed_sessions,
            report_path=report_path,
            allow_local_dev=args.allow_local_dev_db,
            only_arena_ids=parse_only_arena_ids(args.only_arena_ids),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
