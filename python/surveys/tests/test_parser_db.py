import unittest
from unittest.mock import patch

from python.surveys.db import SurveyDB
from python.surveys.parser import parse_survey_page
from python.surveys.schemas import FieldKind, Persona, SurveyField, UserProfile
from python.surveys.profile_refiner import _deep_merge


class TestSurveyParser(unittest.TestCase):
    def test_groups_radio_checkbox(self):
        dom = """
        <h1>Demo</h1>
        <div>Preferred mobile platform</div>
        <div><input type="radio" name="mobile" selector="1a" /> Android</div>
        <div><input type="radio" name="mobile" selector="2a" /> iOS</div>
        <div>Topics</div>
        <div><input type="checkbox" name="topics" selector="3a" /> Music</div>
        <div><input type="checkbox" name="topics" selector="4a" /> Sports</div>
        """
        page = parse_survey_page(dom, url="file://demo")
        radios = [f for f in page.fields if f.kind == FieldKind.RADIO]
        checks = [f for f in page.fields if f.kind == FieldKind.CHECKBOX]
        self.assertEqual(len(radios), 1)
        self.assertEqual(len(checks), 1)
        self.assertIn("android", " ".join(radios[0].options).lower())
        self.assertTrue(radios[0].option_selectors)
        self.assertEqual(set(checks[0].option_selectors.values()), {"3a", "4a"})


class TestSurveyDB(unittest.TestCase):
    def test_db_roundtrip_and_events(self):
        db = SurveyDB(":memory:")
        try:
            persona = Persona(id="p1", name="Test", description="x", constraints={"a": 1})
            db.upsert_persona(persona)
            got = db.get_persona("p1")
            self.assertIsNotNone(got)
            self.assertEqual(got.name, "Test")

            profile = UserProfile(id="default", persona_id="p1", data={"demographics": {"country": "DE"}})
            db.upsert_profile(profile)

            db.create_session("s1", url="file://demo", persona_id="p1", profile_id="default")
            field = SurveyField(selector="1a", kind=FieldKind.TEXT, label="Email")
            db.insert_answer("a1", "s1", "Email", field, "test@example.com")

            evs = db.fetch_unprocessed_answer_events()
            self.assertEqual(len(evs), 1)
            self.assertEqual(evs[0]["profile_id"], "default")
            self.assertEqual(evs[0]["persona_id"], "p1")
            self.assertEqual(evs[0]["answer_text"], "test@example.com")

            db.mark_answers_processed(["a1"])
            self.assertEqual(db.fetch_unprocessed_answer_events(), [])
        finally:
            db.close()

    def test_unprocessed_order_stable_when_created_at_ties(self):
        """Same-second inserts must not rely on undefined SQLite ordering."""
        fixed_ts = 1_700_000_000
        with patch("python.surveys.db._now_ts", return_value=fixed_ts):
            db = SurveyDB(":memory:")
            try:
                persona = Persona(id="p1", name="Test", description="x", constraints={})
                db.upsert_persona(persona)
                profile = UserProfile(id="default", persona_id="p1", data={})
                db.upsert_profile(profile)
                db.create_session("s1", url="file://demo", persona_id="p1", profile_id="default")
                field = SurveyField(selector="1a", kind=FieldKind.TEXT, label="Q")
                # Insert lexicographically later id first; tie-break must still order by id ASC.
                db.insert_answer("b2", "s1", "Q", field, "second")
                db.insert_answer("a1", "s1", "Q", field, "first")

                ids_plain = [r["id"] for r in db.fetch_unprocessed_answers()]
                ids_events = [r["id"] for r in db.fetch_unprocessed_answer_events()]
                self.assertEqual(ids_plain, ["a1", "b2"])
                self.assertEqual(ids_events, ["a1", "b2"])
            finally:
                db.close()


class TestDeepMerge(unittest.TestCase):
    def test_deep_merge(self):
        dst = {"a": {"b": 1}, "x": 1}
        src = {"a": {"c": 2}, "x": 2, "y": 3}
        out = _deep_merge(dst, src)
        self.assertEqual(out["a"]["b"], 1)
        self.assertEqual(out["a"]["c"], 2)
        self.assertEqual(out["x"], 2)
        self.assertEqual(out["y"], 3)


if __name__ == "__main__":
    unittest.main()

