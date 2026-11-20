"""Graphs: one per night/nap, an overview across nights, and a sleep diary."""
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from .analysis import GAP, HR_SURGE, night_of  # noqa: E402

# stage -> (row in the hypnogram, colour, label); Awake at the top like a clinical hypnogram
STAGES = {
    "AWAKE": (3, "#f08c3c", "Awake"),
    "REM": (2, "#a275d6", "REM"),
    "LIGHT": (1, "#74a9e8", "Light"),
    "DEEP": (0, "#1f3b73", "Deep"),
    "RESTLESS": (2, "#f2c14e", "Restless"),
    "ASLEEP": (1, "#74a9e8", "Asleep"),
}
NO_STAGES = "#adb5bd"


def save(fig, out):
    """Write via a temp file and retry the swap: an image viewer that has the old
    file open (e.g. the editor's preview) can briefly block writing on Windows."""
    tmp = out.with_name(out.stem + ".tmp.png")
    fig.savefig(tmp, dpi=110)
    plt.close(fig)
    for attempt in range(10):
        try:
            os.replace(tmp, out)
            return
        except OSError:
            if attempt == 9:
                raise
            time.sleep(0.5)


def stage_style(kind):
    return STAGES.get(kind, (1, NO_STAGES, kind.title()))


def describe(rec):
    parts = []
    if rec.sleep:
        sl = rec.sleep
        parts.append(f"asleep {sl['asleep'] / 60:.1f} h, awake {sl['awake']} min, woke {sl['awakenings']}x")
        if sl["staged"] and sl["asleep"]:
            parts.append(f"deep {100 * sl['minutes'].get('DEEP', 0) / sl['asleep']:.0f}%, "
                         f"REM {100 * sl['minutes'].get('REM', 0) / sl['asleep']:.0f}%")
    if rec.spo2_stats:
        s = rec.spo2_stats
        parts.append(f"SpO2 avg {s['avg']:.1f}%, ODI(3%) {s['odi3']:.1f}/h, ODI(4%) {s['odi4']:.1f}/h")
    vitals = []
    if rec.hr_stats:
        h = rec.hr_stats
        vitals.append(f"heart rate {h['median']} bpm (lowest {h['lowest']}), {h['surges_per_hour']:.1f} surges/h")
    if rec.breathing and rec.breathing["full"]:
        vitals.append(f"breathing {rec.breathing['full']['rate']:.1f}/min")
    return "  |  ".join(parts) + ("\n" + "  |  ".join(vitals) if vitals else "")


def plot_recording(rec, out):
    """One graph for a night or nap. Returns False when there's nothing to draw."""
    s, sl = rec.spo2_stats, rec.sleep
    panels = []
    if sl and sl["stages"]:
        panels.append(("stages", 1.8))
    if s:
        panels.append(("spo2", 4.2))
    if rec.hr_stats:
        panels.append(("hr", 3.0))
    if s:
        panels.append(("hourly", 2.8))
    if not panels:
        return False

    fig, axes = plt.subplots(len(panels), 1, figsize=(14, 1.2 + sum(h for _, h in panels)), sharex=True,
                             gridspec_kw={"height_ratios": [h for _, h in panels]}, squeeze=False)
    axes = dict(zip((p for p, _ in panels), axes[:, 0]))
    label = f"Night of {rec.name}" if rec.kind == "night" else f"Nap on {rec.name[:-4]}"
    fig.suptitle(f"{label} ({rec.start:%H:%M}-{rec.end:%H:%M})\n{describe(rec)}")

    if "stages" in axes:
        ax = axes["stages"]
        for a, b, kind in sl["stages"]:
            row, colour, _ = stage_style(kind)
            ax.broken_barh([(mdates.date2num(a), mdates.date2num(b) - mdates.date2num(a))],
                           (row - 0.4, 0.8), color=colour, lw=0)
        # brief awakenings overlap the stages; draw them as ticks on the Awake row
        for a, b in sl["short_awakenings"]:
            ax.broken_barh([(mdates.date2num(a), max(mdates.date2num(b) - mdates.date2num(a), 1 / 1440))],
                           (stage_style("AWAKE")[0] - 0.4, 0.8), color=stage_style("AWAKE")[1], lw=0.8,
                           edgecolor="#a34a00")
        rows = sorted({stage_style(k)[0]: stage_style(k)[2]
                       for k in [k for _, _, k in sl["stages"]] + ["AWAKE"] * bool(sl["short_awakenings"])}.items())
        ax.set_yticks([r for r, _ in rows], [n for _, n in rows])
        ax.set_ylim(-0.6, 3.6)
        ax.grid(alpha=0.3, axis="x")

    if s:
        recorded, samples, settling = rec.spo2, s["samples"], s["settling"]
        # break the line where data is missing instead of drawing across the gap
        px, py = [], []
        for i, (t, v) in enumerate(recorded):
            if i and t - recorded[i - 1][0] > GAP:
                px.append(t - GAP / 2)
                py.append(float("nan"))
            px.append(t)
            py.append(v)

        ax = axes["spo2"]
        ax.plot(px, py, color="#2a6fdb", lw=1.2, label="SpO2 per minute")
        if settling:
            ax.plot([t for t, _ in settling], [v for _, v in settling], ".", color="#868e96",
                    label="sensor settling (not counted)")
        for start, end, _, _ in s["ev3"]:
            ax.axvspan(start - timedelta(seconds=30), end + timedelta(seconds=30),
                       color="#e8590c", alpha=0.25, lw=0)
        ax.axhline(90, color="#c92a2a", ls="--", lw=1, label="90%")
        ax.set_ylabel("SpO2 %")
        ax.set_ylim(max(70, min(v for _, v in recorded) - 3), 100.5)
        ax.plot([], [], color="#e8590c", alpha=0.4, lw=8, label="dip >= 3%")
        ax.legend(loc="lower left")
        ax.grid(alpha=0.3)

        hourly = defaultdict(list)
        for t, v in samples:
            hourly[t.replace(minute=0, second=0, microsecond=0)].append(v)
        hourly_ev = defaultdict(int)
        for start, *_ in s["ev3"]:
            hourly_ev[start.replace(minute=0, second=0, microsecond=0)] += 1
        hrs = sorted(hourly)
        centers = [h + timedelta(minutes=30) for h in hrs]

        ax = axes["hourly"]
        ax.bar(centers, [sum(hourly[h]) / len(hourly[h]) for h in hrs], width=timedelta(minutes=50),
               color="#a5c3f0", label="hourly average")
        ax.plot(centers, [min(hourly[h]) for h in hrs], "v", color="#c92a2a", label="hourly minimum")
        for c, h in zip(centers, hrs):
            if hourly_ev[h]:
                text = f"{hourly_ev[h]} dip" + ("s" if hourly_ev[h] > 1 else "")
                ax.annotate(text, (c, 100), ha="center", va="top", fontsize=8)
        ax.set_ylabel("SpO2 %")
        ax.set_ylim(max(70, s["min"] - 3), 101)
        ax.legend(loc="lower left")
        ax.grid(alpha=0.3, axis="y")

    if "hr" in axes:
        h = rec.hr_stats
        ax = axes["hr"]
        samples = h["samples"]
        px, py = [], []
        for i, (t, v) in enumerate(samples):
            if i and (t - samples[i - 1][0]).total_seconds() > 60:
                px.append(t)
                py.append(float("nan"))
            px.append(t)
            py.append(v)
        ax.plot(px, py, color="#c2255c", lw=0.6, label="heart rate")
        if h["surges"]:
            ax.plot([t for t, _ in h["surges"]], [peak for _, peak in h["surges"]], "^", color="#5f3dc4", ms=5,
                    label=f"surge >= {HR_SURGE} bpm")
        ax.set_ylabel("bpm")
        ax.legend(loc="upper left")
        ax.grid(alpha=0.3)

    last = axes[panels[-1][0]]
    last.set_xlim(rec.start - timedelta(minutes=10), rec.end + timedelta(minutes=10))
    last.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    fig.tight_layout()
    save(fig, out)
    return True


def plot_summary(recs, out):
    """Per-night trends: time asleep by stage, SpO2 dips and level, heart-rate surges,
    sleeping heart rate and breathing rate (each panel only when its data is there)."""
    nights = [r for r in recs if r.kind == "night"]
    naps = [r for r in recs if r.kind == "nap" and r.spo2_stats]
    staged = [r for r in nights if r.sleep]
    with_spo2 = [r for r in nights if r.spo2_stats]
    with_hr = [r for r in nights if r.hr_stats]
    with_breath = [r for r in nights if r.breathing and r.breathing["full"]]
    if len(nights) < 2:
        return False

    day = lambda r: datetime.fromisoformat(night_of(r.start))  # noqa: E731
    panels = ((["sleep"] if staged else []) + (["odi", "level"] if with_spo2 else [])
              + (["surges"] if with_hr else []) + (["vitals"] if with_hr or with_breath else []))
    if not panels:
        return False
    fig, axes = plt.subplots(len(panels), 1, figsize=(14, 3.4 * len(panels)), sharex=True, squeeze=False)
    axes = dict(zip(panels, axes[:, 0]))
    fig.suptitle(f"Overview - {len(nights)} nights, {sum(r.kind == 'nap' for r in recs)} naps")

    if "sleep" in axes:
        ax = axes["sleep"]
        days = [day(r) for r in staged]
        bottom = [0.0] * len(staged)
        for kind in ("DEEP", "LIGHT", "REM", "ASLEEP", "AWAKE"):
            hours = [r.sleep["minutes"].get(kind, 0) / 60 for r in staged]
            if any(hours):
                _, colour, name = stage_style(kind)
                ax.bar(days, hours, bottom=bottom, color=colour, label=name, width=0.8)
                bottom = [b + h for b, h in zip(bottom, hours)]
        ax.axhline(7, color="#495057", ls="--", lw=1, label="7 h")
        ax.set_ylabel("hours")
        ax.legend(loc="upper left", ncol=6)
        ax.grid(alpha=0.3, axis="y")

    if "odi" in axes:
        ax = axes["odi"]
        days = [day(r) for r in with_spo2]
        ax.bar(days, [r.spo2_stats["odi3"] for r in with_spo2], color="#e8590c", alpha=0.7,
               label="night ODI 3% (dips/hour)")
        ax.plot(days, [r.spo2_stats["odi4"] for r in with_spo2], "o", color="#862e9c", ms=4, label="night ODI 4%")
        if naps:
            ax.plot([day(r) for r in naps], [r.spo2_stats["odi3"] for r in naps], "x", color="#2b8a3e",
                    ms=7, mew=2, label="nap ODI 3%")
        ax.axhline(5, color="#c92a2a", ls="--", lw=1, label="5/h (apnea threshold)")
        top = max(r.spo2_stats["odi3"] for r in with_spo2 + naps)
        ax.set_ylim(0, max(6, top + 1))
        ax.set_ylabel("dips per hour")
        ax.legend(loc="upper left")
        ax.grid(alpha=0.3, axis="y")

        ax = axes["level"]
        ax.plot(days, [r.spo2_stats["avg"] for r in with_spo2], "-o", color="#2a6fdb", ms=3, label="night average")
        ax.plot(days, [r.spo2_stats["min"] for r in with_spo2], "v", color="#c92a2a", ms=4, label="night minimum")
        if naps:
            ax.plot([day(r) for r in naps], [r.spo2_stats["avg"] for r in naps], "x", color="#2b8a3e",
                    ms=6, mew=2, label="nap average")
        ax.axhline(90, color="#c92a2a", ls="--", lw=1)
        ax.set_ylabel("SpO2 %")
        ax.legend(loc="lower left")
        ax.grid(alpha=0.3)

    if "surges" in axes:
        ax = axes["surges"]
        days = [day(r) for r in with_hr]
        ax.bar(days, [r.hr_stats["surges_per_hour"] for r in with_hr], color="#9775fa", alpha=0.8,
               label=f"heart-rate surges >= {HR_SURGE} bpm per hour asleep")
        ax.plot(days, [r.hr_stats["surges_without_awakening"] for r in with_hr], "o", color="#5f3dc4", ms=4,
                label="... of which without a Fitbit-detected awakening")
        ax.set_ylabel("per hour")
        ax.set_ylim(0, max(r.hr_stats["surges_per_hour"] for r in with_hr) * 1.45 + 0.5)  # room for the legend
        ax.legend(loc="upper left")
        ax.grid(alpha=0.3, axis="y")

    if "vitals" in axes:
        ax = axes["vitals"]
        if with_hr:
            ax.plot([day(r) for r in with_hr], [r.hr_stats["median"] for r in with_hr], "-o", color="#c2255c",
                    ms=3, label="sleeping heart rate (bpm)")
            ax.plot([day(r) for r in with_hr], [r.hr_stats["lowest"] for r in with_hr], "v", color="#c2255c",
                    alpha=0.5, ms=4, label="lowest heart rate (bpm)")
        if with_breath:
            ax.plot([day(r) for r in with_breath], [r.breathing["full"]["rate"] for r in with_breath], "-o",
                    color="#0b7285", ms=3, label="breathing rate (breaths/min)")
            ax.axhspan(12, 20, color="#0b7285", alpha=0.08, lw=0, label="usual breathing range 12-20")
        ax.set_ylim(0, None)
        ax.legend(loc="lower left", ncol=2)
        ax.grid(alpha=0.3)

    axes[panels[-1]].xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
    fig.tight_layout()
    save(fig, out)
    return True


def plot_diary(recs, out):
    """Sleep diary: one row per night (18:00 -> 18:00), coloured by sleep stage."""
    if not recs:
        return False
    rows = sorted({night_of(r.start) for r in recs})
    index = {n: i for i, n in enumerate(rows)}
    fig, ax = plt.subplots(figsize=(13, max(5.0, 0.17 * len(rows) + 1.8)))

    def hours(t, night):
        return (t - datetime.fromisoformat(night) - timedelta(hours=18)).total_seconds() / 3600

    for r in recs:
        night = night_of(r.start)
        y = index[night]
        segments = r.sleep["stages"] if r.sleep and r.sleep["stages"] else [(r.start, r.end, None)]
        for a, b, kind in segments:
            colour = stage_style(kind)[1] if kind else NO_STAGES
            ax.broken_barh([(hours(a, night), hours(b, night) - hours(a, night))], (y - 0.4, 0.8),
                           color=colour, lw=0)

    ax.set_ylim(len(rows) - 0.5, -0.5)
    step = max(1, len(rows) // 40)
    ax.set_yticks(range(0, len(rows), step), [datetime.fromisoformat(n).strftime("%a %d %b") for n in rows][::step],
                  fontsize=8)
    ax.set_xlim(0, 24)
    ax.set_xticks(range(0, 25, 3), [f"{(18 + h) % 24:02d}:00" for h in range(0, 25, 3)])
    ax.grid(alpha=0.3, axis="x")
    kinds = {k for r in recs if r.sleep for _, _, k in r.sleep["stages"]}
    handles = [Patch(color=stage_style(k)[1], label=stage_style(k)[2])
               for k in ("DEEP", "LIGHT", "REM", "AWAKE", "ASLEEP", "RESTLESS") if k in kinds]
    if any(not (r.sleep and r.sleep["stages"]) for r in recs):
        handles.append(Patch(color=NO_STAGES, label="no stage data"))
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.06), ncol=len(handles), frameon=False)
    ax.set_title("Sleep diary - each row is one night, 18:00 to 18:00 (naps included)")
    fig.tight_layout()
    save(fig, out)
    return True
