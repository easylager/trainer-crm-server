#!/usr/bin/env python3
"""Generate LinkedIn media for the PulseBridge repository.

Every number and screenshot here comes from the repo itself: the benchmark
tables in docs/benchmarks.md and captures taken from the running compose stack.
"""

from __future__ import annotations

import base64
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "pulsebridge-media"
SHOTS = ROOT / "pulsebridge-shots"

INK = "#12212b"
MUTED = "#5b6b76"
ACCENT = "#0f766e"
ACCENT_SOFT = "#e6f2f0"
LINE = "#d8e0e3"
WARN = "#b45309"

CSS = f"""
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  color: {INK};
  background: #ffffff;
  -webkit-font-smoothing: antialiased;
}}
.card {{
  width: 1600px;
  height: 900px;
  padding: 64px 76px;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}}
.card::after {{
  content: "";
  position: absolute;
  left: 0; right: 0; bottom: 0;
  height: 10px;
  background: {ACCENT};
}}
.kicker {{
  font-size: 19px;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: {ACCENT};
  font-weight: 700;
}}
h1 {{ font-size: 50px; line-height: 1.08; margin-top: 12px; font-weight: 800; }}
h1.big {{ font-size: 78px; }}
.sub {{ font-size: 23px; color: {MUTED}; margin-top: 14px; max-width: 1240px; line-height: 1.45; }}
.muted {{ color: {MUTED}; }}
.accent {{ color: {ACCENT}; }}
.mono {{ font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace; }}
.pill {{
  display: inline-block;
  padding: 7px 16px;
  border: 1px solid {LINE};
  border-radius: 999px;
  font-size: 17px;
  background: #fbfdfd;
}}
.pill-accent {{ background: {ACCENT_SOFT}; border-color: {ACCENT_SOFT}; color: {ACCENT}; font-weight: 600; }}
.foot {{
  margin-top: auto;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 19px;
  color: {MUTED};
  border-top: 1px solid {LINE};
  padding-top: 20px;
}}
.stack {{ display: flex; gap: 10px; flex-wrap: wrap; }}

.flow {{ display: flex; align-items: stretch; gap: 16px; margin-top: 44px; }}
.node {{
  flex: 1;
  border: 2px solid {LINE};
  border-radius: 16px;
  padding: 20px 18px;
  background: #fbfdfd;
}}
.node .n-title {{ font-size: 21px; font-weight: 700; }}
.node .n-body {{ font-size: 16px; color: {MUTED}; margin-top: 8px; line-height: 1.4; }}
.node.hl {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
.node.hl .n-body {{ color: #24564f; }}
.arrow {{ align-self: center; font-size: 28px; color: {ACCENT}; font-weight: 700; }}

table {{ width: 100%; border-collapse: collapse; margin-top: 32px; }}
th, td {{ text-align: left; padding: 15px 18px; font-size: 21px; border-bottom: 1px solid {LINE}; }}
th {{ font-size: 16px; text-transform: uppercase; letter-spacing: 1.4px; color: {MUTED}; font-weight: 700; }}
td.num, th.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
tr.hl td {{ background: {ACCENT_SOFT}; font-weight: 700; }}
td.k {{ font-weight: 700; width: 34%; }}

.shot {{
  margin-top: 30px;
  border: 1px solid {LINE};
  border-radius: 14px;
  overflow: hidden;
  background: #0f1116;
  line-height: 0;
}}
.shot img {{ width: 100%; display: block; }}
.caps {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 26px; margin-top: 26px; }}
.mid {{ flex: 1; display: flex; flex-direction: column; justify-content: center; }}
.mid > :first-child {{ margin-top: 0; }}
.cap {{ font-size: 19px; line-height: 1.4; padding-left: 22px; position: relative; color: {MUTED}; }}
.cap b {{ color: {INK}; }}
.cap::before {{
  content: ""; position: absolute; left: 0; top: 9px;
  width: 9px; height: 9px; border-radius: 3px; background: {ACCENT};
}}
.split {{ display: grid; grid-template-columns: 1fr 1fr; gap: 44px; margin-top: 34px; }}
.box {{ border: 2px solid {LINE}; border-radius: 16px; padding: 26px 28px; }}
.box.bad {{ border-color: #e7c9a9; background: #fdf7f0; }}
.box.good {{ border-color: {ACCENT}; background: {ACCENT_SOFT}; }}
.box h3 {{ font-size: 22px; margin-bottom: 14px; }}
.box.bad h3 {{ color: {WARN}; }}
.box.good h3 {{ color: {ACCENT}; }}
.box p {{ font-size: 19px; line-height: 1.5; color: {MUTED}; }}
.box code {{ font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace; font-size: 17px; color: {INK}; }}
.term {{
  margin-top: 30px;
  background: #0f1116;
  border-radius: 14px;
  padding: 28px 32px;
  font-family: "SF Mono", ui-monospace, Menlo, Consolas, monospace;
  font-size: 20px;
  line-height: 1.65;
  color: #d7dee7;
}}
.term .c {{ color: #7f8c9b; }}
.term .g {{ color: #4ade80; }}
.term .y {{ color: #fbbf24; }}
.term .t {{ color: #2dd4bf; }}
.big-num {{ display: flex; gap: 54px; margin-top: 34px; }}
.bn {{ flex: 1; }}
.bn .v {{ font-size: 56px; font-weight: 800; font-variant-numeric: tabular-nums; }}
.bn .l {{ font-size: 18px; color: {MUTED}; margin-top: 6px; line-height: 1.4; }}
.bn.ok .v {{ color: {ACCENT}; }}
"""

FOOT = (
    '<div class="foot"><div class="stack">'
    '<span class="pill">Python · asyncio</span>'
    '<span class="pill">Go</span>'
    '<span class="pill">Redis Streams</span>'
    '<span class="pill">OpenTelemetry</span>'
    '<span class="pill">Prometheus · Grafana</span>'
    "</div>"
    '<div class="mono">github.com/easylager/pulsebridge</div></div>'
)


def page(body: str) -> str:
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )


def embed(name: str) -> str:
    data = base64.b64encode((SHOTS / name).read_bytes()).decode()
    return f"data:image/png;base64,{data}"


def hero() -> str:
    nodes = [
        ("Producers", "HTTP clients, any language", False),
        ("Gateway", "Python · asyncio · FastAPI<br/>validate, rate-limit, claim id", True),
        ("Redis Streams", "durable log<br/>consumer groups", False),
        ("Worker pool", "Go · bounded goroutines<br/>idempotent handler", True),
        ("Dead letter", "poison quarantined<br/>with replay context", False),
    ]
    flow = []
    for i, (t, b, hl) in enumerate(nodes):
        if i:
            flow.append('<div class="arrow">&rarr;</div>')
        flow.append(
            f'<div class="node{" hl" if hl else ""}"><div class="n-title">{t}</div>'
            f'<div class="n-body">{b}</div></div>'
        )
    return page(f"""<div class="card">
  <div class="kicker">Open source · MIT</div>
  <h1 class="big">PulseBridge</h1>
  <div class="sub">A high-throughput event bridge, built to be argued with.
  Most portfolio repositories show a system working. This one is about what happens
  when it doesn't &mdash; and every answer has a mechanism, a test and a written decision.</div>
  <div class="mid">
    <div class="flow">{''.join(flow)}</div>
    <div class="caps">
      <div class="cap"><b>At-least-once</b>, closed to effectively-once by an idempotent handler</div>
      <div class="cap"><b>One trace</b> spans HTTP request &rarr; Redis &rarr; Go handler</div>
      <div class="cap"><b>Measured</b>, not claimed &mdash; capacity curve and fault injection</div>
    </div>
  </div>
  {FOOT}
</div>""")


def failures() -> str:
    rows = [
        ("A consumer is OOM-killed mid-flight",
         "Stale pending entries reclaimed by a surviving replica via <span class='mono'>XPENDING</span> / <span class='mono'>XCLAIM</span>"),
        ("A message can never be parsed",
         "Bounded retries, then quarantine in a dead-letter stream with full replay context"),
        ("The same event arrives twice",
         "Handler claims the event id atomically before applying the effect"),
        ("Publish fails after the idempotency claim",
         "Claim rolled back and <span class='mono'>503</span> returned &mdash; no silent loss"),
        ("Traffic goes past capacity",
         "Degrades into queueing, not errors &mdash; measured: zero 5xx, zero data loss"),
    ]
    body = "".join(
        f'<tr><td class="k">{q}</td><td class="muted">{a}</td></tr>' for q, a in rows
    )
    return page(f"""<div class="card">
  <div class="kicker">Failure modes</div>
  <h1>The interesting part is what happens when it breaks</h1>
  <div class="sub">Each row is implemented, covered by a test named after the failure,
  and argued in an ADR that records the alternatives that were rejected.</div>
  <div class="mid">
    <table><tbody>{body}</tbody></table>
    <div class="caps">
      <div class="cap"><b>Seven ADRs</b>, each with the alternatives that were rejected</div>
      <div class="cap"><b>Race-enabled</b> Go tests &mdash; three loops share one worker pool</div>
      <div class="cap"><b>CI runs the stack</b>, not just the units: accept, replay, apply, dead-letter</div>
    </div>
  </div>
  {FOOT}
</div>""")


def grafana_serving() -> str:
    return page(f"""<div class="card">
  <div class="kicker">Observability &mdash; 1 of 2</div>
  <h1>Is the caller being served?</h1>
  <div class="sub">Provisioned with the stack, every panel wired to an SLO and an alert rule.
  Captured live at 400&nbsp;rps against the compose stack.</div>
  <div class="mid"><div class="shot"><img src="{embed('grafana-serving.png')}"/></div></div>
  {FOOT}
</div>""")


def grafana_backlog() -> str:
    return page(f"""<div class="card">
  <div class="kicker">Observability &mdash; 2 of 2</div>
  <h1>Is the backlog draining?</h1>
  <div class="sub">Throughput alone hides the failure that matters: a stream growing faster than
  it is consumed. Pending entries, oldest unacknowledged event, retries, reclaims and dead letters
  are all on one screen.</div>
  <div class="mid"><div class="shot"><img src="{embed('grafana-backlog.png')}"/></div></div>
  {FOOT}
</div>""")


def jaeger() -> str:
    return page(f"""<div class="card">
  <div class="kicker">Distributed tracing</div>
  <h1>One trace, two languages, across a queue</h1>
  <div class="sub">The gateway injects a <span class="mono">traceparent</span> into the stream entry,
  so the Go worker's span joins the Python request instead of starting a new orphan trace.</div>
  <div class="mid">
    <div class="shot"><img src="{embed('jaeger-trace.png')}"/></div>
    <div class="caps">
      <div class="cap"><b>POST /v1/events</b> &mdash; FastAPI ingest span</div>
      <div class="cap"><b>pulsebridge.events process</b> &mdash; Go handler, same trace</div>
      <div class="cap"><b>Services 2 · Depth 2</b> &mdash; the queue is not a dead end</div>
    </div>
  </div>
  {FOOT}
</div>""")


def numbers() -> str:
    rows = [
        ("100", "100.0", "0", "2.5", "10.6", False),
        ("400", "400.0", "0", "2.0", "36.7", False),
        ("500", "500.0", "0", "2.6", "61.8", True),
        ("600", "599.9", "0", "8.4", "209.5", False),
        ("800", "532.6", "0", "1 565.9", "17 442.2", False),
    ]
    body = "".join(
        f'<tr class="{"hl" if hl else ""}"><td class="num">{a}</td><td class="num">{b}</td>'
        f'<td class="num">{c}</td><td class="num">{d}</td><td class="num">{e}</td></tr>'
        for a, b, c, d, e, hl in rows
    )
    return page(f"""<div class="card">
  <div class="kicker">Measured, one laptop</div>
  <h1>Where the knee is &mdash; and what it costs past it</h1>
  <div class="sub">k6 driving the full compose stack, 30&nbsp;s steady state, Apple M1 Max.
  The load generator shares the same 10 cores, so these are capacity numbers, not a production claim.</div>
  <div class="mid">
  <table>
    <thead><tr>
      <th class="num">Offered rps</th><th class="num">Achieved</th>
      <th class="num">5xx</th><th class="num">p50, ms</th><th class="num">p99, ms</th>
    </tr></thead>
    <tbody>{body}</tbody>
  </table>
  <div class="caps">
    <div class="cap"><b>~500 rps</b> per gateway process; p99 inside the 50&nbsp;ms objective to 400</div>
    <div class="cap"><b>Zero 5xx</b> in every run, including the overload one</div>
    <div class="cap"><b>258 510 events</b> consumed, split 50.1 / 49.9 with no coordination</div>
  </div>
  </div>
  {FOOT}
</div>""")


def sigkill() -> str:
    return page(f"""<div class="card">
  <div class="kicker">Fault injection</div>
  <h1>SIGKILL, because a graceful drain proves nothing</h1>
  <div class="sub">One replica killed outright under 600&nbsp;rps. The claim worth making is not that
  shutdown is clean &mdash; it is that a worker dying with work in its hands loses none of it.</div>
  <div class="mid">
  <div class="term">
<span class="c"># 600 rps in the background, then kill one replica six seconds in</span><br/>
$ docker compose kill -s SIGKILL worker-1<br/>
<br/>
<span class="c"># the survivor notices the stranded entry and takes it over</span><br/>
pulsebridge_worker_reclaimed_total<span class="c">{{consumer="worker-2"}}</span>&nbsp;&nbsp;<span class="y">0 &rarr; 1</span><br/>
XPENDING pulsebridge.events pulsebridge-workers&nbsp;&nbsp;&rarr;&nbsp;&nbsp;<span class="g">0</span>
  </div>
  <div class="big-num">
    <div class="bn"><div class="v">27 004</div><div class="l">entries written to the stream</div></div>
    <div class="bn"><div class="v">27 003</div><div class="l">applied by the handler</div></div>
    <div class="bn"><div class="v">1</div><div class="l">dead-lettered<br/>(the deliberately malformed entry)</div></div>
    <div class="bn ok"><div class="v">0</div><div class="l">still pending &mdash; nothing lost,<br/>nothing double-applied</div></div>
  </div>
  </div>
  {FOOT}
</div>""")


def bug() -> str:
    return page(f"""<div class="card">
  <div class="kicker">A bug the rewrite found</div>
  <h1>The duplicate that was never written</h1>
  <div class="sub">The gateway claimed the idempotency key before publishing, and kept the claim
  when the publish failed. Every retry then answered <span class="mono">200 duplicate</span> &mdash;
  for an event that does not exist. Silent loss, for the full 24-hour TTL, with no error anywhere.</div>
  <div class="mid">
  <div class="split">
    <div class="box bad">
      <h3>Before</h3>
      <p><code>claim(event_id)</code> &rarr; <code>XADD</code> raises &rarr; claim survives.<br/><br/>
      The retry is mistaken for a replay. The caller is told the event was accepted.
      Nothing in the logs disagrees.</p>
    </div>
    <div class="box good">
      <h3>After</h3>
      <p>The claim still comes first &mdash; two concurrent requests with the same id must not both publish.
      So the fix is a rollback on failure, plus a <code>503</code> that says honestly that nothing was accepted.</p>
    </div>
  </div>
  <div class="caps">
    <div class="cap"><b>ADR 0006</b> records why the ordering cannot simply be reversed</div>
    <div class="cap"><b>The test</b> is named <span class="mono">test_failed_publish_releases_the_idempotency_claim</span></div>
    <div class="cap"><b>At-least-once</b> is stated out loud &mdash; no exactly-once claim</div>
  </div>
  </div>
  {FOOT}
</div>""")


SLIDES = {
    "01-pulsebridge-overview": hero,
    "02-failure-modes": failures,
    "03-grafana-serving": grafana_serving,
    "04-grafana-backlog": grafana_backlog,
    "05-distributed-trace": jaeger,
    "06-measured-capacity": numbers,
    "07-sigkill-accounting": sigkill,
    "08-idempotency-bug": bug,
}

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def render(html_path: Path, png_path: Path) -> None:
    subprocess.run(
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=1",
            "--window-size=1600,900",
            "--virtual-time-budget=8000",
            f"--screenshot={png_path}",
            f"file://{html_path}",
        ],
        check=True,
        capture_output=True,
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, builder in SLIDES.items():
        html_path = OUT_DIR / f"{name}.html"
        html_path.write_text(builder(), encoding="utf-8")
        png_path = OUT_DIR / f"{name}.png"
        render(html_path, png_path)
        print(png_path)

    desktop = Path.home() / "Desktop" / "PulseBridge-media"
    desktop.mkdir(parents=True, exist_ok=True)
    for leftover in list(desktop.glob("*.html")) + list(desktop.glob("*.png")):
        leftover.unlink()
    for png in sorted(OUT_DIR.glob("*.png")):
        shutil.copy2(png, desktop / png.name)
    print(desktop)


if __name__ == "__main__":
    main()
