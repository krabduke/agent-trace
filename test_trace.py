import json
import re
from pathlib import Path

import pytest

from trace import (
    Span, assign_channels, critical_path, load_trace, render_html, serial_time,
)

SAMPLE = Path(__file__).parent / "sample_trace.json"


def spans(*triples):
    return [Span(id=f"s{i}", agent=a, label=a, start_ms=s, end_ms=e)
            for i, (a, s, e) in enumerate(triples)]


def test_loads_sample():
    meta, sp = load_trace(SAMPLE)
    assert meta["run_id"] == "brief-2026-07-24-0600"
    assert len(sp) == 10


def test_spans_sorted_by_start():
    _, sp = load_trace(SAMPLE)
    assert [s.start_ms for s in sp] == sorted(s.start_ms for s in sp)


def test_rejects_inverted_span(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"spans": [
        {"id": "a", "agent": "x", "label": "x", "start_ms": 100, "end_ms": 50}
    ]}))
    with pytest.raises(SystemExit, match="ends before"):
        load_trace(bad)


def test_rejects_empty_trace(tmp_path):
    empty = tmp_path / "empty.json"
    empty.write_text('{"spans": []}')
    with pytest.raises(SystemExit, match="no spans"):
        load_trace(empty)


def test_critical_path_is_wall_clock_not_sum():
    # Two agents fully overlapping: wall clock 100, agent time 200.
    sp = spans(("a", 0, 100), ("b", 0, 100))
    assert critical_path(sp) == 100
    assert serial_time(sp) == 200


def test_critical_path_with_gaps():
    assert critical_path(spans(("a", 0, 10), ("b", 90, 100))) == 100


def test_channels_assigned_per_agent_in_first_appearance_order():
    colours = assign_channels(spans(("geo", 0, 1), ("macro", 1, 2), ("geo", 2, 3)))
    assert len(colours) == 2
    assert colours["geo"] != colours["macro"]


def test_channels_wrap_beyond_palette():
    many = spans(*[(f"agent{i}", i, i + 1) for i in range(20)])
    assert len(assign_channels(many)) == 20  # no crash, colours repeat


def test_html_is_selfcontained():
    meta, sp = load_trace(SAMPLE)
    out = render_html(meta, sp)
    assert out.startswith("<!DOCTYPE html>")
    # No external requests of any kind.
    assert not re.search(r'(src|href)\s*=\s*["\']https?://', out)
    assert "<script src" not in out


def test_html_contains_every_span():
    meta, sp = load_trace(SAMPLE)
    out = render_html(meta, sp)
    for s in sp:
        assert f'data-id="{s.id}"' in out


def test_html_marks_error_and_warn_states():
    meta, sp = load_trace(SAMPLE)
    out = render_html(meta, sp)
    assert 'data-status="error"' in out
    assert 'data-status="warn"' in out


def test_bars_stay_within_the_track():
    meta, sp = load_trace(SAMPLE)
    out = render_html(meta, sp)
    for left, width in re.findall(r"left:([\d.]+)%;width:([\d.]+)%", out):
        assert float(left) + float(width) <= 100.5  # rounding headroom


def test_output_is_escaped(tmp_path):
    evil = tmp_path / "evil.json"
    evil.write_text(json.dumps({"run_id": "<script>alert(1)</script>", "spans": [
        {"id": "a", "agent": "<img onerror=x>", "label": "L", "start_ms": 0, "end_ms": 1}
    ]}))
    out = render_html(*load_trace(evil))
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_accessible_labels_present():
    meta, sp = load_trace(SAMPLE)
    out = render_html(meta, sp)
    assert out.count("aria-label=") == len(sp)


def test_reduced_motion_respected():
    meta, sp = load_trace(SAMPLE)
    assert "prefers-reduced-motion" in render_html(meta, sp)
