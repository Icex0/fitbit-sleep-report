"""Whole-period metrics (medians, regularity, timing) that the literature report is checked against."""
from datetime import datetime, timedelta
from statistics import median, pstdev

from .analysis import night_of


def hours_after_18(t, night):
    """Clock time as hours after 18:00 on the night's evening (so 02:30 -> 8.5)."""
    return (t - datetime.fromisoformat(night) - timedelta(hours=18)).total_seconds() / 3600


def sleep_regularity_index(recs):
    """Sleep Regularity Index: the chance of being in the same state (asleep/awake)
    at any two time points 24 h apart, scaled to -100..100 (100 = identical days).

    Uses Fitbit's sleep stages (naps included) for pairs of consecutive days that
    both have a recorded night, so days the watch wasn't worn don't count as awake.
    """
    asleep = set()
    for r in recs:
        if r.sleep:
            for a, b, kind in r.sleep["stages"]:
                if kind != "AWAKE":
                    m = int(a.timestamp() // 60)
                    asleep.update(range(m, int(b.timestamp() // 60)))
    nights = sorted({night_of(r.start) for r in recs if r.kind == "night" and r.sleep})
    agree = total = 0
    for day in nights:
        nxt = (datetime.fromisoformat(day) + timedelta(days=1)).date().isoformat()
        if nxt not in nights:
            continue
        start = int((datetime.fromisoformat(day) + timedelta(hours=18)).timestamp() // 60)
        for m in range(start, start + 1440):
            agree += (m in asleep) == (m + 1440 in asleep)
            total += 1
    return round(-100 + 200 * agree / total, 1) if total else None


# RMSSD (ms) of Fitbit users, 06:00-07:00, by age: (25th percentile, median, 75th percentile),
# women and men averaged (no significant sex difference in RMSSD). Natarajan et al. 2020,
# supplementary table S2 of the preprint.
HRV_NORMS = {
    20: ((37 + 45) / 2, (56 + 66) / 2, (85 + 96) / 2),
    25: ((32 + 35) / 2, (48 + 54) / 2, (73 + 79) / 2),
    30: ((31 + 34) / 2, (45 + 49) / 2, (67 + 71) / 2),
    35: ((29 + 31) / 2, (41 + 43) / 2, (60 + 62) / 2),
    40: ((26 + 27) / 2, (37 + 38) / 2, (52 + 54) / 2),
    45: ((24 + 25) / 2, (33 + 34) / 2, (46 + 48) / 2),
    50: ((22 + 23) / 2, (31 + 31) / 2, (42 + 42) / 2),
    55: ((22 + 21) / 2, (29 + 29) / 2, (40 + 39) / 2),
    60: ((21 + 20) / 2, (28 + 27) / 2, (38 + 37) / 2),
}


def hrv_norm(age):
    """(p25, median, p75) RMSSD for an age, interpolated between the 5-year table points."""
    a = min(60, max(20, age))
    lo = max(k for k in HRV_NORMS if k <= a)
    hi = min(k for k in HRV_NORMS if k >= a)
    w = 0 if hi == lo else (a - lo) / (hi - lo)
    return tuple(round(x + w * (y - x), 1) for x, y in zip(HRV_NORMS[lo], HRV_NORMS[hi]))


def metrics(recs, free_evenings=("Fri", "Sat"), usual_bedtime_h=5.0, age=None):
    """Numbers describing the whole period. Missing data gives None.

    free_evenings: weekday names of evenings before a day off (for social jetlag).
    usual_bedtime_h: the bedtime the person's schedule asks for, in hours after 18:00.
    """
    nights = [r for r in recs if r.kind == "night"]
    naps = [r for r in recs if r.kind == "nap"]
    slept = [r for r in nights if r.sleep and r.sleep["asleep"]]
    staged = [r for r in slept if r.sleep["staged"]]
    oxy = [r.spo2_stats for r in nights if r.spo2_stats]  # dense SpO2: dips can be counted
    oxy_level = [r.spo2_summary for r in nights if r.spo2_summary]
    hr = [r.hr_stats for r in nights if r.hr_stats]  # dense heart rate: surges can be counted
    hr_level = [r.hr_summary for r in nights if r.hr_summary]
    breaths = [r.breathing["full"]["rate"] for r in nights if r.breathing and r.breathing["full"]]
    med = lambda xs: round(median(xs), 2) if xs else None  # noqa: E731
    share = lambda xs, pred: round(100 * sum(map(pred, xs)) / len(xs), 1) if xs else None  # noqa: E731

    onset = [hours_after_18(r.start, night_of(r.start)) for r in nights]
    wake = [hours_after_18(r.end, night_of(r.start)) for r in nights]
    mid = [(a + b) / 2 for a, b in zip(onset, wake)]
    weekday = [datetime.fromisoformat(night_of(r.start)).strftime("%a") for r in nights]
    free = [m for m, d in zip(mid, weekday) if d in free_evenings]
    work = [m for m, d in zip(mid, weekday) if d not in free_evenings]
    by_day = {}
    for m, d in zip(mid, weekday):
        by_day.setdefault(d, []).append(m)

    def waso(s):  # wake after sleep onset: awake stages in the night + brief awakenings
        return s["awake_mid"] + sum((b - a).total_seconds() / 60 for a, b in s["short_awakenings"])

    def long_awakenings(s):  # awake periods over 5 minutes between falling asleep and final waking
        slept_parts = [(a, b) for a, b, k in s["stages"] if k != "AWAKE"]
        if not slept_parts:
            return 0
        first, last = slept_parts[0][0], slept_parts[-1][1]
        return sum(1 for a, b, k in s["stages"]
                   if k == "AWAKE" and first <= a and b <= last and (b - a) > timedelta(minutes=5))

    nap_days = {night_of(r.start) for r in naps}
    evening_naps = [r for r in naps if 17 <= r.start.hour < 23]
    # bedtime on nights that followed an evening nap, vs other nights
    nap_evenings = {r.start.date().isoformat() for r in evening_naps}
    after_nap = [o for r, o in zip(nights, onset) if r.name in nap_evenings]
    no_nap = [o for r, o in zip(nights, onset) if r.name not in nap_evenings]
    return {
        "nights": len(nights),
        "naps": len(naps),
        # how many nights each kind of data covers: what a finding is "based on"
        "slept_nights": len(slept),
        "staged_nights": len(staged),
        "spo2_nights": len(oxy),
        "spo2_level_nights": len(oxy_level),
        "hr_nights": len(hr_level),
        "surge_nights": len(hr),
        "breathing_nights": len(breaths),
        "hrv_nights": sum(1 for r in nights if r.daily and r.daily.get("hrv") is not None),
        "resting_hr_nights": sum(1 for r in nights if r.daily and r.daily.get("resting_hr") is not None),
        "recovery_nights": sum(1 for r in nights if r.recovery),
        "first_night": nights[0].name if nights else None,
        "last_night": nights[-1].name if nights else None,
        # amount
        "asleep_h": med([r.sleep["asleep"] / 60 for r in slept]),
        "pct_nights_under_7h": share(slept, lambda r: r.sleep["asleep"] < 420),
        "pct_nights_under_6h": share(slept, lambda r: r.sleep["asleep"] < 360),
        "pct_nights_under_8h": share(slept, lambda r: r.sleep["asleep"] < 480),
        "pct_nights_over_9h": share(slept, lambda r: r.sleep["asleep"] > 540),
        "asleep_sd_h": round(pstdev([r.sleep["asleep"] / 60 for r in slept]), 2) if len(slept) > 1 else None,
        "max_short_run": longest_run(slept, lambda r: r.sleep["asleep"] < 360),
        # timing & regularity
        "bedtime_h": med(onset),  # hours after 18:00
        "usual_bedtime_h": usual_bedtime_h,
        "bedtime_delay_h": round(median(onset) - usual_bedtime_h, 2) if onset else None,
        "wake_h": med(wake),
        "midsleep_h": med(mid),
        "bedtime_sd_h": round(pstdev(onset), 2) if len(onset) > 1 else None,
        "wake_sd_h": round(pstdev(wake), 2) if len(wake) > 1 else None,
        "midsleep_sd_h": round(pstdev(mid), 2) if len(mid) > 1 else None,
        "sri": sleep_regularity_index(recs),
        # share of nights before a workday with sleep onset in 'traditional' hours, 20:00-02:00 (Zheng 2024)
        "pct_workdays_onset_20_02": share([o for o, d in zip(onset, weekday) if d not in free_evenings],
                                          lambda o: 2 <= o < 8),
        "pct_onset_after_01": share(onset, lambda o: o > 7),  # after 01:00 (Lok 2024)
        "social_jetlag_h": round(abs(median(free) - median(work)), 2) if free and work else None,
        "midsleep_by_weekday": {d: round(median(v), 2) for d, v in by_day.items()},
        "weekly_drift_h": round(max(map(median, by_day.values())) - min(map(median, by_day.values())), 2)
        if len(by_day) >= 5 else None,
        # quality
        "efficiency_pct": med([r.sleep["efficiency"] for r in slept if r.sleep["efficiency"]]),
        "latency_min": med([r.sleep["to_fall_asleep"] for r in slept]),
        "pct_latency_over_30": share(slept, lambda r: r.sleep["to_fall_asleep"] > 30),
        "waso_min": med([waso(r.sleep) for r in slept]),
        "long_awakenings": med([long_awakenings(r.sleep) for r in slept]),
        "awakenings": med([r.sleep["awakenings"] for r in slept]),
        "after_waking_min": med([r.sleep["after_waking"] for r in slept]),
        "deep_pct": med([100 * r.sleep["minutes"].get("DEEP", 0) / r.sleep["asleep"] for r in staged]),
        "rem_pct": med([100 * r.sleep["minutes"].get("REM", 0) / r.sleep["asleep"] for r in staged]),
        # naps
        "pct_days_with_nap": round(100 * len(nap_days & {r.name for r in nights}) / len(nights), 1) if nights else None,
        "nap_min": med([r.sleep["asleep"] for r in naps if r.sleep]),
        "evening_naps": len(evening_naps),
        # a rate, so the verdict doesn't depend on how many nights were uploaded
        "evening_naps_per_week": round(7 * len(evening_naps) / len(nights), 2) if nights else None,
        "pct_naps_over_60": share([r for r in naps if r.sleep], lambda r: r.sleep["asleep"] > 60),
        "bedtime_after_evening_nap_h": med(after_nap),
        "bedtime_without_evening_nap_h": med(no_nap),
        "nap_bedtime_delay_min": round(60 * (median(after_nap) - median(no_nap))) if after_nap and no_nap else None,
        # oxygen
        "odi3": med([s["odi3"] for s in oxy]),
        "odi4": med([s["odi4"] for s in oxy]),
        "max_odi3": round(max(s["odi3"] for s in oxy), 2) if oxy else None,
        "spo2_avg": med([s["avg"] for s in oxy_level]),
        "spo2_min": med([s["min"] for s in oxy_level]),
        "below90_pct": med([s["below90"] for s in oxy_level]),
        # heart & breathing
        "hr_median": med([h["median"] for h in hr_level]),
        "hr_lowest": med([h["lowest"] for h in hr_level]),
        "surges_per_hour": med([h["surges_per_hour"] for h in hr]),
        "surges_without_awakening": med([h["surges_without_awakening"] for h in hr]),
        "breathing_rate": med(breaths),
        "breathing_min": min(breaths) if breaths else None,
        "breathing_max": max(breaths) if breaths else None,
        # recovery (Fitbit daily summaries) and off nights
        "hrv_median": med([r.daily["hrv"] for r in nights if r.daily and r.daily.get("hrv") is not None]),
        "hrv_deep_median": med([r.daily["hrv_deep"] for r in nights if r.daily and r.daily.get("hrv_deep") is not None]),
        "resting_hr": med([r.daily["resting_hr"] for r in nights if r.daily and r.daily.get("resting_hr") is not None]),
        "hrv_kind": next((r.daily.get("hrv_kind", "rmssd") for r in nights if r.daily and r.daily.get("hrv") is not None), None),
        "breathing_disturbances_median": med([r.daily["breathing_disturbances"] for r in nights
                                              if r.daily and r.daily.get("breathing_disturbances") is not None]),
        "off_nights": sum(1 for r in nights if r.off_night) if any(r.recovery for r in nights) else None,
        "off_nights_before_free_day": sum(1 for r, d in zip(nights, weekday) if r.off_night and d in free_evenings),
        "pct_off_nights": share([r for r in nights if r.recovery], lambda r: r.off_night),
        **off_night_deltas(nights),
        **weekly_metrics(nights),
        **cvhr_metrics(nights),
        **hrv_vs_norm(nights, age),
    }


def weekly(nights):
    """Per 7-night window (any 7 consecutive calendar days with at least 5 nights, as in the
    7-day actigraphy studies): SD of sleep-onset time and of time asleep, and mean time asleep."""
    by_day = {r.name[:10]: r for r in nights if r.sleep and r.sleep["asleep"]}
    days = sorted(by_day)
    out = []
    for end in days:
        last = datetime.fromisoformat(end)
        week = [by_day[d] for d in days if timedelta(0) <= last - datetime.fromisoformat(d) < timedelta(days=7)]
        if len(week) < 5:
            continue
        onset = [hours_after_18(r.start, r.name[:10]) for r in week]
        asleep = [r.sleep["asleep"] / 60 for r in week]
        out.append({"onset_sd": pstdev(onset), "asleep_sd": pstdev(asleep), "asleep_mean": sum(asleep) / len(asleep)})
    return out


def weekly_metrics(nights):
    w = weekly(nights)
    if not w:
        return {}
    share = lambda pred: round(100 * sum(map(pred, w)) / len(w), 1)  # noqa: E731
    return {
        "weeks": len(w),
        "onset_sd7_min": round(60 * median(x["onset_sd"] for x in w)),
        "asleep_sd7_min": round(60 * median(x["asleep_sd"] for x in w)),
        "pct_weeks_onset_sd_over_90": share(lambda x: x["onset_sd"] > 1.5),
        "pct_weeks_under_6h": share(lambda x: x["asleep_mean"] < 6),
        "pct_weeks_6_to_7h": share(lambda x: 6 <= x["asleep_mean"] < 7),
    }


def longest_run(nights, pred):
    """Most consecutive calendar nights meeting pred; a night without data breaks the run."""
    best = run = 0
    prev = None
    for r in sorted(nights, key=lambda r: r.name):
        day = datetime.fromisoformat(r.name[:10])
        consecutive = prev is not None and day - prev == timedelta(days=1)
        run = (run + 1 if consecutive else 1) if pred(r) else 0
        best = max(best, run)
        prev = day
    return best


def off_night_deltas(nights):
    """How far off nights were from the person's own normal, per signal (median over off nights)."""
    off = [r for r in nights if r.off_night]
    out = {}
    for key, name in (("hr", "off_hr_delta"), ("hrv", "off_hrv_delta"), ("breathing", "off_breathing_delta"), ("temp", "off_temp_delta")):
        deltas = [r.recovery[key]["value"] - r.recovery[key]["baseline"] for r in off if key in r.recovery]
        out[name] = round(median(deltas), 2) if deltas else None
    out["off_with_breathing_or_temp_up"] = sum(1 for r in off if any(r.recovery.get(k, {}).get("flagged") for k in ("breathing", "temp")))
    return out


def cvhr_metrics(nights):
    with_cvhr = [r for r in nights if r.cvhr]
    if not with_cvhr:
        return {}
    fcv = [r.cvhr["fcv"] for r in with_cvhr]

    def rate(kinds):
        dips = sum(r.cvhr["by_stage"].get(k, 0) for r in with_cvhr for k in kinds)
        hours = sum(r.cvhr["stage_hours"].get(k, 0) for r in with_cvhr for k in kinds)
        return round(dips / hours, 1) if hours > 1 else None

    return {
        "cvhr_median": round(median(fcv), 1),
        "cvhr_nights_over_11": sum(f >= 11 for f in fcv),
        "cvhr_nights_over_15": sum(f >= 15 for f in fcv),
        "cvhr_nights": len(fcv),
        "cvhr_awake_rate": rate(["AWAKE"]),
        "cvhr_rem_rate": rate(["REM"]),
        "cvhr_nrem_rate": rate(["LIGHT", "DEEP", "ASLEEP"]),
        "cvhr_deep_rate": rate(["DEEP"]),
    }


def hrv_vs_norm(nights, age):
    # the reference values are RMSSD; Apple's HRV is SDNN, a different measure
    values = [r.daily["hrv"] for r in nights
              if r.daily and r.daily.get("hrv") is not None and r.daily.get("hrv_kind", "rmssd") == "rmssd"]
    if not values or age is None:
        return {}
    p25, mid, p75 = hrv_norm(age)
    hrv = median(values)
    return {
        "hrv_norm_p25": p25, "hrv_norm_median": mid, "hrv_norm_p75": p75,
        # <0: below the 25th percentile, 0-1: middle half, >1: above the 75th percentile
        "hrv_position": round((hrv - p25) / (p75 - p25), 2),
    }
