import unittest
from datetime import datetime, timedelta

from sleep_report.analysis import DENSE_SPO2, build_recordings, dense, desaturations, night_of, split_settling

START = datetime(2026, 10, 20, 23, 0)


def series(values, step=timedelta(minutes=1)):
    return [(START + i * step, v) for i, v in enumerate(values)]


class NightTest(unittest.TestCase):
    def test_night_runs_from_18_to_18(self):
        self.assertEqual(night_of(datetime(2026, 10, 20, 23, 0)), "2026-10-20")
        self.assertEqual(night_of(datetime(2026, 10, 21, 3, 0)), "2026-10-20")
        self.assertEqual(night_of(datetime(2026, 10, 21, 17, 59)), "2026-10-20")
        self.assertEqual(night_of(datetime(2026, 10, 21, 18, 0)), "2026-10-21")


class RecordingsTest(unittest.TestCase):
    @staticmethod
    def session(start, end, main):
        span = {"startTime": f"{start:%Y-%m-%dT%H:%M:00Z}", "startUtcOffset": "0s",
                "endTime": f"{end:%Y-%m-%dT%H:%M:00Z}", "endUtcOffset": "0s"}
        return {"interval": span, "type": "STAGES", "stages": [{**span, "type": "LIGHT"}],
                "metadata": {"mainSleep": main, "nap": not main}}

    def test_one_night_per_evening_even_with_two_main_sleeps(self):
        # Fitbit marks a main sleep per day it ends on: an evening sleep and the night after can both be "main"
        evening = self.session(datetime(2026, 11, 3, 18, 54), datetime(2026, 11, 3, 20, 26), True)
        night = self.session(datetime(2026, 11, 4, 2, 58), datetime(2026, 11, 4, 10, 1), True)
        recs = build_recordings({}, [evening, night])
        self.assertEqual([(r.kind, r.start.hour) for r in recs], [("nap", 18), ("night", 2)])
        self.assertEqual(recs[1].name, "2026-11-03")

    def test_a_nap_across_18_00_is_not_split_into_a_guessed_night(self):
        start, end = datetime(2026, 10, 28, 17, 30), datetime(2026, 10, 28, 19, 0)
        span = {"startTime": f"{start:%Y-%m-%dT%H:%M:00Z}", "startUtcOffset": "0s",
                "endTime": f"{end:%Y-%m-%dT%H:%M:00Z}", "endUtcOffset": "0s"}
        nap = {"interval": span, "type": "STAGES", "stages": [{**span, "type": "LIGHT"}],
               "metadata": {"mainSleep": False, "nap": True}}
        rows = {str(i): ((start + timedelta(minutes=i)).isoformat(), 96) for i in range(91)}
        recs = build_recordings(rows, [nap])
        self.assertEqual([r.kind for r in recs], ["nap"])
        self.assertEqual(len(recs[0].spo2), 91)


class DensityTest(unittest.TestCase):
    def test_dense_uses_the_typical_gap(self):
        self.assertTrue(dense(series([96] * 30), DENSE_SPO2))
        self.assertFalse(dense(series([96] * 30, timedelta(minutes=5)), DENSE_SPO2))
        self.assertFalse(dense(series([96]), DENSE_SPO2))


class DesaturationTest(unittest.TestCase):
    def test_a_short_dip_counts_once(self):
        values = [96] * 30 + [92, 92] + [96] * 30
        events = desaturations(series(values), 3)
        self.assertEqual(len(events), 1)
        start, _end, nadir, baseline = events[0]
        self.assertEqual((start, nadir, baseline), (START + timedelta(minutes=30), 92, 96))
        self.assertEqual(len(desaturations(series(values), 4)), 1)
        self.assertEqual(len(desaturations(series(values), 5)), 0)

    def test_a_lasting_drop_is_one_capped_dip_not_many(self):
        values = [96] * 30 + [92] * 40
        self.assertEqual(len(desaturations(series(values), 3)), 1)

    def test_a_gap_ends_a_dip(self):
        samples = series([96] * 30 + [92, 92])
        samples += [(samples[-1][0] + timedelta(minutes=20), 92)]
        start, end, _, _ = desaturations(samples, 3)[0]
        self.assertEqual(end - start, timedelta(minutes=1))

    def test_readings_just_after_a_gap_are_settling(self):
        samples = series([96] * 10)
        samples += [(samples[-1][0] + timedelta(minutes=30) + i * timedelta(minutes=1), 90) for i in range(5)]
        keep, settling = split_settling(samples)
        self.assertEqual(len(settling), 2 + 2)  # first 2 minutes of the night and after the gap
        self.assertEqual(len(keep), len(samples) - len(settling))


if __name__ == "__main__":
    unittest.main()
