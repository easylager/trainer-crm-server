#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""English white-label CV for Security Backend (Python) + Identity — folder 03.08-security.

No Entra ID / Cognito / SailPoint / JML claims.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from docx import Document

from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from build_cv_whitelabel_max import (
    TEMPLATE,
    cleanup_empty_bullets,
    ensure_spacer_after_title,
    remove_square_before_projects_heading,
    set_cell_lines,
    set_merged_value,
    set_runs_text,
    _make_spacer_paragraph,
    _paragraph_text,
)

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "cv-max-vasilenko-senior-security-backend-en-2026.docx"
DESKTOP_DIR = Path.home() / "Desktop" / "CV" / "Вайтлейбл" / "03.08-security"
# Same internal white-label layout as «Василенко М. Senior CV.docx» (Pavel template).
DESKTOP_OUT = DESKTOP_DIR / "Maksim_V_Senior_CV_EN.docx"

SKILLS = [
    "Skills",
    "Python / Go APIs in production",
    "OAuth2, JWT, server-side authorization",
    "Multi-tenant isolation, least privilege",
    "Secure API boundaries, audit trails",
    "FastAPI, Django/DRF, asyncio",
    "Kafka, gRPC, messaging",
    "PostgreSQL, Redis · AWS IAM, Kubernetes",
    "pytest, CI/CD, code review",
]

PROJECT_NAMES = [
    "Projects",
    "Multi-tenant realtime platform for call centres",
    "International SaaS: claims processing & antifraud",
    "High-load insurance platform (USA)",
    "Restaurant delivery integrations platform",
    "Education platform · payments & accounting",
]

SUMMARY = [
    "6+ years building production Python backends: APIs, microservices and integrations in regulated environments with sensitive client data. Hands-on Go on critical paths of a distributed platform.",
    "APIs: FastAPI, Django / DRF, Flask, asyncio, Pydantic, SQLAlchemy, Alembic, Celery, httpx, typing, OpenAPI/Swagger — contracts designed and operated under load.",
    "Access control: OAuth2, JWT validation, server-side authorization. Multi-tenant isolation and clear role separation.",
    "Hardened service boundaries: idempotency, input validation, least-privilege service accounts, auditable status transitions; code review and design focused on unauthorized access and cross-tenant leakage.",
    "Data and messaging: PostgreSQL, MySQL, Redis; Kafka, gRPC, GCP Pub/Sub, Azure Service Bus, RabbitMQ.",
    "Cloud and delivery: AWS (EKS, IAM, RDS, S3, CloudWatch), GCP, Azure; Docker, Kubernetes, ArgoCD, GitHub Actions / GitLab CI/CD; Grafana, Prometheus, Sentry.",
    "Also shipped operator-facing automation with external model APIs where needed — always behind authorization checks and human confirmation on risky actions.",
]

PROJECTS = [
    {
        "from": "From 01.2025",
        "to": "Until 07.2026",
        "role": "Software Engineer",
        "project": (
            "Multi-tenant B2B SaaS for insurance call centres: realtime session backend that serves operators "
            "during live calls. Isolation between platform clients, strict access checks and an auditable trail "
            "of operator actions were as critical as latency. Part of the product surfaces model-backed hints "
            "to operators — always gated by permissions and human confirmation on sensitive steps."
        ),
        "duties": [
            "Owned the realtime backend: session lifecycle, event intake, APIs used by the operator console.",
            "Designed multi-tenant isolation so data, sessions and search never cross client boundaries.",
            "Enforced token/session and role checks on every sensitive endpoint before returning data or invoking privileged actions.",
            "Separated privileges for operators vs service accounts; narrowed what background workers could read or write.",
            "Added correlation IDs and auditable step statuses for end-to-end tracing of actions inside a call session.",
            "Split interactive APIs from heavier async work via Pub/Sub with retries and back-pressure.",
            "Hardened boundaries against cross-session leakage and privilege misuse; covered negative access cases in pytest.",
            "Delivered via GCP (Cloud Run, Pub/Sub, Cloud SQL), Kubernetes, GitLab CI/CD; operated with Prometheus/Grafana/Sentry.",
        ],
        "tech": (
            "Python, Django, Django REST Framework, FastAPI, asyncio, PostgreSQL, Redis, OAuth2/JWT, "
            "GCP (Cloud Run, Pub/Sub, Cloud SQL, GCS), Kubernetes, Docker, GitLab CI/CD, "
            "Prometheus, Grafana, Pytest, Sentry."
        ),
    },
    {
        "from": "From 04.2024",
        "to": "Until 12.2024",
        "role": "Software Engineer",
        "project": (
            "International B2B SaaS for insurance claim processing and antifraud. The platform ingests claim "
            "documents, extracts fields, supports operator review and flags suspicious patterns. Human review, "
            "partner integrations and reliable status delivery mattered."
        ),
        "duties": [
            "Built claim-processing backend: document upload, field extraction, statuses for operator review.",
            "Introduced OAuth2/JWT on operator and partner APIs: validate token and scopes server-side before any claim read or status write; invalid or expired credentials are rejected — no processing continues on a failed check.",
            "Restricted attachments and claim fields by role and the client's organisation so one tenant cannot reach another's case data.",
            "Integrated external partners: versioned contracts, webhook signature verification, idempotent status delivery.",
            "Built Kafka event flows for claim statuses and partner webhook notifications.",
            "Moved heavy document and antifraud stages to workers with narrower service privileges than the public API.",
            "Took part in a live Django → FastAPI migration with no downtime; REST API with an OpenAPI spec.",
            "Evolved the PostgreSQL schema, tuned SQL, cached hot read models in Redis; covered negative authorization paths in pytest.",
        ],
        "tech": (
            "Python, FastAPI, Django, Django REST Framework, PostgreSQL, Redis, Kafka, OAuth2/JWT, Airflow, "
            "Azure (Service Bus, Blob Storage, AKS), Pydantic, Alembic, Docker, Kubernetes, Pytest, OpenAPI/Swagger, GitLab CI/CD."
        ),
    },
    {
        "from": "From 01.2022",
        "to": "Until 03.2024",
        "role": "Software Engineer",
        "project": (
            "Large high-load platform in a regulated US environment: microservices for service eligibility "
            "checks and client data sync. Millions of users — a wrong status hits the customer immediately. "
            "Seasonal peak reliability, change audit, fast incident response and AWS/Kubernetes delivery were critical."
        ),
        "duties": [
            "Built and ran production APIs and a multi-service Kafka status-check pipeline syncing data across services.",
            "Supported dense gRPC traffic between microservices; on the Python/Go boundary tightened contracts and authorization error handling.",
            "Helped move selected pipeline stages to Python without weakening inter-service access checks.",
            "Operated services on AWS EKS/Kubernetes; worked with IAM and least-privilege service roles; deployed via ArgoCD.",
            "Followed safe handling of sensitive client data: least privilege, change audit, observability.",
            "At API boundaries rejected invalid or expired token/call context — no silent continuation of processing.",
            "Tuned hot paths and status reconciliation; used parallel processing under peak load.",
            "Maintained backend APIs and data contracts for internal React ops tools with access separation.",
            "Wrote automated tests (including negatives) and acceptance evidence; joined production incident response.",
        ],
        "tech": (
            "Python, Golang, Flask, Kafka, gRPC, PostgreSQL, MySQL, SQLAlchemy, JWT/OAuth2, "
            "AWS (EKS, EC2, S3, RDS, IAM, CloudWatch, Lambda), Kubernetes, ArgoCD, Docker, Redis, "
            "Prometheus, Grafana, Pytest, Artifactory, GitHub."
        ),
    },
    {
        "from": "From 03.2021",
        "to": "Until 12.2021",
        "role": "Software Engineer",
        "project": (
            "Restaurant delivery integrations platform: one internal API and console over several external "
            "marketplaces. Restaurants manage menus, orders, statuses, metrics and connected providers in one place. "
            "Microservices, events and saga orchestration kept orders and statuses consistent when partners failed."
        ),
        "duties": [
            "Owned integrations with major delivery marketplaces (Uber Eats, Grubhub, DoorDash, GloriaFood).",
            "Unified external APIs behind one internal contract: retries, rate limits, outbound credential checks, resilience to partner behaviour changes.",
            "Designed and evolved the GCP microservice architecture: Cloud Run, Pub/Sub, Datastore, Cloud Scheduler.",
            "Implemented event streams and saga orchestration for order and status consistency.",
            "Migrated services from Falcon/Starlette to FastAPI; REST + OpenAPI; kept a restaurant console from seeing another venue's marketplace data.",
            "Ran daily high-volume syncs and status reconciliation under external API limits.",
            "Set up Redis caching, Docker, Sentry; documented integration contracts and support playbooks.",
        ],
        "tech": (
            "Python, FastAPI, asyncio, GCP (Cloud Run, Pub/Sub, Datastore, Cloud Scheduler), Redis, Docker, "
            "OpenAPI/Swagger, Sentry, Pytest, Git."
        ),
    },
    {
        "from": "From 01.2020",
        "to": "Until 02.2021",
        "role": "Software Engineer",
        "project": (
            "Education services aggregator with sales, payments and accounting. Clients publish institutions, "
            "courses and contests; users discover and purchase. Inside — catalogue, billing, accounting integration, "
            "consistent money-path postings and a legacy migration without losing integrity."
        ),
        "duties": [
            "Built Django/DRF backend: service catalogue, client cards, purchase flows and console access separation.",
            "Designed PostgreSQL model for services, orders, payments and accounting statuses.",
            "Implemented payment and billing flows: payment statuses, protection against duplicates and races on money paths.",
            "Made payment-provider webhooks/callbacks idempotent and rejected callbacks with invalid signature/context.",
            "Integrated the accounting system; kept postings consistent and financial state transitions auditable.",
            "Wrote and ran migration scripts with integrity checks and sync controls.",
            "Shipped Celery + Redis background jobs; Redis catalogue cache; CI/CD, Docker Compose, Swagger, pytest, Sentry.",
        ],
        "tech": (
            "Python, Django, Django REST Framework, Celery, PostgreSQL, Redis, Docker, Docker Compose, "
            "Swagger API, GitLab CI/CD, Sentry, Pytest."
        ),
    },
]

PROJECT_ROW_LABELS = {
    0: "Period",
    1: "Project role",
    2: "Project",
    3: "Responsibilities and achievements",
    4: "Technologies",
}


def _set_heading(doc: Document, old: str, new: str) -> None:
    for p in doc.paragraphs:
        if p.text.strip() == old:
            set_runs_text(p, new)
            return
    # some templates have leading spaces
    for p in doc.paragraphs:
        if p.text.strip() == old.strip() or old in p.text:
            if p.text.strip() in {old, old.strip()} or p.text.strip().endswith(old.strip()):
                set_runs_text(p, new)
                return


def remove_square_before_projects_heading_en(doc: Document) -> None:
    """Same cleanup as RU helper, but for the English projects heading."""
    body = doc.element.body
    children = list(body)
    heading_p = None
    heading_idx = None
    for i, el in enumerate(children):
        if el.tag != qn("w:p"):
            continue
        if _paragraph_text(el).strip() == "Professional experience (projects)":
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
                parent = found.getparent()
                parent.remove(found)
                sect_pr = found
            to_remove.append(el)
        j -= 1

    if sect_pr is not None:
        summary_cell = doc.tables[1].rows[0].cells[0]
        last_p = summary_cell.paragraphs[-1]._p
        pPr = last_p.get_or_add_pPr()
        existing = pPr.find(qn("w:sectPr"))
        if existing is not None:
            pPr.remove(existing)
        pPr.append(sect_pr)

    for el in to_remove:
        body.remove(el)

    heading_p.addprevious(_make_spacer_paragraph(after_pt=6, before_pt=10, line=276))
    h_pPr = heading_p.get_or_add_pPr()
    spacing = h_pPr.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        h_pPr.insert(0, spacing)
    spacing.set(qn("w:before"), "120")
    spacing.set(qn("w:after"), "120")
    if spacing.get(qn("w:line")) is None:
        spacing.set(qn("w:line"), "360")
        spacing.set(qn("w:lineRule"), "auto")


def apply_english(doc: Document) -> None:
    set_runs_text(doc.paragraphs[0], "Maksim V.")
    set_runs_text(doc.paragraphs[1], "Senior Python Backend Engineer")
    ensure_spacer_after_title(doc)

    _set_heading(doc, "Профессиональная деятельность/опыт (резюме)", "Professional summary")
    _set_heading(doc, "Профессиональная деятельность (проекты)", "Professional experience (projects)")

    t0 = doc.tables[0]
    set_cell_lines(t0.rows[0].cells[0], SKILLS)
    set_cell_lines(t0.rows[0].cells[1], PROJECT_NAMES)
    set_cell_lines(
        t0.rows[1].cells[0],
        [
            "Education",
            "Software of Information Technologies, Software Engineer",
            "BSUIR — Faculty of Computer Systems and Networks",
        ],
    )
    set_cell_lines(
        t0.rows[1].cells[1],
        ["Languages", "Russian, English (conversational, B2+)"],
    )
    for row in t0.rows:
        for cell in row.cells:
            cleanup_empty_bullets(cell)

    set_cell_lines(doc.tables[1].rows[0].cells[0], SUMMARY)

    for idx, project in enumerate(PROJECTS):
        table = doc.tables[2 + idx]
        # left-column labels
        for row_i, label in PROJECT_ROW_LABELS.items():
            set_runs_text(table.rows[row_i].cells[0].paragraphs[0], label)
        set_runs_text(table.rows[0].cells[1].paragraphs[0], project["from"])
        set_runs_text(table.rows[0].cells[2].paragraphs[0], project["to"])
        set_merged_value(table.rows[1], 1, project["role"])
        set_merged_value(table.rows[2], 1, project["project"])
        set_cell_lines(table.rows[3].cells[1], project["duties"])
        set_merged_value(table.rows[4], 1, project["tech"])

    body = doc.element.body
    while len(doc.tables) > 2 + len(PROJECTS):
        body.remove(doc.tables[-1]._tbl)

    # Prefer EN-aware cleanup; fall back if heading not yet renamed in edge cases.
    remove_square_before_projects_heading_en(doc)
    if any(
        _paragraph_text(el).strip() == "Профессиональная деятельность (проекты)"
        for el in doc.element.body
        if el.tag == qn("w:p")
    ):
        remove_square_before_projects_heading(doc)


def _set_run(run, *, size=11, bold=False, color="222222"):
    from docx.shared import Pt, RGBColor

    run.font.name = "Arial"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Arial")
    run.font.size = Pt(size)
    run.bold = bold
    run.font.color.rgb = RGBColor.from_string(color)


def build_compatible_docx() -> Path:
    """Plain Arial DOCX without embedded template fonts — opens in Google Docs / LibreOffice / mobile Word."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt, RGBColor

    doc = Document()
    section = doc.sections[0]
    section.top_margin = Cm(1.5)
    section.bottom_margin = Cm(1.5)
    section.left_margin = Cm(1.8)
    section.right_margin = Cm(1.8)

    def para(text, *, size=11, bold=False, color="222222", after=4, before=0, center=False):
        p = doc.add_paragraph()
        if center:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_after = Pt(after)
        p.paragraph_format.space_before = Pt(before)
        r = p.add_run(text)
        _set_run(r, size=size, bold=bold, color=color)
        return p

    def h(text):
        para(text, size=13, bold=True, color="C00000", after=6, before=10)

    para("Maksim V.", size=18, bold=True, color="C00000", after=2)
    para("Senior Python Backend Engineer", size=12, bold=True, after=10)

    # Skills / projects side-by-side via a simple 2-col table
    h("Skills & projects")
    t = doc.add_table(rows=1, cols=2)
    t.style = "Table Grid"
    left, right = t.rows[0].cells
    left.text = ""
    right.text = ""
    for i, line in enumerate(SKILLS):
        p = left.paragraphs[0] if i == 0 else left.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _set_run(p.add_run(line), size=10, bold=(i == 0))
    for i, line in enumerate(PROJECT_NAMES):
        p = right.paragraphs[0] if i == 0 else right.add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _set_run(p.add_run(line), size=10, bold=(i == 0))

    edu = doc.add_table(rows=1, cols=2)
    edu.style = "Table Grid"
    edu.rows[0].cells[0].text = ""
    edu.rows[0].cells[1].text = ""
    for i, line in enumerate(
        [
            "Education",
            "Software of Information Technologies, Software Engineer",
            "BSUIR — Faculty of Computer Systems and Networks",
        ]
    ):
        p = edu.rows[0].cells[0].paragraphs[0] if i == 0 else edu.rows[0].cells[0].add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _set_run(p.add_run(line), size=10, bold=(i == 0))
    for i, line in enumerate(["Languages", "Russian, English (conversational, B2+)"]):
        p = edu.rows[0].cells[1].paragraphs[0] if i == 0 else edu.rows[0].cells[1].add_paragraph()
        p.paragraph_format.space_after = Pt(1)
        _set_run(p.add_run(line), size=10, bold=(i == 0))

    h("Professional summary")
    for line in SUMMARY:
        para(line, size=10.5, after=4)

    h("Professional experience (projects)")
    for proj in PROJECTS:
        para(proj["role"], size=11, bold=True, after=1, before=8)
        para(f"{proj['from']} — {proj['to']}", size=10, color="555555", after=2)
        para(proj["project"], size=10.5, after=3)
        para("Technologies: " + proj["tech"], size=9.5, color="444444", after=3)
        para("Responsibilities and achievements", size=10.5, bold=True, after=2)
        for item in proj["duties"]:
            # Plain text bullets — List Bullet + Mac stylesWithEffects often break Windows Word.
            para("• " + item, size=10, after=1)

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    path = DESKTOP_DIR / "Maksim_V_Senior_Python_Backend_Engineer.docx"
    doc.save(str(path))
    _strip_mac_word_parts(path)
    shutil.copy2(path, OUT)
    return path


def _strip_mac_word_parts(docx_path: Path) -> None:
    """Remove Mac Word extras that Windows Word rejects with a generic open error."""
    import tempfile
    import zipfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(docx_path, "r") as zin:
            zin.extractall(tmp_path)

        # Drop Mac-only styles package.
        (tmp_path / "word" / "stylesWithEffects.xml").unlink(missing_ok=True)

        ct = tmp_path / "[Content_Types].xml"
        ct.write_text(
            ct.read_text(encoding="utf-8")
            .replace(
                '<Override PartName="/word/stylesWithEffects.xml" '
                'ContentType="application/vnd.ms-word.stylesWithEffects+xml"/>',
                "",
            ),
            encoding="utf-8",
        )

        rels = tmp_path / "word" / "_rels" / "document.xml.rels"
        import re

        rels.write_text(
            re.sub(
                r'<Relationship[^>]+stylesWithEffects\.xml"[^>]*/>',
                "",
                rels.read_text(encoding="utf-8"),
            ),
            encoding="utf-8",
        )

        # Prefer numbering-free docs; keep file if present but unused.
        out_tmp = tmp_path / "out.docx"
        with zipfile.ZipFile(out_tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for f in sorted(tmp_path.rglob("*")):
                if f.is_file() and f.name != "out.docx":
                    zout.write(f, f.relative_to(tmp_path).as_posix())
        shutil.move(str(out_tmp), docx_path)


def build_pdf() -> Path:
    from fpdf import FPDF

    font_reg = "/System/Library/Fonts/Supplemental/Arial.ttf"
    font_bold = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

    class PDF(FPDF):
        def footer(self):
            self.set_y(-12)
            self.set_font("Arial", size=8)
            self.set_text_color(120, 120, 120)
            self.cell(0, 5, f"{self.page_no()}", align="C")

    pdf = PDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_font("Arial", "", font_reg)
    pdf.add_font("Arial", "B", font_bold)
    pdf.add_page()
    pdf.set_margins(16, 14, 16)

    def body(text, size=10.5, bold=False, color=(34, 34, 34), after=3):
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Arial", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(0, size * 0.5, text, align="L")
        pdf.ln(after)

    def h(text):
        if pdf.get_y() > 260:
            pdf.add_page()
        pdf.set_x(pdf.l_margin)
        pdf.set_font("Arial", "B", 12)
        pdf.set_text_color(192, 0, 0)
        pdf.multi_cell(0, 6, text, align="L")
        pdf.ln(2)

    pdf.set_x(pdf.l_margin)
    pdf.set_font("Arial", "B", 18)
    pdf.set_text_color(192, 0, 0)
    pdf.multi_cell(0, 8, "Maksim V.", align="L")
    pdf.set_x(pdf.l_margin)
    pdf.set_font("Arial", "B", 12)
    pdf.set_text_color(34, 34, 34)
    pdf.multi_cell(0, 6, "Senior Python Backend Engineer", align="L")
    pdf.ln(4)

    h("Skills")
    for line in SKILLS[1:]:
        body("• " + line, size=10, after=1)
    pdf.ln(2)
    h("Projects")
    for line in PROJECT_NAMES[1:]:
        body("• " + line, size=10, after=1)
    pdf.ln(2)
    h("Education")
    body("Software of Information Technologies, Software Engineer", size=10, bold=True, after=1)
    body("BSUIR — Faculty of Computer Systems and Networks", size=10, color=(85, 85, 85), after=2)
    body("Languages: Russian, English (conversational, B2+)", size=10, after=3)

    h("Professional summary")
    for line in SUMMARY:
        body(line, size=10, after=2)

    h("Professional experience (projects)")
    for proj in PROJECTS:
        if pdf.get_y() > 230:
            pdf.add_page()
        body(proj["role"], size=11, bold=True, after=1)
        body(f"{proj['from']} — {proj['to']}", size=9.5, color=(85, 85, 85), after=1)
        body(proj["project"], size=10, after=2)
        body("Technologies: " + proj["tech"], size=9, color=(68, 68, 68), after=2)
        body("Responsibilities and achievements", size=10, bold=True, after=1)
        for item in proj["duties"]:
            # keep bullet on one page
            pdf.set_font("Arial", "", 9.5)
            hgt = pdf.multi_cell(0, 4.5, "• " + item, align="L", dry_run=True, output="HEIGHT")
            if pdf.get_y() + hgt > pdf.h - pdf.b_margin:
                pdf.add_page()
            body("• " + item, size=9.5, after=0.8)
        pdf.ln(3)

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    path = DESKTOP_DIR / "Maksim_V_Senior_Python_Backend_Engineer.pdf"
    pdf.output(str(path))
    return path


def fill() -> Path:
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    for stale in DESKTOP_DIR.glob("*"):
        if stale.is_file() and stale.name != ".DS_Store":
            stale.unlink()

    # Internal white-label format (same template/structure as Senior CV.docx).
    doc = Document(str(TEMPLATE))
    apply_english(doc)
    doc.save(str(OUT))
    # Drop Mac-only OOXML part that makes Windows Word show a generic open error.
    _strip_mac_word_parts(Path(OUT))
    shutil.copy2(OUT, DESKTOP_OUT)
    return DESKTOP_OUT


if __name__ == "__main__":
    print(fill())
    print(OUT)
