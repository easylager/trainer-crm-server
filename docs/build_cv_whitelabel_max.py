#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fill Pavel's white-label DOCX template with Maksim Vasilenko content (no employer names)."""

from __future__ import annotations

import copy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "Павел К.  Senior CV updated.docx"
OUT = ROOT / "cv-max-vasilenko-senior-python-whitelabel-ru-2026.docx"


def set_runs_text(paragraph: Paragraph, text: str) -> None:
    if not paragraph.runs:
        paragraph.add_run(text)
        return
    paragraph.runs[0].text = text
    for run in paragraph.runs[1:]:
        run.text = ""


def ensure_paragraphs(cell, count: int) -> None:
    while len(cell.paragraphs) < count:
        last = cell.paragraphs[-1]._p
        new_p = copy.deepcopy(last)
        for t in new_p.findall(".//" + qn("w:t")):
            t.text = ""
        last.addnext(new_p)
    while len(cell.paragraphs) > count:
        p = cell.paragraphs[-1]._p
        p.getparent().remove(p)


def _strip_num_pr(paragraph: Paragraph) -> None:
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return
    numPr = pPr.find(qn("w:numPr"))
    if numPr is not None:
        pPr.remove(numPr)


def _has_num_pr(paragraph: Paragraph) -> bool:
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is None:
        return False
    return pPr.find(qn("w:numPr")) is not None


def cleanup_empty_bullets(cell) -> None:
    """Убрать пустые абзацы с маркером списка (квадратик/точка без текста)."""
    for paragraph in list(cell.paragraphs):
        if paragraph.text.strip():
            continue
        if not _has_num_pr(paragraph):
            continue
        parent = paragraph._p.getparent()
        # в ячейке должен остаться хотя бы один абзац
        if len(cell.paragraphs) > 1:
            parent.remove(paragraph._p)
        else:
            _strip_num_pr(paragraph)


def set_cell_lines(cell, lines: list[str]) -> None:
    ensure_paragraphs(cell, max(len(lines), 1))
    for i, line in enumerate(lines):
        set_runs_text(cell.paragraphs[i], line)
    # лишние пустые — удаляем целиком (иначе остаётся квадратный маркер списка)
    while len(cell.paragraphs) > len(lines):
        cell.paragraphs[-1]._p.getparent().remove(cell.paragraphs[-1]._p)
    cleanup_empty_bullets(cell)


def set_merged_value(row, col: int, text: str) -> None:
    cell = row.cells[col]
    if "\n" in text:
        set_cell_lines(cell, [x for x in text.split("\n") if x != ""])
    else:
        if not cell.paragraphs:
            cell.add_paragraph(text)
        else:
            set_runs_text(cell.paragraphs[0], text)
            for p in cell.paragraphs[1:]:
                set_runs_text(p, "")
        cleanup_empty_bullets(cell)


def set_space_after(paragraph: Paragraph, pt: float) -> None:
    pPr = paragraph._p.get_or_add_pPr()
    spacing = pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        pPr.append(spacing)
    spacing.set(qn("w:after"), str(int(pt * 20)))  # twips
    # сохранить line из шаблона, если уже был
    if spacing.get(qn("w:line")) is None:
        spacing.set(qn("w:line"), "360")
        spacing.set(qn("w:lineRule"), "auto")


def ensure_spacer_after_title(doc: Document) -> None:
    """Добавить воздух между 'Senior Python…' и верхней таблицей Навыки/Проекты."""
    title = doc.paragraphs[1]
    set_space_after(title, 12)
    title_p = title._p
    nxt = title_p.getnext()
    # если сразу таблица — вставить пустой абзац-спейсер
    if nxt is not None and nxt.tag == qn("w:tbl"):
        spacer = OxmlElement("w:p")
        pPr = OxmlElement("w:pPr")
        spacing = OxmlElement("w:spacing")
        spacing.set(qn("w:after"), "120")  # 6pt
        spacing.set(qn("w:line"), "240")
        spacing.set(qn("w:lineRule"), "auto")
        pPr.append(spacing)
        spacer.append(pPr)
        title_p.addnext(spacer)


def _paragraph_text(p_elm) -> str:
    return "".join(t.text or "" for t in p_elm.findall(".//" + qn("w:t")))


def _make_spacer_paragraph(after_pt: float = 6, before_pt: float = 0, line: int = 240) -> OxmlElement:
    """Чистый пустой абзац без numPr/sectPr (иначе появляется □)."""
    spacer = OxmlElement("w:p")
    pPr = OxmlElement("w:pPr")
    spacing = OxmlElement("w:spacing")
    if before_pt:
        spacing.set(qn("w:before"), str(int(before_pt * 20)))
    if after_pt:
        spacing.set(qn("w:after"), str(int(after_pt * 20)))
    spacing.set(qn("w:line"), str(line))
    spacing.set(qn("w:lineRule"), "auto")
    pPr.append(spacing)
    spacer.append(pPr)
    return spacer


def remove_square_before_projects_heading(doc: Document) -> None:
    """Убрать □ над «Профессиональная деятельность (проекты)».

    В шаблоне перед заголовком пустой абзац с w:sectPr — в превью/Word
    он рисуется как пустой квадратик слева. Переносим sectPr в последний
    абзац резюме-таблицы, удаляем «грязные» пустые абзацы и ставим
    чистый спейсер, чтобы таблица проектов не прилипала к стеку.
    """
    body = doc.element.body
    children = list(body)
    heading_p = None
    heading_idx = None
    for i, el in enumerate(children):
        if el.tag != qn("w:p"):
            continue
        if _paragraph_text(el).strip() == "Профессиональная деятельность (проекты)":
            heading_p = el
            heading_idx = i
            break
    if heading_p is None or heading_idx is None:
        return

    sect_pr = None
    to_remove = []
    j = heading_idx - 1
    while j >= 0:
        el = children[j]
        if el.tag == qn("w:tbl"):
            break
        if el.tag == qn("w:p"):
            if _paragraph_text(el).strip():
                break
            found = el.find(".//" + qn("w:sectPr"))
            if found is not None and sect_pr is None:
                # отвязать от пустого абзаца
                parent = found.getparent()
                parent.remove(found)
                sect_pr = found
            to_remove.append(el)
        j -= 1

    if sect_pr is not None:
        # последний абзац ячейки summary (таблица перед пустыми)
        summary_cell = doc.tables[1].rows[0].cells[0]
        last_p = summary_cell.paragraphs[-1]._p
        pPr = last_p.get_or_add_pPr()
        # sectPr должен быть последним ребёнком pPr
        existing = pPr.find(qn("w:sectPr"))
        if existing is not None:
            pPr.remove(existing)
        pPr.append(sect_pr)

    for el in to_remove:
        body.remove(el)

    # воздух между стеком технологий и заголовком/таблицей проектов
    heading_p.addprevious(_make_spacer_paragraph(after_pt=6, before_pt=10, line=276))
    # чуть отступа и у самого заголовка
    h_pPr = heading_p.get_or_add_pPr()
    spacing = h_pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        h_pPr.insert(0, spacing)
    spacing.set(qn("w:before"), "120")  # 6pt
    spacing.set(qn("w:after"), "120")
    if spacing.get(qn("w:line")) is None:
        spacing.set(qn("w:line"), "360")
        spacing.set(qn("w:lineRule"), "auto")


SKILLS = [
    "Навыки",
    "Python, FastAPI, Django, DRF",
    "Микросервисы и event-driven",
    "Kafka, gRPC, очереди сообщений",
    "PostgreSQL, Redis, оптимизация SQL",
    "AWS, GCP, Azure, Kubernetes",
    "Интеграции внешних API",
    "AI/LLM в production",
    "pytest, CI/CD, code review",
]

PROJECT_NAMES = [
    "Проекты",
    "Realtime AI-ассистент для страховых кол-центров",
    "Международный SaaS: страховые заявки и antifraud",
    "Высоконагруженная страховая платформа (США)",
    "Платформа интеграций доставки",
    "Образовательная платформа · платежи и учёт",
]

SUMMARY = [
    "6+ лет коммерческой разработки на Python: высоконагруженные backend-системы, микросервисы, интеграции с внешними API, платежные контуры и AI-фичи в production.",
    "Языки программирования: Python; практический опыт Golang на критичных участках распределённой платформы.",
    "Бэкенд: Django, Django REST Framework, FastAPI, Flask, Pydantic, SQLAlchemy, Alembic, Celery, httpx, aiohttp, OAuth2/JWT, Pandas, Pytest, Sentry-sdk, OpenAPI/Swagger.",
    "AI в production: OpenAI API, Anthropic Claude, пайплайны STT→LLM, обработка документов, защитные ограничения (guardrails), сценарии с обязательным подтверждением оператором.",
    "Базы данных: PostgreSQL, MySQL, Redis, Cloud SQL, GCP Datastore.",
    "Межсервисное взаимодействие: Kafka, gRPC, GCP Pub/Sub, Azure Service Bus, RabbitMQ; Airflow для оркестрации ETL и пакетной обработки.",
    "Облака: GCP (Cloud Run, Pub/Sub, Cloud SQL, GCS, Scheduler, Datastore), AWS (EKS, EC2, S3, RDS, IAM, CloudWatch, Lambda), Azure (AKS, Blob Storage, Service Bus).",
    "DevOps: Docker, Docker Compose, Kubernetes, ArgoCD, Helm, GitHub Actions, GitLab CI/CD.",
    "Мониторинг: Grafana, Prometheus, Sentry.",
    "Серверы: Nginx, Gunicorn, Uvicorn.",
    "Системы контроля версий: Git, GitLab, GitHub.",
]

# Хронология подряд (новый → старый), без пересечений.
# AI ~19м | EU ~9м | US ~27м (самый длинный) | Delivery ~10м | Edu+Payments ~14м
PROJECTS = [
    {
        "from": "С 01.2025",
        "to": "До 07.2026",
        "role": "Инженер-программист",
        "project": (
            "Мультитенантный B2B SaaS для realtime AI-ассистенса в страховых кол-центрах. "
            "Во время звонка система подсказывает оператору следующий шаг по контексту разговора: "
            "транскрибация, извлечение намерений, подсказки и шаблоны ответов. Критичны низкая задержка, "
            "изоляция клиентов платформы и то, чтобы автоматизация не подставляла оператора на рискованных решениях."
        ),
        "duties": [
            "Отвечал за backend realtime-контура: приём аудио/событий звонка, статусы сессии, выдача подсказок оператору.",
            "Спроектировал мультитенантную архитектуру с изоляцией данных и прав доступа между клиентами платформы.",
            "Внедрил production-пайплайны STT→LLM (OpenAI, Claude): промпты, ограничения на небезопасные ответы, подтверждение оператором на рискованных шагах.",
            "Разделил sync API и тяжёлые AI-стадии: быстрый ответ в звонке, фоновая обработка через GCP Pub/Sub с ретраями и back-pressure.",
            "Добавил correlation ID и auditable-статусы для сквозной трассировки шагов ассистента в рамках звонка.",
            "Работал с GCP на постоянной основе: Cloud Run, Pub/Sub, Cloud SQL, GCS; выкат сервисов в Kubernetes.",
            "Оптимизировал задержку подсказок: кеш в Redis, контроль стоимости и latency LLM-вызовов, деградация без обрыва сценария.",
            "Проектировал схему PostgreSQL под сессии звонков, подсказки и аудит действий оператора.",
            "Настроил CI/CD в GitLab CI, контейнеризацию и безопасные релизы без простоя критичных сценариев.",
            "Вёл мониторинг Prometheus/Grafana и Sentry: ошибки, latency, срывы пайплайна во время звонка.",
            "Покрыл ключевые сценарии pytest; проводил code review и онбординг коллег.",
            "Документировал API, архитектурные решения и регламенты поддержки.",
            "Участвовал в разборе production-инцидентов и post-mortem.",
        ],
        "tech": (
            "Python, Django, Django REST Framework, FastAPI, PostgreSQL, Redis, OpenAI API, Anthropic Claude, "
            "GCP (Cloud Run, Pub/Sub, Cloud SQL, GCS), Kubernetes, Docker, GitLab CI/CD, Prometheus, Grafana, Pytest, Sentry."
        ),
    },
    {
        "from": "С 04.2024",
        "to": "До 12.2024",
        "role": "Инженер-программист",
        "project": (
            "Международный B2B SaaS для обработки страховых заявок и выявления мошенничества (antifraud). "
            "Платформа принимает документы по заявке, извлекает данные, помогает проверить кейс и сигнализирует "
            "о подозрительных паттернах. Важны проверка человеком, партнёрские интеграции и надёжная доставка статусов."
        ),
        "duties": [
            "Разработал backend обработки страховых заявок: загрузка документов, извлечение полей, статусы для проверки оператором.",
            "Реализовал antifraud-сигналы и AI-подсказки по заявке: скоринг/эвристики, оценка уверенности, возможность переопределения человеком.",
            "Построил event-driven потоки на Kafka для статусов заявок и webhook-уведомлений партнёрам.",
            "Оркестрировал пакетную обработку, пересчёт и ETL через Airflow DAG.",
            "Организовал хранение вложений в Azure Blob Storage; работал с Azure Service Bus и контуром AKS.",
            "Интегрировал внешних партнёров: версионируемые контракты, идемпотентная доставка статусов.",
            "Участвовал в миграции Django → FastAPI на живом продукте без простоя; REST API с OpenAPI-спецификацией.",
            "Развивал схему PostgreSQL под заявки и проверки, оптимизировал SQL, кешировал горячие read-модели в Redis.",
            "Вынес тяжёлую обработку документов и antifraud-стадии в отдельные воркеры — меньше влияние сбоев на API.",
            "Настроил ретраи и наблюдаемость на чувствительных путях данных; покрыл сценарии pytest.",
            "Согласовывал API-контракты со смежными командами; проводил code review.",
            "Вёл техническую документацию сервисов, схем данных и интеграционных потоков.",
        ],
        "tech": (
            "Python, FastAPI, Django, Django REST Framework, PostgreSQL, Redis, Kafka, Airflow, "
            "Azure (Service Bus, Blob Storage, AKS), Pydantic, Alembic, Docker, Kubernetes, Pytest, OpenAPI/Swagger, GitLab CI/CD."
        ),
    },
    {
        "from": "С 01.2022",
        "to": "До 03.2024",
        "role": "Инженер-программист",
        "project": (
            "Крупная высоконагруженная платформа в регулируемой среде (США): микросервисы для проверки "
            "доступности услуг и синхронизации клиентских данных. Система обслуживает миллионы пользователей, "
            "где ошибка в статусе сразу бьёт по клиенту. Критичны надёжность на сезонных пиках нагрузки, "
            "аудит изменений, быстрый разбор инцидентов и поставка в AWS/Kubernetes."
        ),
        "duties": [
            "Разрабатывал и поддерживал мультисервисный пайплайн проверки статусов на Kafka — синхронизация данных между сервисами.",
            "Обеспечивал устойчивость сервисов на сезонных пиках нагрузки.",
            "Сопровождал плотный gRPC-трафик между соседними микросервисами.",
            "Работал на стыке Python и Golang на критичных участках; участвовал в переносе отдельных стадий пайплайна на Python.",
            "Эксплуатировал микросервисы в AWS: EKS/Kubernetes, EC2, S3, RDS, IAM, CloudWatch; деплой через ArgoCD.",
            "Настраивал CI/CD и артефакты поставки (Artifactory) для предсказуемых релизов в нескольких окружениях.",
            "Соблюдал практики безопасной работы с чувствительными данными: минимальные права доступа, аудит, наблюдаемость.",
            "Вёл мониторинг Prometheus/Grafana; участвовал в разборе и восстановлении после production-инцидентов.",
            "Поддерживал backend API и контракты данных для внутренних React-инструментов операционных команд.",
            "Оптимизировал горячие пути и согласование статусов между сервисами; применял параллельную обработку под пиковую нагрузку.",
            "Писал автотесты и собирал доказательства для приёмки фич и фиксов; проводил code review в распределённой команде.",
            "Автоматизировал data-fix скриптами для исторических несоответствий в БД — меньше ручной работы и операционных затрат.",
            "Развивал интеграции со смежными вендорами и сервисами; сопровождал релизы без деградации пользовательских сценариев.",
        ],
        "tech": (
            "Python, Golang, Flask, Kafka, gRPC, PostgreSQL, MySQL, SQLAlchemy, "
            "AWS (EKS, EC2, S3, RDS, IAM, CloudWatch, Lambda), Kubernetes, ArgoCD, Docker, Redis, "
            "Prometheus, Grafana, Pytest, Artifactory, GitHub."
        ),
    },
    {
        "from": "С 03.2021",
        "to": "До 12.2021",
        "role": "Инженер-программист",
        "project": (
            "Платформа интеграций доставки для ресторанов: единый внутренний API и кабинет поверх нескольких "
            "внешних площадок. Рестораны управляют меню, заказами, статусами, метриками и подключёнными "
            "провайдерами в одном месте. Нужны микросервисы, событийная модель и saga-оркестрация, чтобы "
            "заказы и статусы оставались согласованными при сбоях на стороне партнёров."
        ),
        "duties": [
            "Отвечал за интеграции с крупными площадками доставки (Uber Eats, Grubhub, DoorDash, GloriaFood).",
            "Свёл разные внешние API к единому внутреннему контракту: ретраи, rate limit, устойчивость к смене поведения партнёров.",
            "Проектировал и развивал микросервисную архитектуру на GCP: Cloud Run, Pub/Sub, Datastore, Cloud Scheduler.",
            "Реализовал событийные потоки и saga-оркестрацию для согласованности заказов и статусов.",
            "Перевёл сервисы с Falcon/Starlette на FastAPI; REST-слой с OpenAPI для продукта и адаптеров провайдеров.",
            "Обеспечил ежедневные высоконагруженные синхронизации и сверку статусов под лимитами внешних API.",
            "Настроил кеширование в Redis, мониторинг ошибок в Sentry, дисциплину релизов без простоя ресторанов.",
            "Контейнеризировал сервисы (Docker); автоматизировал фоновые и по расписанию задачи.",
            "Документировал интеграционные контракты и регламенты поддержки production-интеграций.",
            "Оптимизировал задержки и устойчивость адаптеров; разбирал инциденты на стороне партнёрских API.",
            "Проводил code review и улучшал переиспользуемые SDK/адаптеры внутри платформы.",
        ],
        "tech": (
            "Python, FastAPI, GCP (Cloud Run, Pub/Sub, Datastore, Cloud Scheduler), Redis, Docker, "
            "OpenAPI/Swagger, Sentry, Pytest, Git."
        ),
    },
    {
        "from": "С 01.2020",
        "to": "До 02.2021",
        "role": "Инженер-программист",
        "project": (
            "Образовательная платформа-агрегатор услуг с контуром продаж, платежей и учёта. "
            "Клиенты публикуют учреждения, курсы и конкурсы; пользователи находят услугу и оформляют покупку. "
            "Внутри — витрина, биллинг, интеграция с бухгалтерией, согласованность проводок на денежных путях "
            "и миграция данных с legacy-контура без потери целостности."
        ),
        "duties": [
            "Разрабатывал backend на Django и Django REST Framework: каталог услуг, карточки клиентов, сценарии покупки.",
            "Спроектировал модель данных PostgreSQL под услуги, заказы, платежи и учётные статусы.",
            "Реализовал платёжный и биллинговый контур: статусы оплаты, защита от дублей и гонок на денежных путях.",
            "Интегрировал бухгалтерскую систему для автоматизации платёжных и учётных процессов.",
            "Обеспечил согласованность проводок и auditable-переходы состояний финансовых сущностей.",
            "Написал и провёл миграционные скрипты переноса данных с контролем целостности и синхронизации.",
            "Настроил Django Signals для автоматических процессов при создании и обновлении сущностей.",
            "Реализовал фоновые задачи на Celery + Redis: уведомления, сверка, отчётность, отложенная обработка платежей.",
            "Внедрил кеширование каталога в Redis; оптимизировал SQL на витрине и checkout.",
            "Обеспечил идемпотентность webhook/callback-сценариев платёжных провайдеров.",
            "Документировал API через Swagger; покрыл ключевые сценарии Pytest.",
            "Настроил CI/CD в GitLab CI/CD, контейнеризацию Docker/Docker Compose, мониторинг ошибок через Sentry.",
            "Рефакторил код для поддерживаемости; проводил code review и вёл техническую документацию.",
        ],
        "tech": (
            "Python, Django, Django REST Framework, Celery, PostgreSQL, Redis, Docker, Docker Compose, "
            "Swagger API, GitLab CI/CD, Sentry, Pytest."
        ),
    },
]


def fill() -> Path:
    doc = Document(str(TEMPLATE))

    set_runs_text(doc.paragraphs[0], "Максим В.")
    set_runs_text(doc.paragraphs[1], "Senior Python Разработчик")
    ensure_spacer_after_title(doc)

    t0 = doc.tables[0]
    set_cell_lines(t0.rows[0].cells[0], SKILLS)
    set_cell_lines(t0.rows[0].cells[1], PROJECT_NAMES)
    set_cell_lines(
        t0.rows[1].cells[0],
        ["Образование", "Компьютерные сети и системы, инженер-программист"],
    )
    set_cell_lines(
        t0.rows[1].cells[1],
        ["Языковые навыки", "Русский, Английский (B2+)"],
    )
    # на всякий случай вычистить пустые маркеры во всех ячейках шапки
    for row in t0.rows:
        for cell in row.cells:
            cleanup_empty_bullets(cell)

    set_cell_lines(doc.tables[1].rows[0].cells[0], SUMMARY)

    for idx, project in enumerate(PROJECTS):
        table = doc.tables[2 + idx]
        set_runs_text(table.rows[0].cells[1].paragraphs[0], project["from"])
        set_runs_text(table.rows[0].cells[2].paragraphs[0], project["to"])
        set_merged_value(table.rows[1], 1, project["role"])
        set_merged_value(table.rows[2], 1, project["project"])
        set_cell_lines(table.rows[3].cells[1], project["duties"])
        set_merged_value(table.rows[4], 1, project["tech"])

    # В шаблоне 6 проектных таблиц — лишние удаляем (остаётся ровно len(PROJECTS)).
    body = doc.element.body
    while len(doc.tables) > 2 + len(PROJECTS):
        tbl = doc.tables[-1]._tbl
        body.remove(tbl)

    remove_square_before_projects_heading(doc)

    doc.save(str(OUT))
    return OUT


if __name__ == "__main__":
    print(fill())
