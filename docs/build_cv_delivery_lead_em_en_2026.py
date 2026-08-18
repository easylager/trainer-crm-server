#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Software Delivery Lead CV — ATS-tuned for Engineering Manager / delivery leadership roles.

Title and section headers avoid Python, Go, Backend, and Engineering Manager labels;
technology keywords live in skills, stacks, and project bullets.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESKTOP = Path.home() / "Desktop" / "CV"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")

BASE = "cv-max-vasilenka-software-delivery-lead-em-en-2026"
DESKTOP_NAME = "Maksim_Vasilenko_Software_Delivery_Lead.pdf"

LOC_BY = "Minsk, Belarus · Remote (worldwide)"
LOC_GE = "Georgia · Remote (worldwide)"
PHONE_BY = "+375 29 667-53-89"
PHONE_GE = "+995 599 255 351"

CSS = """
@page { size: A4; margin: 9.5mm 11mm 9.5mm 11mm; }
:root {
  --ink: #0f172a;
  --body: #1e293b;
  --muted: #64748b;
  --accent: #1d4ed8;
  --line: #e2e8f0;
  --pill-border: #bfdbfe;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
html, body {
  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
  color: var(--body);
  font-size: 8.7pt;
  line-height: 1.32;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  background: #fff;
}
.name {
  font-size: 19.5pt;
  font-weight: 800;
  color: var(--ink);
  letter-spacing: -0.01em;
  line-height: 1.08;
}
.tagline {
  margin-top: 1.3mm;
  font-size: 9.8pt;
  font-weight: 600;
  color: var(--accent);
}
.contacts {
  margin-top: 2mm;
  font-size: 7.9pt;
  color: var(--muted);
  line-height: 1.38;
}
.summary {
  margin-top: 3.2mm;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 2.6mm 3mm;
  font-size: 8.3pt;
}
.summary strong { color: var(--ink); font-weight: 700; }
.skills-ats {
  margin-top: 2.2mm;
  font-size: 7.35pt;
  line-height: 1.36;
}
.skills-ats strong { color: var(--ink); }
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 1.3mm;
  margin-top: 1.9mm;
}
.pill {
  font-size: 7.1pt;
  padding: 0.9mm 2mm;
  border-radius: 999px;
  border: 1px solid var(--pill-border);
  color: var(--accent);
  white-space: nowrap;
}
.pill.gray {
  border-color: #cbd5e1;
  color: var(--muted);
}
.section { margin-top: 3.2mm; }
.section-h {
  font-size: 7.35pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--accent);
  padding-bottom: 1.1mm;
  border-bottom: 1.2px solid var(--accent);
  margin-bottom: 2.1mm;
}
.results {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.1mm 4mm;
}
.results li {
  list-style: none;
  position: relative;
  padding-left: 3mm;
  font-size: 7.95pt;
  margin-bottom: 0.85mm;
}
.results li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.55mm;
  width: 1.25mm;
  height: 1.25mm;
  border-radius: 50%;
  background: var(--accent);
}
.results strong { color: var(--ink); }
.job {
  margin-bottom: 2.5mm;
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
  font-size: 8.95pt;
  font-weight: 800;
  color: var(--ink);
}
.job-dates {
  font-size: 7.35pt;
  color: var(--muted);
  white-space: nowrap;
}
.job-role {
  margin-top: 0.25mm;
  font-size: 7.85pt;
  font-weight: 600;
}
.job-stack {
  margin-top: 0.15mm;
  font-size: 7.15pt;
  color: var(--muted);
  margin-bottom: 0.95mm;
}
.job ul { list-style: none; }
.job li {
  position: relative;
  padding-left: 3mm;
  font-size: 7.85pt;
  margin-bottom: 0.75mm;
}
.job li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.55mm;
  width: 1.15mm;
  height: 1.15mm;
  border-radius: 50%;
  background: var(--body);
}
.job strong { color: var(--ink); }
.stack { width: 100%; border-collapse: collapse; }
.stack td {
  vertical-align: top;
  padding: 0.85mm 0;
  font-size: 7.75pt;
}
.stack td.k {
  width: 30mm;
  font-weight: 700;
  color: var(--ink);
  padding-right: 2.5mm;
}
.edu, .format-line { font-size: 7.85pt; }
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
</html>"""


def header(*, tagline: str, location: str, phone: str) -> str:
    return f"""
<div class="name">Maksim Vasilenka</div>
<div class="tagline">{tagline}</div>
<div class="contacts">
  {location}<br/>
  pinkpanterpython3@gmail.com · {phone}
  · Telegram: @maksimvasilenko11
  · English B2+ (verbal &amp; written)
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
  <div class="section-h">Leadership Highlights</div>
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
  <div class="section-h">Leadership &amp; Organization Skills</div>
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


SKILLS_ATS = (
    "People Management, Team Leadership, Talent Acquisition, Recruitment, Hiring, Onboarding, "
    "Competency Development, Skills Matrix, Personal Development Plans, Coaching, Mentoring, "
    "Performance Feedback, Career Development, Knowledge Management, Learning & Development, "
    "Resource Planning, Capacity Planning, Delivery Management, Client Relationship Management, "
    "Stakeholder Management, Project Scheduling, Prioritization, Risk Management, Issue Resolution, "
    "Agile, Scrum, Kanban, Software Engineering Standards, Technical Governance, Code Review, "
    "Release Management, B2B SaaS, Healthcare, Insurance, Partner Integrations, "
    "Python, Cloud Technologies, AWS, GCP, Azure, Kubernetes, CI/CD, Microservices, Distributed Systems"
)


def build(*, location: str, phone: str, availability: str) -> str:
    tagline = "People Leadership · Delivery · Organization Building"
    doc_title = "Maksim Vasilenka — Software Delivery Lead"

    return page(
        doc_title,
        header(tagline=tagline, location=location, phone=phone)
        + summary_box(
            "<strong>Software delivery leader</strong> with a <strong>7+ year engineering foundation</strong> "
            "(full-stack and backend in Python, React, cloud, and distributed systems) and "
            "<strong>2+ years</strong> growing into people leadership within <strong>Agile</strong> environments "
            "(Scrum/Kanban). Career arc: integrations and health-insurance platforms → architecture and migration "
            "ownership → leading a five-engineer team with hiring, coaching, PDPs, and client delivery accountability. "
            "Experienced in <strong>recruitment, competency building, resource planning</strong>, and engineering "
            "standards across regulated <strong>healthcare and insurance SaaS</strong>."
        )
        + skills_block(
            SKILLS_ATS,
            [
                "Talent Acquisition · Hiring",
                "Competency · PDP · Coaching",
                "Team Leadership · 1:1s",
                "Delivery · Client Management",
                "Agile · Scrum · Kanban",
            ],
            [
                "Resource · Capacity Planning",
                "Knowledge Management · L&D",
                "Engineering Standards · Governance",
                "Stakeholder Communication",
                "Python · Cloud · Kubernetes",
            ],
        )
        + highlights(
            [
                "Progressed from <strong>full-stack and backend engineering</strong> (integrations, health insurance, "
                "insurtech) into <strong>team leadership</strong> on a multi-tenant B2B AI SaaS product.",
                "Currently lead a <strong>five-engineer team</strong> — hiring, interviews, onboarding, 1:1s, PDPs, "
                "and growing the team’s <strong>Python competency</strong>.",
                "Owned architecture and delivery on regulated platforms: Kafka event streams, Kubernetes releases, "
                "multi-tenant isolation, and partner API integrations.",
                "At Qantev, combined hands-on engineering with grooming, migration leadership, and code-review "
                "standards — first clear step toward people and delivery ownership.",
                "Established engineering governance on current product: Agile cadence, CI/CD gates, observability, "
                "and client delivery accountability with executive stakeholders.",
                "Strong client and partner communication track record across B2B insurers and delivery integrations.",
            ]
        )
        + experience(
            job(
                "AI SaaS for Insurance Call Centers (B2B, Multi-tenant)",
                "Software Delivery Lead",
                "01.2025 — Present",
                "Team leadership, hiring, competency building, Agile/Scrum · Python, FastAPI, Django, PostgreSQL, "
                "Redis, GCP, Kubernetes, Docker, CI/CD, OpenAI, Claude, RAG, REST APIs, Observability",
                [
                    "Grew from hands-on engineering into leading a <strong>five-person engineering team</strong> — "
                    "hiring roadmap, role profiles, technical interviews, onboarding, and structured "
                    "<strong>1:1 coaching</strong> with personal development plans for key engineers.",
                    "Build the team’s <strong>Python engineering competency</strong>: skill expectations, "
                    "knowledge-sharing sessions, review standards, mentoring senior/junior pairs, and tracking "
                    "growth through regular feedback.",
                    "Own <strong>resource and delivery planning</strong> with the CEO — translate business priorities "
                    "into sprint backlogs, release schedules, and measurable outcomes for B2B insurance clients.",
                    "Set team-level <strong>engineering governance</strong>: Agile ceremonies, code-review policy, "
                    "CI/CD quality gates, observability, and incident playbooks; unblock engineers and keep delivery "
                    "predictable without becoming a single point of failure.",
                    "Act as delivery owner for client releases — manage expectations, supervise rollout readiness, "
                    "review deliverables, and drive defect resolution with product and operations stakeholders.",
                    "Still hands-on on critical paths when needed: multi-tenant SaaS architecture, realtime event "
                    "pipelines, RAG/LLM workflows with human-in-the-loop controls, and private-cloud deployments "
                    "for regulated workloads.",
                ],
            ),
            job(
                "Qantev — European Health Insurance SaaS",
                "Software Engineer (Backend / Python)",
                "04.2024 — 12.2024",
                "Python, FastAPI, asyncio, Django, PostgreSQL, Kafka, Azure (AKS, Blob, Service Bus), "
                "REST APIs, Microservices, LLM",
                [
                    "Hands-on backend engineer on a new insurance platform — with growing ownership of "
                    "<strong>architecture discussions, grooming, and engineering coordination</strong> alongside IC work.",
                    "Participated in product grooming, technical planning, and demos — translating business "
                    "requirements into delivery plans and helping align engineers with stakeholder expectations.",
                    "Led the <strong>Django → FastAPI migration</strong> stream: service boundaries, async handlers, "
                    "OpenAPI contracts, and code-review standards while keeping production stable.",
                    "Designed and built claims-processing workflows — Kafka status streams, partner webhooks, "
                    "document intelligence, and antifraud signals with mandatory human override.",
                    "Drove integration and defect resolution across partner interchange formats and status-exchange flows.",
                    "Stepped into informal tech-lead responsibilities: mentoring teammates, facilitating review "
                    "quality, and onboarding engineers joining the backend stream — clear progression toward "
                    "people leadership.",
                ],
            ),
            job(
                "Oscar Health — US Health Insurance",
                "Software Engineer (Backend / Python)",
                "01.2022 — 03.2024",
                "Python, Go, Kafka, gRPC, AWS (EKS, RDS, S3), Kubernetes, ArgoCD, Canary Releases, "
                "PostgreSQL, React, Material UI, Microservices",
                [
                    "Designed and built distributed services for eligibility, benefits, and member-management "
                    "workflows on a large digital health-insurance platform.",
                    "Owned Kubernetes deployment on AWS EKS, including <strong>canary releases</strong>, and "
                    "strengthened auditability for sensitive healthcare workflows.",
                    "Built internal operational UIs in <strong>React and Material UI</strong> for business teams "
                    "managing member and benefits workflows.",
                    "Engineered high-throughput <strong>event-driven pipelines</strong> (Kafka) through "
                    "<strong>Open Enrollment</strong> seasonal peaks on regulated member-data paths.",
                    "Contributed to a <strong>Go → Python</strong> migration of critical pipeline stages; "
                    "optimized cross-service gRPC traffic and production hot paths.",
                    "Supported production incidents and partner integrations; worked with healthcare "
                    "eligibility/benefits data formats and interchange standards in restricted network environments.",
                ],
            ),
            job(
                "KitchenHub — Delivery Integrations Platform",
                "Software Engineer (Backend / Full-stack)",
                "01.2020 — 12.2021",
                "Python, FastAPI, asyncio, GCP, Redis, Docker, REST APIs, OpenAPI, "
                "React, TypeScript, Redux, React Router, Material-UI, Webpack, Axios, Partner API Integrations",
                [
                    "Full-stack engineer owning production integrations with Uber Eats, Grubhub, and GloriaFood — "
                    "partner-facing APIs used across restaurant and delivery workflows.",
                    "Built a React authorization microservice for partner integrations "
                    "(TypeScript, Redux, React Router, Material-UI, Webpack, Axios).",
                    "Developed FastAPI backend services: async handlers, Redis caching, Dockerized deploys on GCP, "
                    "and OpenAPI-documented REST contracts.",
                    "Designed resilient distributed workflows — retries, idempotency, saga-style orchestration, "
                    "and mixed sync/async microservice communication across providers.",
                    "Worked directly with external partner engineering teams on API changes, outages, rate limits, "
                    "and integration incidents.",
                    "Defined versioned partner API contracts and engineering data formats (OpenAPI) shared "
                    "across delivery-provider adapters.",
                ],
            ),
        )
        + skills_table(
            [
                (
                    "People & Organization",
                    "Team leadership, 1:1s, coaching, motivation, performance feedback, personal development plans, "
                    "competency building, skills matrix, talent acquisition, recruitment, interviews, onboarding, "
                    "knowledge management, mentoring programs",
                ),
                (
                    "Delivery & Clients",
                    "Resource planning, capacity planning, sprint/backlog prioritization, release management, "
                    "client relationship management, stakeholder alignment, delivery reviews, expectation management, "
                    "issue/defect resolution, risk management",
                ),
                (
                    "Process & Governance",
                    "Agile, Scrum, Kanban, engineering standards, technical governance, code-review culture, "
                    "CI/CD governance, incident response, cross-team coordination",
                ),
                (
                    "Technical Foundation",
                    "7+ years software engineering background; strong familiarity with Python ecosystems, "
                    "cloud platforms (AWS, GCP, Azure), Kubernetes, microservices, and regulated SaaS delivery — "
                    "used to set standards and evaluate team output, not as primary IC focus",
                ),
                (
                    "Domains",
                    "B2B SaaS, healthcare technology, insurance platforms, regulated systems, "
                    "partner integrations, AI-assisted product delivery",
                ),
            ]
        )
        + education_format(
            "Computer Networks and Systems — Software Engineer degree<br/>"
            '<span class="muted">Relevant focus: software engineering, networks, distributed systems</span>',
            availability,
        ),
    )


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
    (DESKTOP / "Lead").mkdir(parents=True, exist_ok=True)
    (DESKTOP / "Lead" / "Georgia").mkdir(parents=True, exist_ok=True)


def main() -> None:
    by_html = ROOT / f"{BASE}.html"
    ge_html = ROOT / f"{BASE}-georgia.html"
    by_pdf = ROOT / f"{BASE}.pdf"
    ge_pdf = ROOT / f"{BASE}-georgia.pdf"

    by_html.write_text(
        build(
            location=LOC_BY,
            phone=PHONE_BY,
            availability="Full-time · Remote · Open to people leadership & software delivery management roles · Open to relocation.",
        ),
        encoding="utf-8",
    )
    ge_html.write_text(
        build(
            location=LOC_GE,
            phone=PHONE_GE,
            availability="Full-time · Remote from Georgia · Open to people leadership & software delivery management roles.",
        ),
        encoding="utf-8",
    )
    print(by_html)
    print(ge_html)

    html_to_pdf(by_html, by_pdf)
    html_to_pdf(ge_html, ge_pdf)
    print(by_pdf)
    print(ge_pdf)

    ensure_desktop_dirs()
    lead_dir = DESKTOP / "Lead"
    ge_dir = lead_dir / "Georgia"
    for path in lead_dir.glob("*.html"):
        path.unlink()
    for path in ge_dir.glob("*.html"):
        path.unlink()

    dest_by = lead_dir / DESKTOP_NAME
    dest_ge = ge_dir / DESKTOP_NAME
    shutil.copy2(by_pdf, dest_by)
    shutil.copy2(ge_pdf, dest_ge)
    print(dest_by)
    print(dest_ge)


if __name__ == "__main__":
    main()
