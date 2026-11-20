"""Sleep report: command line.

    python -m sleep_report auth                       sign in with Google (Fitbit, Pixel Watch; again every 7 days)
    python -m sleep_report fetch --days 90            download SpO2, sleep, heart rate, breathing into data/
    python -m sleep_report import-apple export.zip    Apple Watch: import an Apple Health export instead
    python -m sleep_report report                     graphs in reports/ + a stats table
    python -m sleep_report report --night 2026-10-26  just one night (named by the evening's date)
    python -m sleep_report setup                      age, days off, usual bedtime (picks reference ranges)
    python -m sleep_report export                     data + literature report for the web app (web/)

After  pip install -e .  the same commands also work as  sleep-report <command>.
See README.md for the one-time setup.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import median

from . import store
from .sources import google
from .analysis import load_recordings, night_of

REPORT_DIR = store.HOME / "reports"
WEB_DATA_DIR = store.WEB_DATA_DIR


def cmd_auth(_args):
    google.sign_in()


def check_source(data_dir, device, replace=False):
    """Don't mix data from two kinds of device in one data folder."""
    existing = store.load_source(data_dir)
    has_data = (data_dir / "sleep.json").exists() or (data_dir / "spo2.csv").exists()
    if has_data and existing != device and not replace:
        sys.exit(f"{data_dir} holds data from another device ({store.DEVICES[existing]}).\n"
                 f"Use a different folder with --data-dir, or add --replace to delete it and start over.")
    if has_data and existing != device:
        import shutil
        shutil.rmtree(data_dir)


def cmd_import_apple(args):
    from .sources import apple
    if not args.file.exists():
        sys.exit(f"File not found: {args.file}")
    check_source(args.data_dir, "apple", args.replace)
    print(f"Reading {args.file} (large exports take a minute)...")
    n = apple.import_export(args.file, args.data_dir)
    print(f"Imported {n['records']} records: {n['nights']} nights, {n['naps']} naps, {n['spo2']} SpO2 readings, "
          f"heart rate for {n['heart_rate_sleeps']} sleeps, breathing rate for {n['breathing']} nights.")


def cmd_fetch(args):
    check_source(args.data_dir, "google")
    token = google.access_token()
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=args.days)

    spo2_file = args.data_dir / "spo2.csv"
    rows = store.load_spo2(spo2_file)
    new = google.fetch_spo2(token, start, end, rows)
    store.save_spo2(spo2_file, rows)
    print(f"SpO2:  {new} new readings, {len(rows)} total in {spo2_file}")
    store.save_source(args.data_dir, "google")
    (args.data_dir / "last_fetch.json").write_text(json.dumps({"at": end.isoformat(timespec="seconds"), "days": args.days}))

    if google.SLEEP_SCOPE not in google.granted_scopes():
        print("Sleep: skipped - no sleep access yet. Run  python -m sleep_report auth  and allow sleep data.")
        return
    sleep_file = args.data_dir / "sleep.json"
    sleeps = store.load_sleep(sleep_file)
    new = google.fetch_sleep(token, start, end, sleeps)
    store.save_sleep(sleep_file, sleeps)
    print(f"Sleep: {new} new sessions, {len(sleeps)} total in {sleep_file}")

    breathing_file = args.data_dir / "breathing.json"
    breathing = store.load_breathing(breathing_file)
    new = google.fetch_breathing(token, start, end, breathing)
    store.save_breathing(breathing_file, breathing)
    print(f"Breathing: {new} new summaries, {len(breathing)} total in {breathing_file}")

    hr_dir = args.data_dir / "heart_rate"
    new = google.fetch_heart_rate(token, sleeps.values(), hr_dir)
    print(f"Heart rate: downloaded for {new} new sleep sessions into {hr_dir}")

    daily_file = args.data_dir / "daily.json"
    daily = store.load_daily(daily_file)
    new = google.fetch_daily(token, start, end, daily)
    store.save_daily(daily_file, daily)
    print(f"Daily HRV, resting heart rate and temperature: {new} new values, {len(daily)} days in {daily_file}")


def fmt(value, spec):
    return "-" if value is None else format(value, spec)


def table_row(r):
    sl, s, h = r.sleep, r.spo2_stats, r.hr_stats
    breath = r.breathing and r.breathing["full"] and r.breathing["full"]["rate"]
    deep = rem = None
    if sl and sl["staged"] and sl["asleep"]:
        deep = 100 * sl["minutes"].get("DEEP", 0) / sl["asleep"]
        rem = 100 * sl["minutes"].get("REM", 0) / sl["asleep"]
    return (f"{r.name:<22}{r.start:%H:%M}-{r.end:%H:%M}"
            f"{fmt(sl and sl['asleep'] / 60, '.1f'):>7}{fmt(sl and sl['awake'], 'd'):>6}"
            f"{fmt(sl and sl['efficiency'], '.0f'):>5}{fmt(deep, '.0f'):>5}{fmt(rem, '.0f'):>5}"
            f"{fmt(sl and sl['awakenings'], 'd'):>6}  |"
            f"{fmt(s and s['avg'], '.1f'):>6}{fmt(s and s['min'], '.1f'):>6}{fmt(s and s['below90'], '.1f'):>6}"
            f"{fmt(s and s['odi3'], '.1f'):>6}{fmt(s and s['odi4'], '.1f'):>6}  |"
            f"{fmt(h and h['median'], 'd'):>5}{fmt(h and h['surges_per_hour'], '.1f'):>7}{fmt(breath or None, '.1f'):>7}")


HEADER = (f"{'':<22}{'bed-up':<11}{'asleep':>7}{'awake':>6}{'eff%':>5}{'deep':>5}{'REM':>5}{'wakes':>6}  |"
          f"{'SpO2':>6}{'min':>6}{'<90%':>6}{'ODI3':>6}{'ODI4':>6}  |{'HR':>5}{'surg/h':>7}{'breath':>7}")


def clock(hours_after_18):
    m = round(hours_after_18 * 60)
    return f"{(18 + m // 60) % 24:02d}:{m % 60:02d}"


def overall(recs):
    """A few medians across all nights, for the bottom of the report."""
    nights = [r for r in recs if r.kind == "night"]
    naps = [r for r in recs if r.kind == "nap"]
    after_18 = lambda t, r: (t - datetime.fromisoformat(night_of(r.start)) - timedelta(hours=18)).total_seconds() / 3600  # noqa: E731
    lines = [f"{len(nights)} nights, {len(naps)} naps",
             f"  bedtime median {clock(median(after_18(r.start, r) for r in nights))}, "
             f"wake-up median {clock(median(after_18(r.end, r) for r in nights))}"]
    slept = [r.sleep for r in nights if r.sleep]
    if slept:
        lines.append(f"  asleep median {median(s['asleep'] for s in slept) / 60:.1f} h "
                     f"({sum(s['asleep'] < 360 for s in slept)} nights under 6 h), "
                     f"awake in bed median {median(s['awake'] for s in slept):.0f} min, "
                     f"efficiency median {median(s['efficiency'] or 0 for s in slept):.0f}%")
        lines.append(f"  awake time median: {median(s['to_fall_asleep'] for s in slept):.0f} min before falling asleep, "
                     f"{median(s['awake_mid'] for s in slept):.0f} min during the night, "
                     f"{median(s['after_waking'] for s in slept):.0f} min in bed after waking up")
        lines.append(f"  wake-ups (incl. brief ones) median {median(s['awakenings'] for s in slept):.0f} per night, "
                     f"{median(s['awakenings'] / (s['asleep'] / 60) for s in slept if s['asleep']):.1f} per hour asleep")
        staged = [s for s in slept if s["staged"] and s["asleep"]]
        if staged:
            lines.append(f"  deep sleep median {median(100 * s['minutes'].get('DEEP', 0) / s['asleep'] for s in staged):.0f}%, "
                         f"REM median {median(100 * s['minutes'].get('REM', 0) / s['asleep'] for s in staged):.0f}%")
    oxy = [r.spo2_stats for r in nights if r.spo2_stats]
    if oxy:
        lines.append(f"  SpO2: median ODI3 {median(s['odi3'] for s in oxy):.1f}/h, "
                     f"{sum(s['odi3'] >= 5 for s in oxy)} nights at 5/h or more, "
                     f"median night average {median(s['avg'] for s in oxy):.1f}%")
    hr = [r.hr_stats for r in nights if r.hr_stats]
    if hr:
        with_short = [h["awakenings_with_surge"] for h in hr if h["awakenings_with_surge"] is not None]
        lines.append(f"  heart rate asleep median {median(h['median'] for h in hr)} bpm "
                     f"(lowest typically {median(h['lowest'] for h in hr)}), "
                     f"surges median {median(h['surges_per_hour'] for h in hr):.1f}/h, "
                     f"of which {median(h['surges_without_awakening'] for h in hr):.1f}/h without a Fitbit-detected awakening")
        if with_short:
            lines.append(f"  {100 * median(with_short):.0f}% of Fitbit's brief awakenings come with a heart-rate surge (median)")
    rates = [r.breathing["full"]["rate"] for r in nights if r.breathing and r.breathing["full"]]
    if rates:
        lines.append(f"  breathing rate median {median(rates):.1f}/min (range {min(rates):.1f}-{max(rates):.1f}), "
                     f"{sum(not 12 <= x <= 20 for x in rates)} nights outside 12-20")
    return lines


def cmd_setup(args):
    from . import settings
    if not args.stdin:
        settings.setup()
        return
    # non-interactive, used by the web app: settings as JSON on stdin
    try:
        saved = settings.save(json.loads(sys.stdin.read()))
    except (ValueError, json.JSONDecodeError) as e:
        sys.exit(f"Settings not saved: {e}")
    print(json.dumps(saved))


def cmd_status(args):
    """Where setup stands, as JSON for the web app (or readable text)."""
    from . import settings
    status = {"source": store.load_source(args.data_dir) if (args.data_dir / "sleep.json").exists() else None,
              "credentials": google.CLIENT_FILE.exists(), "signedIn": False, "signedInAt": None,
              "scopes": {"spo2": False, "sleep": False}, "lastFetch": None, "data": None, "exported": None,
              "settings": None, "settingsSaved": settings.SETTINGS_FILE.exists(), "settingsError": None}
    if google.TOKEN_FILE.exists():
        tok = json.loads(google.TOKEN_FILE.read_text())
        granted = set(tok.get("scope", "").split())
        status.update(signedIn="refresh_token" in tok, scopes={"spo2": google.SPO2_SCOPE in granted, "sleep": google.SLEEP_SCOPE in granted})
        if tok.get("signed_in_at"):
            status["signedInAt"] = datetime.fromtimestamp(tok["signed_in_at"], timezone.utc).isoformat(timespec="seconds")
    last = args.data_dir / "last_fetch.json"
    if last.exists():
        status["lastFetch"] = json.loads(last.read_text())
    spo2_file, sleep_file = args.data_dir / "spo2.csv", args.data_dir / "sleep.json"
    if spo2_file.exists() or sleep_file.exists():
        status["data"] = {"spo2Readings": len(store.load_spo2(spo2_file)), "sleepSessions": len(store.load_sleep(sleep_file))}
    summary = WEB_DATA_DIR / "summary.json"
    if summary.exists():
        status["exported"] = json.loads(summary.read_text()).get("generated")
    try:
        raw = json.loads(settings.SETTINGS_FILE.read_text(encoding="utf-8")) if status["settingsSaved"] else {}
        merged = {**settings.DEFAULTS, **raw}
        problems = settings.validate(merged)
        status["settings"] = merged
        status["settingsError"] = "; ".join(problems) or None
    except json.JSONDecodeError as e:
        status["settingsError"] = f"settings.json isn't valid JSON: {e}"
    if args.json:
        print(json.dumps(status))
    else:
        for k, v in status.items():
            print(f"{k:<14} {v}")


def cmd_export(args):
    from . import settings
    from .export import export
    from .literature import MIN_NIGHTS, evaluate
    from .metrics import metrics

    recs = load_recordings(args.data_dir)
    if not any(r.kind == "night" for r in recs):
        sys.exit("No nights with enough data. Run fetch first.")
    in_app = os.environ.get("SLEEP_REPORT_APP") == "1"  # run from the web app: skip command-line hints
    if not settings.SETTINGS_FILE.exists() and not in_app:
        print("No settings.json yet: using adult reference ranges, days off Sat+Sun and a 23:00 bedtime.\n"
              "Run  python -m sleep_report setup  to set your age and schedule.")
    profile = {**settings.profile(settings.load()), "source": store.load_source(args.data_dir)}
    m = metrics(recs, settings.free_evenings(profile["daysOff"]), profile["usualBedtimeH"], profile["age"])
    enough = m["nights"] >= MIN_NIGHTS
    findings, references = evaluate(m, profile) if enough else ([], [])
    files = export(recs, args.out, findings, references, profile, m)
    if enough:
        print(f"Wrote {files} files to {args.out} ({len(findings)} literature findings, ranges for {profile['groupLabel']}"
              f"{', age not set' if profile['ageAssumed'] else ''}).")
    else:
        print(f"Wrote {files} files to {args.out}. No literature report yet: it needs at least {MIN_NIGHTS} nights, "
              f"and there {'is' if m['nights'] == 1 else 'are'} {m['nights']}.")
    if not in_app:
        print("Start the app:  cd web  then  npm install  (first time)  and  npm run dev")


def cmd_report(args):
    from . import plots  # matplotlib is slow to import; only needed here

    sleeps = store.load_sleep(args.data_dir / "sleep.json")
    recs = load_recordings(args.data_dir, sleeps)
    if args.night:
        recs = [r for r in recs if night_of(r.start) == args.night]
    if not any(r.kind == "night" for r in recs):
        sys.exit("No nights with enough data. Run fetch first (and wear the watch to bed).")

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    if not args.night:
        for pattern in ("night-*.png", "nap-*.png", "spo2-*.png"):
            for old in out.glob(pattern):
                old.unlink()

    lines = ["NIGHTS" + HEADER[6:]]
    lines += [table_row(r) for r in recs if r.kind == "night"]
    if any(r.kind == "nap" for r in recs):
        lines += ["", "NAPS" + HEADER[4:]]
        lines += [table_row(r) for r in recs if r.kind == "nap"]
    lines += [""] + overall(recs)
    if not sleeps:
        lines += ["", "No Fitbit sleep data yet - nights were guessed from SpO2 readings. "
                      "Run auth + fetch to add sleep stages."]
    lines += ["",
              "asleep = hours asleep, awake = minutes awake in bed, eff = % of time in bed asleep,",
              "deep/REM = % of sleep, wakes = times awake incl. brief awakenings, ODI = SpO2 dips per hour,",
              "HR = median heart rate asleep, surg/h = heart-rate surges (>= 10 bpm) per hour asleep,",
              "breath = breaths per minute.",
              "ODI guide: <5 normal, 5-15 mild, 15-30 moderate, 30+ severe. A wrist estimate is not",
              "a diagnosis - see a doctor for a sleep study if it looks high or you're always tired."]
    print("\n".join(lines))
    if not args.night:
        (out / "stats.txt").write_text("\n".join(lines) + "\n")

    for r in recs:
        name = f"night-{r.name}.png" if r.kind == "night" else f"nap-{r.start:%Y-%m-%d-%H%M}.png"
        plots.plot_recording(r, out / name)
    if not args.night:
        plots.plot_summary(recs, out / "summary.png")
        plots.plot_diary(recs, out / "sleep-diary.png")
    print(f"\nGraphs saved in {out}")


def main():
    p = argparse.ArgumentParser(prog="sleep-report", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth", help="sign in with Google (first time, then every 7 days)")
    f = sub.add_parser("fetch", help="download SpO2 and sleep data")
    f.add_argument("--days", type=int, default=7, help="how many days back to download (default 7)")
    r = sub.add_parser("report", help="make graphs and print stats")
    r.add_argument("--night", help="YYYY-MM-DD, the evening the night started")
    r.add_argument("--out", type=Path, default=REPORT_DIR, help=argparse.SUPPRESS)
    ia = sub.add_parser("import-apple", help="import an Apple Health export (export.zip or export.xml)")
    ia.add_argument("file", type=Path)
    ia.add_argument("--replace", action="store_true", help="delete data from another device in the data folder first")
    st = sub.add_parser("setup", help="set your age and schedule, which pick the reference ranges")
    st.add_argument("--stdin", action="store_true", help=argparse.SUPPRESS)
    ss = sub.add_parser("status", help="show where setup stands")
    ss.add_argument("--json", action="store_true", help=argparse.SUPPRESS)
    e = sub.add_parser("export", help="write data and the literature report for the web app")
    e.add_argument("--out", type=Path, default=WEB_DATA_DIR, help=argparse.SUPPRESS)
    for s in (f, r, e, ss, ia):
        s.add_argument("--data-dir", type=Path, default=store.DATA_DIR, help=argparse.SUPPRESS)
    args = p.parse_args()
    {"auth": cmd_auth, "fetch": cmd_fetch, "report": cmd_report, "setup": cmd_setup, "status": cmd_status, "export": cmd_export,
     "import-apple": cmd_import_apple}[args.cmd](args)


if __name__ == "__main__":
    main()
