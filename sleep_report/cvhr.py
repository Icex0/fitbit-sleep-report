"""Cyclic variation of heart rate (CVHR): a sleep-apnea screen from heart rate alone.

During an apnea the heart slows, and it speeds up abruptly when breathing resumes, so
repeated apneas make heart rate cycle every 25-130 seconds. This follows the published
ACAT algorithm (autocorrelated wave detection with adaptive threshold; Hayano et al.
2011, restated with parameters in Sleep Breath 2013, Europace 2017, PLOS ONE 2020 and
Ann Noninvasive Electrocardiol 2021):

  1. inter-beat interval series, step-interpolated and resampled at 2 Hz
  2. smoothed by second-order polynomial fitting in a 20 s moving window
  3. candidate dips: width 10-120 s, depth-to-width ratio > 0.7 ms/s
  4. adaptive threshold: depth > 40% of the range between the 95th and 5th percentile
     of the smoothed series in a 130 s window around the dip
  5. cycle length (dip to dip) 25-130 s
  6. waveform similar to the two preceding and two following dips (mean r > 0.4)
  7. three consecutive cycle lengths equivalent: (3-2l1/s)(3-2l2/s)(3-2l3/s) > 0.8
  Fcv = dips meeting all criteria per hour of time in bed.

Adaptation (not validated): the papers used beat-to-beat intervals from ECG or the
watch's pulse wave. Fitbit gives a heart rate about every 2 seconds, so the interval
is taken as 60000 / bpm. Details the papers leave open (dip boundaries, the length of
the waveform compared) are this module's own choices, noted below.
"""
import numpy as np

FS = 2.0  # Hz
SMOOTH_S = 20
DIP_WIDTH = (10, 120)  # s
MIN_SLOPE = 0.7  # ms per s
ENVELOPE_S = 130
REL_DEPTH = 0.40
CYCLE = (25, 130)  # s
MIN_CORR = 0.4
MIN_EQUIVALENCE = 0.8
MAX_GAP_S = 30  # a longer gap in the heart-rate data splits the night into segments
SHAPE_S = 15  # own choice: compare waveforms over +-15 s around each dip


def savgol(y, window, order=2):
    """Second-order polynomial smoothing (Savitzky-Golay) with edge handling by reflection."""
    half = window // 2
    x = np.arange(-half, half + 1)
    coeffs = np.linalg.pinv(np.vander(x, order + 1, increasing=True))[0]
    padded = np.concatenate([y[half:0:-1], y, y[-2:-half - 2:-1]])
    return np.convolve(padded, coeffs[::-1], mode="valid")


def segments(samples):
    """[(t seconds, bpm)] -> list of 2 Hz interval series [(t0, intervals_ms)] without long gaps."""
    out, cur = [], [samples[0]]
    for prev, s in zip(samples, samples[1:]):
        if s[0] - prev[0] > MAX_GAP_S:
            out.append(cur)
            cur = []
        cur.append(s)
    out.append(cur)
    series = []
    for seg in out:
        if seg[-1][0] - seg[0][0] < 4 * CYCLE[0]:
            continue
        t = np.array([p[0] for p in seg], dtype=float)
        ms = 60000.0 / np.array([p[1] for p in seg], dtype=float)
        grid = np.arange(t[0], t[-1], 1 / FS)
        idx = np.searchsorted(t, grid, side="right") - 1  # step (sample-and-hold) interpolation
        series.append((t[0], ms[idx]))
    return series


def find_dips(y, t0):
    """Candidate dips (criteria 3 and 4) in one smoothed segment."""
    d = np.diff(y)
    minima = np.where((np.r_[d, 0] > 0) & (np.r_[0, d] < 0))[0]
    maxima = np.where((np.r_[d, 0] < 0) & (np.r_[0, d] > 0))[0]
    half_env = int(ENVELOPE_S * FS / 2)
    dips = []
    for m in minima:
        # dip boundaries: the nearest local maxima on each side (own choice; not specified)
        left = maxima[maxima < m]
        right = maxima[maxima > m]
        if not len(left) or not len(right):
            continue
        a, b = left[-1], right[0]
        width = (b - a) / FS
        depth = (y[a] + y[b]) / 2 - y[m]
        if not DIP_WIDTH[0] <= width <= DIP_WIDTH[1] or depth / width <= MIN_SLOPE:
            continue
        lo, hi = max(0, m - half_env), min(len(y), m + half_env + 1)
        p95, p5 = np.percentile(y[lo:hi], [95, 5])
        if p95 - p5 <= 0 or depth <= REL_DEPTH * (p95 - p5):
            continue
        dips.append(m)
    return dips


def detect(samples, time_in_bed_h):
    """samples: [(seconds, bpm)] for one sleep. Returns {"dips": [seconds], "fcv": per hour in bed}."""
    if len(samples) < 60 or time_in_bed_h <= 0:
        return None
    found = []
    window = int(SMOOTH_S * FS) | 1
    shape = int(SHAPE_S * FS)
    for t0, raw in segments(samples):
        y = savgol(raw, window)
        dips = find_dips(y, t0)
        if len(dips) < 4:
            continue
        times = [t0 + m / FS for m in dips]

        def wave(m):
            if m - shape < 0 or m + shape + 1 > len(y):
                return None
            w = y[m - shape:m + shape + 1]
            return w - w.mean()

        waves = [wave(m) for m in dips]

        def similar(i):
            rs = []
            for j in (i - 2, i - 1, i + 1, i + 2):
                if 0 <= j < len(dips) and waves[i] is not None and waves[j] is not None:
                    a, b = waves[i], waves[j]
                    denom = np.sqrt((a * a).sum() * (b * b).sum())
                    if denom > 0:
                        rs.append(float((a * b).sum() / denom))
            return bool(rs) and sum(rs) / len(rs) > MIN_CORR

        ok = [similar(i) for i in range(len(dips))]
        marked = set()
        for i in range(len(dips) - 3):
            cycles = [times[i + k + 1] - times[i + k] for k in range(3)]
            if not all(CYCLE[0] <= c <= CYCLE[1] for c in cycles):
                continue
            s = sum(cycles) / 3
            if np.prod([3 - 2 * c / s for c in cycles]) <= MIN_EQUIVALENCE:
                continue
            if not all(ok[i:i + 4]):
                continue
            marked.update(range(i, i + 4))
        found += [times[i] for i in sorted(marked)]
    return {"dips": found, "fcv": len(found) / time_in_bed_h}


def annotate(recs):
    """Run the detector on every sleep with heart rate. Sets r.cvhr = {fcv, dips (datetimes),
    by_stage {stage: dips}, stage_hours {stage: hours}}. Time in bed is the sleep session."""
    from datetime import timedelta

    for r in recs:
        if not r.hr_stats:
            continue
        samples = [((t - r.start).total_seconds(), v) for t, v in r.hr_stats["samples"]]
        found = detect(samples, (r.end - r.start).total_seconds() / 3600)
        if not found:
            continue
        dips = [r.start + timedelta(seconds=s) for s in found["dips"]]
        by_stage, stage_hours = {}, {}
        if r.sleep:
            for a, b, kind in r.sleep["stages"]:
                stage_hours[kind] = stage_hours.get(kind, 0) + (b - a).total_seconds() / 3600
            for d in dips:
                kind = next((k for a, b, k in r.sleep["stages"] if a <= d < b), None)
                if kind:
                    by_stage[kind] = by_stage.get(kind, 0) + 1
        r.cvhr = {"fcv": found["fcv"], "dips": dips, "by_stage": by_stage, "stage_hours": stage_hours}
