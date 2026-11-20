"""The data format every source writes, and reading/writing it in data/.

A source (google.py for Fitbit and Pixel Watch, apple.py for Apple Watch) fills these files;
everything after that (analysis, metrics, literature, export) only reads them:

  spo2.csv         utc_time, local_time, spo2: blood-oxygen readings in %
  sleep.json       {id: session}, one per sleep, in the Google Health shape:
                     interval {startTime, startUtcOffset, endTime, endUtcOffset}
                     type "STAGES" (or "CLASSIC" without stages)
                     stages [{startTime, startUtcOffset, endTime, endUtcOffset, type}]
                       with type LIGHT / DEEP / REM / AWAKE (classic: ASLEEP / RESTLESS / AWAKE)
                     shortAwakenings [same shape, type AWAKE] (optional)
                     metadata {mainSleep, nap} and summary {...} (optional; derived when missing)
                   Times are RFC 3339; offsets are durations like "3600s".
  heart_rate/      one CSV per sleep (named by session_key), local_time, bpm
  breathing.json   {id: {sampleTime {physicalTime, utcOffset}, fullSleepStats {breathsPerMinute, ...}}}
  daily.json       {wake-up date: {hrv, hrv_kind ("rmssd" or "sdnn"), hrv_deep, nonrem_hr, resting_hr,
                    temp, temp_baseline, temp_sd, breathing_disturbances}}; every field optional
  source.json      {"device": "google" | "apple", ...}: which source wrote the files
"""
import csv
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# SLEEP_REPORT_HOME keeps someone's data, settings and report in their own folder (e.g. several people on
# one computer); Google credentials stay in the project folder.
HOME = Path(os.environ["SLEEP_REPORT_HOME"]).resolve() if os.environ.get("SLEEP_REPORT_HOME") else ROOT
DATA_DIR = HOME / "data"
WEB_DATA_DIR = HOME / "public" / "data" if HOME != ROOT else ROOT / "web" / "public" / "data"
DEVICES = {"google": "Fitbit or Pixel Watch, via the Google Health API", "apple": "Apple Watch, from an Apple Health export"}


def parse_offset(s):
    """Duration string like '3600s' or '-18000.000s'."""
    return timedelta(seconds=float(s.rstrip("s"))) if s else timedelta(0)


def to_local(timestamp, offset):
    """RFC 3339 timestamp + the user's UTC offset -> naive local datetime."""
    utc = datetime.fromisoformat(timestamp).astimezone(timezone.utc)
    return (utc + parse_offset(offset)).replace(tzinfo=None)


def num(v):
    """Numbers sometimes arrive as strings; None and NaN mean no value."""
    if v in (None, ""):
        return None
    v = float(v)
    return None if v != v else v


def session_key(raw_sleep):
    """Stable id for a sleep session: its UTC start time, e.g. 20261021T005300Z."""
    start = datetime.fromisoformat(raw_sleep["interval"]["startTime"]).astimezone(timezone.utc)
    return start.strftime("%Y%m%dT%H%M%SZ")


def load_spo2(path):
    """{utc_time: (local_time, spo2)} from data/spo2.csv."""
    rows = {}
    if path.exists():
        with path.open(newline="") as f:
            for r in csv.DictReader(f):
                rows[r["utc_time"]] = (r["local_time"], float(r["spo2"]))
    return rows


def save_spo2(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["utc_time", "local_time", "spo2"])
        for utc in sorted(rows):
            w.writerow([utc, *rows[utc]])


def load_sleep(path):
    """{session id: session} from data/sleep.json."""
    return json.loads(path.read_text()) if path.exists() else {}


def save_sleep(path, sleeps):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sleeps, indent=1, sort_keys=True))


# breathing summaries and daily summaries are stored the same way: JSON objects
load_breathing = load_daily = load_sleep
save_breathing = save_daily = save_sleep


def load_heart_rate(hr_dir):
    """{session key: [(local datetime, bpm)]} from data/heart_rate/*.csv."""
    out = {}
    for path in sorted(hr_dir.glob("*.csv")) if hr_dir.exists() else []:
        with path.open(newline="") as f:
            out[path.stem] = [(datetime.fromisoformat(r["local_time"]), int(r["bpm"])) for r in csv.DictReader(f)]
    return out


def save_heart_rate(path, rows):
    """rows: [(local ISO time, bpm)] for one sleep."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["local_time", "bpm"])
        w.writerows(sorted(rows))


def load_source(data_dir):
    """Which source wrote data_dir: "google" (also for data from before source.json existed) or "apple"."""
    path = data_dir / "source.json"
    return json.loads(path.read_text()).get("device", "google") if path.exists() else "google"


def save_source(data_dir, device, **extra):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "source.json").write_text(json.dumps({"device": device, **extra}, indent=1))
