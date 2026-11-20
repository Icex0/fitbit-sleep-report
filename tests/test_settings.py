import unittest

from sleep_report import settings


class SettingsTest(unittest.TestCase):
    def test_bedtime_is_hours_after_18(self):
        self.assertEqual(settings.bedtime_h("23:00"), 5.0)
        self.assertEqual(settings.bedtime_h("01:30"), 7.5)
        self.assertEqual(settings.bedtime_h("18:00"), 0.0)
        with self.assertRaises(ValueError):
            settings.bedtime_h("25:00")

    def test_free_evenings_are_the_evenings_before_days_off(self):
        self.assertEqual(settings.free_evenings(["Sat", "Sun"]), {"Fri", "Sat"})
        self.assertEqual(settings.free_evenings(["Mon"]), {"Sun"})

    def test_validate(self):
        self.assertEqual(settings.validate(dict(settings.DEFAULTS)), [])
        for bad in ({"age": 10}, {"age": "thirty"}, {"days_off": ["Saturday"]}, {"usual_bedtime": "late"},
                    {"shift_work": "no"}, {"often_tired": "sometimes"}, {"device": "garmin"}):
            with self.subTest(bad=bad):
                self.assertTrue(settings.validate({**settings.DEFAULTS, **bad}))

    def test_profile_age_groups(self):
        def group(age):
            return settings.profile({**settings.DEFAULTS, "age": age})["group"]

        self.assertEqual(group(16), "teen")
        self.assertEqual(group(22), "young_adult")
        self.assertEqual(group(40), "adult")
        self.assertEqual(group(70), "older")
        no_age = settings.profile(dict(settings.DEFAULTS))
        self.assertEqual(no_age["group"], "adult")
        self.assertTrue(no_age["ageAssumed"])


if __name__ == "__main__":
    unittest.main()
