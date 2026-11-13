import unittest
from pathlib import Path
from PIL import Image
from healing import HealthReader, HealthView, HealPolicy

ROOT = Path(__file__).resolve().parents[1]


def view(stage="main", hp=(.4, 1, .7, 1), y=256):
    return HealthView(True, stage, hp, y, stage != "main", stage != "main")


class HealingTests(unittest.TestCase):
    def test_real_screens_and_hp_percentages(self):
        reader = HealthReader(ROOT / "assets/healing")
        expected = {"main": "main", "items": "main", "healer": "healer", "ability": "ability", "target": "target", "after": "target"}
        for name, stage in expected.items():
            with Image.open(ROOT / "tests/fixtures" / f"heal_{name}.png") as image:
                reading = reader.read(image)
            self.assertEqual(reading.stage, stage)
            self.assertEqual(len(reading.hp), 4)
            if name in ("healer", "ability", "target"):
                self.assertAlmostEqual(reading.hp[0], 446/1043, delta=.02)
            else:
                self.assertGreater(reading.hp[0], .6)

    def test_field_is_not_a_health_menu(self):
        reader = HealthReader(ROOT / "assets/healing")
        with Image.open(ROOT / "tests/fixtures/bp_three.png") as image:
            self.assertFalse(reader.read(image).menu)

    def go_to_cast(self, policy):
        policy.begin(0)
        self.assertEqual(policy.step(HealthView(), True, 0), ("tap", "menu"))
        policy.step(view(), False, .4)
        policy.step(view(), False, .5)
        self.assertEqual(policy.step(view(), False, .6), ("tap", "confirm"))
        self.assertEqual(policy.step(view("healer", y=126), False, 1), ("tap", "confirm"))
        self.assertEqual(policy.step(view("ability", y=134), False, 1.4), ("tap", "confirm"))
        self.assertEqual(policy.step(view("target", y=None), False, 1.8), ("tap", "confirm"))
        self.assertEqual(policy.casts, 1)

    def test_low_hp_heals_then_verifies_before_returning_to_field(self):
        policy = HealPolicy()
        self.go_to_cast(policy)
        healthy = view("target", (.8, 1, 1, 1), None)
        policy.step(healthy, False, 2.3)
        policy.step(healthy, False, 2.4)
        self.assertEqual(policy.phase, "exit")
        self.assertEqual(policy.step(healthy, False, 2.5), ("tap", "cancel"))
        policy.step(HealthView(), True, 3)
        self.assertEqual(policy.step(HealthView(), True, 3.1)[0], "done")

    def test_healthy_party_skips_ability_and_exits(self):
        policy = HealPolicy()
        policy.begin(0)
        policy.step(HealthView(), True, 0)
        healthy = view(hp=(.65, 1, 1, 1))
        policy.step(healthy, False, .4)
        policy.step(healthy, False, .5)
        self.assertEqual(policy.step(healthy, False, .6), ("tap", "cancel"))
        self.assertEqual(policy.casts, 0)

    def test_no_hp_increase_stops_without_repeating_cast(self):
        policy = HealPolicy()
        self.go_to_cast(policy)
        unchanged = view("target", y=None)
        self.assertEqual(policy.step(unchanged, False, 2.3)[0], "idle")
        self.assertEqual(policy.step(unchanged, False, 6)[0], "stop")
        self.assertEqual(policy.casts, 1)

    def test_disabled_ability_does_not_receive_unbounded_confirms(self):
        policy = HealPolicy()
        self.go_to_cast(policy)
        # New run ending at the ability-to-target transition, where SP may be insufficient.
        policy.phase = "target"
        policy.waiting_stage = "ability"
        policy.deadline = 5
        self.assertEqual(policy.step(view("ability", y=134), False, 2.3)[0], "idle")
        self.assertEqual(policy.step(view("ability", y=134), False, 6)[0], "stop")

    def test_navigation_uses_current_cursor_instead_of_assuming_menu_selection(self):
        policy = HealPolicy()
        policy.begin(0)
        policy.step(HealthView(), True, 0)
        policy.step(view(y=206), False, .4)
        policy.step(view(y=206), False, .5)
        self.assertEqual(policy.step(view(y=206), False, .6), ("tap", "down"))

    def test_missing_hp_and_zero_hp_stop(self):
        policy = HealPolicy()
        policy.begin(0)
        policy.step(HealthView(), True, 0)
        self.assertEqual(policy.step(view(hp=None), False, 6)[0], "stop")
        self.assertEqual(policy.step(view(hp=(0, 1, 1, 1)), False, .5)[0], "stop")


if __name__ == "__main__":
    unittest.main()
