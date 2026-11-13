import unittest
from PIL import Image
from engine import Loop, Limits
from vision import classify


class LoopTests(unittest.TestCase):
    def test_fast_confirm_keeps_distinct_press_intervals(self):
        loop = Loop(0, Limits(confirm_interval=.15))
        loop.step("battle", 0)
        self.assertEqual(loop.step("battle", .08)[0], "tap")
        self.assertEqual(loop.step("battle", .16)[0], "idle")
        self.assertEqual(loop.step("battle", .24)[0], "tap")

    def test_levelup_before_regular_result_counts_one_win(self):
        loop = Loop(0, Limits())
        for scene, now in [("battle", 0), ("battle", .2), ("levelup", 1), ("levelup", 1.2)]:
            loop.step(scene, now)
        self.assertEqual(loop.wins, 1)
        loop.step("victory", 2)
        loop.step("victory", 2.2)
        self.assertEqual(loop.wins, 1)
        self.assertEqual(loop.step("levelup", 32)[0], "stop")

    def test_result_variants_do_not_conflict(self):
        image = Image.new("RGB", (100, 100), "white")
        templates = {s: [((0, 0, 50, 50), image.crop((0, 0, 50, 50)))] for s in ("victory", "levelup")}
        self.assertIn(classify(image, templates, 12)[0], ("victory", "levelup"))

    def test_wait_for_stable_scene_and_release_on_unknown(self):
        loop = Loop(0, Limits())
        self.assertEqual(loop.step("field", 0)[0], "idle")
        self.assertEqual(loop.step("field", .2), ("hold", "left"))
        self.assertEqual(loop.step("field", 1.1), ("hold", "right"))
        self.assertEqual(loop.step("unknown", 1.3)[0], "idle")
        self.assertEqual(loop.step("unknown", 22)[0], "stop")

    def test_complete_cycle_counts_once(self):
        loop = Loop(0, Limits())
        for scene, now in [("field", 0), ("field", .2), ("battle", 1), ("battle", 1.2),
                           ("victory", 2), ("victory", 2.2), ("victory", 3)]:
            loop.step(scene, now)
        self.assertEqual(loop.wins, 1)
        loop.step("field", 4)
        loop.step("field", 4.2)
        self.assertIsNone(loop.encounter_started)

    def test_battle_deadline_survives_unknown_animation(self):
        loop = Loop(0, Limits(battle=10, unknown=20))
        loop.step("battle", 0)
        loop.step("battle", .2)
        loop.step("unknown", 9)
        self.assertEqual(loop.step("battle", 11)[0], "stop")

    def test_danger_and_runtime_stop_immediately(self):
        self.assertEqual(Loop(0, Limits()).step("danger", 0)[0], "stop")
        self.assertEqual(Loop(0, Limits(duration=10)).step("field", 10)[0], "stop")

    def test_no_encounter_stops(self):
        loop = Loop(0, Limits(field=10))
        loop.step("field", 0)
        loop.step("field", .2)
        self.assertEqual(loop.step("field", 11)[0], "stop")

    def test_ambiguous_and_unmatched_images_do_not_trigger_input(self):
        image = Image.new("RGB", (100, 100), "white")
        templates = {s: [((0, 0, 50, 50), image.crop((0, 0, 50, 50)))] for s in ("battle", "victory")}
        self.assertEqual(classify(image, templates, 12)[0], "unknown")
        self.assertEqual(classify(Image.new("RGB", (100, 100)), templates, 12)[0], "unknown")
        templates = {"field": [((0, 0, 50, 50), image.crop((0, 0, 50, 50)))]}
        # A featureless patch cannot identify a field, even when it is the only reference.
        self.assertEqual(classify(image, templates, 12)[0], "unknown")


if __name__ == "__main__":
    unittest.main()
