#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backend Team Lead / Senior Backend CV — healthcare & insurance focus, no location."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESKTOP = Path.home() / "Desktop" / "CV"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

CSS = """
@page { size: A4; margin: 10mm 11mm 10mm 11mm; }
:root {
  --ink: #0f1419;
  --body: #1f2937;
  --muted: #6b7280;
  --teal: #0f766e;
  --line: #e5e7eb;
  --pill-border: #99f6e4;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: var(--body);
  font-size: 8.9pt;
  line-height: 1.33;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  background: #fff;
}
.name {
  font-size: 20pt;
  font-weight: 800;
  color: var(--ink);
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.tagline {
  margin-top: 1.4mm;
  font-size: 10pt;
  font-weight: 600;
  color: var(--teal);
}
.contacts {
  margin-top: 2mm;
  font-size: 8pt;
  color: var(--muted);
  line-height: 1.4;
}
.contacts a { color: var(--muted); text-decoration: none; }
.summary {
  margin-top: 3.5mm;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 2.8mm 3.2mm;
  font-size: 8.5pt;
  color: var(--body);
}
.summary strong { color: var(--ink); font-weight: 700; }
.skills-ats {
  margin-top: 2.4mm;
  font-size: 7.5pt;
  color: var(--body);
  line-height: 1.38;
}
.skills-ats strong { color: var(--ink); }
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 1.4mm;
  margin-top: 2.1mm;
}
.pill {
  font-size: 7.2pt;
  padding: 1mm 2.2mm;
  border-radius: 999px;
  border: 1px solid var(--pill-border);
  color: var(--teal);
  white-space: nowrap;
}
.pill.gray {
  border-color: #d1d5db;
  color: var(--muted);
}
.section { margin-top: 3.6mm; }
.section-h {
  font-size: 7.5pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--teal);
  padding-bottom: 1.2mm;
  border-bottom: 1.2px solid var(--teal);
  margin-bottom: 2.4mm;
}
.results {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.3mm 4.5mm;
}
.results li {
  list-style: none;
  position: relative;
  padding-left: 3.2mm;
  font-size: 8.1pt;
  margin-bottom: 1mm;
}
.results li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.6mm;
  width: 1.3mm;
  height: 1.3mm;
  border-radius: 50%;
  background: var(--teal);
}
.results strong { color: var(--ink); }
.job {
  margin-bottom: 2.8mm;
  break-inside: avoid;
  page-break-inside: avoid;
}
.job-top {
  display: flex;
  justify-content: space-between;
  gap: 4mm;
  align-items: baseline;
}
.job-company {
  font-size: 9.1pt;
  font-weight: 800;
  color: var(--ink);
}
.job-dates {
  font-size: 7.5pt;
  color: var(--muted);
  white-space: nowrap;
}
.job-role {
  margin-top: 0.3mm;
  font-size: 8pt;
  font-weight: 600;
  color: var(--body);
}
.job-stack {
  margin-top: 0.2mm;
  font-size: 7.3pt;
  color: var(--muted);
  margin-bottom: 1.1mm;
}
.job ul { list-style: none; }
.job li {
  position: relative;
  padding-left: 3.2mm;
  font-size: 8pt;
  margin-bottom: 0.85mm;
}
.job li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.6mm;
  width: 1.25mm;
  height: 1.25mm;
  border-radius: 50%;
  background: var(--body);
}
.job strong { color: var(--ink); }
.stack {
  width: 100%;
  border-collapse: collapse;
}
.stack td {
  vertical-align: top;
  padding: 1mm 0;
  font-size: 7.9pt;
}
.stack td.k {
  width: 28mm;
  font-weight: 700;
  color: var(--ink);
  padding-right: 3mm;
}
.stack td.v { color: var(--body); }
.edu, .format-line {
  font-size: 8pt;
  color: var(--body);
}
.edu .muted { color: var(--muted); }
"""


def page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="description" content="{title}" />
<title>{title}</title>
<style>{CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""


PHONE_GE = "+995 599 255 351"


def header(*, phone: str | None = None, tagline: str | None = None) -> str:
    tag = tagline or "Senior Software Engineer · Distributed Systems · Python"
    phone_bit = f"\n  · {phone}" if phone else ""
    return f"""
<div class="name">Maksim Vasilenka</div>
<div class="tagline">{tag}</div>
<div class="contacts">
  pinkpanterpython3@gmail.com{phone_bit}
  · Telegram: @maksimvasilenko11
  · English B2+ (working proficiency)
</div>
"""


def summary_box(html: str) -> str:
    return (
        '<section class="section" style="margin-top:0">'
        '<div class="section-h">Professional Summary</div>'
        f'<div class="summary">{html}</div></section>'
    )


def skills_block(plain: str, primary: list[str], secondary: list[str]) -> str:
    pills = ['<div class="pills">']
    for p in primary:
        pills.append(f'<span class="pill">{p}</span>')
    for p in secondary:
        pills.append(f'<span class="pill gray">{p}</span>')
    pills.append("</div>")
    return f"""
<section class="section">
  <div class="section-h">Core Skills</div>
  <div class="skills-ats"><strong>Skills:</strong> {plain}</div>
  {"".join(pills)}
</section>
"""


def highlights(items: list[str]) -> str:
    lis = "\n".join(f"<li>{x}</li>" for x in items)
    return f"""
<section class="section">
  <div class="section-h">Highlights</div>
  <ul class="results">{lis}</ul>
</section>
"""


def job(company: str, role: str, dates: str, stack: str, bullets: list[str]) -> str:
    lis = "\n".join(f"<li>{b}</li>" for b in bullets)
    return f"""
<article class="job">
  <div class="job-top">
    <div class="job-company">{company}</div>
    <div class="job-dates">{dates}</div>
  </div>
  <div class="job-role">{role}</div>
  <div class="job-stack">{stack}</div>
  <ul>{lis}</ul>
</article>
"""


def experience(*jobs: str) -> str:
    return f"""
<section class="section">
  <div class="section-h">Work Experience</div>
  {"".join(jobs)}
</section>
"""


def skills_table(rows: list[tuple[str, str]]) -> str:
    trs = "\n".join(f'<tr><td class="k">{k}</td><td class="v">{v}</td></tr>' for k, v in rows)
    return f"""
<section class="section">
  <div class="section-h">Technical Skills</div>
  <table class="stack">{trs}</table>
</section>
"""


def education_format(edu: str, fmt: str) -> str:
    return f"""
<section class="section">
  <div class="section-h">Education</div>
  <div class="edu">{edu}</div>
</section>
<section class="section">
  <div class="section-h">Availability</div>
  <div class="format-line">{fmt}</div>
</section>
"""


SKILLS = (
    "Python, FastAPI, asyncio, Django, React, TypeScript, Redux, Material UI, Team Coordination, "
    "Cross-team Collaboration, Mentoring, Code Review, Technical Leadership, Product Ownership, System Design, "
    "Microservices, Event-Driven Architecture, Kafka, PostgreSQL, Redis, Docker, Kubernetes, "
    "CI/CD, Release Management, Distributed Systems, REST APIs, AWS, GCP, Azure, Observability, "
    "Agile, LLM, RAG, OpenAI, Claude, Healthcare Technology, Insurance Platforms, B2B SaaS"
)

# Belarus and Georgia outputs share the same contact block (no phones / no location).


def build(
    *,
    phone: str | None = None,
    drop_senior: bool = False,
) -> str:
    if drop_senior:
        title = "Maksim Vasilenka — Software Engineer (Python)"
        tagline = "Software Engineer · Distributed Systems · Python"
        current_role = "Software Engineer"
        availability = "Full-time · Open to Software Engineer roles · Open to relocation."
    else:
        title = "Maksim Vasilenka — Senior Software Engineer (Python)"
        tagline = "Senior Software Engineer · Distributed Systems · Python"
        current_role = "Senior Software Engineer"
        availability = "Full-time · Open to Senior Software Engineer roles · Open to relocation."

    return page(
        title,
        header(phone=phone, tagline=tagline)
        + summary_box(
            "I help teams build reliable technical solutions by combining strong engineering fundamentals "
            "with architectural thinking, clear communication, and close collaboration with engineers and "
            "business stakeholders. Over the past several years I have worked on "
            "<strong>healthcare, insurance, and AI platforms</strong> where reliability, correctness, and "
            "maintainability are critical. Beyond hands-on backend development, I have taken "
            "<strong>team leadership</strong> and <strong>production ownership</strong> — coordinating "
            "engineering work, owning the path to production (CI/CD, containers, releases, monitoring), "
            "mentoring teammates, and translating business requirements into scalable solutions. Core focus: "
            "<strong>distributed backend systems, FastAPI microservices, Kafka event-driven workflows, "
            "cloud platforms, and AI-powered product capabilities</strong>."
        )
        + skills_block(
            SKILLS,
            [
                "Team Coordination · Mentoring",
                "Cross-team Collaboration · Code Review",
                "CI/CD · Production Ownership",
                "Python · FastAPI · Django",
                "Kafka · Redis · PostgreSQL",
            ],
            [
                "Docker · Kubernetes · Cloud",
                "React · TypeScript · Material UI",
                "Healthcare · Insurance · B2B SaaS",
                "RAG · LLM · OpenAI · Claude",
                "System Design · Architecture",
            ],
        )
        + highlights(
            [
                "Grew into <strong>backend team leadership</strong> for a five-person engineering team on a multi-tenant AI insurance product.",
                "Owned the path to production: containerization, CI/CD, cloud deployment, monitoring, and production troubleshooting.",
                "Shipped customer-facing integrations and partner APIs (KitchenHub) with external engineering/support collaboration.",
                "Built production <strong>Kafka / event-driven</strong> systems at Qantev and Oscar Health under regulated constraints.",
                "Owned Kubernetes releases (incl. canary) and auditability on a US health-insurance platform.",
                "Delivered React UIs (managerial tools + KitchenHub auth microservice) with TypeScript / Redux / Material-UI.",
            ]
        )
        + experience(
            job(
                "AI SaaS for Insurance Call Centers (B2B, Multi-tenant)",
                current_role,
                "01.2025 — Present",
                "Python, FastAPI, asyncio, Django, PostgreSQL, Redis, GCP, Kubernetes, Docker, "
                "CI/CD, OpenAI, Claude, RAG, LLM, REST APIs, Observability",
                [
                    "Progressed from hands-on backend engineering into a technical leadership role, coordinating a "
                    "<strong>five-person engineering team</strong>, conducting interviews, reviewing code, "
                    "unblocking engineers, and working with the CEO on technical direction.",
                    "Worked closely with the CEO and stakeholders on product direction, technical priorities, "
                    "and architectural trade-offs.",
                    "Owned production delivery workflows, including containerization, CI/CD automation, cloud "
                    "deployment, monitoring, and production troubleshooting.",
                    "Designed and developed backend architecture for a realtime AI assistant platform: "
                    "session management, event processing, low-latency workflows, and AI-powered recommendations.",
                    "Built production AI capabilities using <strong>RAG, LLM integrations, and "
                    "human-in-the-loop</strong> workflows for sensitive insurance operations.",
                    "Owned implementation of <strong>full multi-tenant isolation</strong> — beyond database "
                    "boundaries — across auth context, APIs, caches, queues, and storage paths to prevent "
                    "cross-tenant data leakage.",
                    "Delivered <strong>real-time</strong> call-session pipelines (live event/audio intake and "
                    "operator suggestions) under strict latency constraints.",
                    "Deployed platform services into <strong>restricted / private network environments</strong> "
                    "for regulated insurance workloads (VPC isolation, controlled egress, non-public service access).",
                ],
            ),
            job(
                "Qantev — European Health Insurance SaaS",
                "Software Engineer (Backend / Python)",
                "04.2024 — 12.2024",
                "Python, FastAPI, asyncio, Django, PostgreSQL, Kafka, Azure (AKS, Blob, Service Bus), "
                "REST APIs, Microservices, LLM",
                [
                    "Participated in architecture decisions for a new insurance platform — evaluating trade-offs "
                    "and shaping long-term system direction while evolving existing production systems.",
                    "Participated in product grooming sessions, technical planning, and product demos, helping "
                    "translate business requirements into technical solutions.",
                    "Collaborated with stakeholders during platform planning, technical grooming, and product "
                    "demonstrations.",
                    "Led <strong>Django → FastAPI</strong> migration while maintaining production stability and "
                    "improving service boundaries; led code reviews and engineering discussions.",
                    "Built backend workflows for claims processing, document intelligence, and healthcare integrations "
                    "(Kafka status streams, partner webhooks, antifraud signals with human override).",
                    "Worked with insurance claims/document <strong>data formats and partner interchange contracts</strong> "
                    "across integrations and status-exchange flows.",
                    "Built antifraud/AI assistance with <strong>confidence scoring</strong> and mandatory human "
                    "override — treating model outputs as estimates that must defer to operators on high-risk steps.",
                ],
            ),
            job(
                "Oscar Health — US Health Insurance",
                "Software Engineer (Backend / Python)",
                "01.2022 — 03.2024",
                "Python, Go, Kafka, gRPC, AWS (EKS, RDS, S3), Kubernetes, ArgoCD, Canary Releases, "
                "PostgreSQL, React, Material UI, Microservices",
                [
                    "Designed distributed services for eligibility, benefits, and member-management workflows "
                    "on a large digital health insurance platform.",
                    "Owned Kubernetes deployment on AWS EKS, including <strong>canary releases</strong>, and "
                    "strengthened auditability for sensitive healthcare workflows.",
                    "Built managerial-unit UI interfaces in <strong>React and Material UI</strong> for internal "
                    "operational tools used by business teams.",
                    "Worked on high-throughput <strong>event-driven systems</strong> supporting Open Enrollment "
                    "peaks and sensitive healthcare data paths.",
                    "Supported production systems, investigated incidents, and worked across engineering and "
                    "external partners to resolve reliability and integration issues.",
                    "Contributed to a <strong>Go → Python</strong> migration of critical pipeline stages.",
                    "Worked with healthcare eligibility/benefits <strong>data formats and partner interchange "
                    "standards</strong> on regulated member-data paths.",
                    "Operated services in <strong>restricted network environments</strong> typical of regulated "
                    "healthcare platforms (private cluster networking, controlled access paths).",
                ],
            ),
            job(
                "KitchenHub — Delivery Integrations Platform",
                "Software Engineer (Backend / Full-stack)",
                "01.2020 — 12.2021",
                "Python, FastAPI, asyncio, GCP, Redis, Docker, REST APIs, OpenAPI, "
                "React, TypeScript, Redux, React Router, Material-UI, Webpack, Axios, Partner API Integrations",
                [
                    "Owned integrations with Uber Eats, Grubhub, and GloriaFood — shipping partner-facing APIs "
                    "used across restaurant and delivery workflows.",
                    "Built a React frontend microservice for authorization in partner integrations "
                    "(TypeScript, Redux, React Router, Material-UI, Webpack, Axios).",
                    "Worked directly with external partner engineering and support teams to resolve API changes, "
                    "incidents, rate limits, and integration issues.",
                    "Designed distributed workflows to improve consistency across external systems "
                    "(retries, idempotency, orchestration).",
                    "Defined and evolved versioned partner API contracts and <strong>engineering data formats</strong> "
                    "(OpenAPI) used across external delivery providers.",
                    "Implemented <strong>distributed transaction</strong> patterns (saga-style orchestration) and "
                    "mixed <strong>synchronous / asynchronous</strong> microservice communication across partner "
                    "integration services.",
                ],
            ),
        )
        + skills_table(
            [
                ("Languages", "Python (primary), Go (production microservices)"),
                (
                    "Leadership / Product",
                    "Team coordination, cross-team collaboration, mentoring, code review, hiring, product grooming/demos, stakeholder communication",
                ),
                (
                    "Backend",
                    "FastAPI, asyncio, Django/DRF, Pydantic, SQLAlchemy, REST APIs, OpenAPI, microservices",
                ),
                (
                    "Frontend",
                    "React, TypeScript, Redux, React Router, Material UI / Material-UI, Webpack, Axios",
                ),
                (
                    "Architecture",
                    "System design, event-driven systems, distributed systems, API design, production ownership",
                ),
                (
                    "Data / Events",
                    "PostgreSQL, Redis, Kafka, gRPC, GCP Pub/Sub, Azure Service Bus",
                ),
                (
                    "AI / LLM",
                    "RAG, OpenAI, Claude, retrieval pipelines, human-in-the-loop workflows",
                ),
                (
                    "Cloud / DevOps",
                    "AWS, GCP, Azure, Docker, Kubernetes, ArgoCD, canary releases, CI/CD, release management, observability, production support",
                ),
                (
                    "Domains",
                    "Healthcare technology, insurance platforms, regulated systems, B2B SaaS, partner integrations",
                ),
            ]
        )
        + education_format(
            "Computer Networks and Systems — Software Engineer degree<br/>"
            '<span class="muted">Relevant focus: software engineering, networks, systems</span>',
            availability,
        ),
    )



BASE = "cv-max-vasilenka-backend-team-lead-healthcare-en-2026"


def html_to_pdf(html_path: Path, pdf_path: Path) -> None:
    subprocess.run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            html_path.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
    )


def ensure_desktop_dirs() -> None:
    for folder in ("Lead", "Senior", "Health", "Golang"):
        (DESKTOP / folder).mkdir(parents=True, exist_ok=True)
        (DESKTOP / folder / "Georgia").mkdir(parents=True, exist_ok=True)


def clean_html_on_desktop(folder: Path) -> None:
    for path in folder.rglob("*.html"):
        path.unlink()


def copy_pdfs(by_pdf: Path, ge_health_pdf: Path) -> None:
    # Primary fit: Lead + Senior + Health (parent keeps Senior naming)
    mapping = {
        "Lead": "Maksim_Vasilenka_Backend_Tech_Lead_Python.pdf",
        "Senior": "Maksim_Vasilenka_Senior_Software_Engineer_Python.pdf",
        "Health": "Maksim_Vasilenka_Senior_Health_Insurance_Python.pdf",
    }
    for folder, name in mapping.items():
        dest_dir = DESKTOP / folder
        ge_dir = dest_dir / "Georgia"
        clean_html_on_desktop(dest_dir)
        for leftover in dest_dir.glob("*.pdf"):
            leftover.unlink()
        for leftover in ge_dir.glob("*.pdf"):
            leftover.unlink()
        shutil.copy2(by_pdf, dest_dir / name)
        if folder == "Health":
            # Georgia Health: no "Senior" in filename/content + Georgian phone
            ge_name = "Maksim_Vasilenka_Health_Insurance_Python.pdf"
            shutil.copy2(ge_health_pdf, ge_dir / ge_name)
            print(ge_dir / ge_name)
        else:
            shutil.copy2(by_pdf, ge_dir / name)
            print(ge_dir / name)
        print(dest_dir / name)


def main() -> None:
    by_html = ROOT / f"{BASE}.html"
    ge_html = ROOT / f"{BASE}-georgia-health.html"
    by_pdf = ROOT / f"{BASE}.pdf"
    ge_pdf = ROOT / f"{BASE}-georgia-health.pdf"

    html = build()
    ge_html_text = build(phone=PHONE_GE, drop_senior=True)
    by_html.write_text(html, encoding="utf-8")
    ge_html.write_text(ge_html_text, encoding="utf-8")
    print(by_html)
    print(ge_html)

    html_to_pdf(by_html, by_pdf)
    html_to_pdf(ge_html, ge_pdf)
    print(by_pdf)
    print(ge_pdf)

    ensure_desktop_dirs()
    copy_pdfs(by_pdf, ge_pdf)


if __name__ == "__main__":
    main()
