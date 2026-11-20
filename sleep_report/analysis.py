"""Turning raw readings into nights and naps, and the numbers reported for each."""
from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from . import cvhr, store
from .recovery import attach_daily, mark_off_nights
from .store import session_key, to_local

GAP = timedelta(minutes=3)  # longer than this between SpO2 samples = missing data
SETTLE = timedelta(minutes=2)  # readings this soon after a gap are left out of the stats
# Dip and surge detection need dense data; sparser data (e.g. Apple Watch) only gets summaries.
DENSE_SPO2 = timedelta(seconds=90)  # median gap between SpO2 readings
DENSE_HR = timedelta(seconds=10)  # median gap between heart-rate readings
ASLEEP_STAGES = ("LIGHT", "DEEP", "REM", "ASLEEP")
HR_SURGE = 10  # bpm above the previous minute's median that counts as a heart-rate surge


@dataclass
class Recording:
    name: str  # night: evening date "2026-10-26"; nap: "2026-10-26 18:24 nap"
    kind: str  # "night" or "nap"
    spo2: list  # [(local datetime, percent)]
    sleep: dict = None  # parse_sleep() result when Fitbit sleep data is available
    spo2_stats: dict = None  # spo2_stats() result when there are enough readings
    spo2_summary: dict = None  # average, lowest, % below 90: also from sparse SpO2
    hr_stats: dict = None  # heart_rate_stats() result when heart rate is dense enough
    hr_summary: dict = None  # median and lowest heart rate: also from sparse heart rate
    breathing: dict = None  # parse_breathing() result for this sleep, if any
    daily: dict = None  # Fitbit's daily summary for the morning after (HRV, resting HR, temperature)
    recovery: dict = None  # recovery.mark_off_nights(): each signal against your recent normal
    off_night: bool = False
    off_reasons: list = None
    cvhr: dict = None  # cvhr.detect(): cyclic heart-rate variation

    @property
    def start(self):
        return self.sleep["start"] if self.sleep else self.spo2[0][0]

    @property
    def end(self):
        return self.sleep["end"] if self.sleep else self.spo2[-1][0]


def dense(samples, max_gap):
    """True when the typical (median) gap between readings is at most max_gap."""
    gaps = sorted(b[0] - a[0] for a, b in zip(samples, samples[1:]))
    return bool(gaps) and gaps[len(gaps) // 2] <= max_gap


def night_of(t):
    """A night runs 18:00 -> 18:00 and is named by the evening's date."""
    return (t - timedelta(hours=18)).date().isoformat()


# ---------------------------------------------------------------- recordings

def build_recordings(rows, raw_sleeps, heart=None, raw_breathing=()):
    """Nights and naps, sorted by start time.

    Where Fitbit sleep sessions exist they define the nights and naps, and the
    SpO2 readings, heart rate (`heart`: {session key: samples}) and breathing
    summary of each session are attached. SpO2 readings from before or after
    the downloaded sleep history fall back to guess_sleeps().
    """
    readings = sorted((datetime.fromisoformat(local), v) for local, v in rows.values())
    sessions = sorted((parse_sleep(s) for s in raw_sleeps), key=lambda s: s["start"])
    if sessions and not any(s["main"] for s in sessions):
        for s in sessions:  # no main-sleep flags in the data: treat 3 h+ as a night
            s["main"] = s["period"] >= 180
    # Fitbit marks a main sleep per day the sleep ends on, so an evening sleep can be a second main sleep
    # in one 18:00-18:00 night: the longest is the night, the others are naps
    longest = {}
    for s in sessions:
        k = night_of(s["start"])
        if s["main"] and (k not in longest or s["asleep"] > longest[k]["asleep"]):
            longest[k] = s
    for s in sessions:
        s["main"] = longest.get(night_of(s["start"])) is s

    recs = []
    times = [t for t, _ in readings]
    for s in sessions:
        spo2 = readings[bisect_left(times, s["start"]):bisect_right(times, s["end"])]
        if s["main"]:
            recs.append(Recording(night_of(s["start"]), "night", spo2, s))
        else:
            recs.append(Recording(f"{s['start']:%Y-%m-%d %H:%M} nap", "nap", spo2, s))

    if sessions:
        first, last = night_of(sessions[0]["start"]), night_of(sessions[-1]["start"])
        covered = [(s["start"], s["end"]) for s in sessions]
        # readings from a sleep that crosses 18:00 fall in the next night's window but belong to that sleep
        readings = [(t, v) for t, v in readings
                    if not first <= night_of(t) <= last and not any(a <= t <= b for a, b in covered)]
    recs += guess_sleeps(readings)

    # A breathing summary is stamped at or some time after the end of the sleep it
    # describes (often when the watch syncs): give it to the latest sleep that ended
    # before it, at most 4 h earlier. Prefer measured summaries, then the earliest.
    slept = sorted((r for r in recs if r.sleep), key=lambda r: r.end)
    candidates = defaultdict(list)
    for b in map(parse_breathing, raw_breathing):
        before = [r for r in slept if r.end - timedelta(minutes=15) <= b["time"] <= r.end + timedelta(hours=4)]
        if before:
            candidates[id(before[-1])].append(b)
    for r in slept:
        if candidates[id(r)]:
            r.breathing = min(candidates[id(r)], key=lambda b: (b["full"] is None, b["time"]))

    for r in recs:
        if len(r.spo2) >= 30 and dense(r.spo2, DENSE_SPO2):
            r.spo2_stats = spo2_stats(r.spo2)
        if len(r.spo2) >= 3:
            vals = [v for _, v in (r.spo2_stats["samples"] if r.spo2_stats else r.spo2)]
            r.spo2_summary = {"avg": sum(vals) / len(vals), "min": min(vals),
                              "below90": 100 * sum(v < 90 for v in vals) / len(vals)}
        if r.sleep:
            samples = (heart or {}).get(r.sleep["key"], [])
            samples = [(t, v) for t, v in samples if r.start <= t <= r.end]
            if len(samples) >= 300 and r.sleep["asleep"] and dense(samples, DENSE_HR):
                r.hr_stats = heart_rate_stats(samples, r.sleep)
            if r.hr_stats:
                r.hr_summary = {"median": r.hr_stats["median"], "lowest": r.hr_stats["lowest"]}
            elif len(samples) >= 20:
                vals = sorted(v for _, v in samples)
                r.hr_summary = {"median": vals[len(vals) // 2], "lowest": vals[0]}
    return sorted(recs, key=lambda r: r.start)


def load_recordings(data_dir, sleeps=None):
    """Everything in a data folder (the shared format in store.py) as analysed nights and naps."""
    sleeps = store.load_sleep(data_dir / "sleep.json") if sleeps is None else sleeps
    recs = build_recordings(store.load_spo2(data_dir / "spo2.csv"), sleeps.values(),
                            store.load_heart_rate(data_dir / "heart_rate"),
                            store.load_breathing(data_dir / "breathing.json").values())
    attach_daily(recs, store.load_daily(data_dir / "daily.json"))
    mark_off_nights(recs)
    cvhr.annotate(recs)
    return recs


def parse_sleep(raw):
    """Fitbit sleep session -> local times, stage segments and minute totals."""
    iv = raw["interval"]
    start = to_local(iv["startTime"], iv.get("startUtcOffset"))
    end = to_local(iv["endTime"], iv.get("endUtcOffset", iv.get("startUtcOffset")))
    stages = []
    for st in raw.get("stages", []):
        stages.append((to_local(st["startTime"], st.get("startUtcOffset", iv.get("startUtcOffset"))),
                       to_local(st["endTime"], st.get("endUtcOffset", iv.get("endUtcOffset"))),
                       st.get("type", "")))

    minutes = defaultdict(int)
    for a, b, kind in stages:
        minutes[kind] += round((b - a).total_seconds() / 60)
    summary = raw.get("summary", {})
    for s in summary.get("stagesSummary", []):  # prefer Fitbit's own totals when present
        minutes[s["type"]] = int(s.get("minutes", 0))

    asleep = int(summary.get("minutesAsleep") or sum(minutes[k] for k in ASLEEP_STAGES))
    period = int(summary.get("minutesInSleepPeriod") or round((end - start).total_seconds() / 60))

    # Brief awakenings (30 s to a few minutes) are listed separately from the stages.
    short = [(to_local(a["startTime"], a.get("startUtcOffset", iv.get("startUtcOffset"))),
              to_local(a["endTime"], a.get("endUtcOffset", iv.get("endUtcOffset"))))
             for a in raw.get("shortAwakenings", [])]
    # Split awake time into before falling asleep, during the night, after the final wake-up.
    slept = [(a, b) for a, b, kind in stages if kind != "AWAKE"]
    first, last = (slept[0][0], slept[-1][1]) if slept else (start, end)
    mid_awake = [(a, b) for a, b, kind in stages if kind == "AWAKE" and first <= a and b <= last]

    def mins(a, b):
        return max(0, round((b - a).total_seconds() / 60))

    meta = raw.get("metadata", {})
    return {
        "key": session_key(raw),
        "start": start,
        "end": end,
        "stages": stages,
        "short_awakenings": short,
        "staged": raw.get("type") == "STAGES",
        "minutes": dict(minutes),
        "asleep": asleep,
        "awake": int(summary.get("minutesAwake") or minutes.get("AWAKE", 0)),
        "to_fall_asleep": mins(start, first),
        "awake_mid": sum(mins(a, b) for a, b in mid_awake),
        "after_waking": mins(last, end),
        "period": period,
        "efficiency": 100 * asleep / period if period else None,
        "awakenings": len(mid_awake) + len(short),
        "main": bool(meta.get("mainSleep")),
    }


def guess_sleeps(readings):
    """Find nights and naps from SpO2 readings alone (no Fitbit sleep data).

    The watch only records SpO2 while you sleep. Each night's readings are split
    into blocks wherever there's a gap over 1 h. The biggest block is the main
    sleep; neighbouring blocks join it only if they hold at least 1 h of readings
    and the gap is under 2.5 h (waking up mid-night). Other blocks with at least
    45 min of readings are naps; anything shorter is left out.
    """
    windows = defaultdict(list)
    for t, v in readings:
        windows[night_of(t)].append((t, v))
    recs, naps = [], []
    for night, samples in sorted(windows.items()):
        blocks = [[samples[0]]]
        for prev, cur in zip(samples, samples[1:]):
            if cur[0] - prev[0] > timedelta(hours=1):
                blocks.append([])
            blocks[-1].append(cur)

        def joins(block, gap):
            return len(block) >= 60 and gap <= timedelta(hours=2.5)

        lo = hi = max(range(len(blocks)), key=lambda i: len(blocks[i]))
        while lo > 0 and joins(blocks[lo - 1], blocks[lo][0][0] - blocks[lo - 1][-1][0]):
            lo -= 1
        while hi < len(blocks) - 1 and joins(blocks[hi + 1], blocks[hi + 1][0][0] - blocks[hi][-1][0]):
            hi += 1
        main = [s for b in blocks[lo:hi + 1] for s in b]
        if len(main) >= 120:  # at least 2 h of readings
            recs.append(Recording(night, "night", main))
        else:
            lo, hi = len(blocks), -1  # no main sleep: every block may be a nap
        naps += [b for i, b in enumerate(blocks) if not lo <= i <= hi and len(b) >= 45]

    # a nap running across 18:00 lands in two windows; stitch it back together
    merged = []
    for nap in sorted(naps):
        if merged and nap[0][0] - merged[-1][-1][0] <= timedelta(hours=1):
            merged[-1] = merged[-1] + nap
        else:
            merged.append(nap)
    return recs + [Recording(f"{n[0][0]:%Y-%m-%d %H:%M} nap", "nap", n) for n in merged]


# ---------------------------------------------------------------- heart rate and breathing

def heart_rate_stats(samples, sleep):
    """Sleeping heart rate and heart-rate surges while asleep.

    A surge is a rise of at least HR_SURGE bpm above the median of the previous
    minute that lasts at least 6 seconds (it ends when HR falls back to within
    half that). Brief arousals and breathing events usually come with one.
    Readings inside Fitbit's AWAKE stages are left out.
    """
    awake = [(a, b) for a, b, kind in sleep["stages"] if kind == "AWAKE"]
    asleep = [(t, v) for t, v in samples if not any(a <= t < b for a, b in awake)]
    times = [t for t, _ in asleep]
    surges, current = [], None
    for k, (t, v) in enumerate(asleep):
        if k and t - asleep[k - 1][0] > timedelta(seconds=30):
            current = None  # awake stage or missing data in between: start over
        if current:
            if v <= current[1] + HR_SURGE / 2:
                if t - current[0] >= timedelta(seconds=6):
                    surges.append((current[0], current[2]))
                current = None
            else:
                current[2] = max(current[2], v)
            continue
        window = sorted(x for _, x in asleep[bisect_left(times, t - timedelta(seconds=60)):k])
        if len(window) >= 15 and v >= window[len(window) // 2] + HR_SURGE:
            current = [t, window[len(window) // 2], v]

    minutes = defaultdict(list)
    for t, v in asleep:
        minutes[t.replace(second=0)].append(v)
    per_minute = sorted(sorted(vs)[len(vs) // 2] for vs in minutes.values())
    short = [a for a, _ in sleep["short_awakenings"]]
    near = lambda a, b: abs((a - b).total_seconds()) <= 60  # noqa: E731
    return {
        "samples": samples,
        "surges": surges,
        "median": per_minute[len(per_minute) // 2],
        "lowest": per_minute[0],  # lowest 1-minute median, so a single odd reading doesn't count
        "surges_per_hour": len(surges) / (sleep["asleep"] / 60),
        # share of Fitbit's brief awakenings that came with a surge (a check that both see the same thing)
        "awakenings_with_surge": (sum(any(near(w, t) for t, _ in surges) for w in short) / len(short)
                                  if short else None),
        # surges with no brief awakening nearby: arousals too short for Fitbit to call "awake"
        "surges_without_awakening": sum(not any(near(t, w) for w in short) for t, _ in surges)
                                    / (sleep["asleep"] / 60),
    }


def parse_breathing(raw):
    """Breathing-rate summary for one sleep; a stage the watch couldn't measure is None."""
    st = raw["sampleTime"]

    def stats(key):
        s = raw.get(key) or {}
        rate = s.get("breathsPerMinute") or 0
        return {"rate": rate, "sd": s.get("standardDeviation"), "snr": s.get("signalToNoise")} if rate else None

    return {
        "time": to_local(st["physicalTime"], st.get("utcOffset")),
        "full": stats("fullSleepStats"),
        "deep": stats("deepSleepStats"),
        "light": stats("lightSleepStats"),
        "rem": stats("remSleepStats"),
    }


# ---------------------------------------------------------------- SpO2

def split_settling(samples):
    """The first readings after a gap read low while the watch's average warms up."""
    keep, settling = [], []
    start = samples[0][0]
    for i, (t, v) in enumerate(samples):
        if i and t - samples[i - 1][0] > timedelta(minutes=10):
            start = t
        (settling if t - start < SETTLE else keep).append((t, v))
    return keep, settling


def desaturations(samples, drop):
    """Count dips of >= `drop` points below the recent baseline.

    Baseline = 75th percentile of the previous 10 minutes, frozen for the
    duration of a dip. A dip ends when SpO2 recovers to within 1 point of
    that baseline, the data has a gap, or after 5 minutes (a longer drop is a
    shift in level, not a breathing pause; the baseline then re-adapts).
    Returns [(start, end, nadir, baseline)].
    """
    events = []
    current = None
    quiet_until = None  # after a capped dip, wait for the baseline to re-adapt
    for i, (t, v) in enumerate(samples):
        if current:
            gap = t - samples[i - 1][0] > GAP
            capped = t - current[0] > timedelta(minutes=5)
            if gap or capped or v >= current[3] - 1:
                events.append((current[0], samples[i - 1][0], current[2], current[3]))
                current = None
                if capped and not gap:
                    quiet_until = t + timedelta(minutes=10)
            else:
                current[2] = min(current[2], v)
                continue
        if quiet_until and t < quiet_until:
            continue
        window = sorted(sv for st, sv in samples[max(0, i - 10):i] if t - st <= timedelta(minutes=10))
        if len(window) < 3:
            continue
        base = window[int(len(window) * 0.75)]
        if v <= base - drop:
            current = [t, None, v, base]
    if current:
        events.append((current[0], samples[-1][0], current[2], current[3]))
    return events


def spo2_stats(recorded):
    samples, settling = split_settling(recorded)
    vals = [v for _, v in samples]
    hours = len(samples) / 60  # one validated reading per minute
    ev3 = desaturations(samples, 3)
    ev4 = desaturations(samples, 4)
    return {
        "samples": samples,
        "settling": settling,
        "ev3": ev3,
        "hours": hours,
        "avg": sum(vals) / len(vals),
        "min": min(vals),
        "below90": 100 * sum(v < 90 for v in vals) / len(vals),
        "odi3": len(ev3) / hours,
        "odi4": len(ev4) / hours,
    }
