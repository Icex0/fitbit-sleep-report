"""The Apple Health import and the whole report pipeline, on a small generated export."""
import json
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from xml.sax.saxutils import quoteattr

from sleep_report import cli, settings, store
from sleep_report.analysis import load_recordings
from sleep_report.export import export
from sleep_report.literature import evaluate
from sleep_report.metrics import metrics
from sleep_report.sources import apple

TZ = timezone(timedelta(hours=2))
NIGHTS = 14
WATCH = ("Test Apple Watch", "<<HKDevice: 0x1>, name:Apple Watch, manufacturer:Apple Inc., model:Watch>")
PHONE = ("Test iPhone", "<<HKDevice: 0x2>, name:iPhone, manufacturer:Apple Inc., model:iPhone>")
OTHER_APP = ("SleepApp", None)
NIGHT_STAGES = [("Core", 60), ("Deep", 45), ("Core", 30), ("REM", 25), ("Awake", 5), ("Core", 60), ("Deep", 30),
                ("REM", 40), ("Core", 60), ("REM", 30)]


def record(kind, source, start, end, value, unit=None):
    name, device = source
    attrs = {"type": kind, "sourceName": name, "unit": unit, "startDate": start.strftime("%Y-%m-%d %H:%M:%S %z"),
             "endDate": end.strftime("%Y-%m-%d %H:%M:%S %z"), "value": value}
    if device:
        attrs["device"] = device
    return "<Record " + " ".join(f"{k}={quoteattr(str(v))}" for k, v in attrs.items() if v is not None) + "/>"


def sleep(source, start, minutes, stage):
    return record("HKCategoryTypeIdentifierSleepAnalysis", source, start, start + timedelta(minutes=minutes),
                  f"HKCategoryValueSleepAnalysis{stage}")


def quantity(kind, t, value, unit):
    return record(f"HKQuantityTypeIdentifier{kind}", WATCH, t, t, value, unit)


def make_export():
    """14 nights from an Apple Watch, one nap, and records the import should ignore."""
    rows = []
    for i in range(NIGHTS):
        bed = datetime(2026, 10, 1, 23, 30, tzinfo=TZ) + timedelta(days=i, minutes=20 * (i % 3))
        t = bed
        for stage, minutes in NIGHT_STAGES:
            rows.append(sleep(WATCH, t, minutes, "Asleep" + stage if stage != "Awake" else "Awake"))
            t += timedelta(minutes=minutes)
        wake = t
        rows.append(sleep(PHONE, bed - timedelta(minutes=10), (wake - bed).seconds // 60 + 15, "InBed"))
        rows.append(sleep(OTHER_APP, bed, (wake - bed).seconds // 60, "AsleepUnspecified"))
        rows.append(sleep(OTHER_APP, wake + timedelta(hours=7), 60, "AsleepUnspecified"))  # not a nap: other app
        t = bed
        while t < wake:  # sparse, like a standard Apple Watch: oxygen every 30 min, heart rate every 5 min
            if (t - bed).seconds % 1800 == 0:
                rows.append(quantity("OxygenSaturation", t, 0.96, "%"))
                rows.append(quantity("RespiratoryRate", t, 14.5, "count/min"))
            rows.append(quantity("HeartRate", t, 56 + (t - bed).seconds // 300 % 4, "count/min"))
            t += timedelta(minutes=5)
        for k in range(3):
            rows.append(quantity("HeartRateVariabilitySDNN", bed + timedelta(hours=2 * k + 1), 45 + k, "ms"))
        rows.append(quantity("AppleSleepingWristTemperature", wake - timedelta(minutes=30), 35.8 + 0.02 * (i % 4), "degC"))
        rows.append(quantity("RestingHeartRate", wake + timedelta(hours=1), 52, "count/min"))
    nap = datetime(2026, 10, 4, 15, 0, tzinfo=TZ)
    rows.append(sleep(WATCH, nap, 50, "AsleepCore"))
    return '<?xml version="1.0" encoding="UTF-8"?>\n<HealthData locale="en_US">\n' + "\n".join(rows) + "\n</HealthData>\n"


class AppleImportTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.zip = root / "export.zip"
        with zipfile.ZipFile(cls.zip, "w") as z:
            z.writestr("apple_health_export/export.xml", make_export())
        cls.data = root / "data"
        cls.data.mkdir()
        cls.summary = apple.import_export(cls.zip, cls.data)
        cls.recs = load_recordings(cls.data)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_nights_and_naps_from_the_watch_only(self):
        self.assertEqual((self.summary["nights"], self.summary["naps"]), (NIGHTS, 1))
        self.assertEqual(sum(r.kind == "night" for r in self.recs), NIGHTS)
        self.assertEqual(store.load_source(self.data), "apple")

    def test_stages_carry_over(self):
        night = next(r for r in self.recs if r.kind == "night")
        minutes = night.sleep["minutes"]
        self.assertEqual(minutes.get("DEEP"), 75)
        self.assertEqual(minutes.get("REM"), 95)
        self.assertEqual(night.sleep["asleep"], sum(m for s, m in NIGHT_STAGES if s != "Awake"))

    def test_oxygen_is_stored_in_percent(self):
        values = {v for _, (_, v) in store.load_spo2(self.data / "spo2.csv").items()}
        self.assertEqual(values, {96.0})

    def test_sparse_readings_give_averages_not_counts(self):
        night = next(r for r in self.recs if r.kind == "night")
        self.assertIsNone(night.spo2_stats)
        self.assertEqual(round(night.spo2_summary["avg"]), 96)
        self.assertIsNone(night.hr_stats)
        self.assertIsNotNone(night.hr_summary)

    def test_daily_values(self):
        daily = store.load_daily(self.data / "daily.json")
        day = daily[min(daily)]
        self.assertEqual((day["hrv"], day["hrv_kind"], day["resting_hr"]), (46, "sdnn", 52))
        self.assertTrue(any("temp_baseline" in d for d in daily.values()))

    def test_refuses_to_mix_devices(self):
        with self.assertRaises(SystemExit):
            cli.check_source(self.data, "google")

    def test_report_end_to_end(self):
        profile = {**settings.profile({**settings.DEFAULTS, "age": 30}), "source": "apple"}
        m = metrics(self.recs, settings.free_evenings(profile["daysOff"]), profile["usualBedtimeH"], profile["age"])
        self.assertIsNone(m.get("odi3_median"))
        findings, refs = evaluate(m, profile)
        ids = {f["id"] for f in findings}
        self.assertIn("apple-device", ids)
        self.assertNotIn("device-accuracy", ids)
        self.assertNotIn("hrv-norm", ids)  # SDNN is not comparable with the RMSSD norms
        for f in findings:
            text = f["headline"] + f["detail"] + f["background"] + f["caveat"] + " ".join(b["range"] for b in f["bands"])
            with self.subTest(finding=f["id"]):
                self.assertNotIn("{", text)
        out = Path(self.tmp.name) / "web"
        export(self.recs, out, findings, refs, profile, m)
        summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
        self.assertEqual(len(summary["recordings"]), NIGHTS + 1)
        self.assertEqual(len(list((out / "nights").glob("*.json"))), NIGHTS + 1)


if __name__ == "__main__":
    unittest.main()
