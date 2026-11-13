import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from bp import BPReader, BPPolicy, Reading

ROOT = Path(__file__).resolve().parents[1]


class BPTests(unittest.TestCase):
    def setUp(self):
        with Image.open(ROOT / "assets/bp_command.png") as source:
            self.command = source.convert("RGB")
        self.reader = BPReader(self.command)

    def hud(self, active, amounts):
        image = Image.new("RGB", (1280, 720), (40, 60, 90))
        image.paste(self.command, (850, 400))
        draw = ImageDraw.Draw(image)
        for row, amount in enumerate(amounts):
            x, y = (1063 if row == active else 1113), 78+102*row
            draw.rectangle((x, y, x+120, y+5), fill=(100, 145, 100))
            for slot in range(amount):
                cx, cy = x+6+10*slot, y-30
                draw.ellipse((cx-3, cy-3, cx+3, cy+3), fill=(255, 180, 80))
        return image

    def test_real_frame_before_and_after_boost_despite_background_change(self):
        for name, expected in (("bp_three.png", 3), ("bp_two.png", 2)):
            with Image.open(ROOT / "tests/fixtures" / name) as source:
                reading = self.reader.read(source)
            self.assertTrue(reading.ready)
            self.assertEqual((reading.actor, reading.bp), (0, expected))

    def test_only_shifted_active_actor_is_read(self):
        for actor in range(4):
            amounts = [1, 2, 3, 5]
            reading = self.reader.read(self.hud(actor, amounts))
            self.assertEqual((reading.actor, reading.bp), (actor, amounts[actor]))

    def test_empty_active_bp_is_not_confused_with_full_inactive_bp(self):
        reading = self.reader.read(self.hud(1, [5, 0, 5]))
        self.assertEqual((reading.actor, reading.bp), (1, 0))

    def test_no_left_shift_is_unreliable(self):
        reading = self.reader.read(self.hud(-1, [2, 3, 5]))
        self.assertIsNone(reading.bp)

    def test_field_is_not_a_command_screen(self):
        self.assertFalse(self.reader.read(Image.new("RGB", (1280, 720), "green")).ready)

    def test_active_hud_is_read_before_command_label_appears(self):
        image = self.hud(1, [4, 1, 3])
        ImageDraw.Draw(image).rectangle((850, 400, 899, 419), fill=(40, 60, 90))
        reading = self.reader.read(image)
        self.assertFalse(reading.ready)
        self.assertEqual((reading.actor, reading.bp), (1, 1))

    def test_unreadable_command_and_bp_still_progress_to_attack(self):
        policy = BPPolicy()
        actions = [policy.step(Reading(False), now) for now in (0, .11, .22, .33, .44)]
        self.assertEqual(actions, [("tap", "boost")]*3+[("tap", "confirm")]*2)

    def test_zero_and_full_bp_produce_the_same_all_in_sequence(self):
        for bp in (None, 0, 1, 4, 5):
            policy = BPPolicy()
            actions = [policy.step(Reading(True, 1, bp), now) for now in (0, .11, .22, .33, .44)]
            self.assertEqual(actions.count(("tap", "boost")), 3)
            self.assertEqual(actions.count(("tap", "confirm")), 2)

    def test_no_bp_decrease_is_needed_for_next_key(self):
        policy = BPPolicy()
        self.assertEqual(policy.step(Reading(True, 0, 3), 0), ("tap", "boost"))
        self.assertEqual(policy.step(Reading(True, 0, 3), .11), ("tap", "boost"))
        self.assertEqual(policy.step(Reading(True, 0, 3), .22), ("tap", "boost"))
        self.assertEqual(policy.step(Reading(True, 0, 3), .33), ("tap", "confirm"))

    def test_flickering_label_does_not_restart_unfinished_burst(self):
        policy = BPPolicy()
        readings = [Reading(True, 0, 3), Reading(False), Reading(True, 0, 3), Reading(False)]
        actions = [policy.step(reading, now) for reading, now in zip(readings, (0, .11, .22, .33))]
        self.assertEqual(actions[-1], ("tap", "confirm"))

    def test_perception_flicker_cannot_starve_enter(self):
        policy = BPPolicy()
        actions = [policy.step(Reading(i % 2 == 0, i % 4, None), i*.11) for i in range(50)]
        self.assertEqual(actions.count(("tap", "confirm")), 20)

    def test_cycle_continues_and_interval_is_bounded(self):
        policy = BPPolicy()
        self.assertEqual(policy.step(Reading(False, 0, 1), 0), ("tap", "boost"))
        self.assertEqual(policy.step(Reading(False, 0, 1), .05)[0], "idle")
        for now in (.11, .22, .33, .44):
            policy.step(Reading(False), now)
        self.assertEqual(policy.step(Reading(False), .55), ("tap", "boost"))


if __name__ == "__main__":
    unittest.main()
