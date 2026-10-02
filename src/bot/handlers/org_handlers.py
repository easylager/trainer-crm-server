"""
Org bot handlers (TASK-141/EPIC5 TASK-105/106) — school director/operator entry point.

Separate bot/process from trainer_handlers.py: an operator is not a coach (PDEC-007/008).
`/start col_claim_<token>` activates a draft collective's operator, then opens the org Mini App.

Fresh claim opens straight into org-profile (the checklist screen, S3) — the button already
said "Заполнить профиль"; it used to land on org-home regardless, costing the director an
extra tap on the one screen this flow exists to get them to. The persistent chat menu button
(``org_app.py::setup_org_menu``) still opens org-home — that one isn't tied to a fresh claim.
"""
import html

from aiogram import Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart
from aiogram.types import Message

from src.application.trainer_start_payload import START_COLLECTIVE_CLAIM_PREFIX
from src.bot import messages as msg
from src.infrastructure.db import async_session_factory
from src.shared.config import Settings
from src.shared.mini_app_https import mini_app_https_base

router = Router(name="org")


def org_cabinet_webapp_url(*, path: str = "org-home") -> str | None:
    """HTTPS (prod) or configured base (tests/dev) + the given webapp screen."""
    settings = Settings()
    org = (settings.org_webapp_base_url or "").strip().rstrip("/")
    if org:
        base = org
    else:
        https, _reason = mini_app_https_base(settings)
        base = https or (settings.webapp_base_url or "").strip().rstrip("/")
    if not base:
        return None
    return f"{base}/webapp/{path}"


def _org_webapp_markup(*, fill_profile: bool):
    url = org_cabinet_webapp_url(path="org-profile" if fill_profile else "org-home")
    if not url:
        return None
    return msg.build_org_webapp_reply_markup(url=url, fill_profile=fill_profile)


async def _cmd_org_collective_claim(message: Message, session, token: str) -> None:
    """Activate studio draft as operator when director opens col_claim_* deep link."""
    from src.application.collective_use_cases import consume_collective_claim_token_for_operator

    user_id = message.from_user.id if message.from_user else 0
    if not user_id:
        await message.answer(msg.ORG_CLAIM_INVALID, parse_mode=ParseMode.HTML)
        return

    outcome = await consume_collective_claim_token_for_operator(session, token, user_id)
    if outcome.error == "invalid_token":
        await message.answer(msg.ORG_CLAIM_INVALID, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "collective_not_draft":
        await message.answer(msg.ORG_CLAIM_NOT_DRAFT, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "already_in_collective":
        await message.answer(msg.ORG_CLAIM_ALREADY_OPERATOR, parse_mode=ParseMode.HTML)
        return
    if outcome.error == "already_claimed":
        await message.answer(msg.ORG_CLAIM_ALREADY, parse_mode=ParseMode.HTML)
        return
    if outcome.error or outcome.collective_id is None:
        await message.answer(msg.ORG_CLAIM_INVALID, parse_mode=ParseMode.HTML)
        return

    name = html.escape((outcome.display_name or outcome.slug or "Школа").strip())
    await message.answer(
        msg.ORG_CLAIM_SUCCESS.format(name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=_org_webapp_markup(fill_profile=True),
    )


async def _cmd_org_operator_home(message: Message, session, telegram_id: int) -> None:
    from src.application.collective_use_cases import resolve_operator_membership

    membership = await resolve_operator_membership(session, telegram_id)
    if membership is None:
        await message.answer(msg.ORG_START_GENERIC, parse_mode=ParseMode.HTML)
        return

    name = html.escape((membership.display_name or membership.slug or "Школа").strip())
    await message.answer(
        msg.ORG_START_OPERATOR.format(name=name),
        parse_mode=ParseMode.HTML,
        reply_markup=_org_webapp_markup(fill_profile=False),
    )


@router.message(CommandStart())
async def cmd_org_start(message: Message) -> None:
    text = message.text or ""
    args = text.split(maxsplit=1)
    payload = args[1].strip() if len(args) > 1 else ""
    user_id = message.from_user.id if message.from_user else 0

    async with async_session_factory() as session:
        if payload.startswith(START_COLLECTIVE_CLAIM_PREFIX):
            token = payload.removeprefix(START_COLLECTIVE_CLAIM_PREFIX).strip()
            await _cmd_org_collective_claim(message, session, token)
            return
        if user_id:
            await _cmd_org_operator_home(message, session, user_id)
            return

    await message.answer(msg.ORG_START_GENERIC, parse_mode=ParseMode.HTML)
