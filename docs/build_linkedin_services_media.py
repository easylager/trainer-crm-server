#!/usr/bin/env python3
"""Generate LinkedIn "Services provided" media: capability sheet + case cards.

Content is restricted to facts already present in the CV and in the public
PulseBridge repository. No client names, no invented metrics.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "linkedin-services"

INK = "#12212b"
MUTED = "#5b6b76"
ACCENT = "#0f766e"
ACCENT_SOFT = "#e6f2f0"
LINE = "#d8e0e3"

BASE_CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  color: {INK};
  background: #ffffff;
  -webkit-font-smoothing: antialiased;
}}
.muted {{ color: {MUTED}; }}
.accent {{ color: {ACCENT}; }}
strong {{ font-weight: 700; }}
.rule {{ height: 3px; width: 64px; background: {ACCENT}; border-radius: 2px; }}
.pill {{
  display: inline-block;
  padding: 6px 14px;
  border: 1px solid {LINE};
  border-radius: 999px;
  font-size: 15px;
  color: {INK};
  background: #fbfdfd;
}}
.pill-accent {{
  background: {ACCENT_SOFT};
  border-color: {ACCENT_SOFT};
  color: {ACCENT};
  font-weight: 600;
}}
"""

CARD_CSS = f"""
{BASE_CSS}
.card {{
  width: 1600px;
  height: 900px;
  padding: 72px 80px;
  display: flex;
  flex-direction: column;
  position: relative;
}}
.card::after {{
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 10px;
  background: {ACCENT};
}}
.kicker {{
  font-size: 20px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: {ACCENT};
  font-weight: 700;
}}
h1 {{ font-size: 54px; line-height: 1.1; margin-top: 14px; font-weight: 800; }}
.sub {{ font-size: 24px; color: {MUTED}; margin-top: 14px; max-width: 1180px; line-height: 1.45; }}
.flow {{
  display: flex;
  align-items: stretch;
  gap: 18px;
  margin-top: 46px;
}}
.node {{
  flex: 1;
  border: 2px solid {LINE};
  border-radius: 16px;
  padding: 22px 20px;
  background: #fbfdfd;
}}
.node .n-title {{ font-size: 22px; font-weight: 700; }}
.node .n-body {{ font-size: 17px; color: {MUTED}; margin-top: 10px; line-height: 1.45; }}
.node.hl {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
.node.hl .n-body {{ color: #24564f; }}
.arrow {{
  align-self: center;
  font-size: 30px;
  color: {ACCENT};
  font-weight: 700;
}}
.bullets {{
  margin-top: 46px;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px 44px;
}}
.bullet {{ font-size: 21px; line-height: 1.45; padding-left: 26px; position: relative; }}
.bullet::before {{
  content: "";
  position: absolute;
  left: 0; top: 11px;
  width: 10px; height: 10px;
  border-radius: 3px;
  background: {ACCENT};
}}
.foot {{
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 19px;
  color: {MUTED};
  border-top: 1px solid {LINE};
  padding-top: 22px;
}}
.stack {{ display: flex; gap: 10px; flex-wrap: wrap; }}
"""


def card_html(kicker: str, title: str, sub: str, nodes: list[tuple[str, str, bool]],
              bullets: list[str], stack: list[str], foot_right: str) -> str:
    flow_parts: list[str] = []
    for i, (n_title, n_body, hl) in enumerate(nodes):
        if i:
            flow_parts.append('<div class="arrow">&rarr;</div>')
        cls = "node hl" if hl else "node"
        flow_parts.append(
            f'<div class="{cls}"><div class="n-title">{n_title}</div>'
            f'<div class="n-body">{n_body}</div></div>'
        )
    bullets_html = "".join(f'<div class="bullet">{b}</div>' for b in bullets)
    stack_html = "".join(f'<span class="pill">{s}</span>' for s in stack)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{CARD_CSS}</style></head>
<body><div class="card">
  <div class="kicker">{kicker}</div>
  <h1>{title}</h1>
  <div class="sub">{sub}</div>
  <div class="flow">{''.join(flow_parts)}</div>
  <div class="bullets">{bullets_html}</div>
  <div class="foot">
    <div class="stack">{stack_html}</div>
    <div>{foot_right}</div>
  </div>
</div></body></html>"""


SHEET_CSS = f"""
{BASE_CSS}
@page {{ size: A4; margin: 0; }}
.page {{
  width: 210mm;
  height: 297mm;
  padding: 13mm 14mm 10mm;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}}
.head h1 {{ font-size: 26px; font-weight: 800; }}
.head .role {{ font-size: 14px; color: {ACCENT}; font-weight: 700; margin-top: 3px; }}
.head .contact {{ font-size: 10.5px; color: {MUTED}; margin-top: 6px; line-height: 1.5; }}
.intro {{
  margin-top: 10px;
  background: {ACCENT_SOFT};
  border-radius: 8px;
  padding: 10px 12px;
  font-size: 11.2px;
  line-height: 1.5;
}}
h2 {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1.3px;
  color: {ACCENT};
  margin-top: 12px;
  margin-bottom: 6px;
  font-weight: 800;
}}
.grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 7px 14px; }}
.svc {{ border: 1px solid {LINE}; border-radius: 8px; padding: 8px 10px; }}
.svc .t {{ font-size: 11.5px; font-weight: 700; }}
.svc .d {{ font-size: 10px; color: {MUTED}; margin-top: 3px; line-height: 1.42; }}
ul {{ list-style: none; }}
li {{
  font-size: 10.6px;
  line-height: 1.45;
  padding-left: 13px;
  position: relative;
  margin-bottom: 4px;
}}
li::before {{
  content: "";
  position: absolute;
  left: 0; top: 5.5px;
  width: 5px; height: 5px;
  border-radius: 2px;
  background: {ACCENT};
}}
.stackrow {{ display: flex; gap: 5px; flex-wrap: wrap; margin-top: 2px; }}
.stackrow .pill {{ font-size: 10px; padding: 3px 8px; }}
.foot {{
  margin-top: auto;
  border-top: 1px solid {LINE};
  padding-top: 8px;
  font-size: 10px;
  color: {MUTED};
  display: flex;
  justify-content: space-between;
}}
"""

SERVICES = [
    (
        "Backend architecture &amp; APIs",
        "REST services on FastAPI and Django/DRF, async processing, service boundaries, "
        "OpenAPI contracts, migrations on live systems without downtime.",
    ),
    (
        "AI agents, RAG &amp; LLM integration",
        "Multi-step agent workflows with tool calls, retrieval over your documents "
        "(embeddings, pgvector), guardrails and human-in-the-loop on risky steps.",
    ),
    (
        "Distributed &amp; event-driven systems",
        "Kafka, Redis Streams, Pub/Sub, Service Bus: idempotent consumers, retries, "
        "back-pressure, versioned contracts between services.",
    ),
    (
        "External API integrations",
        "Partner and vendor integrations with rate limits, retries, reconciliation "
        "and graceful degradation when the other side fails.",
    ),
    (
        "Cloud, delivery &amp; observability",
        "Docker, Kubernetes, GitLab CI/CD and GitHub Actions on AWS, GCP and Azure; "
        "Prometheus, Grafana and Sentry wired into the flows that matter.",
    ),
    (
        "Technical consulting &amp; review",
        "Architecture review, trade-off analysis (quality vs cost vs latency), "
        "code review standards, ADRs and onboarding documentation.",
    ),
]

EXPERIENCE = [
    "<strong>Realtime AI assistant (B2B SaaS, insurance call centers)</strong> — agent workflows with tools "
    "and session context, production RAG (ingest, embeddings, pgvector retrieval), STT&rarr;LLM pipelines with "
    "guardrails, multi-tenant isolation, GCP Pub/Sub workers and Kubernetes delivery.",
    "<strong>Claims &amp; antifraud SaaS (international, B2B)</strong> — document intake and review backend, "
    "antifraud signals with human override, Kafka status events, idempotent partner webhooks, "
    "Airflow batch/ETL, live Django&rarr;FastAPI migration.",
    "<strong>US health insurance platform (regulated, high load)</strong> — multi-service eligibility and "
    "member-data pipelines on Kafka and gRPC, seasonal peak readiness, AWS EKS with ArgoCD, "
    "least-privilege and audit-friendly practices, production incident support.",
    "<strong>Delivery integrations platform</strong> — one internal contract over several partner APIs, "
    "saga-style order/status consistency, retries, rate limits, idempotency, GCP reconciliation jobs.",
]


def sheet_html() -> str:
    svc = "".join(
        f'<div class="svc"><div class="t">{t}</div><div class="d">{d}</div></div>'
        for t, d in SERVICES
    )
    exp = "".join(f"<li>{x}</li>" for x in EXPERIENCE)
    stack = [
        "Python", "FastAPI", "asyncio", "Django / DRF", "PostgreSQL", "pgvector", "Redis",
        "Kafka", "gRPC", "Airflow", "OpenAI", "Claude", "RAG", "Docker", "Kubernetes",
        "AWS", "GCP", "Azure", "Go", "pytest", "Prometheus", "Grafana", "Sentry",
    ]
    stack_html = "".join(f'<span class="pill">{s}</span>' for s in stack)
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><style>{SHEET_CSS}</style></head>
<body><div class="page">
  <div class="head">
    <h1>Maksim Vasilenka</h1>
    <div class="role">Senior Python Engineer &middot; Backend &amp; AI Systems</div>
    <div class="contact">
      Remote (worldwide) &middot; pinkpanterpython3@gmail.com &middot; Telegram: @maksimvasilenko11<br/>
      Public code: github.com/easylager/pulsebridge
    </div>
  </div>

  <div class="intro">
    I build reliable Python backend systems that are designed for production, not just demos.
    Six-plus years across regulated health insurance platforms, insurtech claims and antifraud,
    realtime AI assistants and multi-partner integrations &mdash; the kind of systems where a wrong
    status or a hallucinated answer costs real money.
  </div>

  <h2>Services</h2>
  <div class="grid2">{svc}</div>

  <h2>Selected production work</h2>
  <ul>{exp}</ul>

  <h2>Core stack</h2>
  <div class="stackrow">{stack_html}</div>

  <h2>How I work</h2>
  <ul>
    <li>Start from failure modes: what breaks, who notices, and how the system degrades safely.</li>
    <li>Correctness first on money, status and compliance paths &mdash; idempotency, audit trails, retries.</li>
    <li>Explicit trade-offs between quality, cost, latency and long-term maintenance cost.</li>
    <li>Observability and tests shipped with the feature, not bolted on after the first incident.</li>
  </ul>

  <div class="foot">
    <div>Available for backend development, technical consulting and AI integration projects.</div>
    <div>Remote &middot; EU / US time zones</div>
  </div>
</div></body></html>"""


CARDS = {
    "01-ai-agents-rag": card_html(
        kicker="Service · AI agents, RAG &amp; LLM integration",
        title="Grounded AI assistants that operators can trust",
        sub="Production pattern I ship: retrieval over your own documents, multi-step agent workflows with "
            "tool calls, and a human confirmation step before anything risky is executed.",
        nodes=[
            ("Documents", "Ingest &amp; chunking of policies, manuals, internal knowledge", False),
            ("Embeddings", "Vector index in PostgreSQL / pgvector", False),
            ("Retrieval", "Top-k context with source references", True),
            ("Agent + LLM", "Tool calls, session memory, multi-step workflow", True),
            ("Human-in-the-loop", "Confirmation on high-risk steps, full audit trail", False),
        ],
        bullets=[
            "Grounded answers with sources instead of free-form model output",
            "Guardrails and fallbacks so a model failure never breaks the flow",
            "Sync API separated from heavy AI work via queues with retries and back-pressure",
            "Cost and latency budgets per call, measured and monitored",
            "Multi-tenant isolation of knowledge bases and conversation data",
            "Correlation IDs and auditable step statuses for every request",
        ],
        stack=["Python", "FastAPI", "asyncio", "OpenAI", "Claude", "pgvector", "PostgreSQL", "Redis", "GCP Pub/Sub", "Kubernetes"],
        foot_right="Shipped in production &middot; B2B insurance SaaS",
    ),
    "02-backend-architecture": card_html(
        kicker="Service · Backend architecture &amp; APIs",
        title="Async Python services built for real traffic",
        sub="FastAPI and Django/DRF services with clear boundaries, async I/O where it actually helps, "
            "and migrations performed on live systems without downtime.",
        nodes=[
            ("API layer", "FastAPI, OpenAPI contracts, validation with Pydantic", True),
            ("Domain", "Use cases isolated from frameworks and vendors", False),
            ("Adapters", "PostgreSQL, Redis, external APIs behind ports", False),
            ("Workers", "Async and background processing off the request path", True),
        ],
        bullets=[
            "Hexagonal boundaries so vendors and databases stay replaceable",
            "Idempotent write paths on money, status and compliance flows",
            "Django &rarr; FastAPI migration executed on a live product",
            "SQL and schema tuning on hot paths, cached read models in Redis",
            "pytest coverage on domain and integration scenarios",
            "CI/CD, containerised releases and health probes from day one",
        ],
        stack=["Python", "FastAPI", "Django / DRF", "Pydantic", "SQLAlchemy", "PostgreSQL", "Redis", "pytest", "Docker", "GitLab CI"],
        foot_right="6+ years &middot; regulated and high-load products",
    ),
    "03-event-driven": card_html(
        kicker="Service · Distributed &amp; event-driven systems",
        title="Events that stay consistent when things fail",
        sub="Kafka, Redis Streams and Pub/Sub pipelines with idempotent consumers, retries and "
            "back-pressure &mdash; so partner outages and peaks degrade instead of corrupting state.",
        nodes=[
            ("Producers", "Services emitting versioned domain events", False),
            ("Broker", "Kafka &middot; Redis Streams &middot; Pub/Sub", True),
            ("Consumers", "Consumer groups, bounded concurrency, ACK on success", True),
            ("Delivery", "Idempotent webhooks and reconciliation jobs", False),
        ],
        bullets=[
            "Idempotency keys and dedupe so retries never double-charge or double-book",
            "Back-pressure and bounded workers instead of unbounded queues",
            "Versioned message contracts agreed across teams",
            "Saga-style orchestration for multi-step order and claim lifecycles",
            "Seasonal peak readiness on regulated platforms",
            "Prometheus metrics and alerting on lag, retries and failures",
        ],
        stack=["Kafka", "Redis Streams", "GCP Pub/Sub", "Azure Service Bus", "gRPC", "Airflow", "Go", "Prometheus", "Grafana"],
        foot_right="Public reference code &middot; github.com/easylager/pulsebridge",
    ),
    "04-integrations": card_html(
        kicker="Service · External API integrations",
        title="Third-party APIs that stop being your weakest link",
        sub="Partner integrations normalised into one internal contract, with retries, rate limits and "
            "reconciliation &mdash; built across delivery marketplaces, insurers and cloud vendors.",
        nodes=[
            ("Partner APIs", "Different auth, formats, limits and failure modes", False),
            ("Adapters", "Retries, rate limiting, timeouts, circuit-breaking", True),
            ("Internal contract", "One normalised model for the whole product", True),
            ("Reconciliation", "Scheduled sync and drift detection", False),
        ],
        bullets=[
            "One internal contract instead of per-partner branching across the codebase",
            "Graceful degradation when a partner is slow, rate-limited or down",
            "High-frequency sync and status reconciliation under external API limits",
            "Versioned contracts and idempotent webhook delivery to partners",
            "Direct communication with partner engineering teams on incidents",
            "Documented integration contracts and support runbooks",
        ],
        stack=["Python", "asyncio", "httpx", "FastAPI", "OpenAPI", "Redis", "GCP Cloud Run", "Sentry"],
        foot_right="Delivery marketplaces &middot; insurers &middot; payment flows",
    ),
    "05-open-source": card_html(
        kicker="Public code · Open engineering showcase",
        title="PulseBridge — async event bridge you can audit",
        sub="A public reference implementation of the patterns above: Python asyncio gateway, Go worker pool, "
            "Redis Streams, idempotency, rate limiting, metrics, ADRs and a readable commit history.",
        nodes=[
            ("HTTP clients", "POST /v1/events", False),
            ("Gateway (Python)", "FastAPI, asyncio, token bucket, idempotency", True),
            ("Redis Streams", "XADD / XREADGROUP with consumer groups", False),
            ("Worker (Go)", "Bounded goroutine pool, timeouts, ACK", True),
        ],
        bullets=[
            "Hexagonal architecture with domain isolated from adapters",
            "Real async I/O — no sleep-based fake concurrency in the demos",
            "Idempotency and token-bucket rate limiting in the ingest path",
            "Prometheus metrics, docker-compose stack and load-test hooks",
            "Architecture notes, high-load readiness doc and ADRs",
            "CI for both services; every commit reviewable",
        ],
        stack=["Python 3.11+", "asyncio", "FastAPI", "Go 1.22", "Redis Streams", "Prometheus", "Docker Compose", "GitHub Actions"],
        foot_right="github.com/easylager/pulsebridge &middot; MIT",
    ),
}


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "services-overview.html").write_text(sheet_html(), encoding="utf-8")
    print(OUT_DIR / "services-overview.html")
    for name, html in CARDS.items():
        path = OUT_DIR / f"{name}.html"
        path.write_text(html, encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
