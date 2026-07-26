# agent-trace

Render a multi-agent run as a single self-contained HTML timeline.

Multi-agent pipelines fail in ways logs hide: one agent quietly takes 40s, two
agents you thought ran in parallel are actually serial, a retry loop fires
three times. A timeline makes all three obvious in a glance.

```
$ python3 trace.py sample_trace.json -o trace.html
10 spans across 7 agents, 41.20s wall clock -> trace.html
```

Open `trace.html` in a browser. No server, no external requests, nothing
fetched at runtime, so it can be committed as a build artifact or opened from
disk on a machine with no network.

## The design

One horizontal lane per agent, in the manner of a logic analyser rather than a
dashboard. The signature element is a **scope cursor**: a hairline that follows
the pointer across every lane at once with the exact time offset, so
correlating what four agents were doing at t=11.5s takes no arithmetic.

The readout panel deliberately shows wall clock **and** summed agent time. The
ratio between them is the real parallelism, which is usually lower than the
architecture diagram suggests.

## Trace format

```json
{
  "run_id": "brief-2026-07-24-0600",
  "pipeline": "daily intelligence brief",
  "spans": [
    {"id": "geo-01", "agent": "geo", "label": "Scan situation tracker",
     "start_ms": 0, "end_ms": 1840, "status": "ok",
     "model": "qwen3.5:4b", "tokens_in": 3120, "tokens_out": 480,
     "output": "...", "error": ""}
  ]
}
```

Only `id`, `agent`, `label`, `start_ms`, `end_ms` are required. `status` is
`ok`, `warn`, or `error`.

Emitting this from an existing pipeline is a few lines: record
`time.monotonic() * 1000` at the start and end of each agent call and append a
dict.

Stdlib only. Tests: `python3 -m pytest test_trace.py` (15 tests, including
HTML escaping and no-external-requests checks)
