#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One-off: polished 2-page RU CV PDF for Max Vasilenko (backend/Python)."""

from __future__ import annotations

from pathlib import Path

from fpdf import FPDF

# macOS Cyrillic-capable fonts (adjust on Linux: e.g. DejaVu paths)
FONT_REG = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

# Palette: deep ink + warm gold (print-friendly)
C_INK = (28, 32, 40)
C_MUTED = (95, 99, 110)
C_GOLD = (180, 138, 48)
C_LINE = (220, 222, 228)
C_BG_TINT = (252, 251, 248)


class CVPDF(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4", unit="mm")
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=18)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("CV", "", 8)
        self.set_text_color(*C_MUTED)
        self.cell(0, 6, f"Страница {self.page_no()}", align="C")


def section_title(pdf: CVPDF, title: str) -> None:
    pdf.ln(3)
    pdf.set_font("CV", "B", 10)
    pdf.set_text_color(*C_GOLD)
    pdf.cell(0, 6, title.upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*C_GOLD)
    pdf.set_line_width(0.35)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(*C_INK)


def bullet(pdf: CVPDF, text: str) -> None:
    pdf.set_font("CV", "", 9.5)
    pdf.set_text_color(*C_INK)
    x = pdf.get_x()
    y = pdf.get_y()
    pdf.set_x(x + 4)
    pdf.multi_cell(0, 4.6, f"▸  {text}")
    pdf.set_x(x)


def job_block(
    pdf: CVPDF,
    company: str,
    role: str,
    period: str,
    lines: list[str],
) -> None:
    pdf.set_font("CV", "B", 10)
    pdf.set_text_color(*C_INK)
    pdf.cell(0, 5, company, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("CV", "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.cell(0, 4, f"{role}  ·  {period}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*C_INK)
    for t in lines:
        bullet(pdf, t)
    pdf.ln(1)


def main() -> Path:
    for p in (FONT_REG, FONT_BOLD):
        if not Path(p).is_file():
            raise FileNotFoundError(f"Font not found: {p}")

    pdf = CVPDF()
    pdf.add_font("CV", "", FONT_REG)
    pdf.add_font("CV", "B", FONT_BOLD)
    pdf.add_page()

    # Top banner
    pdf.set_fill_color(*C_INK)
    pdf.rect(0, 0, 210, 32, "F")
    pdf.set_xy(16, 8)
    pdf.set_font("CV", "B", 20)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 9, "Максим Василенко", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(16)
    pdf.set_font("CV", "", 11)
    pdf.set_text_color(220, 215, 200)
    pdf.cell(0, 6, "Backend / Python Engineer  ·  B2B SaaS & high-load systems", new_x="LMARGIN", new_y="NEXT")
    pdf.set_xy(16, 24)
    pdf.set_font("CV", "", 8.5)
    pdf.set_text_color(200, 198, 190)
    contacts = (
        "pinkpanterpython3@gmail.com  ·  +375 29 667-53-89  ·  @maksimvasilenko11  ·  "
        "Минск, Беларусь (remote / гибрид)"
    )
    pdf.multi_cell(0, 4, contacts)
    pdf.set_y(38)

    pdf.set_text_color(*C_INK)
    pdf.set_fill_color(*C_BG_TINT)
    pdf.rect(pdf.l_margin, pdf.get_y(), pdf.w - pdf.l_margin - pdf.r_margin, 22, "F")

    pdf.set_xy(pdf.l_margin + 3, pdf.get_y() + 2)
    pdf.set_font("CV", "B", 10)
    pdf.cell(0, 5, "Профиль", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(pdf.l_margin + 3)
    pdf.set_font("CV", "", 9.5)
    pdf.set_text_color(*C_INK)
    summary = (
        "6+ лет в продуктовой разработке: Python, событийные и микросервисные архитектуры, "
        "интеграции и облака (GCP, Azure). Домены: страхование и healthtech, real-time телефония с AI, "
        "маркетплейсы и агрегаторы. Участвовал в командах уровня Qantev, Oscar Health, экосистемы доставки; "
        "фокус на чистой архитектуре, наблюдаемости и безопасности данных."
    )
    pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 6, 4.5, summary)
    pdf.ln(6)

    section_title(pdf, "Ключевые результаты")
    highlights = [
        "Qantev: лидировал миграцию Django → FastAPI; сократил баги в проде на ~35%, MTTR ~−50%; ускорил циклы разработки ~30%.",
        "40+ REST-эндпоинтов, оптимизация SQL и кэширование под высокую нагрузку; интеграция ML-пайплайнов классификации документов.",
        "AI-телефония (2025–н.в.): событийная архитектура Twilio Media Streams + GCP Pub/Sub + STT; подготовка к требованиям SOC 2, PII-redaction (Modal).",
        "Дашборды и отчётность: ускорение в ~2× за счёт запросов и кэширования.",
        "Oscar Health / смежные: Kubernetes, ArgoCD, gRPC; миграция критичного пайплайна с Go на Python.",
    ]
    for h in highlights:
        bullet(pdf, h)

    section_title(pdf, "Стек (сжато)")
    pdf.set_font("CV", "", 9.3)
    pdf.set_text_color(*C_INK)
    stack = (
        "Python · FastAPI · Django · DRF · SQLAlchemy · Alembic · Pydantic · Celery · PostgreSQL · MySQL · Redis · "
        "Kafka · RabbitMQ · gRPC · WebSockets\n"
        "GCP: Cloud Run, Cloud SQL, Pub/Sub, Tasks, GCS, Logging/Monitoring · Azure: Functions, Service Bus, Cosmos, Blob · "
        "Docker · Kubernetes · ArgoCD · GitHub Actions · GitLab CI · Prometheus · Grafana · Sentry · OpenAI / Anthropic APIs"
    )
    pdf.multi_cell(0, 4.5, stack)

    section_title(pdf, "Опыт")
    job_block(
        pdf,
        "AI-платформа корпоративной телефонии (real-time)",
        "Software Engineer",
        "2025 — н.в.",
        [
            "Django, GCP, Twilio Media Streams; живая транскрипция, намерения, ассистирование операторам.",
            "Pub/Sub, Cloud Run/SQL; документация и сетевые схемы под аудит SOC 2; multitenancy на уровне авторизации.",
        ],
    )
    job_block(
        pdf,
        "Qantev — международная SaaS для страховщиков (claims, AI-аналитика)",
        "Backend Developer",
        "2024 — авг. 2025",
        [
            "Миграция на FastAPI, масштабируемая схема БД; Azure, webhooks, асинхронные процессы.",
            "Совместная работа с ML по классификации меддокументов; Prometheus/Grafana, тестовая стратегия.",
        ],
    )
    job_block(
        pdf,
        "Oscar Health — платформа медицинского страхования (США)",
        "Backend Developer",
        "мар. 2023 — мар. 2024",
        [
            "Микросервисы, K8s/ArgoCD, Aurora/Artifactory; интеграции с вендорами, gRPC между сервисами.",
            "Рефакторинг пайплайна с Go на Python; Prometheus/Grafana, прод-поддержка.",
        ],
    )

    pdf.add_page()
    pdf.set_y(16)

    job_block(
        pdf,
        "Netrika — образовательная платформа (агрегатор услуг)",
        "Full-stack Developer",
        "2022 — 2023",
        [
            "Django, DRF, Celery, Redis, PostgreSQL; интеграция с бухгалтерией, миграции данных, кэширование.",
        ],
    )
    job_block(
        pdf,
        "Kitchenhub — virtual food hall (экосистема доставки)",
        "Backend Developer",
        "2021 — мар. 2023",
        [
            "Миграция сервисов Falcon/Starlette → FastAPI; GCP (Datastore, Cloud Run, Scheduler), Redis, Sentry.",
            "Единая аутентификация для интеграций; оптимизация REST API и фоновых задач.",
        ],
    )
    job_block(
        pdf,
        "Perfect Art — облачная платформа для клининга",
        "Backend Developer",
        "2019 — 2021",
        [
            "Azure Functions, Service Bus, Durable Functions; RBAC в JWT; OpenAPI-документация.",
        ],
    )

    section_title(pdf, "Компетенции и формат работы")
    pdf.set_font("CV", "", 9.5)
    pdf.multi_cell(
        0,
        4.6,
        "Архитектура и API · событийные системы · производительность и кэш · безопасность и соответствие (SOC 2) · "
        "код-ревью · менторство · работа с инцидентами в проде. Английский — рабочий (продуктовая переписка, созвоны).",
    )

    section_title(pdf, "Дополнительно")
    pdf.set_font("CV", "", 9)
    pdf.set_text_color(*C_MUTED)
    pdf.multi_cell(
        0,
        4.5,
        "По запросу: рекомендации, детализация по проектам, портфолио ссылок. Готов к техническому интервью и тестовому заданию.",
    )

    out_dir = Path(__file__).resolve().parent.parent / "docs" / "cv"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "Max_Vasilenko_Backend_CV_2026.pdf"
    pdf.output(str(out_path))
    return out_path


if __name__ == "__main__":
    p = main()
    print(p)
