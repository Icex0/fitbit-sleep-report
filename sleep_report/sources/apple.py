"""Source for Apple Watch: import an Apple Health export (export.zip or export.xml).

On the iPhone: Health app > your profile picture > Export All Health Data. The export is an XML
file of records; this reads it as a stream (exports can be gigabytes) and writes the shared data
format described in store.py.

Mapping (record types are HealthKit identifiers):
  HKCategoryTypeIdentifierSleepAnalysis            sleep stages: AsleepCore -> LIGHT, AsleepDeep -> DEEP,
                                                   AsleepREM -> REM, Awake -> AWAKE, AsleepUnspecified -> ASLEEP;
                                                   InBed is ignored. Records from an Apple Watch are preferred.
  HKQuantityTypeIdentifierOxygenSaturation         SpO2 (stored by Apple as a fraction, 0.97 = 97%)
  HKQuantityTypeIdentifierHeartRate                heart rate during each sleep
  HKQuantityTypeIdentifierRespiratoryRate          breathing rate: median per sleep
  HKQuantityTypeIdentifierRestingHeartRate         resting heart rate per day
  HKQuantityTypeIdentifierHeartRateVariabilitySDNN HRV as SDNN (not RMSSD), median per sleep
  HKQuantityTypeIdentifierAppleSleepingWristTemperature   nightly wrist temperature
  ...BreathingDisturbances (if present)            Apple's nightly breathing-disturbance value

Untested on a real export so far: written from Apple's documented identifiers and tested on a
generated export.
"""
import sys
import zipfile
from bisect import bisect_left, bisect_right
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from statistics import median
from xml.etree.ElementTree import iterparse

from ..analysis import night_of
from ..store import save_breathing, save_daily, save_heart_rate, save_sleep, save_source, save_spo2, session_key

STAGES = {
    "HKCategoryValueSleepAnalysisAsleepCore": "LIGHT",
    "HKCategoryValueSleepAnalysisAsleepDeep": "DEEP",
    "HKCategoryValueSleepAnalysisAsleepREM": "REM",
    "HKCategoryValueSleepAnalysisAwake": "AWAKE",
    "HKCategoryValueSleepAnalysisAsleepUnspecified": "ASLEEP",
    "HKCategoryValueSleepAnalysisAsleep": "ASLEEP",  # before watchOS 9
}
QUANTITIES = {
    "HKQuantityTypeIdentifierOxygenSaturation": "spo2",
    "HKQuantityTypeIdentifierHeartRate": "hr",
    "HKQuantityTypeIdentifierRespiratoryRate": "breathing",
    "HKQuantityTypeIdentifierRestingHeartRate": "resting_hr",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN": "sdnn",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature": "wrist_temp",
}
SESSION_GAP = timedelta(minutes=60)  # stage records further apart than this start a new sleep


def parse_time(text):
    """Apple export time, e.g. "2026-10-21 02:13:00 +0200" -> aware datetime."""
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S %z")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def offset(dt):
    return f"{int(dt.utcoffset().total_seconds())}s"


def local(dt):
    return dt.replace(tzinfo=None)


@contextmanager
def open_export(path):
    """A file object for export.xml, from the zip or the XML itself."""
    if not zipfile.is_zipfile(path):
        with open(path, "rb") as f:
            yield f
        return
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.endswith("export.xml") and "cda" not in n]
        if not names:
            sys.exit(f"{path} has no export.xml inside. Use the export.zip from the Health app.")
        with z.open(names[0]) as f:
            yield f


def read_records(path):
    """Collect the records this report uses: (stages per source, quantities by kind)."""
    stages = defaultdict(list)  # source -> [(start, end, kind)]
    quantities = defaultdict(list)  # kind -> [(start, end, value)]
    watch_sources = set()
    count = 0
    with open_export(path) as f:
        events = iterparse(f, events=("start", "end"))
        _, root = next(events)
        for event, el in events:
            if event != "end" or el.tag != "Record":
                continue
            count += 1
            kind = el.get("type", "")
            try:
                if kind == "HKCategoryTypeIdentifierSleepAnalysis":
                    stage = STAGES.get(el.get("value", ""))
                    if stage:
                        source = el.get("sourceName", "")
                        if "watch" in (el.get("device", "") + source).lower():
                            watch_sources.add(source)
                        stages[source].append((parse_time(el.get("startDate")), parse_time(el.get("endDate")), stage))
                elif kind in QUANTITIES or "BreathingDisturbances" in kind:
                    name = QUANTITIES.get(kind, "breathing_disturbances")
                    quantities[name].append((parse_time(el.get("startDate")), parse_time(el.get("endDate")),
                                             float(el.get("value"))))
            except (TypeError, ValueError):
                pass  # a record without a usable time or value
            root.clear()  # release processed records: exports can be gigabytes
    if not count:
        sys.exit(f"No health records found in {path}.")
    # prefer the watch's sleep records; other apps may write overlapping sleep data
    chosen = [s for s in stages if s in watch_sources] or list(stages)
    segments = sorted(seg for s in chosen for seg in stages[s])
    for v in quantities.values():
        v.sort()
    return segments, quantities, count


def build_sessions(segments):
    """Group stage records into sleep sessions in the shared (Google Health) shape."""
    sessions, current = [], []
    for seg in segments:
        if current and seg[0] - max(e for _, e, _ in current) > SESSION_GAP:
            sessions.append(current)
            current = []
        if current and seg[0] < current[-1][1]:  # overlap: keep the earlier record, trim this one
            seg = (current[-1][1], seg[1], seg[2])
            if seg[1] <= seg[0]:
                continue
        current.append(seg)
    if current:
        sessions.append(current)

    out = []
    for segs in sessions:
        asleep = sum((e - s).total_seconds() for s, e, k in segs if k != "AWAKE") / 60
        if asleep < 20:
            continue
        start, end = segs[0][0], max(e for _, e, _ in segs)
        out.append({
            "interval": {"startTime": iso(start), "startUtcOffset": offset(start), "endTime": iso(end), "endUtcOffset": offset(end)},
            "type": "STAGES" if any(k in ("LIGHT", "DEEP", "REM") for _, _, k in segs) else "CLASSIC",
            "stages": [{"startTime": iso(s), "startUtcOffset": offset(s), "endTime": iso(e), "endUtcOffset": offset(e), "type": k}
                       for s, e, k in segs],
            "metadata": {"mainSleep": False},
            "_start": start, "_end": end, "_asleep": asleep,
        })
    # main sleep: the longest sleep in each 18:00-18:00 night; the rest are naps
    by_night = defaultdict(list)
    for s in out:
        by_night[night_of(local(s["_start"]))].append(s)
    for group in by_night.values():
        main = max(group, key=lambda s: s["_asleep"])
        main["metadata"]["mainSleep"] = True
        for s in group:
            s["metadata"]["nap"] = s is not main
    return out


def within(series, start, end):
    """Values of [(start, end, value)] whose start falls between start and end."""
    keys = [s for s, _, _ in series]
    return series[bisect_left(keys, start):bisect_right(keys, end)]


def import_export(path, data_dir):
    """Read an Apple Health export and write data_dir in the shared format. Returns a summary."""
    segments, q, count = read_records(path)
    if not segments:
        sys.exit("The export has no sleep stages. Sleep tracking needs an Apple Watch worn to bed with Sleep turned on.")
    sessions = build_sessions(segments)

    spo2 = {}
    for s, _, v in q["spo2"]:
        pct = v * 100 if v <= 1.0 else v
        spo2[s.astimezone(timezone.utc).isoformat()] = (local(s).isoformat(timespec="seconds"), round(pct, 1))

    hr_dir = data_dir / "heart_rate"
    if hr_dir.exists():
        for old in hr_dir.glob("*.csv"):
            old.unlink()
    sleeps, breathing, daily = {}, {}, {}
    for s in sessions:
        start, end = s.pop("_start"), s.pop("_end")
        s.pop("_asleep")
        key = session_key(s)
        sleeps[key] = s
        hr = within(q["hr"], start - timedelta(minutes=5), end + timedelta(minutes=5))
        if hr:
            save_heart_rate(hr_dir / f"{key}.csv", [(local(t).isoformat(timespec="seconds"), round(v)) for t, _, v in hr])
        if not s["metadata"]["mainSleep"]:
            continue
        rates = [v for _, _, v in within(q["breathing"], start, end)]
        if rates:
            breathing[iso(end)] = {"sampleTime": {"physicalTime": iso(end), "utcOffset": offset(end)},
                                   "fullSleepStats": {"breathsPerMinute": round(median(rates), 1)}}
        day = local(end).date().isoformat()
        row = daily.setdefault(day, {})
        sdnn = [v for _, _, v in within(q["sdnn"], start, end)]
        if sdnn:
            row.update(hrv=round(median(sdnn), 1), hrv_kind="sdnn")
        temps = [v for _, _, v in within(q["wrist_temp"], start - timedelta(hours=1), end)]
        if temps:
            row["temp"] = round(median(temps), 2)
        dist = [v for _, _, v in within(q["breathing_disturbances"], start - timedelta(hours=1), end + timedelta(hours=12))]
        if dist:
            row["breathing_disturbances"] = dist[0]
    for t, _, v in q["resting_hr"]:
        day = local(t).date().isoformat()
        if day in daily:
            daily[day]["resting_hr"] = v
    # temperature baseline: median of the previous 30 nights (at least 5), like Fitbit's baseline
    temps = sorted((d, r["temp"]) for d, r in daily.items() if "temp" in r)
    for i, (d, _) in enumerate(temps):
        past = [v for _, v in temps[max(0, i - 30):i]]
        if len(past) >= 5:
            daily[d]["temp_baseline"] = round(median(past), 2)

    save_spo2(data_dir / "spo2.csv", spo2)
    save_sleep(data_dir / "sleep.json", sleeps)
    save_breathing(data_dir / "breathing.json", breathing)
    save_daily(data_dir / "daily.json", daily)
    save_source(data_dir, "apple", imported=datetime.now().isoformat(timespec="seconds"), file=str(path))
    mains = sum(1 for s in sleeps.values() if s["metadata"]["mainSleep"])
    return {"records": count, "nights": mains, "naps": len(sleeps) - mains, "spo2": len(spo2),
            "heart_rate_sleeps": len(list(hr_dir.glob("*.csv"))) if hr_dir.exists() else 0,
            "breathing": len(breathing), "days": len(daily)}
