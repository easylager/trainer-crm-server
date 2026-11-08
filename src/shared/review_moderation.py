"""Модерация текстов отзывов о тренере: коды кнопок админ-бота и границы показа на сайте."""
from __future__ import annotations

#: ``rvm:ok:<rating_id>`` — подтвердить, ``rvm:no:<rating_id>`` — отклонить.
REVIEW_MOD_PREFIX = "rvm:"
REVIEW_APPROVE = "ok"
REVIEW_REJECT = "no"

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

#: Секция «Отзывы» на сайте появляется, когда подтверждённых отзывов с текстом хотя бы столько.
REVIEWS_MIN_SHOWN = 3
