"""Optional AttrViz performance spans for bottleneck harnesses.

Disabled by default (near-zero cost). Enable with::

    from attrviz import perf
    perf.enable(True)

Or env ``ATTRVIZ_PERF=1``. Spans accumulate ms samples; print with
``perf.report()`` or dump JSON via ``perf.as_dict()``.
"""
from __future__ import annotations

import os
import time
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional

_enabled = False
_samples: Dict[str, List[float]] = defaultdict(list)
_meta: Dict[str, object] = {}
_active_stack: List[str] = []


def enable(on: bool = True) -> None:
    global _enabled
    _enabled = bool(on)
    if on and not _samples:
        # pick up env toggle for nested imports
        pass


def enabled() -> bool:
    return _enabled


def reset() -> None:
    _samples.clear()
    _meta.clear()
    _active_stack.clear()


def set_meta(**kwargs) -> None:
    _meta.update(kwargs)


def note(key: str, value) -> None:
    """Record a non-timing datum (counts, sizes)."""
    bucket = _meta.setdefault("notes", {})
    if not isinstance(bucket, dict):
        bucket = {}
        _meta["notes"] = bucket
    bucket[key] = value


@contextmanager
def span(name: str) -> Iterator[None]:
    if not _enabled:
        yield
        return
    _active_stack.append(name)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        dt_ms = (time.perf_counter() - t0) * 1000.0
        _samples[name].append(dt_ms)
        if _active_stack and _active_stack[-1] == name:
            _active_stack.pop()


def add_ms(name: str, ms: float) -> None:
    if _enabled:
        _samples[name].append(float(ms))


def _stats(xs: List[float]) -> dict:
    if not xs:
        return {"n": 0, "total_ms": 0.0, "mean_ms": 0.0,
                "min_ms": 0.0, "max_ms": 0.0}
    total = float(sum(xs))
    return {
        "n": len(xs),
        "total_ms": total,
        "mean_ms": total / len(xs),
        "min_ms": float(min(xs)),
        "max_ms": float(max(xs)),
    }


def as_dict() -> dict:
    spans = {k: _stats(v) for k, v in sorted(_samples.items())}
    ranked = sorted(
        spans.items(),
        key=lambda kv: kv[1]["total_ms"],
        reverse=True,
    )
    return {
        "meta": dict(_meta),
        "spans": spans,
        "ranked_by_total_ms": [
            {"name": k, **v} for k, v in ranked
        ],
    }


def report(stream=None, *, top: int = 30) -> str:
    data = as_dict()
    lines = []
    lines.append("=== AttrViz perf report ===")
    meta = data.get("meta") or {}
    if meta:
        for k, v in meta.items():
            if k == "notes":
                continue
            lines.append(f"  {k}: {v}")
        notes = meta.get("notes")
        if isinstance(notes, dict) and notes:
            lines.append("  notes:")
            for k, v in notes.items():
                lines.append(f"    {k}: {v}")
    lines.append(
        f"  {'span':<40} {'n':>5} {'total_ms':>10} {'mean_ms':>10} "
        f"{'max_ms':>10}"
    )
    lines.append("  " + "-" * 78)
    for row in data["ranked_by_total_ms"][:top]:
        lines.append(
            f"  {row['name']:<40} {row['n']:>5} {row['total_ms']:10.2f} "
            f"{row['mean_ms']:10.2f} {row['max_ms']:10.2f}"
        )
    if not data["ranked_by_total_ms"]:
        lines.append("  (no spans recorded — was perf.enable(True)?)")
    text = "\n".join(lines) + "\n"
    if stream is None:
        print(text, end="")
    else:
        stream.write(text)
    return text


def bootstrap_from_env() -> None:
    raw = os.environ.get("ATTRVIZ_PERF", "").strip().lower()
    if raw in ("1", "true", "yes", "on"):
        enable(True)


bootstrap_from_env()
