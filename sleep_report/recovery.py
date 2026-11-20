"""Nightly recovery signals (HRV, resting heart rate, skin temperature) and "off" nights.

Fitbit's daily summaries are keyed by the date you woke up; they belong to the main
sleep that ended on that date. An off night is one where at least two signals moved
clearly away from your own recent normal in the direction that illness, alcohol or
strain push them: heart rate up, HRV down, breathing rate up, skin temperature up.
"""
from datetime import timedelta
from statistics import median

BASELINE_NIGHTS = 28  # compare with this many previous nights
MIN_BASELINE = 7  # need at least this many before judging a night
Z = 2.0  # how far from normal counts as a clear deviation
# floors for the spread, so a very steady baseline doesn't make tiny changes look big
MIN_SPREAD = {"hr": 1.5, "hrv": 2.0, "breathing": 0.3, "temp": 0.1}
# direction that illness/alcohol/strain push each signal
DIRECTION = {"hr": 1, "hrv": -1, "breathing": 1, "temp": 1}
LABEL = {"hr": "heart rate up", "hrv": "HRV down", "breathing": "breathing rate up", "temp": "skin temperature up"}


def attach_daily(recs, daily):
    """Give each night the daily summary of the morning it ended on."""
    for r in recs:
        if r.kind == "night":
            r.daily = daily.get(r.end.date().isoformat()) or daily.get((r.end - timedelta(hours=12)).date().isoformat())


def signals(r):
    """The four nightly signals; None where missing."""
    d = r.daily or {}
    temp = d.get("temp") - d.get("temp_baseline") if d.get("temp") is not None and d.get("temp_baseline") is not None else None
    return {
        "hr": r.hr_summary["median"] if r.hr_summary else d.get("nonrem_hr"),
        "hrv": d.get("hrv"),
        "breathing": r.breathing["full"]["rate"] if r.breathing and r.breathing["full"] else None,
        "temp": temp,
    }


def mark_off_nights(recs):
    """Sets r.recovery = {signal: {value, baseline, z, flagged}}, r.off_night and r.off_reasons."""
    nights = sorted((r for r in recs if r.kind == "night"), key=lambda r: r.start)
    history = []
    for r in nights:
        sig = signals(r)
        r.recovery, reasons = {}, []
        for key, value in sig.items():
            past = [h[key] for h in history[-BASELINE_NIGHTS:] if h[key] is not None]
            if value is None or len(past) < MIN_BASELINE:
                continue
            base = median(past)
            spread = max(MIN_SPREAD[key], 1.4826 * median(abs(x - base) for x in past))
            z = (value - base) / spread
            flagged = z * DIRECTION[key] >= Z
            r.recovery[key] = {"value": value, "baseline": round(base, 2), "z": round(z, 2), "flagged": flagged}
            if flagged:
                reasons.append(LABEL[key])
        r.off_night = len(reasons) >= 2
        r.off_reasons = reasons
        history.append(sig)
