import json
import re
import unittest

from sleep_report.literature import FORMATS, KNOWLEDGE_BASE, evaluate

KB = json.loads(KNOWLEDGE_BASE.read_text(encoding="utf-8"))
GROUPS = {"teen", "young_adult", "adult", "older"}
REPUTES = {"good", "attention", "info"}


class KnowledgeBaseTest(unittest.TestCase):
    def test_ids_are_unique(self):
        ids = [f["id"] for f in KB["findings"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_citation_exists(self):
        for f in KB["findings"]:
            for ref in f.get("refs", []) + [r for b in f.get("bands", []) for r in b.get("refs", [])]:
                with self.subTest(finding=f["id"], ref=ref):
                    self.assertIn(ref, KB["references"])

    def test_every_reference_is_cited_and_traceable(self):
        cited = {r for f in KB["findings"] for r in f.get("refs", []) + [r for b in f.get("bands", []) for r in b.get("refs", [])]}
        for ref_id, ref in KB["references"].items():
            with self.subTest(ref=ref_id):
                self.assertIn(ref_id, cited)
                self.assertTrue(ref.get("pmid") or ref.get("doi") or ref.get("url"), "needs a PMID, DOI or URL")

    def test_findings_are_well_formed(self):
        for f in KB["findings"]:
            with self.subTest(finding=f["id"]):
                self.assertIn(f.get("format", "number"), FORMATS)
                self.assertLessEqual(set(f.get("groups", [])), GROUPS)
                for b in f.get("bands", []):
                    self.assertIn(b.get("repute", "info"), REPUTES)
                    self.assertLessEqual(set(b.get("groups", [])), GROUPS)
                    self.assertIn("headline", b)
                if not f.get("bands"):
                    self.assertIn("headline", f)

    def test_bands_do_not_overlap(self):
        for f in KB["findings"]:
            for group in GROUPS:
                bands = [b for b in f.get("bands", []) if "groups" not in b or group in b["groups"]]
                spans = sorted((b.get("min", float("-inf")), b.get("max", float("inf"))) for b in bands)
                for (_, hi), (lo, _) in zip(spans, spans[1:]):
                    with self.subTest(finding=f["id"], group=group):
                        self.assertLessEqual(hi, lo)

    def test_placeholders_are_python_format_fields(self):
        def strings(x):
            if isinstance(x, str):
                yield x
            elif isinstance(x, dict):
                for v in x.values():
                    yield from strings(v)
            elif isinstance(x, list):
                for v in x:
                    yield from strings(v)

        for text in strings(KB["findings"]):
            for field in re.findall(r"\{([^{}]*)\}", text):
                with self.subTest(field=field):
                    self.assertRegex(field, r"^[a-z0-9_]+(:[^{}]+)?$")


class EvaluateTest(unittest.TestCase):
    KB = {"references": {}, "findings": [{
        "id": "x", "topic": "t", "title": "x", "metric": "m", "detail": "about the study",
        "bands": [{"max": 1, "headline": "low"}, {"min": 1, "headline": "high", "detail": "about high values"}],
    }]}

    def detail(self, value):
        findings, _ = evaluate({"m": value}, {"group": "adult"}, self.KB)
        return findings[0]["detail"]

    def test_a_band_without_detail_shows_the_findings_detail(self):
        self.assertEqual(self.detail(0.5), "about the study")

    def test_a_bands_own_detail_wins(self):
        self.assertEqual(self.detail(2), "about high values")

    def test_too_few_nights_gives_a_pending_finding(self):
        kb = {"references": {}, "findings": [{**self.KB["findings"][0], "basis": "staged", "minNights": 14}]}
        few, _ = evaluate({"m": 2, "staged": 5}, {"group": "adult"}, kb)
        self.assertTrue(few[0]["pending"])
        self.assertIsNone(few[0]["valueText"])
        self.assertIn("14 nights", few[0]["headline"])
        enough, _ = evaluate({"m": 2, "staged": 14}, {"group": "adult"}, kb)
        self.assertFalse(enough[0]["pending"])
        self.assertEqual((enough[0]["headline"], enough[0]["basedOn"]), ("high", 14))

    def test_minimums_are_on_measured_findings(self):
        for f in KB["findings"]:
            with self.subTest(finding=f["id"]):
                if "minNights" in f:
                    self.assertTrue(f.get("metric"))
                if "basis" in f:
                    self.assertRegex(f["basis"], r"^[a-z0-9_]+_nights$")


if __name__ == "__main__":
    unittest.main()
