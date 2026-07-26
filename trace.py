#!/usr/bin/env python3
"""Render a multi-agent run as a single-file HTML timeline.

Multi-agent pipelines fail in ways logs hide: one agent quietly takes 40s, two
agents you thought ran in parallel are actually serial, a retry loop fires
three times. A timeline makes all three obvious at a glance.

Input is a JSON trace. Output is one self-contained HTML file with no external
requests, so it can be opened from disk or committed as a build artifact.
"""
from __future__ import annotations

import argparse
import html
import json
from dataclasses import dataclass
from pathlib import Path

# Desaturated channel colours, in the manner of a logic analyser rather than a
# dashboard. Assigned to agents in first-appearance order.
CHANNELS = ["#7FA88C", "#C89F6D", "#6E90C4", "#A98BB5", "#C47D7D", "#8FA5A0", "#B79A6B"]
STATUS_COLOURS = {"ok": None, "warn": "#E8B44A", "error": "#C4574D"}


@dataclass
class Span:
    id: str
    agent: str
    label: str
    start_ms: float
    end_ms: float
    status: str = "ok"
    model: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str = ""
    output: str = ""

    @property
    def duration_ms(self) -> float:
        return self.end_ms - self.start_ms


def load_trace(path: Path) -> tuple[dict, list[Span]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    spans = [Span(**s) for s in raw["spans"]]
    if not spans:
        raise SystemExit(f"{path}: trace has no spans")
    for s in spans:
        if s.end_ms < s.start_ms:
            raise SystemExit(f"{path}: span {s.id!r} ends before it starts")
    spans.sort(key=lambda s: s.start_ms)
    meta = {k: v for k, v in raw.items() if k != "spans"}
    return meta, spans


def assign_channels(spans: list[Span]) -> dict[str, str]:
    agents: list[str] = []
    for s in spans:
        if s.agent not in agents:
            agents.append(s.agent)
    return {a: CHANNELS[i % len(CHANNELS)] for i, a in enumerate(agents)}


def critical_path(spans: list[Span]) -> float:
    """Wall-clock span of the whole run, which is what actually costs time."""
    return max(s.end_ms for s in spans) - min(s.start_ms for s in spans)


def serial_time(spans: list[Span]) -> float:
    """Summed agent time. Much larger than wall clock means real parallelism."""
    return sum(s.duration_ms for s in spans)


def _fmt_ms(ms: float) -> str:
    return f"{ms:.0f}ms" if ms < 1000 else f"{ms / 1000:.2f}s"


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root {
    --ground: #0E1A1C;
    --panel: #142326;
    --rule: #1F3438;
    --ink: #DCE6E4;
    --dim: #7C918F;
    --faint: #4A605E;
    --playhead: #E8B44A;
    --gutter: 118px;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0;
    background: var(--ground);
    color: var(--ink);
    font: 13px/1.5 ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 1180px; margin: 0 auto; padding: 40px 28px 72px; }

  /* ---- masthead: the run is an instrument reading, so state it like one ---- */
  .eyebrow {
    font-size: 10px; letter-spacing: 0.22em; text-transform: uppercase;
    color: var(--faint); margin-bottom: 14px;
  }
  h1 { font-size: 26px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 4px; }
  .sub { color: var(--dim); font-size: 12px; margin-bottom: 32px; }

  .readout {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
    gap: 1px; background: var(--rule); border: 1px solid var(--rule);
    margin-bottom: 40px;
  }
  .cell { background: var(--panel); padding: 14px 16px; }
  .cell dt {
    font-size: 10px; letter-spacing: 0.14em; text-transform: uppercase;
    color: var(--faint); margin-bottom: 6px;
  }
  .cell dd { margin: 0; font-size: 19px; font-weight: 500; font-variant-numeric: tabular-nums; }
  .cell dd small { font-size: 11px; color: var(--dim); font-weight: 400; }

  /* ---- the chart ---- */
  .chart { position: relative; border-top: 1px solid var(--rule); }
  .ruler {
    position: relative; height: 26px; border-bottom: 1px solid var(--rule);
    margin-left: var(--gutter); 
  }
  .tick { position: absolute; top: 0; height: 100%; border-left: 1px solid var(--rule); }
  .tick span {
    position: absolute; left: 5px; top: 6px; font-size: 10px; color: var(--faint);
    font-variant-numeric: tabular-nums; white-space: nowrap;
  }

  .lane {
    position: relative; display: grid; grid-template-columns: var(--gutter) 1fr;
    border-bottom: 1px solid var(--rule); min-height: 42px; align-items: center;
  }
  .lane:hover { background: rgba(255,255,255,0.018); }
  .lane-name {
    padding-right: 16px; text-align: right; font-size: 11px;
    letter-spacing: 0.08em; text-transform: uppercase; color: var(--dim);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .lane-track { position: relative; height: 42px; }

  .bar {
    position: absolute; top: 11px; height: 20px; min-width: 3px;
    border-radius: 2px; cursor: pointer; border: 0; padding: 0;
    transform-origin: left center; color: inherit;
    transition: filter .12s ease;
  }
  .bar:hover, .bar:focus-visible { filter: brightness(1.35); }
  .bar:focus-visible { outline: 2px solid var(--playhead); outline-offset: 2px; }
  .bar[data-status="error"] { box-shadow: inset 0 0 0 2px #C4574D; }
  .bar[data-status="warn"]  { box-shadow: inset 0 0 0 2px #E8B44A; }
  .bar-label {
    position: absolute; left: 100%; margin-left: 8px; top: 50%;
    transform: translateY(-50%); font-size: 10px; color: var(--dim);
    white-space: nowrap; pointer-events: none; font-variant-numeric: tabular-nums;
  }

  /* ---- signature: a scope cursor spanning every channel at once ---- */
  #playhead {
    position: absolute; top: 0; bottom: 0; width: 1px;
    background: var(--playhead); opacity: 0; pointer-events: none; z-index: 5;
  }
  #playhead::after {
    content: attr(data-t); position: absolute; top: -1px; left: 6px;
    background: var(--playhead); color: #0E1A1C; font-size: 10px;
    padding: 1px 5px; font-weight: 600; white-space: nowrap;
    font-variant-numeric: tabular-nums;
  }
  .chart:hover #playhead { opacity: 1; }

  /* ---- detail ---- */
  .detail {
    margin-top: 32px; border: 1px solid var(--rule); background: var(--panel);
    padding: 20px 22px; min-height: 96px;
  }
  .detail h2 { margin: 0 0 3px; font-size: 15px; font-weight: 600; }
  .detail .meta { color: var(--dim); font-size: 11px; margin-bottom: 16px; }
  .kv { display: grid; grid-template-columns: 118px 1fr; gap: 5px 18px; font-size: 12px; }
  .kv dt { color: var(--faint); }
  .kv dd { margin: 0; word-break: break-word; }
  .detail pre {
    margin: 16px 0 0; padding: 14px; background: #0B1517; border: 1px solid var(--rule);
    font-size: 11px; line-height: 1.6; overflow-x: auto; white-space: pre-wrap;
    color: var(--dim); max-height: 260px;
  }
  .detail .err { color: #E08A80; }
  .placeholder { color: var(--faint); font-size: 12px; padding-top: 4px; }

  @media (max-width: 640px) {
    :root { --gutter: 76px; }
    .wrap { padding: 24px 14px 48px; }
    h1 { font-size: 20px; }
    .bar-label { display: none; }
  }
  @media (prefers-reduced-motion: no-preference) {
    .bar { animation: draw .42s cubic-bezier(.2,.7,.3,1) backwards; }
    @keyframes draw { from { transform: scaleX(0); opacity: 0; } }
  }
</style>
</head>
<body>
<div class="wrap">
  <p class="eyebrow">Agent trace</p>
  <h1>__TITLE__</h1>
  <p class="sub">__SUBTITLE__</p>

  <dl class="readout">__READOUT__</dl>

  <div class="chart" id="chart">
    <div id="playhead"></div>
    <div class="ruler" id="ruler">__TICKS__</div>
    __LANES__
  </div>

  <div class="detail" id="detail">
    <p class="placeholder">Select a span to inspect its payload. Hover the chart for a time cursor.</p>
  </div>
</div>

<script>
const SPANS = __SPANS_JSON__;
const T0 = __T0__, SPAN_MS = __SPAN_MS__;

function fmt(ms) { return ms < 1000 ? ms.toFixed(0) + "ms" : (ms / 1000).toFixed(2) + "s"; }

const chart = document.getElementById("chart");
const playhead = document.getElementById("playhead");
const ruler = document.getElementById("ruler");

chart.addEventListener("pointermove", (e) => {
  const box = ruler.getBoundingClientRect();
  const x = e.clientX - box.left;
  if (x < 0 || x > box.width) { playhead.style.opacity = 0; return; }
  playhead.style.opacity = 1;
  playhead.style.left = (e.clientX - chart.getBoundingClientRect().left) + "px";
  playhead.dataset.t = fmt((x / box.width) * SPAN_MS);
});
chart.addEventListener("pointerleave", () => { playhead.style.opacity = 0; });

const detail = document.getElementById("detail");
function show(id) {
  const s = SPANS.find(x => x.id === id);
  if (!s) return;
  const rows = [
    ["agent", s.agent],
    ["status", s.status],
    ["start", fmt(s.start_ms - T0)],
    ["duration", fmt(s.end_ms - s.start_ms)],
  ];
  if (s.model) rows.push(["model", s.model]);
  if (s.tokens_in || s.tokens_out) {
    rows.push(["tokens", s.tokens_in.toLocaleString() + " in / " + s.tokens_out.toLocaleString() + " out"]);
  }
  detail.innerHTML =
    "<h2>" + s.label + "</h2>" +
    "<p class='meta'>" + s.id + "</p>" +
    "<dl class='kv'>" + rows.map(r => "<dt>" + r[0] + "</dt><dd>" + r[1] + "</dd>").join("") + "</dl>" +
    (s.error ? "<pre class='err'>" + s.error + "</pre>" : "") +
    (s.output ? "<pre>" + s.output + "</pre>" : "");
}

document.querySelectorAll(".bar").forEach(bar => {
  bar.addEventListener("click", () => show(bar.dataset.id));
  bar.addEventListener("focus", () => show(bar.dataset.id));
});
</script>
</body>
</html>
"""


def render_html(meta: dict, spans: list[Span]) -> str:
    colours = assign_channels(spans)
    t0 = min(s.start_ms for s in spans)
    total = critical_path(spans) or 1.0
    serial = serial_time(spans)

    # ---- readout cells
    errors = sum(1 for s in spans if s.status == "error")
    tokens = sum(s.tokens_in + s.tokens_out for s in spans)
    slowest = max(spans, key=lambda s: s.duration_ms)
    cells = [
        ("wall clock", _fmt_ms(total), ""),
        ("agent time", _fmt_ms(serial), f"{serial / total:.1f}x parallel"),
        ("spans", str(len(spans)), f"{len(colours)} agents"),
        ("slowest", _fmt_ms(slowest.duration_ms), slowest.agent),
        ("tokens", f"{tokens:,}", ""),
        ("errors", str(errors), ""),
    ]
    readout = "".join(
        f'<div class="cell"><dt>{html.escape(k)}</dt>'
        f'<dd>{html.escape(v)}{f" <small>{html.escape(note)}</small>" if note else ""}</dd></div>'
        for k, v, note in cells
    )

    # ---- ruler ticks at readable intervals
    step = next(s for s in (50, 100, 250, 500, 1000, 2500, 5000, 10_000, 30_000, 60_000)
                if total / s <= 12)
    ticks = "".join(
        f'<div class="tick" style="left:{(t / total) * 100:.3f}%"><span>{_fmt_ms(t)}</span></div>'
        for t in range(0, int(total) + 1, step)
    )

    # ---- one lane per agent, spans placed inside
    lanes = []
    for agent, colour in colours.items():
        bars = []
        for s in (x for x in spans if x.agent == agent):
            left = (s.start_ms - t0) / total * 100
            width = max(s.duration_ms / total * 100, 0.25)
            delay = (s.start_ms - t0) / total * 0.35
            bars.append(
                f'<button class="bar" data-id="{html.escape(s.id)}" data-status="{html.escape(s.status)}" '
                f'style="left:{left:.3f}%;width:{width:.3f}%;background:{colour};'
                f'animation-delay:{delay:.2f}s" '
                f'title="{html.escape(s.label)} &middot; {_fmt_ms(s.duration_ms)}" '
                f'aria-label="{html.escape(s.label)}, {_fmt_ms(s.duration_ms)}, {s.status}">'
                f'<span class="bar-label">{_fmt_ms(s.duration_ms)}</span></button>'
            )
        lanes.append(
            f'<div class="lane"><div class="lane-name">{html.escape(agent)}</div>'
            f'<div class="lane-track">{"".join(bars)}</div></div>'
        )

    payload = json.dumps([
        {
            "id": s.id, "agent": s.agent, "label": s.label, "status": s.status,
            "start_ms": s.start_ms, "end_ms": s.end_ms, "model": s.model,
            "tokens_in": s.tokens_in, "tokens_out": s.tokens_out,
            "error": s.error, "output": s.output,
        }
        for s in spans
    ])

    title = meta.get("run_id", "run")
    subtitle = " · ".join(
        x for x in (meta.get("started_at", ""), meta.get("pipeline", ""), f"{len(spans)} spans") if x
    )

    return (
        TEMPLATE
        .replace("__TITLE__", html.escape(str(title)))
        .replace("__SUBTITLE__", html.escape(subtitle))
        .replace("__READOUT__", readout)
        .replace("__TICKS__", ticks)
        .replace("__LANES__", "".join(lanes))
        .replace("__SPANS_JSON__", payload)
        .replace("__T0__", str(t0))
        .replace("__SPAN_MS__", str(total))
    )


def main() -> None:
    p = argparse.ArgumentParser(description="Render an agent trace as a single HTML file.")
    p.add_argument("trace", type=Path, help="JSON trace file")
    p.add_argument("-o", "--out", type=Path, default=Path("trace.html"))
    args = p.parse_args()

    meta, spans = load_trace(args.trace)
    args.out.write_text(render_html(meta, spans), encoding="utf-8")

    total = critical_path(spans)
    print(f"{len(spans)} spans across {len(assign_channels(spans))} agents, "
          f"{_fmt_ms(total)} wall clock -> {args.out}")


if __name__ == "__main__":
    main()
