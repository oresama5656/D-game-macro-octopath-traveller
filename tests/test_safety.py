import ctypes
import tkinter as tk
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from unittest.mock import Mock, patch
from PIL import Image
from app import App
from engine import Loop, Limits
from win32_io import INPUT, Keyboard, WindowKeyboard, BackgroundFrames
from healing import HealthView


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.config_patch = patch("app.CONFIG", Path(self.temporary.name) / "settings.json")
        self.config_patch.start()
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root)
        self.app.topmost.set(False)  # Unit tests isolate foreground capture from floating UI.
        self.app.keyboard = Mock()

    def tearDown(self):
        self.root.destroy()
        self.config_patch.stop()
        self.temporary.cleanup()

    def test_operation_mode_survives_reload(self):
        self.app.dry.set(False)
        self.app.background.set(True)
        self.app.heal_mode.set(True)
        self.app.save()
        self.app.dry.set(True)
        self.app.background.set(False)
        self.app.heal_mode.set(False)
        self.app.topmost.set(True)
        self.app.load()
        self.assertFalse(self.app.dry.get())
        self.assertTrue(self.app.background.get())
        self.assertTrue(self.app.heal_mode.get())
        self.assertFalse(self.app.topmost.get())

    def test_post_battle_health_check_opens_menu_before_any_movement(self):
        self.app.run_heal = True
        self.app.run_dry = False
        self.app.settings()
        self.app.loop = Loop(0, Limits())
        self.app.loop.step("battle", 0)
        self.app.loop.step("battle", .1)
        with patch.object(self.app, "recognize", return_value=("field", {})), patch.object(self.app.health_reader, "read", return_value=HealthView()), patch("app.foreground", return_value=True), patch("app.pressed", return_value=False):
            self.app.process_frame(.2, Mock())
            self.app.process_frame(.3, Mock())
        self.app.keyboard.hold.assert_called_once_with("i")
        self.assertTrue(self.app.heal_policy.active)

    def test_healing_menu_bypasses_simple_mode_and_boost_inputs(self):
        self.app.run_heal = True
        self.app.run_simple = True
        self.app.run_bp = True
        self.app.run_dry = False
        self.app.settings()
        self.app.loop = Loop(0, Limits())
        self.app.heal_policy.begin(0)
        self.app.heal_policy.phase = "verify"
        self.app.heal_policy.baseline = (.4, 1, 1, 1)
        with patch.object(self.app, "recognize", return_value=("unknown", {})), patch.object(self.app.health_reader, "read", return_value=HealthView(True, "target", (.5, 1, 1, 1))), patch.object(self.app.bp_reader, "read") as bp_read:
            self.app.process_frame(.5, Mock())
        bp_read.assert_not_called()
        self.app.keyboard.hold.assert_not_called()

    def test_f9_also_cancels_healing(self):
        self.app.run_heal = True
        self.app.heal_policy.begin(0)
        with patch("app.pressed", side_effect=lambda key: key == 0x78):
            self.app.tick()
        self.assertFalse(self.app.heal_policy.active)
        self.app.keyboard.release.assert_called_once()

    def test_background_keys_never_use_global_keyboard(self):
        keyboard = WindowKeyboard(123)
        with patch("win32_io.u.IsWindow", return_value=True), patch("win32_io.u.PostMessageW", return_value=1) as post, patch("win32_io.u.SendInput") as global_send:
            keyboard.hold(["lshift", "left"])
            keyboard.release()
        global_send.assert_not_called()
        self.assertEqual(post.call_count, 4)
        for call in post.call_args_list:
            self.assertEqual(call.args[0], 123)
        self.assertEqual(keyboard.held, set())

    def test_failed_background_input_never_falls_back_to_global_input(self):
        keyboard = WindowKeyboard(123)
        with patch("win32_io.u.IsWindow", return_value=True), patch("win32_io.u.PostMessageW", return_value=0), patch("win32_io.u.SendInput") as global_send:
            with self.assertRaises(RuntimeError):
                keyboard.hold("left")
        global_send.assert_not_called()

    def test_background_capture_timeout_rejects_stale_frames(self):
        source = BackgroundFrames.__new__(BackgroundFrames)
        source.lock = Lock()
        source.latest = (1, 10, object())
        source.started = 10
        source.error = None
        with patch("win32_io.time.monotonic", return_value=13):
            with self.assertRaises(RuntimeError):
                source.poll()

    def test_repeated_background_frame_does_not_generate_input(self):
        self.app.run_background = True
        self.app.run_dry = False
        self.app.loop = Loop(0, Limits())
        self.app.frame_sequence = 1
        self.app.frame_source = Mock()
        self.app.frame_source.poll.return_value = (1, object())
        with patch("app.background_available", return_value=True), patch("app.pressed", return_value=False), patch("app.time.monotonic", return_value=.2):
            self.app.tick()
        self.app.keyboard.hold.assert_not_called()

    def test_bp_overrides_enter_and_finds_battle_without_portrait_reference(self):
        self.app.run_bp = True
        self.app.run_dry = False
        self.app.settings()
        self.app.loop = Loop(0, Limits())
        image = Image.open(Path(__file__).parent / "fixtures/bp_three.png").convert("RGB")
        with patch.object(self.app, "recognize", return_value=("unknown", {})), patch("app.foreground", return_value=True), patch("app.pressed", return_value=False):
            self.app.process_frame(.1, image)
            self.app.process_frame(.2, image)
        self.assertEqual(self.app.keyboard.hold.call_count, 2)
        for call in self.app.keyboard.hold.call_args_list:
            self.assertEqual(call.args, ("o",))

    def test_stop_screen_has_priority_over_bp(self):
        self.app.run_bp = True
        self.app.run_dry = False
        self.app.loop = Loop(0, Limits())
        with patch.object(self.app, "recognize", return_value=("danger", {})):
            self.app.process_frame(.1, Image.new("RGB", (1280, 720)))
        self.assertIsNone(self.app.loop)
        self.app.keyboard.hold.assert_not_called()

    def test_background_continues_without_focus_but_stops_when_minimized(self):
        self.app.run_dry = False
        self.app.run_background = True
        self.app.settings()
        self.app.loop = Loop(0, Limits())
        self.app.loop.step("field", .1)
        source = Mock()
        source.poll.return_value = (1, Mock())
        self.app.frame_source = source
        with patch("app.foreground", return_value=False), patch("app.background_available", return_value=True), patch("app.pressed", return_value=False), patch("app.capture") as desktop_capture, patch.object(self.app, "recognize", return_value=("field", {})), patch("app.time.monotonic", return_value=.2):
            self.app.tick()
        self.app.keyboard.hold.assert_called_once_with(["lshift", "left"])
        desktop_capture.assert_not_called()
        self.assertIsNotNone(self.app.loop)
        self.app.keyboard.reset_mock()
        with patch("app.background_available", return_value=False), patch("app.pressed", return_value=False):
            self.app.tick()
        self.assertIsNone(self.app.loop)
        self.app.keyboard.release.assert_called_once()
        source.close.assert_called_once()

    def test_changing_mode_stops_old_run(self):
        self.app.loop = Loop(0, Limits())
        self.app.dry.set(False)
        self.app.change_mode()
        self.assertIsNone(self.app.loop)
        self.app.keyboard.release.assert_called_once()
        self.assertIn("再度開始", self.app.status.get())

    def test_focus_loss_releases_keys_and_stops(self):
        self.app.loop = Loop(0, Limits())
        with patch("app.foreground", return_value=False), patch("app.pressed", return_value=False):
            self.app.tick()
        self.assertIsNone(self.app.loop)
        self.app.keyboard.release.assert_called_once()
        self.app.keyboard.hold.assert_not_called()

    def test_pinned_foreground_run_uses_window_frames_and_keeps_focus_guard(self):
        self.app.topmost.set(True)
        self.app.templates = {scene: [object()] for scene in ("field", "battle", "victory")}
        source = Mock()
        with patch.object(self.app, "later_capture") as capture, patch.object(self.app, "recognize", return_value=("field", {})), patch("app.BackgroundFrames", return_value=source) as frames, patch("app.Keyboard", return_value=self.app.keyboard):
            self.app.start()
            capture.call_args.args[0](None)
        frames.assert_called_once_with(self.app.hwnd)
        self.assertFalse(self.app.run_background)
        self.assertIs(self.app.frame_source, source)
        with patch("app.foreground", return_value=False), patch("app.pressed", return_value=False):
            self.app.tick()
        self.assertIsNone(self.app.loop)
        source.close.assert_called_once()

    def test_f9_cancels_countdown(self):
        self.app.armed = True
        with patch("app.pressed", side_effect=lambda vk: vk == 0x78):
            self.app.tick()
        self.assertFalse(self.app.armed)
        self.app.keyboard.release.assert_called_once()

    def test_f8_requests_immediate_start(self):
        with patch("app.pressed", side_effect=lambda vk: vk == 0x77), patch.object(self.app, "start") as start:
            self.app.tick()
        start.assert_called_once_with(immediate=True)

    def test_can_resume_from_registered_levelup_page(self):
        self.app.templates = {scene: [object()] for scene in ("field", "battle", "victory")}
        with patch.object(self.app, "later_capture") as capture, patch.object(self.app, "recognize", return_value=("levelup", {})):
            self.app.start()
            capture.call_args.args[0](None)
        self.assertIsNotNone(self.app.loop)

    def test_immediate_start_rejects_other_foreground_window(self):
        self.app.templates = {scene: [object()] for scene in ("field", "battle", "victory")}
        with patch.object(self.app, "select_game"), patch("app.foreground", return_value=False), patch.object(self.app, "later_capture") as capture:
            self.app.start(immediate=True)
        capture.assert_not_called()
        self.assertIsNone(self.app.loop)

    def test_old_capture_callback_cannot_start_new_run(self):
        self.app.capture_generation = 2
        self.app.armed = True
        callback = Mock()
        with patch("app.capture") as capture:
            self.app.finish_capture(callback, 1)
        callback.assert_not_called()
        capture.assert_not_called()

    def test_keyboard_releases_previous_direction(self):
        keyboard = Keyboard()
        with patch("win32_io.u.SendInput", return_value=1) as send:
            keyboard.hold("left")
            keyboard.hold("right")
            self.assertEqual(keyboard.held, {"right"})
            keyboard.release()
        self.assertEqual(keyboard.held, set())
        self.assertEqual(send.call_count, 4)
        self.assertEqual(ctypes.sizeof(INPUT), 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_dash_remains_held_during_turn_and_releases_for_battle(self):
        keyboard = Keyboard()
        with patch("win32_io.u.SendInput", return_value=1), patch.object(keyboard, "send", wraps=keyboard.send) as send:
            keyboard.hold(["lshift", "left"])
            self.assertEqual(keyboard.held, {"lshift", "left"})
            keyboard.hold(["lshift", "right"])
            self.assertEqual(keyboard.held, {"lshift", "right"})
            self.assertNotIn(unittest.mock.call("lshift", False), send.call_args_list)
            keyboard.hold("enter")
            self.assertEqual(keyboard.held, {"enter"})
            self.assertIn(unittest.mock.call("lshift", False), send.call_args_list)
            keyboard.release()
            self.assertEqual(keyboard.held, set())

    def test_field_dash_releases_immediately_on_battle_transition(self):
        self.app.run_dry = False
        self.app.settings()
        self.app.loop = Loop(0, Limits())
        self.app.loop.step("field", .1)
        with patch("app.foreground", return_value=True), patch("app.pressed", return_value=False), patch("app.capture"), patch.object(self.app, "recognize", return_value=("field", {})), patch("app.time.monotonic", return_value=.2):
            self.app.tick()
        self.app.keyboard.hold.assert_called_once_with(["lshift", "left"])
        self.app.keyboard.reset_mock()
        with patch("app.foreground", return_value=True), patch("app.pressed", return_value=False), patch("app.capture"), patch.object(self.app, "recognize", return_value=("battle", {})), patch("app.time.monotonic", return_value=.4):
            self.app.tick()
        self.app.keyboard.release.assert_called_once()
        self.app.keyboard.hold.assert_not_called()


if __name__ == "__main__":
    unittest.main()
