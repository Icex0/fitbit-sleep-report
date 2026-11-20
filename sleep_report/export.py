"""Write the data the web app reads: summary.json plus one detail file per night or nap.

Times in a detail file are seconds after the recording's start, to keep the files small.
"""
import json
from datetime import datetime

from .analysis import night_of
from .literature import MIN_NIGHTS
from .metrics import hours_after_18, metrics

STAGE_CODE = {"DEEP": "D", "LIGHT": "L", "REM": "R", "AWAKE": "W", "ASLEEP": "A", "RESTLESS": "S"}


def rec_id(r):
    return f"night-{r.name}" if r.kind == "night" else f"nap-{r.start:%Y-%m-%d-%H%M}"


def rounded(value, digits=1):
    return None if value is None else round(value, digits)


def summary_row(r):
    sl, s, h, b = r.sleep, r.spo2_stats, r.hr_stats, r.breathing
    night = night_of(r.start)
    row = {
        "id": rec_id(r),
        "kind": r.kind,
        "night": night,
        "start": r.start.isoformat(timespec="seconds"),
        "end": r.end.isoformat(timespec="seconds"),
        "startH": rounded(hours_after_18(r.start, night), 3),
        "endH": rounded(hours_after_18(r.end, night), 3),
        "sleep": None,
        "spo2": None,
        "hr": None,
        "breathing": rounded(b["full"]["rate"]) if b and b["full"] else None,
        "hrv": rounded((r.daily or {}).get("hrv")),
        "restingHr": (r.daily or {}).get("resting_hr"),
        "tempDev": rounded((r.daily or {})["temp"] - (r.daily or {})["temp_baseline"], 2)
        if r.daily and r.daily.get("temp") is not None and r.daily.get("temp_baseline") is not None else None,
        "offNight": r.off_night,
        "offReasons": r.off_reasons or [],
        "recovery": r.recovery or {},
        "cvhr": rounded(r.cvhr["fcv"]) if r.cvhr else None,
    }
    if sl:
        asleep = sl["asleep"] or None
        row["sleep"] = {
            "asleep": sl["asleep"],
            "awake": sl["awake"],
            "efficiency": rounded(sl["efficiency"]),
            "minutes": sl["minutes"],
            "deepPct": rounded(100 * sl["minutes"].get("DEEP", 0) / asleep) if asleep and sl["staged"] else None,
            "remPct": rounded(100 * sl["minutes"].get("REM", 0) / asleep) if asleep and sl["staged"] else None,
            "awakenings": sl["awakenings"],
            "toFallAsleep": sl["to_fall_asleep"],
            "awakeMid": sl["awake_mid"],
            "afterWaking": sl["after_waking"],
            # for the sleep diary: [start, end, stage] in hours after 18:00
            "segments": [[rounded(hours_after_18(a, night), 3), rounded(hours_after_18(b2, night), 3),
                          STAGE_CODE.get(k, "A")] for a, b2, k in sl["stages"]],
        }
    if r.spo2_summary:  # dip counts only when the SpO2 data is dense enough
        row["spo2"] = {**{k: rounded(r.spo2_summary[k], 2) for k in ("avg", "min", "below90")},
                       "odi3": rounded(s["odi3"], 2) if s else None, "odi4": rounded(s["odi4"], 2) if s else None}
    if r.hr_summary:  # surges only when heart rate is dense enough
        row["hr"] = {"median": r.hr_summary["median"], "lowest": r.hr_summary["lowest"],
                     "surgesPerHour": rounded(h["surges_per_hour"], 2) if h else None,
                     "surgesWithoutAwakening": rounded(h["surges_without_awakening"], 2) if h else None}
    return row


def detail(r):
    t0 = r.start

    def sec(t):
        return round((t - t0).total_seconds())

    out = {"id": rec_id(r), "start": t0.isoformat(timespec="seconds"), "end": r.end.isoformat(timespec="seconds"),
           "stages": [], "short": [], "spo2": [], "settling": [], "dips": [], "hr": [], "surges": []}
    if r.sleep:
        out["stages"] = [[sec(a), sec(b), STAGE_CODE.get(k, "A")] for a, b, k in r.sleep["stages"]]
        out["short"] = [[sec(a), sec(b)] for a, b in r.sleep["short_awakenings"]]
    if r.spo2_stats:
        out["spo2"] = [[sec(t), v] for t, v in r.spo2]
        out["settling"] = [sec(t) for t, _ in r.spo2_stats["settling"]]
        out["dips"] = [[sec(a), sec(b), nadir, base] for a, b, nadir, base in r.spo2_stats["ev3"]]
    if r.hr_stats:
        out["hr"] = [[sec(t), v] for t, v in r.hr_stats["samples"]]
        out["surges"] = [[sec(t), peak] for t, peak in r.hr_stats["surges"]]
    out["cvhr"] = [sec(t) for t in r.cvhr["dips"]] if r.cvhr else []
    return out


def export(recs, out_dir, findings=None, references=None, profile=None, period_metrics=None):
    """Write summary.json and nights/<id>.json into out_dir. Returns the number of files."""
    nights_dir = out_dir / "nights"
    nights_dir.mkdir(parents=True, exist_ok=True)
    for old in nights_dir.glob("*.json"):
        old.unlink()
    summary = {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "metrics": period_metrics or metrics(recs),
        "profile": profile,
        "recordings": [summary_row(r) for r in recs],
        "findings": findings or [],
        "minNights": MIN_NIGHTS,  # the literature report needs this many nights
        "references": references or [],
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, separators=(",", ":")))
    for r in recs:
        (nights_dir / f"{rec_id(r)}.json").write_text(json.dumps(detail(r), separators=(",", ":")))
    return len(recs) + 1
