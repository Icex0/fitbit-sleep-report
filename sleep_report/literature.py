"""Promethease-style literature report: match your metrics against curated published findings.

The knowledge base is literature.json next to this file. Each finding names a metric
from metrics.py and a list of value bands; the band your value falls in decides what
the finding says about you, its repute (good / attention / info) and its magnitude
(0-4, how much it's worth reading). Findings without a metric are general context.
Every claim cites references in the same file.

Personal settings (settings.py) decide what applies:
  "groups": [...]          on a band or finding: only for these age groups
                           (teen, young_adult, adult, older); no "groups" = everyone
  "sources": [...]         only for data from these sources ("google", "apple")
  "skip_if": [...]         skip the finding when any of these profile flags is true
  "skip_if_false": [...]   skip the finding when any of these profile flags is false
  "display": {...}         show a different metric than the one the bands test
  "basis": "metric"        the count of nights the finding rests on (default "nights");
                           exported as basedOn
  "minNights": n           below n nights of that basis, say how many more are needed
                           instead of judging the value
"""
import json
from pathlib import Path

KNOWLEDGE_BASE = Path(__file__).with_name("literature.json")
# Fewer nights than this give no literature report: a single night says little about what's typical,
# and the studies compared against recorded at least a week.
MIN_NIGHTS = 7


def clock(hours_after_18):
    m = round(hours_after_18 * 60)
    return f"{(18 + m // 60) % 24:02d}:{m % 60:02d}"


FORMATS = {
    "hours": lambda v: f"{v:.1f} h",
    "clock": clock,
    "pct": lambda v: f"{v:.0f}%",
    "pct1": lambda v: f"{v:.1f}%",
    "min": lambda v: f"{v:.0f} min",
    "per_hour": lambda v: f"{v:.1f} per hour",
    "per_week": lambda v: f"{v:.1f} per week",
    "bpm": lambda v: f"{v:.0f} bpm",
    "breaths": lambda v: f"{v:.1f} per minute",
    "ms": lambda v: f"{v:.1f} ms",
    "number": lambda v: f"{v:g}",
}


class _Values(dict):
    """Lets texts use {metric} placeholders; clock metrics also get a {name_clock} form."""

    def __missing__(self, key):
        if key.endswith("_clock") and isinstance(self.get(key[:-6] + "_h"), (int, float)):
            return clock(self[key[:-6] + "_h"])
        return "{" + key + "}"


def fill(text, values):
    try:
        return text.format_map(values)
    except (ValueError, TypeError, KeyError, IndexError):
        return text


def in_band(value, band):
    return ("min" not in band or value >= band["min"]) and ("max" not in band or value < band["max"])


def applies(item, group):
    return "groups" not in item or group in item["groups"]


def pending(f, bands, based_on, need, values):
    """A finding that needs more nights before it says anything about you."""
    return {
        "id": f["id"], "topic": f["topic"], "title": f["title"], "metric": f.get("metric"),
        "value": None, "valueText": None, "valueLabel": f.get("valueLabel"),
        "repute": "info", "magnitude": 0,
        "headline": f"Needs at least {need} nights before it can say what's typical for you; "
                    f"there {'is' if based_on == 1 else 'are'} {based_on} so far.",
        "detail": "", "background": "", "reference": None,
        "bands": [{"range": fill(b.get("label", ""), values), "repute": b.get("repute", "info"), "current": False}
                  for b in bands],
        "refs": [], "caveat": "", "basedOn": based_on, "pending": True,
    }


def evaluate(metrics, profile, kb=None):
    """Returns (findings, references) ready for export, most important first."""
    kb = kb or json.loads(KNOWLEDGE_BASE.read_text(encoding="utf-8"))
    group = profile["group"]
    values = _Values({k: v for k, v in metrics.items() if isinstance(v, (int, float))})
    if profile.get("age") is not None:
        values["age"] = profile["age"]
    out = []
    for f in kb["findings"]:
        if not applies(f, group):
            continue
        if f.get("sources") and profile.get("source", "google") not in f["sources"]:
            continue
        if any(profile.get(k) for k in f.get("skip_if", [])) or any(profile.get(k) is False for k in f.get("skip_if_false", [])):
            continue
        value = metrics.get(f["metric"]) if f.get("metric") else None
        if f.get("metric") and value is None:
            continue  # no data for this metric
        bands = [b for b in f.get("bands", []) if applies(b, group)]
        if f.get("bands") and not bands:
            continue  # no ranges for this age group
        band = next((b for b in bands if value is not None and in_band(value, b)), None)
        if bands and not band:
            continue  # value outside every band
        based_on = metrics.get(f.get("basis", "nights"))
        need = f.get("minNights", 0)
        if based_on is not None and based_on < need:
            out.append(pending(f, bands, based_on, need, values))
            continue
        result = band or f
        shown = f.get("display", {"metric": f.get("metric"), "format": f.get("format", "number")})
        shown_value = metrics.get(shown["metric"]) if shown["metric"] else None
        good = next((b for b in bands if b.get("repute") == "good"), None)
        out.append({
            "id": f["id"],
            "topic": f["topic"],
            "title": f["title"],
            "metric": f.get("metric"),
            "value": shown_value,
            "valueText": FORMATS[shown["format"]](shown_value) if shown_value is not None else None,
            "valueLabel": f.get("valueLabel"),
            "repute": result.get("repute", "info"),
            "magnitude": result.get("magnitude", 1),
            "headline": fill(result["headline"], values),
            "detail": fill(result.get("detail", f.get("detail", "")), values),  # a band's own detail wins
            "background": fill(f.get("background", ""), values),
            "reference": fill(good["label"], values) if good else None,
            "bands": [{"range": fill(b.get("label", ""), values), "repute": b.get("repute", "info"), "current": b is band}
                      for b in bands],
            "refs": f.get("refs", []) + (band or {}).get("refs", []),
            "caveat": fill(f.get("caveat", ""), values),
            "basedOn": based_on,
            "pending": False,
        })
    out.sort(key=lambda x: (-x["magnitude"], {"attention": 0, "good": 1, "info": 2}.get(x["repute"], 3)))
    # number references in order of first citation, like a paper
    order = list(dict.fromkeys(r for x in out for r in x["refs"]))
    missing = [r for r in order if r not in kb["references"]]
    if missing:
        raise ValueError(f"literature.json cites unknown references: {missing}")
    return out, [dict(id=r, **kb["references"][r]) for r in order]
