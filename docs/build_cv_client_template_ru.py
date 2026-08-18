#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Клиентский шаблон резюме (заказчик) — вайтлейбл на основе Senior CV.

Порядок полей как в «Шаблон резюме.pdf»: менять нельзя.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from fpdf import FPDF

ROOT = Path(__file__).resolve().parent
OUT_DOCX = ROOT / "cv-vasilenko-m-python-senior-client-template-ru-2026.docx"
OUT_PDF = ROOT / "cv-vasilenko-m-python-senior-client-template-ru-2026.pdf"
DESKTOP_DIR = Path.home() / "Desktop" / "CV" / "Вайтлейбл"
DESKTOP_DOCX = DESKTOP_DIR / "Василенко М. Python Senior — шаблон заказчика.docx"
DESKTOP_PDF = DESKTOP_DIR / "Василенко М. Python Senior.pdf"

FONT_REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

DOCX_RED = RGBColor(0xC0, 0x00, 0x00)
DOCX_DARK = RGBColor(0x22, 0x22, 0x22)
DOCX_GRAY = RGBColor(0x55, 0x55, 0x55)

# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

NAME = "Василенко Максим Петрович"
POSITION = "Python разработчик"
LEVEL = "Senior"
# В русскоязычных IT-анкетах чаще всего пишут просто ASAP (или «сразу»).
AVAILABLE_FROM = "ASAP"
LOCATION = "г. Минск, Беларусь"

COVER = (
    "Занимаюсь коммерческой разработкой на Python более 6 лет: асинхронный код (asyncio / FastAPI), "
    "строгая типизация, автотесты (pytest) и поставка backend-сервисов в production. "
    "Уверенный бэкенд-фундамент: REST и gRPC, очереди и стримы (Kafka, Redis, RabbitMQ, Pub/Sub), "
    "PostgreSQL, Docker, базовая эксплуатация Kubernetes (EKS / AKS / Cloud Run + k8s). "
    "Есть практический опыт разработки ИИ-агентов и LLM-based решений в production: "
    "многошаговые агентские сценарии с вызовом инструментов, RAG (embeddings / retrieval / pgvector), "
    "пайплайны STT→LLM, guardrails и human-in-the-loop. "
    "ИИ-инструменты использую в ежедневной работе — от проектирования и код-ревью до ускорения "
    "разработки, анализа инцидентов и проверки гипотез по latency/стоимости LLM-вызовов."
)

CHECKLIST = [
    "От 3 лет опыта в разработке на Python: асинхронный код, типизация, тесты",
    "Уверенный бэкенд-фундамент: REST/gRPC, очереди (Kafka / Redis / RabbitMQ), Postgres, Docker, "
    "базовая работа с k8s или аналогами",
    "Практический опыт разработки ИИ-агентов и LLM-based решений",
    "Используешь ИИ-инструменты в ежедневной работе",
]

SKILLS = [
    ("Платформы", "Linux, macOS, MS Windows"),
    ("Языки программирования", "Python (основной); практический опыт Golang на критичных участках"),
    (
        "Инструменты",
        "Python, asyncio, typing, FastAPI, Django, Django REST Framework, Flask, Pydantic, "
        "SQLAlchemy, Alembic, Celery, httpx, aiohttp, REST, gRPC, OpenAPI/Swagger, "
        "Kafka, Redis Streams / Pub-Sub, RabbitMQ, GCP Pub/Sub, Azure Service Bus, "
        "Docker, docker-compose, Kubernetes, Helm, ArgoCD, GitHub Actions, GitLab CI/CD, "
        "OpenAI API, Anthropic Claude, AI-агенты, RAG, embeddings, pgvector, "
        "STT→LLM пайплайны, guardrails, human-in-the-loop, "
        "Pytest, Prometheus, Grafana, Sentry, Git, Design patterns",
    ),
    ("Базы данных", "PostgreSQL, Redis, MySQL, Cloud SQL, GCP Datastore; векторный поиск (pgvector)"),
]

# В БГУИР квалификация «инженер-программист» — у специальности
# «Программное обеспечение информационных технологий» (фак. КСиС).
# «Вычислительные машины, системы и сети» / «Компьютерные системы и сети»
# дают инженера-системотехника — это другая специальность.
EDU_PROGRAM = "Программное обеспечение информационных технологий, инженер-программист"
EDU_ORG = (
    "Белорусский государственный университет информатики и радиоэлектроники (БГУИР), "
    "факультет компьютерных систем и сетей"
)

# Согласовано с датами последнего проекта и готовностью выйти с 11.08.2026.
EXP_DATES = "Январь 2020 – Июль 2026"
EXP_TEXT = (
    "Senior Python разработчик. Backend и интеграции для высоконагруженных и регулируемых SaaS: "
    "микросервисы, event-driven, REST/gRPC, очереди, PostgreSQL, Docker/Kubernetes. "
    "Последние проекты — AI-агенты и LLM-based продукты в production (realtime-ассистент, RAG, "
    "antifraud-подсказки). Сильная сторона — надёжная доставка и наблюдаемость: идемпотентность, "
    "ретраи, back-pressure, аудит, тесты, разбор инцидентов."
)

PROJECTS = [
    {
        "title": "Realtime AI-ассистент для страховых кол-центров (B2B SaaS)",
        "dates": "Январь 2025 – Июль 2026",
        "tech": (
            "Python, Django, DRF, FastAPI, asyncio, PostgreSQL, pgvector, Redis, "
            "OpenAI API, Anthropic Claude, RAG, embeddings, GCP (Cloud Run, Pub/Sub, Cloud SQL, GCS), "
            "Kubernetes, Docker, GitLab CI/CD, Prometheus, Grafana, Pytest, Sentry"
        ),
        "desc": (
            "Мультитенантный B2B SaaS: во время звонка система ведёт оператора по сценарию — "
            "транскрибация, извлечение намерений, подсказки, вызов инструментов и ответы с опорой "
            "на базу знаний. Критичны низкая задержка, изоляция клиентов и human-in-the-loop "
            "на рискованных решениях."
        ),
        "done": [
            "Отвечал за backend realtime-контура: приём аудио/событий звонка, статусы сессии, выдача подсказок оператору.",
            "Спроектировал мультитенантную архитектуру с изоляцией данных и прав доступа между клиентами платформы.",
            "Разрабатывал AI-агентские сценарии: многошаговые workflow, tool calling, память сессии, human-in-the-loop на рискованных шагах.",
            "Построил production RAG: ingest/chunking, embeddings, retrieval (pgvector), grounded-ответы LLM с опорой на источник.",
            "Внедрил пайплайны STT→LLM (OpenAI, Claude): промпты, guardrails, деградация без обрыва сценария звонка.",
            "Разделил sync API и тяжёлые AI-стадии через GCP Pub/Sub: ретраи, back-pressure, correlation ID и auditable-статусы.",
            "Сравнивал варианты retrieval и LLM-вызовов по качеству, стоимости и latency; оставлял наблюдаемый контур.",
            "Оптимизировал задержку подсказок: кеш в Redis, контроль стоимости LLM-вызовов, устойчивость при сбоях внешних API.",
            "Проектировал схему PostgreSQL под сессии звонков, подсказки, retrieval-контекст и аудит действий оператора.",
            "Настроил CI/CD в GitLab CI/CD, Docker/Kubernetes, Prometheus/Grafana/Sentry; покрыл ключевые сценарии pytest.",
        ],
    },
    {
        "title": "Международный SaaS: страховые заявки и antifraud",
        "dates": "Апрель 2024 – Декабрь 2024",
        "tech": (
            "Python, FastAPI, Django, DRF, PostgreSQL, Redis, Kafka, Airflow, "
            "Azure (Service Bus, Blob Storage, AKS), Pydantic, Alembic, Docker, Kubernetes, Pytest, OpenAPI"
        ),
        "desc": (
            "B2B-платформа обработки страховых заявок и выявления мошенничества. "
            "Приём документов, извлечение данных, проверка кейса оператором, сигналы о подозрительных "
            "паттернах. Важны human review, партнёрские интеграции и надёжная доставка статусов."
        ),
        "done": [
            "Разработал backend обработки страховых заявок: загрузка документов, извлечение полей, статусы для проверки оператором.",
            "Реализовал antifraud-сигналы и AI-подсказки: скоринг/эвристики, оценка уверенности, переопределение человеком.",
            "Построил event-driven потоки на Kafka для статусов заявок и webhook-уведомлений партнёрам.",
            "Интегрировал внешних партнёров: версионируемые контракты, идемпотентная доставка статусов.",
            "Оркестрировал пакетную обработку и ETL через Airflow; хранение вложений в Azure Blob Storage; контур AKS.",
            "Вынес тяжёлую обработку документов и antifraud-стадии в отдельные воркеры — меньше влияние сбоев на API.",
            "Участвовал в миграции Django → FastAPI на живом продукте без простоя; REST API с OpenAPI-спецификацией.",
            "Развивал схему PostgreSQL, оптимизировал SQL, кешировал горячие read-модели в Redis; покрыл сценарии pytest.",
        ],
    },
    {
        "title": "Высоконагруженная страховая платформа (США)",
        "dates": "Январь 2022 – Март 2024",
        "tech": (
            "Python, Golang, Flask, Kafka, gRPC, PostgreSQL, MySQL, SQLAlchemy, "
            "AWS (EKS, EC2, S3, RDS, IAM, CloudWatch, Lambda), Kubernetes, ArgoCD, Docker, "
            "Redis, Prometheus, Grafana, Pytest, Artifactory"
        ),
        "desc": (
            "Микросервисная платформа в регулируемой среде: проверка доступности услуг и синхронизация "
            "клиентских данных для миллионов пользователей. Критичны надёжность на сезонных пиках, "
            "аудит изменений и поставка в AWS/Kubernetes."
        ),
        "done": [
            "Разрабатывал и поддерживал мультисервисный пайплайн проверки статусов на Kafka — синхронизация между сервисами.",
            "Сопровождал плотный gRPC-трафик между соседними микросервисами; обеспечивал устойчивость на сезонных пиках.",
            "Работал на стыке Python и Golang на критичных участках; участвовал в переносе отдельных стадий пайплайна на Python.",
            "Эксплуатировал микросервисы в AWS EKS/Kubernetes; деплой через ArgoCD; CI/CD и артефакты поставки (Artifactory).",
            "Соблюдал практики безопасной работы с чувствительными данными: минимальные права, аудит, наблюдаемость.",
            "Оптимизировал горячие пути и согласование статусов; применял параллельную обработку под пиковую нагрузку.",
            "Поддерживал backend API и контракты данных для внутренних React-инструментов операционных команд.",
            "Автоматизировал data-fix скриптами для исторических несоответствий в БД; участвовал в разборе production-инцидентов.",
            "Писал автотесты и собирал доказательства для приёмки фич; проводил code review в распределённой команде.",
        ],
    },
    {
        "title": "Платформа интеграций доставки для ресторанов",
        "dates": "Март 2021 – Декабрь 2021",
        "tech": (
            "Python, FastAPI, asyncio, GCP (Cloud Run, Pub/Sub, Datastore, Cloud Scheduler), "
            "Redis, Docker, OpenAPI/Swagger, Sentry, Pytest"
        ),
        "desc": (
            "Единый внутренний API и кабинет поверх нескольких внешних площадок доставки. "
            "Микросервисы, событийная модель и saga-оркестрация для согласованности заказов "
            "и статусов при сбоях на стороне партнёров."
        ),
        "done": [
            "Отвечал за интеграции с крупными площадками доставки (Uber Eats, Grubhub, DoorDash, GloriaFood).",
            "Свёл разные внешние API к единому внутреннему контракту: ретраи, rate limit, устойчивость к смене поведения партнёров.",
            "Проектировал и развивал микросервисную архитектуру на GCP: Cloud Run, Pub/Sub, Datastore, Cloud Scheduler.",
            "Реализовал событийные потоки и saga-оркестрацию для согласованности заказов и статусов.",
            "Перевёл сервисы с Falcon/Starlette на FastAPI; REST-слой с OpenAPI для продукта и адаптеров провайдеров.",
            "Обеспечил ежедневные высоконагруженные синхронизации и сверку статусов под лимитами внешних API.",
            "Настроил кеширование в Redis, Docker, Sentry; документировал интеграционные контракты; проводил code review.",
        ],
    },
    {
        "title": "Образовательная платформа · платежи и учёт",
        "dates": "Январь 2020 – Февраль 2021",
        "tech": (
            "Python, Django, Django REST Framework, Celery, PostgreSQL, Redis, "
            "Docker, Docker Compose, Swagger, GitLab CI/CD, Sentry, Pytest"
        ),
        "desc": (
            "Агрегатор образовательных услуг с контуром продаж, платежей и учёта: витрина, биллинг, "
            "интеграция с бухгалтерией, согласованность проводок и миграция с legacy без потери целостности."
        ),
        "done": [
            "Разрабатывал backend на Django/DRF: каталог услуг, карточки клиентов, сценарии покупки.",
            "Спроектировал модель данных PostgreSQL под услуги, заказы, платежи и учётные статусы.",
            "Реализовал платёжный и биллинговый контур: статусы оплаты, защита от дублей и гонок на денежных путях.",
            "Интегрировал бухгалтерскую систему; обеспечил согласованность проводок и auditable-переходы финансовых сущностей.",
            "Написал и провёл миграционные скрипты переноса данных с контролем целостности и синхронизации.",
            "Реализовал фоновые задачи на Celery + Redis; идемпотентные webhook/callback платёжных провайдеров.",
            "Внедрил кеш каталога в Redis, оптимизировал SQL; настроил CI/CD, Docker Compose, Swagger, pytest, Sentry.",
        ],
    },
]


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def set_run(run, *, size=11, bold=False, color=DOCX_DARK, font="Arial"):
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = color


def add_para(doc, text="", *, size=11, bold=False, color=DOCX_DARK, space_after=6, space_before=0, align=None):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    if text:
        set_run(p.add_run(text), size=size, bold=bold, color=color)
    return p


def add_rich(doc, parts, *, space_after=6, space_before=0):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    pf.line_spacing_rule = WD_LINE_SPACING.SINGLE
    for text, kwargs in parts:
        set_run(p.add_run(text), **kwargs)
    return p


def add_bullet(doc, text, *, size=10.5):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.space_after = Pt(2)
    pf.space_before = Pt(0)
    if p.runs:
        p.runs[0].text = text
        set_run(p.runs[0], size=size)
        for r in p.runs[1:]:
            r.text = ""
    else:
        set_run(p.add_run(text), size=size)
    return p


def set_cell_shading(cell, hex_color: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), hex_color)
    shd.set(qn("w:val"), "clear")
    tcPr.append(shd)


def fill_cell(cell, text, *, bold=False, size=10.5, color=DOCX_DARK):
    lines = text.split("\n") if text else [""]
    cell.text = ""
    p0 = cell.paragraphs[0]
    p0.paragraph_format.space_after = Pt(1)
    p0.paragraph_format.space_before = Pt(2)
    set_run(p0.add_run(lines[0]), size=size, bold=bold, color=color)
    for line in lines[1:]:
        p = cell.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        p.paragraph_format.space_before = Pt(0)
        set_run(p.add_run(line), size=size, bold=bold, color=color)


def build_docx() -> Path:
    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.6)
    section.bottom_margin = Cm(1.6)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    add_para(doc, "Резюме кандидата", size=16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=14)
    add_para(doc, NAME, size=18, bold=True, color=DOCX_RED, space_after=8)
    add_rich(doc, [("Позиция: ", {"bold": True, "size": 11}), (POSITION, {"size": 11})], space_after=2)
    add_rich(doc, [("Уровень: ", {"bold": True, "size": 11}), (LEVEL, {"size": 11})], space_after=2)
    add_rich(
        doc,
        [("Готов выйти на проект: ", {"bold": True, "size": 11}), (AVAILABLE_FROM, {"size": 11})],
        space_after=2,
    )
    add_rich(doc, [("Локация: ", {"bold": True, "size": 11}), (LOCATION, {"size": 11})], space_after=10)

    add_para(doc, "Сопроводительное письмо (О себе, знания и навыки)", size=13, bold=True, color=DOCX_RED, space_after=6)
    add_para(doc, COVER, size=10.5, space_after=12)

    add_para(doc, "Чек-лист", size=13, bold=True, color=DOCX_RED, space_after=6)
    for req in CHECKLIST:
        add_para(doc, f"+ {req}", size=10.5, space_after=4)

    add_para(doc, "Ключевые навыки (Основной стек)", size=13, bold=True, color=DOCX_RED, space_before=6, space_after=8)
    table = doc.add_table(rows=len(SKILLS), cols=2)
    table.style = "Table Grid"
    table.autofit = False
    left_w, right_w = Cm(5.4), Cm(11.3)
    for i, (left, right) in enumerate(SKILLS):
        # Длинные подписи («Языки программирования») переносим явно —
        # иначе в узкой колонке текст уезжает поверх правой ячейки.
        left_text = left.replace(" ", "\n", 1) if left == "Языки программирования" else left
        fill_cell(table.rows[i].cells[0], left_text, bold=True, size=10)
        fill_cell(table.rows[i].cells[1], right, size=10)
        set_cell_shading(table.rows[i].cells[0], "F7F7F7")
        table.rows[i].cells[0].width = left_w
        table.rows[i].cells[1].width = right_w

    add_para(doc, "", space_after=4)
    add_para(doc, "Образование", size=13, bold=True, color=DOCX_RED, space_after=4)
    add_para(doc, EDU_PROGRAM, size=10.5, bold=True, space_after=2)
    add_para(doc, EDU_ORG, size=10.5, color=DOCX_GRAY, space_after=10)

    add_para(doc, "Опыт работы", size=13, bold=True, color=DOCX_RED, space_after=2)
    add_para(doc, "(Роль — Уровень — Компетенция)", size=9, color=DOCX_GRAY, space_after=4)
    add_para(doc, EXP_DATES, size=11, bold=True, space_after=4)
    add_para(doc, EXP_TEXT, size=10.5, space_after=12)

    add_para(doc, "Недавние проекты", size=13, bold=True, color=DOCX_RED, space_after=10)
    for proj in PROJECTS:
        add_para(doc, proj["title"], size=12, bold=True, space_after=2)
        add_para(doc, proj["dates"], size=10, color=DOCX_GRAY, space_after=2)
        add_rich(
            doc,
            [
                ("Набор использованных технологий: ", {"bold": True, "size": 10}),
                (proj["tech"], {"size": 10}),
            ],
            space_after=6,
        )
        add_para(doc, "Описание проекта", size=11, bold=True, space_after=2)
        add_para(doc, proj["desc"], size=10.5, space_after=6)
        add_para(doc, "Что было сделано", size=11, bold=True, space_after=2)
        for item in proj["done"]:
            add_bullet(doc, item)
        add_para(doc, "", space_after=8)

    add_para(
        doc,
        "* Все поля обязательны для заполнения, изменение порядка полей не допускается.",
        size=8,
        color=DOCX_GRAY,
        space_before=6,
    )

    doc.save(str(OUT_DOCX))
    return OUT_DOCX


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


class ResumePDF(FPDF):
    def footer(self):
        self.set_y(-12)
        self.set_font("Arial", size=7)
        self.set_text_color(120, 120, 120)
        self.cell(
            0,
            5,
            "* Все поля обязательны для заполнения, изменение порядка полей не допускается.",
            align="L",
        )


def build_pdf() -> Path:
    pdf = ResumePDF(format="A4")
    # Авторазрыв оставляем, но для буллетов/блоков сами решаем,
    # чтобы не резать предложение посередине между страницами.
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_font("Arial", "", FONT_REG)
    pdf.add_font("Arial", "B", FONT_BOLD)
    pdf.add_page()
    pdf.set_margins(16, 14, 16)

    def remaining() -> float:
        return pdf.h - pdf.b_margin - pdf.get_y()

    def ensure(min_mm: float) -> None:
        if remaining() < min_mm:
            pdf.add_page()

    def h(text, size=13):
        ensure(12)
        pdf.set_font("Arial", "B", size)
        pdf.set_text_color(192, 0, 0)
        # L, не J: иначе fpdf растягивает пробелы на полных строках.
        pdf.multi_cell(0, size * 0.55, text, align="L")
        pdf.ln(2)

    def body(text, size=10.5, bold=False, color=(34, 34, 34), after=3, keep=None):
        pdf.set_font("Arial", "B" if bold else "", size)
        pdf.set_text_color(*color)
        line_h = size * 0.5
        height = pdf.multi_cell(0, line_h, text, align="L", dry_run=True, output="HEIGHT")
        need = height + after
        if keep is not None:
            need = max(need, keep)
        ensure(need + 1)
        pdf.set_font("Arial", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, line_h, text, align="L")
        pdf.ln(after)

    def label_value(label, value, size=11):
        pdf.set_font("Arial", "B", size)
        pdf.set_text_color(34, 34, 34)
        w = pdf.get_string_width(label) + 1
        pdf.cell(w, size * 0.5, label)
        pdf.set_font("Arial", "", size)
        pdf.multi_cell(0, size * 0.5, value, align="L")
        pdf.ln(1)

    pdf.set_font("Arial", "B", 16)
    pdf.set_text_color(34, 34, 34)
    pdf.cell(0, 8, "Резюме кандидата", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    pdf.set_font("Arial", "B", 18)
    pdf.set_text_color(192, 0, 0)
    pdf.multi_cell(0, 9, NAME, align="L")
    pdf.ln(2)

    label_value("Позиция: ", POSITION)
    label_value("Уровень: ", LEVEL)
    label_value("Готов выйти на проект: ", AVAILABLE_FROM)
    label_value("Локация: ", LOCATION)
    pdf.ln(3)

    h("Сопроводительное письмо (О себе, знания и навыки)")
    body(COVER, size=10, after=5)

    h("Чек-лист")
    for req in CHECKLIST:
        body(f"+ {req}", size=10, after=2)

    # Таблица навыков целиком на новой странице — иначе последняя строка
    # («Базы данных») остаётся сиротой после огромного блока «Инструменты».
    pdf.add_page()
    h("Ключевые навыки (Основной стек)")
    # Левая колонка с переносом; высоту меряем dry_run'ом (без двойной отрисовки).
    col_w = 48
    pad = 1.5
    line_h = 4.2
    for left, right in SKILLS:
        pdf.set_text_color(34, 34, 34)
        pdf.set_font("Arial", "B", 9)
        h_left = pdf.multi_cell(
            col_w - 2 * pad, line_h, left, border=0, align="L", dry_run=True, output="HEIGHT"
        )
        pdf.set_font("Arial", "", 9)
        h_right = pdf.multi_cell(
            pdf.epw - col_w - 2 * pad,
            line_h,
            right,
            border=0,
            align="L",
            dry_run=True,
            output="HEIGHT",
        )
        h_box = max(h_left, h_right) + 2
        ensure(h_box + 2)
        y0 = pdf.get_y()

        pdf.set_fill_color(247, 247, 247)
        pdf.set_draw_color(200, 200, 200)
        pdf.rect(pdf.l_margin, y0, col_w, h_box, style="DF")
        pdf.rect(pdf.l_margin + col_w, y0, pdf.epw - col_w, h_box, style="D")

        pdf.set_xy(pdf.l_margin + pad, y0 + 1)
        pdf.set_font("Arial", "B", 9)
        pdf.multi_cell(col_w - 2 * pad, line_h, left, border=0, align="L")

        pdf.set_xy(pdf.l_margin + col_w + pad, y0 + 1)
        pdf.set_font("Arial", "", 9)
        pdf.multi_cell(pdf.epw - col_w - 2 * pad, line_h, right, border=0, align="L")

        pdf.set_y(y0 + h_box)

    pdf.ln(4)
    h("Образование")
    body(EDU_PROGRAM, bold=True, after=1, keep=16)
    body(EDU_ORG, size=10, color=(85, 85, 85), after=4)

    h("Опыт работы")
    body("(Роль — Уровень — Компетенция)", size=9, color=(85, 85, 85), after=2, keep=28)
    body(EXP_DATES, bold=True, size=11, after=2)
    body(EXP_TEXT, size=10, after=5)

    h("Недавние проекты")
    for proj in PROJECTS:
        # Заголовок проекта + даты + стек + «Описание» не оставляем сиротами внизу страницы.
        ensure(55)
        body(proj["title"], bold=True, size=11.5, after=1)
        body(proj["dates"], size=9.5, color=(85, 85, 85), after=1)
        body("Набор использованных технологий: " + proj["tech"], size=9.5, after=2)
        body("Описание проекта", bold=True, size=10.5, after=1)
        body(proj["desc"], size=10, after=2)
        body("Что было сделано", bold=True, size=10.5, after=1)
        for item in proj["done"]:
            # Каждый буллет целиком — без разрыва «…correlation ID и» / «auditable-статусы».
            body("• " + item, size=9.5, after=0.8)
        pdf.ln(3)

    pdf.output(str(OUT_PDF))
    return OUT_PDF


def main() -> None:
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    docx = build_docx()
    pdf = build_pdf()
    shutil.copy2(docx, DESKTOP_DOCX)
    shutil.copy2(pdf, DESKTOP_PDF)
    print(docx)
    print(pdf)
    print(DESKTOP_DOCX)
    print(DESKTOP_PDF)


if __name__ == "__main__":
    main()
