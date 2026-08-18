#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build 3 English CVs — visual style of reference + ATS/HR-optimized wording."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESKTOP = Path.home() / "Desktop" / "CV"

CSS = """
@page { size: A4; margin: 11mm 12mm 11mm 12mm; }
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
  font-size: 9pt;
  line-height: 1.35;
  -webkit-print-color-adjust: exact;
  print-color-adjust: exact;
  background: #fff;
}
.name {
  font-size: 21pt;
  font-weight: 800;
  color: var(--ink);
  letter-spacing: -0.01em;
  line-height: 1.1;
}
.tagline {
  margin-top: 1.5mm;
  font-size: 10.5pt;
  font-weight: 600;
  color: var(--teal);
}
.contacts {
  margin-top: 2.2mm;
  font-size: 8.1pt;
  color: var(--muted);
  line-height: 1.45;
}
.contacts a { color: var(--muted); text-decoration: none; }
.summary {
  margin-top: 4.5mm;
  border: 1px solid var(--line);
  border-radius: 3px;
  padding: 3.2mm 3.5mm;
  font-size: 8.9pt;
  color: var(--body);
}
.summary strong { color: var(--ink); font-weight: 700; }
.skills-ats {
  margin-top: 2.8mm;
  font-size: 7.8pt;
  color: var(--body);
  line-height: 1.4;
}
.skills-ats strong { color: var(--ink); }
.pills {
  display: flex;
  flex-wrap: wrap;
  gap: 1.6mm;
  margin-top: 2.4mm;
}
.pill {
  font-size: 7.4pt;
  padding: 1.1mm 2.4mm;
  border-radius: 999px;
  border: 1px solid var(--pill-border);
  color: var(--teal);
  white-space: nowrap;
}
.pill.gray {
  border-color: #d1d5db;
  color: var(--muted);
}
.section { margin-top: 4.2mm; }
.section-h {
  font-size: 7.7pt;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--teal);
  padding-bottom: 1.4mm;
  border-bottom: 1.2px solid var(--teal);
  margin-bottom: 2.8mm;
}
.results {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.6mm 5mm;
}
.results li {
  list-style: none;
  position: relative;
  padding-left: 3.4mm;
  font-size: 8.5pt;
  margin-bottom: 1.2mm;
}
.results li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.7mm;
  width: 1.4mm;
  height: 1.4mm;
  border-radius: 50%;
  background: var(--teal);
}
.results strong { color: var(--ink); }
.job {
  margin-bottom: 3.2mm;
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
  font-size: 9.4pt;
  font-weight: 800;
  color: var(--ink);
}
.job-dates {
  font-size: 7.7pt;
  color: var(--muted);
  white-space: nowrap;
}
.job-role {
  margin-top: 0.4mm;
  font-size: 8.2pt;
  font-weight: 600;
  color: var(--body);
}
.job-stack {
  margin-top: 0.3mm;
  font-size: 7.5pt;
  color: var(--muted);
  margin-bottom: 1.3mm;
}
.job ul { list-style: none; }
.job li {
  position: relative;
  padding-left: 3.4mm;
  font-size: 8.3pt;
  margin-bottom: 1mm;
}
.job li::before {
  content: "";
  position: absolute;
  left: 0;
  top: 1.7mm;
  width: 1.35mm;
  height: 1.35mm;
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
  padding: 1.2mm 0;
  font-size: 8.2pt;
}
.stack td.k {
  width: 28mm;
  font-weight: 700;
  color: var(--ink);
  padding-right: 3mm;
}
.stack td.v { color: var(--body); }
.edu, .format-line {
  font-size: 8.3pt;
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


def header(tagline: str, location: str = "Minsk, Belarus · Remote (worldwide)", phone: str = "+375 29 667-53-89") -> str:
    return f"""
<div class="name">Maksim Vasilenko</div>
<div class="tagline">{tagline}</div>
<div class="contacts">
  {location}<br/>
  pinkpanterpython3@gmail.com
  · {phone}
  · Telegram: @maksimvasilenko11
  · English B2+ (working proficiency)
</div>
"""


LOC_BY = "Minsk, Belarus · Remote (worldwide)"
LOC_HEALTH_BY = "Minsk, Belarus (B2B Georgia) · Remote (worldwide)"
PHONE_BY = "+375 29 667-53-89"
LOC_GE = "Georgia · Remote (worldwide)"
PHONE_GE = "+995 599 255 351"


def summary_box(html: str) -> str:
    return f'<section class="section" style="margin-top:0"><div class="section-h">Professional Summary</div><div class="summary">{html}</div></section>'


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


# Shared chronology: KitchenHub 01.2020–12.2021 → Oscar → Qantev → AI

SENIOR_SKILLS = (
    "Python, FastAPI, asyncio, Django, Django REST Framework, Flask, REST APIs, Microservices, "
    "Event-Driven Architecture, Kafka, gRPC, PostgreSQL, Redis, SQL, AWS, GCP, Azure, "
    "Docker, Kubernetes, CI/CD, pytest, System Design, Distributed Systems, "
    "API Integration, OpenAPI, Celery, SQLAlchemy, Agile, "
    "LLM, Generative AI, OpenAI, Claude, Anthropic, RAG, Retrieval-Augmented Generation, "
    "Embeddings, Vector Search, pgvector, STT, Prompt Engineering, Guardrails, Human-in-the-Loop"
)

SENIOR = page(
    "Maksim Vasilenko — Senior Software Engineer (Python)",
    header("Senior Software Engineer · Python · Backend · Distributed Systems")
    + summary_box(
        "<strong>Senior Software Engineer</strong> with <strong>6+ years</strong> of Python backend development "
        "for systems where mistakes are expensive: US health insurance platforms, insurtech claims/antifraud, "
        "realtime AI with <strong>RAG</strong> + LLM assistants (OpenAI, Claude), and multi-partner delivery integrations "
        "(<strong>Grubhub, Uber Eats, GloriaFood</strong>). Strong in <strong>REST APIs, microservices, Kafka, "
        "PostgreSQL, AWS/GCP/Azure, Docker, Kubernetes</strong>. Delivers reliable integrations, peak-load readiness, "
        "and production ownership end-to-end."
    )
    + skills_block(
        SENIOR_SKILLS,
        ["Python · FastAPI · asyncio · Django", "RAG · Embeddings · LLM", "OpenAI · Claude", "Kafka · gRPC · REST APIs", "PostgreSQL · pgvector · Redis"],
        ["Microservices · AWS/GCP/Azure", "Kubernetes · Docker · CI/CD", "STT→LLM · Guardrails", "System Design", "pytest · Observability"],
    )
    + highlights(
        [
            "Built production <strong>RAG</strong> for insurance call-center AI: ingest → embeddings → retrieval → grounded LLM answers.",
            "Built and operated <strong>high-stakes backend systems</strong> where wrong status immediately impacts members, restaurants, or claims.",
            "US health insurance: <strong>eligibility / benefits</strong> pipelines through <strong>Open Enrollment</strong> peaks; HIPAA-aware practices.",
            "KitchenHub: production integrations with <strong>Grubhub, Uber Eats, GloriaFood</strong> + partner engineering communication.",
            "Insurtech claims SaaS: <strong>Kafka</strong> status flows, idempotent webhooks, antifraud signals with human override.",
            "Consistently owned <strong>API design, data consistency, CI/CD, and production incidents</strong> across AWS/GCP/Azure.",
        ]
    )
    + experience(
        job(
            "AI SaaS for Insurance Call Centers (B2B)",
            "Senior Software Engineer (Python Backend)",
            "01.2025 — Present",
            "Python, FastAPI, asyncio, Django, PostgreSQL, pgvector, Redis, GCP, Kubernetes, OpenAI, Claude, "
            "RAG, Embeddings, Vector Search, LLM, STT, Prompt Engineering, REST APIs, CI/CD",
            [
                "Owned realtime backend for live insurance calls: event/audio intake, session state, operator suggestions under low latency.",
                "Built production <strong>RAG</strong>: document ingest/chunking, embeddings, vector retrieval (pgvector), grounded LLM answers with source context.",
                "Shipped STT→LLM features (OpenAI, Claude) with guardrails and mandatory human confirmation on high-risk steps.",
                "Separated sync REST APIs from heavy AI/RAG workers via GCP Pub/Sub (retries, back-pressure) to protect call-time performance.",
                "Designed multi-tenant data isolation and access control for B2B insurance clients.",
                "Observability + delivery: correlation IDs, Prometheus/Grafana/Sentry, GitLab CI/CD, Kubernetes releases, pytest on core flows.",
            ],
        ),
        job(
            "Qantev — InsurTech B2B SaaS (Claims & Antifraud)",
            "Software Engineer (Backend / Python)",
            "04.2024 — 12.2024",
            "Python, FastAPI, asyncio, Django, PostgreSQL, Kafka, Airflow, Azure, REST APIs, Microservices, LLM",
            [
                "Built claims backend for document intake, field extraction, and operator review — wrong status directly hurts claim handling.",
                "Implemented antifraud signals and AI assistance with confidence scoring and human override.",
                "Delivered Kafka event streams and idempotent partner webhooks for reliable claim-status delivery.",
                "Ran batch/ETL recompute with Airflow; stored attachments in Azure Blob; async processing via Service Bus / AKS.",
                "Led hands-on parts of live Django → FastAPI migration with zero downtime and clearer service boundaries.",
                "Tuned PostgreSQL/Redis hot paths and covered domain + integration scenarios with pytest.",
            ],
        ),
        job(
            "Oscar Health — US Health Insurance Platform",
            "Software Engineer (Backend / Python)",
            "01.2022 — 03.2024",
            "Python, Golang, Flask, Kafka, gRPC, AWS, Kubernetes, ArgoCD, PostgreSQL, MySQL, Microservices",
            [
                "Developed multi-service eligibility / benefit-availability and member-data sync pipelines on Kafka.",
                "Hardened services for Open Enrollment seasonal peaks; optimized peak pipeline throughput under load.",
                "Maintained high-volume gRPC traffic between microservices; contributed to Golang → Python rewrite of critical stages.",
                "Deployed with Kubernetes/ArgoCD on AWS (EKS, EC2, S3, RDS, IAM, CloudWatch); stable multi-environment releases.",
                "Followed HIPAA-aware practices: least-privilege access, audit trails, observability; supported production incidents.",
                "Automated historical data-fix scripts and vendor integrations without degrading member-facing scenarios.",
            ],
        ),
        job(
            "KitchenHub — Delivery Integrations Platform",
            "Software Engineer (Backend / Python)",
            "01.2020 — 12.2021",
            "Python, FastAPI, asyncio, GCP, Redis, Docker, REST APIs, OpenAPI, Partner API Integrations",
            [
                "Owned production integrations with Grubhub, Uber Eats, and GloriaFood; unified partner APIs into one internal contract.",
                "Communicated with partner engineering/support teams on API changes, outages, rate limits, and contract issues.",
                "Built resilient adapters: retries, rate limiting, idempotency, and graceful degradation on partner failures.",
                "Implemented event-driven flows and saga-style orchestration to keep orders/statuses consistent across providers.",
                "Migrated services from Falcon/Starlette to FastAPI; published OpenAPI contracts for product and adapters.",
                "Ran high-frequency sync/reconciliation on GCP (Cloud Run, Pub/Sub, Datastore, Cloud Scheduler) under API limits.",
            ],
        ),
    )
    + skills_table(
        [
            ("Languages", "Python (primary), Golang (critical pipeline paths)"),
            ("Backend", "FastAPI, asyncio, Django, Django REST Framework, Flask, Pydantic, SQLAlchemy, Alembic, Celery, REST APIs, OpenAPI"),
            (
                "AI / LLM",
                "RAG, embeddings, vector search (pgvector), OpenAI, Claude, STT→LLM, prompt templates, "
                "guardrails, human-in-the-loop, cost/latency control",
            ),
            ("Data", "PostgreSQL, MySQL, Redis, SQL optimization, schema design, idempotent write paths"),
            ("Architecture", "Microservices, event-driven systems, distributed systems, system design"),
            ("Messaging", "Kafka, gRPC, GCP Pub/Sub, Azure Service Bus, Airflow"),
            ("Cloud / DevOps", "AWS (EKS, S3, RDS, IAM, CloudWatch), GCP, Azure, Docker, Kubernetes, ArgoCD, CI/CD"),
            ("Quality", "pytest, code review, Prometheus, Grafana, Sentry, incident response, Agile"),
        ]
    )
    + education_format(
        "Computer Networks and Systems — Software Engineer degree<br/><span class=\"muted\">Relevant focus: software engineering, networks, systems</span>",
        "Remote · Full-time · Open to Senior Software Engineer / Senior Backend Engineer (Python) roles.",
    ),
)


LEAD_SKILLS = (
    "Python, FastAPI, asyncio, Django, Microservices, System Design, Technical Leadership, "
    "Architecture Decision Records (ADR), Mentoring, Code Review, Kafka, PostgreSQL, Redis, "
    "AWS, GCP, Azure, Kubernetes, Docker, CI/CD, REST APIs, Distributed Systems, pytest, Agile, "
    "LLM, Generative AI, OpenAI, Claude, Anthropic, RAG, Retrieval-Augmented Generation, "
    "Embeddings, Vector Search, pgvector, STT, Prompt Engineering, Guardrails, Human-in-the-Loop"
)

TECHLEAD = page(
    "Maksim Vasilenko — Backend Tech Lead (Python)",
    header("Backend Tech Lead · Staff Software Engineer · Python · Regulated SaaS")
    + summary_box(
        "<strong>Backend Tech Lead / Staff Software Engineer</strong> with <strong>6+ years</strong> in Python, "
        "including <strong>2+ years</strong> leading architecture, code review, mentoring, and service boundaries. "
        "Domains: regulated SaaS, InsurTech (<strong>Qantev</strong>), US health insurance (<strong>Oscar Health</strong>), "
        "and multi-partner delivery (<strong>KitchenHub</strong>). Hands-on with <strong>FastAPI, asyncio, Django, Kafka, PostgreSQL, "
        "Redis, Kubernetes, CI/CD</strong>, and production <strong>RAG</strong> + LLM assistants (OpenAI, Claude)."
    )
    + skills_block(
        LEAD_SKILLS,
        ["Tech Lead · Mentoring", "RAG · Embeddings · LLM", "OpenAI · Claude", "FastAPI · asyncio · Django", "System Design · ADR"],
        ["Kafka · PostgreSQL · pgvector", "Kubernetes · CI/CD", "STT→LLM · Guardrails", "Regulated SaaS", "pytest · Observability"],
    )
    + highlights(
        [
            "Led production <strong>RAG</strong> architecture for B2B AI: ingest → embeddings → retrieval → grounded LLM answers.",
            "Led backend for a B2B team of <strong>3–4 engineers</strong>: sprint planning, ADR, review standards, API vs worker split.",
            "Drove live <strong>Django → FastAPI</strong> migration (Qantev): clearer boundaries and fewer production defects.",
            "Shipped production <strong>Kafka</strong> at Qantev and Oscar: idempotent consumers, versioned contracts, peak-load readiness.",
            "KitchenHub: unified partner integration contracts across delivery providers with resilient adapters.",
            "Consistent technical governance: mentoring, cross-team API contracts, incident response, pytest discipline.",
        ]
    )
    + experience(
        job(
            "Corporate AI SaaS Platform (B2B)",
            "Staff Software Engineer / Backend Tech Lead",
            "01.2025 — Present",
            "Python, FastAPI, asyncio, Django, PostgreSQL, pgvector, Redis, GCP, Kubernetes, OpenAI, Claude, "
            "RAG, Embeddings, Vector Search, LLM, STT, System Design, Mentoring, CI/CD",
            [
                "Led backend for 3 engineers: roadmap with product, architecture decisions, ADR, and code-review standards.",
                "Owned production <strong>RAG</strong> design: document ingest/chunking, embeddings, vector retrieval (pgvector), grounded LLM answers.",
                "Defined service boundaries between sync APIs and heavy AI/RAG workers; retry/back-pressure for LLM/STT pipelines.",
                "Shipped LLM assistants (OpenAI, Claude) with human-in-the-loop controls and cost/latency budgets.",
                "Designed multi-tenant authorization and data isolation for B2B customers; correlation IDs and UI read-models.",
                "Raised delivery quality via GitLab CI/CD, Kubernetes releases, Prometheus/Grafana, pytest; mentored on async ownership.",
            ],
        ),
        job(
            "Qantev — International B2B SaaS for Insurers",
            "Software Engineer (Backend / Python)",
            "04.2024 — 12.2024",
            "Python, FastAPI, asyncio, Django, PostgreSQL, Kafka, Azure, Microservices, REST APIs, LLM",
            [
                "Led hands-on Django → FastAPI migration: async handlers, OpenAPI, service extraction — zero downtime.",
                "Built production Kafka flows for document/status events with idempotent consumers and failure budgets.",
                "Delivered versioned partner contracts/webhooks; isolated ML inference workers to reduce blast radius.",
                "Evolved PostgreSQL schemas on critical claims paths; tuned SQL on hot queries.",
                "Aligned API contracts across teams; enforced review standards and pytest coverage for domain logic.",
                "Operated Azure async paths (Service Bus, Blob, AKS) for reliable document processing.",
            ],
        ),
        job(
            "Oscar Health — US Health Insurance Platform",
            "Software Engineer (Backend / Python)",
            "01.2022 — 03.2024",
            "Python, Kafka, gRPC, AWS, Kubernetes, ArgoCD, PostgreSQL, Microservices, Distributed Systems",
            [
                "Owned parts of multi-service eligibility pipeline on Kafka through Open Enrollment peaks.",
                "Kept cross-service status consistency where incorrect eligibility immediately impacts members.",
                "Maintained dense gRPC traffic; contributed to Golang → Python rewrite of critical pipeline stages.",
                "Shipped via Kubernetes/ArgoCD on AWS with observability-first practices in a regulated environment.",
                "Applied least-privilege and audit-friendly practices on sensitive member data paths.",
                "Supported production incidents, data-fix automation, and vendor integrations.",
            ],
        ),
        job(
            "KitchenHub — Delivery Integrations Platform",
            "Software Engineer (Backend / Python)",
            "01.2020 — 12.2021",
            "Python, FastAPI, asyncio, GCP, Redis, Docker, REST APIs, Partner Integrations",
            [
                "Built FastAPI REST layer unifying menus, orders, and statuses across delivery providers.",
                "Owned adapters for Grubhub, Uber Eats, GloriaFood: retries, rate limits, contract normalization.",
                "Coordinated with partner engineering teams on API changes, outages, and integration incidents.",
                "Migrated Falcon/Starlette services to FastAPI for consistency and maintainability.",
                "Implemented high-volume daily sync/reconciliation under partner API constraints on GCP.",
                "Improved reusable adapter patterns through code review and shared SDK work.",
            ],
        ),
    )
    + skills_table(
        [
            ("Leadership", "Tech Lead, mentoring, ADR, code review, cross-team contracts, technical governance, Agile"),
            ("Backend", "Python 3.11+, FastAPI, asyncio, Pydantic, SQLAlchemy, Django/DRF, REST APIs, OpenAPI"),
            (
                "AI / LLM",
                "RAG, embeddings, vector search (pgvector), OpenAI, Claude, STT→LLM, prompt templates, "
                "guardrails, human-in-the-loop, cost/latency control",
            ),
            ("Data / Events", "PostgreSQL, Redis, Kafka, versioned message contracts, async workers, Pub/Sub"),
            ("Architecture", "Microservices, system design, distributed systems, multi-tenant AuthZ"),
            ("Cloud / DevOps", "Docker, Kubernetes, ArgoCD, GitLab CI, AWS, GCP, Azure, Prometheus, Grafana"),
            ("Quality", "pytest, typing, structured logging, health probes, incident response"),
        ]
    )
    + education_format(
        "Computer Networks and Systems — Software Engineer degree",
        "Remote · Full-time · Open to Backend Tech Lead / Staff Software Engineer / Engineering Lead (Python) roles.",
    ),
)


HEALTH_SKILLS = (
    "Python, FastAPI, asyncio, Django, Health Insurance, InsurTech, HIPAA, PHI, Eligibility, Benefits, "
    "Open Enrollment, Claims Processing, Antifraud, Member Data Sync, REST APIs, Microservices, "
    "Kafka, gRPC, PostgreSQL, Redis, AWS, Azure, GCP, Kubernetes, CI/CD, pytest, Healthcare Backend, "
    "LLM, Generative AI, OpenAI, Claude, Anthropic, RAG, Retrieval-Augmented Generation, "
    "Embeddings, Vector Search, pgvector, STT, Prompt Engineering, Guardrails, Human-in-the-Loop"
)

HEALTH = page(
    "Maksim Vasilenko — Senior Software Engineer (Health Insurance / Python)",
    header(
        "Senior Software Engineer · Health Insurance · InsurTech · Python Backend",
        location=LOC_HEALTH_BY,
    )
    + summary_box(
        "<strong>Senior Software Engineer</strong> specializing in <strong>health insurance / InsurTech backends</strong> "
        "with delivery across <strong>Oscar Health</strong> (US regulated member platform), <strong>Qantev</strong> "
        "(claims &amp; antifraud SaaS), and realtime insurance AI with <strong>RAG</strong> + LLM assistants. "
        "Domain exposure beyond backend syntax: "
        "<strong>eligibility, benefits, Open Enrollment peaks, claims lifecycle, antifraud review, PHI/HIPAA-aware handling, "
        "member status sync, and partner status exchange</strong>. Strong Python stack: FastAPI, asyncio, Django, Kafka, AWS/GCP/Azure, Kubernetes."
    )
    + skills_block(
        HEALTH_SKILLS,
        ["Eligibility · Benefits", "Open Enrollment", "Claims · Antifraud", "RAG · LLM for Insurance Ops", "PHI / HIPAA-aware"],
        ["Python · FastAPI · asyncio · Django", "OpenAI · Claude · pgvector", "Kafka · gRPC · REST APIs", "AWS · Azure · GCP · K8s", "STT→LLM · Guardrails"],
    )
    + highlights(
        [
            "Built production <strong>RAG</strong> for insurance call-center ops: embeddings, retrieval, grounded LLM answers with source context.",
            "Oscar Health: multi-service <strong>eligibility / benefit availability</strong> pipelines with member-data sync under load.",
            "Operated through <strong>Open Enrollment</strong> peaks — seasonal traffic where status correctness is non-negotiable.",
            "Qantev: claims intake → review statuses → <strong>antifraud signals</strong> with mandatory human override.",
            "Regulated delivery: least-privilege access, audit trails, PHI-sensitive paths, production incident recovery.",
            "Partner integrations: versioned contracts and idempotent status webhooks across insurer/ops workflows.",
        ]
    )
    + experience(
        job(
            "AI Assistant for Insurance Call Centers (B2B SaaS)",
            "Senior Software Engineer (Python / Insurance Operations)",
            "01.2025 — Present",
            "Python, FastAPI, asyncio, Django, PostgreSQL, pgvector, GCP, Kubernetes, OpenAI, Claude, "
            "RAG, Embeddings, Vector Search, LLM, STT, Healthcare Ops, REST APIs",
            [
                "Built realtime backend supporting insurance operators on live member calls: transcription, intent, next-best actions.",
                "Built production <strong>RAG</strong> for policy/ops knowledge: ingest/chunking, embeddings, vector retrieval (pgvector), grounded answers.",
                "Encoded insurance-ops safety with human-in-the-loop confirmation before high-risk coverage/claims recommendations.",
                "Designed multi-tenant isolation so each insurer/call-center client’s conversation and knowledge data stayed separated.",
                "Separated low-latency call APIs from heavy STT/LLM/RAG stages (Pub/Sub retries/back-pressure) to protect handle time.",
                "Added auditable step statuses, correlation IDs, and latency/failure monitoring for compliance-friendly call tracing.",
            ],
        ),
        job(
            "Qantev — Claims & Antifraud SaaS for Insurers",
            "Software Engineer (Backend / InsurTech)",
            "04.2024 — 12.2024",
            "Python, FastAPI, asyncio, Django, Kafka, Azure, Airflow, Claims Processing, Antifraud, LLM",
            [
                "Implemented claims intake backend: document upload, field extraction, and operator review across claim lifecycle.",
                "Built antifraud scoring/heuristics and AI case assistance with confidence scoring and human override.",
                "Delivered Kafka claim-status events and idempotent partner webhooks for consistent partner state.",
                "Orchestrated document/batch recompute via Airflow; claim attachments in Azure Blob with async processing.",
                "Participated in Django → FastAPI migration on live regulated paths without interrupting claim handling.",
                "Aligned versioned integration contracts with adjacent teams for document/status exchange.",
            ],
        ),
        job(
            "Oscar Health — US Health Insurance Technology Platform",
            "Software Engineer (Backend / Health Insurance)",
            "01.2022 — 03.2024",
            "Python, Kafka, gRPC, AWS, Kubernetes, Eligibility, Benefits, HIPAA-aware systems, Microservices",
            [
                "Developed multi-service pipelines for member eligibility / benefit availability — incorrect status blocks care access.",
                "Synced member/coverage-related data across services with strict status-transition consistency.",
                "Hardened systems for Open Enrollment and plan-year peaks; parallelized hot pipeline stages under seasonal load.",
                "Worked in HIPAA-aware environment: least-privilege access, auditability, observability-first production support.",
                "Maintained dense gRPC service communication and Kafka consumers; contributed to Golang → Python pipeline rewrite.",
                "Supported vendor integrations and automated historical data fixes to reduce operational/compliance risk.",
            ],
        ),
        job(
            "KitchenHub — Multi-Provider Delivery Integrations",
            "Software Engineer (Backend / Python)",
            "01.2020 — 12.2021",
            "Python, FastAPI, asyncio, GCP, Redis, Partner API Integrations, Event-Driven Systems",
            [
                "Owned multi-partner order/status integrations where lost/duplicated state is immediately costly (same failure class as coverage status sync).",
                "Normalized Grubhub / Uber Eats / GloriaFood APIs into one internal contract with retries, rate limits, and idempotency.",
                "Communicated with partner engineering teams on outages, contract drift, and production incidents.",
                "Built saga-style orchestration to keep order lifecycle consistent across unreliable external systems.",
                "Migrated services to FastAPI; high-frequency reconciliation jobs on GCP under external API constraints.",
                "Strengthened reusable adapter patterns for long-lived partner integrations.",
            ],
        ),
    )
    + skills_table(
        [
            ("Insurance domain", "Eligibility, benefits, Open Enrollment, claims intake/review, antifraud, member status sync, call-center ops, partner status exchange"),
            ("Compliance", "HIPAA-aware / PHI-sensitive handling, least privilege, audit trails, human override on risky automation"),
            ("Backend", "Python, FastAPI, asyncio, Django/DRF, Flask, REST APIs, OpenAPI, SQLAlchemy, Celery"),
            (
                "AI for ops",
                "RAG, embeddings, vector search (pgvector), OpenAI, Claude, STT→LLM, guardrails, "
                "human-in-the-loop, cost/latency control for insurance operator workflows",
            ),
            ("Data / Events", "Kafka, gRPC, Pub/Sub, Service Bus, Airflow, PostgreSQL, Redis, idempotent consumers"),
            ("Cloud", "AWS (EKS, RDS, S3), Azure (AKS, Blob, Service Bus), GCP, Kubernetes, ArgoCD, CI/CD"),
        ]
    )
    + education_format(
        "Computer Networks and Systems — Software Engineer degree",
        "Remote · Full-time · Strongest fit for Senior Software Engineer roles in Health Insurance / InsurTech / Healthcare Backend.",
    ),
)


GOLANG_SKILLS = (
    "Python, Go, FastAPI, asyncio, Django, REST APIs, Microservices, gRPC, Kafka, "
    "PostgreSQL, Redis, AWS, Kubernetes, Docker, CI/CD, System Design, Distributed Systems, "
    "Concurrency, SQL, pytest, Agile, Event-Driven Architecture, "
    "LLM, Generative AI, OpenAI, Claude, Anthropic, RAG, Retrieval-Augmented Generation, "
    "Embeddings, Vector Search, pgvector, STT, Prompt Engineering, Guardrails, Human-in-the-Loop"
)

GOLANG = page(
    "Maksim Vasilenko — Senior Backend Engineer",
    header("Senior Backend Engineer · Python · Go")
    + summary_box(
        "<strong>Senior Backend Engineer</strong> with <strong>6+ years</strong> building backend systems — "
        "<strong>Senior-level Python</strong> and solid <strong>production Go</strong> (middle level). "
        "Strongest combo: Python services/APIs (FastAPI, asyncio, Django) plus Go microservices for high-throughput pipelines. "
        "Domains: US health insurance (<strong>Oscar Health</strong> — Go as primary language), InsurTech claims/antifraud, "
        "realtime AI with <strong>RAG</strong> + LLM assistants (OpenAI, Claude), and multi-partner delivery integrations. "
        "Comfortable with Kafka, gRPC, PostgreSQL, AWS, Kubernetes."
    )
    + skills_block(
        GOLANG_SKILLS,
        ["Python (Senior)", "Go (Middle)", "RAG · Embeddings · LLM", "OpenAI · Claude", "FastAPI · asyncio · Django"],
        ["gRPC · Kafka · Microservices", "AWS · Kubernetes · Docker", "PostgreSQL · pgvector · Redis", "STT→LLM · Guardrails", "CI/CD · pytest"],
    )
    + highlights(
        [
            "Built production <strong>RAG</strong> for insurance call-center AI: ingest → embeddings → retrieval → grounded LLM answers.",
            "Production <strong>Go</strong> at Oscar Health on eligibility/member-data microservices (Kafka, gRPC, AWS/K8s).",
            "<strong>Senior Python</strong> delivery across InsurTech, realtime AI, and partner-integration platforms.",
            "KitchenHub: production integrations with <strong>Grubhub, Uber Eats, GloriaFood</strong> + partner-team communication.",
            "Event-driven consistency: idempotent consumers, retries, versioned contracts across Python and Go services.",
            "End-to-end ownership: API design, peak-load readiness, CI/CD, observability, production incidents.",
        ]
    )
    + experience(
        job(
            "AI SaaS for Insurance Call Centers (B2B)",
            "Senior Backend Engineer",
            "01.2025 — Present",
            "Python, FastAPI, asyncio, Django, PostgreSQL, pgvector, Redis, GCP, Kubernetes, OpenAI, Claude, "
            "RAG, Embeddings, Vector Search, LLM, STT, Prompt Engineering, REST APIs, CI/CD",
            [
                "Owned realtime Python backend for live insurance calls: event/audio intake, session state, operator suggestions.",
                "Built production <strong>RAG</strong>: document ingest/chunking, embeddings, vector retrieval (pgvector), grounded LLM answers with source context.",
                "Shipped STT→LLM features (OpenAI, Claude) with prompt templates, guardrails, and human confirmation on high-risk steps.",
                "Separated sync REST APIs from heavy AI/RAG workers via GCP Pub/Sub (retries, back-pressure) for stable latency.",
                "Designed multi-tenant data isolation and access control for B2B insurance clients.",
                "Observability + delivery: correlation IDs, Prometheus/Grafana/Sentry, GitLab CI/CD, Kubernetes releases, pytest on core flows.",
            ],
        ),
        job(
            "Qantev — InsurTech B2B SaaS (Claims & Antifraud)",
            "Senior Backend Engineer (Python)",
            "04.2024 — 12.2024",
            "Python, FastAPI, asyncio, Django, PostgreSQL, Kafka, Airflow, Azure, REST APIs, Microservices, LLM",
            [
                "Built Python claims backend for document intake, field extraction, and operator review statuses.",
                "Implemented antifraud signals and AI assistance with confidence scoring and human-in-the-loop override.",
                "Delivered Kafka event streams and idempotent partner webhooks for reliable claim-status delivery.",
                "Ran batch/ETL recompute with Airflow; attachments in Azure Blob; async work via Service Bus / AKS.",
                "Led hands-on Django → FastAPI migration with zero downtime and clearer service boundaries.",
                "Tuned PostgreSQL/Redis hot paths; covered domain and integration scenarios with pytest.",
            ],
        ),
        job(
            "Oscar Health — US Health Insurance Platform",
            "Backend Engineer",
            "01.2022 — 03.2024",
            "Go, gRPC, Kafka, AWS, Kubernetes, ArgoCD, PostgreSQL, MySQL, Python, Microservices",
            [
                "Developed and operated eligibility / benefit-availability microservices in <strong>Go</strong> on Kafka.",
                "Built and maintained high-volume <strong>gRPC</strong> services in Go for cross-service member/status exchange.",
                "Used Go concurrency to sustain Open Enrollment peak pipeline load.",
                "Owned containerized Go service delivery on AWS EKS via Kubernetes/ArgoCD; CI/CD and Artifactory artifacts.",
                "Applied HIPAA-aware practices on sensitive member data paths; observability with Prometheus/Grafana; incident support.",
                "Used Python for operational tooling, data-fix automation, and selected pipeline stages alongside Go services.",
            ],
        ),
        job(
            "KitchenHub — Delivery Integrations Platform",
            "Backend Engineer (Python)",
            "01.2020 — 12.2021",
            "Python, FastAPI, asyncio, GCP, Redis, Docker, REST APIs, OpenAPI, Partner API Integrations",
            [
                "Owned production integrations with Grubhub, Uber Eats, and GloriaFood; unified partner APIs into one internal contract.",
                "Communicated with partner engineering/support teams on API changes, outages, rate limits, and contract issues.",
                "Built resilient adapters: retries, rate limiting, idempotency, and graceful degradation on partner failures.",
                "Implemented event-driven flows and saga-style orchestration for order/status consistency across providers.",
                "Migrated services from Falcon/Starlette to FastAPI; published OpenAPI contracts for product and adapters.",
                "Ran high-frequency sync/reconciliation on GCP (Cloud Run, Pub/Sub, Datastore, Cloud Scheduler) under API limits.",
            ],
        ),
    )
    + skills_table(
        [
            ("Languages", "Python (Senior) · Go (Middle, production at Oscar Health)"),
            ("Go stack", "Go services, gRPC, Kafka consumers/producers, concurrency for peak load, PostgreSQL/MySQL, Kubernetes"),
            ("Python stack", "FastAPI, asyncio, Django/DRF, Flask, Pydantic, SQLAlchemy, Celery, REST APIs, OpenAPI, pytest"),
            (
                "AI / LLM",
                "RAG, embeddings, vector search (pgvector), OpenAI, Claude, STT→LLM, prompt templates, "
                "guardrails, human-in-the-loop, cost/latency control",
            ),
            ("Architecture", "Microservices, event-driven systems, distributed systems, system design"),
            ("Data / Messaging", "PostgreSQL, Redis, Kafka, gRPC, GCP Pub/Sub, Azure Service Bus"),
            ("Cloud / DevOps", "AWS (EKS, S3, RDS), GCP, Azure, Docker, Kubernetes, ArgoCD, CI/CD"),
            ("Quality", "pytest, code review, Prometheus, Grafana, Sentry, incident response, Agile"),
        ]
    )
    + education_format(
        "Computer Networks and Systems — Software Engineer degree",
        "Remote · Full-time · Open to Senior Backend Engineer roles (Python + Go).",
    ),
)


OUTPUTS = {
    "senior": {
        "html": "cv-max-vasilenko-senior-python-en-2026.html",
        "pdf": "cv-max-vasilenko-senior-python-en-2026.pdf",
        "desktop_dir": "Senior",
        "desktop_name": "Maksim_Vasilenko_Senior_Software_Engineer_Python.pdf",
        "ge_html": "cv-max-vasilenko-senior-python-en-2026-georgia.html",
        "ge_pdf": "cv-max-vasilenko-senior-python-en-2026-georgia.pdf",
        "ge_desktop_name": "Maksim_Vasilenko_Senior_Software_Engineer_Python.pdf",
    },
    "lead": {
        "html": "cv-max-vasilenko-techlead-python-en-2026.html",
        "pdf": "cv-max-vasilenko-techlead-python-en-2026.pdf",
        "desktop_dir": "Lead",
        "desktop_name": "Maksim_Vasilenko_Backend_Tech_Lead_Python.pdf",
        "ge_html": "cv-max-vasilenko-techlead-python-en-2026-georgia.html",
        "ge_pdf": "cv-max-vasilenko-techlead-python-en-2026-georgia.pdf",
        "ge_desktop_name": "Maksim_Vasilenko_Backend_Tech_Lead_Python.pdf",
    },
    "health": {
        "html": "cv-max-vasilenko-health-insurance-en-2026.html",
        "pdf": "cv-max-vasilenko-health-insurance-en-2026.pdf",
        "desktop_dir": "Health",
        "desktop_name": "Maksim_Vasilenko_Senior_Health_Insurance_Python.pdf",
        "ge_html": "cv-max-vasilenko-health-insurance-en-2026-georgia.html",
        "ge_pdf": "cv-max-vasilenko-health-insurance-en-2026-georgia.pdf",
        "ge_desktop_name": "Maksim_Vasilenko_Senior_Health_Insurance_Python.pdf",
    },
    "golang": {
        "html": "cv-max-vasilenko-senior-backend-python-go-en-2026.html",
        "pdf": "cv-max-vasilenko-senior-backend-python-go-en-2026.pdf",
        "desktop_dir": "Golang",
        "desktop_name": "Maksim_Vasilenko_Senior_Backend_Engineer_Python_Go.pdf",
        "ge_html": "cv-max-vasilenko-senior-backend-python-go-en-2026-georgia.html",
        "ge_pdf": "cv-max-vasilenko-senior-backend-python-go-en-2026-georgia.pdf",
        "ge_desktop_name": "Maksim_Vasilenko_Senior_Backend_Engineer_Python_Go.pdf",
    },
}


def to_georgia(html: str) -> str:
    return (
        html.replace(LOC_HEALTH_BY, LOC_GE)
        .replace(LOC_BY, LOC_GE)
        .replace(PHONE_BY, PHONE_GE)
        .replace("Minsk, Belarus", "Georgia")
    )


def main() -> None:
    contents = {
        "senior": SENIOR,
        "lead": TECHLEAD,
        "health": HEALTH,
        "golang": GOLANG,
    }
    for key, html in contents.items():
        meta = OUTPUTS[key]
        by_path = ROOT / meta["html"]
        by_path.write_text(html, encoding="utf-8")
        print(by_path)
        ge_path = ROOT / meta["ge_html"]
        ge_path.write_text(to_georgia(html), encoding="utf-8")
        print(ge_path)


if __name__ == "__main__":
    main()