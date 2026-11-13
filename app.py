"""Octopath 1 farming assistant. Run with python app.py on Windows."""
import ctypes
try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except (AttributeError, OSError):
    pass

import json
import logging
from logging.handlers import RotatingFileHandler
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from PIL import Image, ImageTk, ImageStat
from engine import Loop, Limits
from vision import SCENES, classify
from bp import BPReader, BPPolicy, Reading
from healing import HealthReader, HealPolicy
from win32_io import (Keyboard, WindowKeyboard, BackgroundFrames, KEYS, windows, foreground,
                      capture, capture_background, background_available, pressed)

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "profiles"
DATA.mkdir(exist_ok=True)
CONFIG = DATA / "settings.json"
POLL_MS = 20
SCAN_INTERVAL = 0.08
TAP_SECONDS = 0.04
LOG = logging.getLogger("octopath_macro")


class App:
    def __init__(self, root):
        self.root = root
        self.keyboard = Keyboard()
        self.frame_source = None
        self.frame_sequence = None
        self.last_runtime_scene = None
        self.run_background = False
        self.run_bp = False
        self.run_simple = False
        self.run_heal = False
        self.manual_health_check = False
        self.heal_policy = HealPolicy()
        self.health_reader = HealthReader(ROOT / "assets/healing")
        self.last_heal_report = None
        self.bp_policy = BPPolicy()
        with Image.open(ROOT / "assets" / "bp_command.png") as source:
            self.bp_reader = BPReader(source)
        self.last_bp_report = None
        self.loop = None
        self.armed = False
        self.capture_generation = 0
        self.hwnd = None
        self.templates = {}
        self.profile = {"size": None, "markers": {}}
        self.sample_size = None
        self.last_scan = 0
        self.tap_until = None
        self.hotkeys = {0x77: False, 0x78: False}
        self.dry = tk.BooleanVar(value=True)
        self.background = tk.BooleanVar(value=False)
        self.bp_mode = tk.BooleanVar(value=False)
        self.simple = tk.BooleanVar(value=False)
        self.heal_mode = tk.BooleanVar(value=False)
        self.topmost = tk.BooleanVar(value=True)
        self.heal_status = tk.StringVar(value="戦闘後回復：OFF")
        self.bp_status = tk.StringVar(value="BP監視：OFF")
        self.mode_status = tk.StringVar()
        self.status = tk.StringVar(value="未実行：最初に画面を登録してください")
        self.marker_status = tk.StringVar()
        self.scene = tk.StringVar(value="field")
        self.values = {}
        self.build()
        self.load()
        self.ui.apply_pin()
        self.refresh_mode()
        self.refresh_markers()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.after(POLL_MS, self.tick)

    def build(self):
        from companion_ui import CompanionUI
        self.ui = CompanionUI(self)

    def load(self):
        if not CONFIG.exists():
            return
        try:
            data = json.loads(CONFIG.read_text(encoding="utf-8"))
            dry_run = data.get("dry_run", True)
            if not isinstance(dry_run, bool):
                raise ValueError("実行モードの設定が不正です")
            self.dry.set(dry_run)
            self.topmost.set(data.get("topmost", True) if isinstance(data.get("topmost", True), bool) else True)
            background = data.get("background", False)
            if not isinstance(background, bool):
                raise ValueError("バックグラウンド設定が不正です")
            self.background.set(background)
            for key, variable in (("bp_mode", self.bp_mode), ("simple", self.simple), ("heal_mode", self.heal_mode)):
                value = data.get(key, False)
                if not isinstance(value, bool):
                    raise ValueError(f"{key}の設定が不正です")
                variable.set(value)
            self.profile = data["profile"]
            for key, value in data.get("values", {}).items():
                if key in self.values:
                    self.values[key].set(value)
            for scene, entries in self.profile["markers"].items():
                if scene not in SCENES:
                    raise ValueError("不明な画面種類")
                self.templates[scene] = []
                for entry in entries:
                    path = (DATA / entry["file"]).resolve()
                    if path.parent != DATA.resolve():
                        raise ValueError("不正な見本パス")
                    with Image.open(path) as source:
                        template = source.convert("RGB")
                    self.templates[scene].append((tuple(entry["box"]), template))
        except (KeyError, TypeError, ValueError, OSError) as error:
            self.dry.set(True)
            self.background.set(False)
            self.bp_mode.set(False)
            self.simple.set(False)
            self.heal_mode.set(False)
            self.profile = {"size": None, "markers": {}}
            self.templates = {}
            self.status.set(f"設定の読み込みに失敗。画面を再登録してください：{error}")

    def save(self):
        data = {"profile": self.profile, "values": {k: v.get() for k, v in self.values.items()},
                "dry_run": self.dry.get(), "background": self.background.get(),
                "bp_mode": self.bp_mode.get(), "simple": self.simple.get(), "heal_mode": self.heal_mode.get(),
                "topmost": self.topmost.get()}
        temporary = CONFIG.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(CONFIG)

    def refresh_mode(self):
        mode = " / バックグラウンド" if self.background.get() else " / 前面のみ"
        self.mode_status.set(("キー送信：OFF（判定のみ）" if self.dry.get() else "キー送信：ON（開始すると実際に操作）") + mode)
        self.bp_status.set("BP全投入：ON / 3回ブースト→決定2回 / BP数の確認は待ちません" if self.bp_mode.get() else "BP全投入：OFF")
        self.heal_status.set(f"戦闘後回復：HP{self.values['heal_percent'].get()}%未満 / {self.values['heal_members'].get()}人編成" if self.heal_mode.get() else "戦闘後回復：OFF")

    def healing_settings(self):
        self.ui.open_settings("healing")

    def change_mode(self):
        if self.loop or self.armed:
            self.stop("実行モードを変更しました。再度開始してください")
        self.refresh_mode()
        try:
            self.save()
        except OSError as error:
            self.status.set(f"実行モードを保存できません：{error}")

    def refresh_markers(self):
        self.marker_status.set(" / ".join(f"{label}: {len(self.templates.get(key, []))}枚" for key, label in SCENES.items()))

    def select_game(self):
        found = windows()
        if len(found) != 1:
            raise RuntimeError(f"OCTOPATH TRAVELER のウィンドウが{len(found)}個あります。1個だけ開いてください")
        self.hwnd = found[0][0]

    def later_capture(self, callback, delay_ms=5000):
        if self.loop or self.armed:
            return
        try:
            self.select_game()
        except Exception as error:
            messagebox.showerror("ゲームの確認", str(error))
            return
        self.armed = True
        self.capture_generation += 1
        generation = self.capture_generation
        self.status.set("5秒以内にゲームを前面にしてください。F9で中止できます" if delay_ms else "ゲーム画面を確認しています")
        self.root.after(delay_ms, lambda: self.finish_capture(callback, generation))

    def finish_capture(self, callback, generation):
        if not self.armed or generation != self.capture_generation:
            return
        self.armed = False
        try:
            if not self.background.get() and not foreground(self.hwnd):
                raise RuntimeError("ゲームを前面にしてください")
            image = capture_background(self.hwnd) if self.background.get() or self.topmost.get() else capture(self.hwnd)
            callback(image)
        except Exception as error:
            self.status.set(f"撮影できません：{error}")

    def register(self):
        scene = self.scene.get()
        self.later_capture(lambda image: self.editor(image, scene))

    def editor(self, image, scene):
        if self.profile["size"] and list(image.size) != self.profile["size"]:
            messagebox.showerror("解像度が違います", "登録時の解像度に戻してください。変更する場合は登録した全種類を消してから登録し直してください")
            return
        window = tk.Toplevel(self.root)
        window.title(f"{SCENES[scene]}：判定に使う目印をドラッグして登録")
        window.grab_set()
        hint = ("ミニマップ中央の小さな丸印を、周囲2〜3pxの余白を含めて囲んでください。景色・マップ全体は不要です。"
                if scene == "field" else "『Level Up』など、この画面固有の固定文字を囲んでください。レベルや能力値の数字は避けてください。"
                if scene == "levelup" else "固有の文字・枠を囲む → 登録。背景・キャラ・HP数値・点滅するカーソルは避けてください。")
        ttk.Label(window, text=hint).pack()
        preview = image.copy()
        preview.thumbnail((1000, 580))
        photo = ImageTk.PhotoImage(preview)
        canvas = tk.Canvas(window, width=preview.width, height=preview.height, cursor="crosshair")
        canvas.pack()
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.image = photo
        selection = {"start": None, "rect": None, "box": None}

        def begin(event):
            if selection["rect"]:
                canvas.delete(selection["rect"])
            selection["start"] = (event.x, event.y)
            selection["rect"] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#00ff88", width=2)

        def drag(event):
            if selection["start"] is None:
                return
            x, y = selection["start"]
            ex = max(0, min(preview.width, event.x))
            ey = max(0, min(preview.height, event.y))
            canvas.coords(selection["rect"], x, y, ex, ey)
            scale_x, scale_y = image.width / preview.width, image.height / preview.height
            selection["box"] = [round(min(x, ex)*scale_x), round(min(y, ey)*scale_y),
                                round(max(x, ex)*scale_x), round(max(y, ey)*scale_y)]

        def commit():
            box = selection["box"]
            if not box or box[2]-box[0] < 12 or box[3]-box[1] < 12:
                messagebox.showinfo("範囲の確認", "文字や枠を含む、もう少し大きな範囲を選んでください", parent=window)
                return
            template = image.crop(box)
            if scene == "field" and (template.width > image.width * .08 or template.height > image.height * .12):
                messagebox.showinfo("範囲の確認", "範囲が広すぎます。ミニマップ全体ではなく中央の小さな丸印だけを囲んでください", parent=window)
                return
            if sum(ImageStat.Stat(template).stddev) / 3 < 8:
                messagebox.showinfo("範囲の確認", "単色に近い範囲です。画面固有の文字や模様を含めてください", parent=window)
                return
            filename = f"{scene}_{time.time_ns()}.png"
            template.save(DATA / filename)
            self.profile["size"] = list(image.size)
            self.profile["markers"].setdefault(scene, []).append({"box": box, "file": filename})
            self.templates.setdefault(scene, []).append((tuple(box), template))
            self.save()
            self.refresh_markers()
            self.status.set(f"{SCENES[scene]}の見本を登録しました")
            window.destroy()

        canvas.bind("<ButtonPress-1>", begin)
        canvas.bind("<B1-Motion>", drag)
        canvas.bind("<ButtonRelease-1>", drag)
        ttk.Button(window, text="この範囲を登録", command=commit).pack(pady=6)
        window.bind("<Escape>", lambda e: window.destroy())

    def clear_marker(self):
        if self.loop or self.armed:
            return
        scene = self.scene.get()
        self.profile["markers"].pop(scene, None)
        self.templates.pop(scene, None)
        if not self.templates:
            self.profile["size"] = None
        self.save()
        self.refresh_markers()

    def recognize(self, image):
        if list(image.size) != self.profile["size"]:
            raise RuntimeError("登録時からゲームの解像度が変わりました")
        return classify(image, self.templates, self.threshold)

    def test(self):
        try:
            self.settings()
        except ValueError as error:
            messagebox.showerror("設定", str(error))
            return

        def show(image):
            scene, scores = self.recognize(image)
            reason = ""
            if scene == "unknown":
                reason = (f"（許容差{self.threshold:g}を超過）" if scores and min(scores.values()) > self.threshold
                          else "（候補が競合、または見本なし）")
            self.status.set(f"判定：{SCENES.get(scene, '不明')}{reason} / " + " / ".join(f"{SCENES[k]} 差={v:.1f}" for k, v in scores.items()))
        self.later_capture(show)

    def settings(self):
        for name in ("left", "right", "confirm"):
            if self.values[name].get() not in KEYS:
                raise ValueError("キーの指定が不正です")
        if len({self.values[k].get() for k in ("left", "right", "confirm")}) != 3:
            raise ValueError("左・右・決定は異なるキーにしてください")
        dash = self.values["dash"].get()
        if dash != "none" and (dash not in KEYS or dash in {self.values[k].get() for k in ("left", "right", "confirm")}):
            raise ValueError("ダッシュは左・右・決定とは別のキー、またはnoneを指定してください")
        boost = self.values["boost"].get()
        if boost not in KEYS or boost in {self.values[k].get() for k in ("left", "right", "confirm", "dash")}:
            raise ValueError("ブーストは移動・決定・ダッシュとは別のキーを指定してください")
        if self.values["heal_percent"].get() not in ("50", "60", "70", "80", "90") or self.values["heal_members"].get() not in ("1", "2", "3", "4"):
            raise ValueError("回復基準または編成人数が不正です")
        if any(self.values[key].get() not in KEYS for key in ("menu", "cancel")):
            raise ValueError("回復メニューのキー設定が不正です")
        if len({self.values[key].get() for key in ("menu", "cancel", "confirm")}) != 3:
            raise ValueError("メニュー・戻る・決定は異なるキーにしてください")
        self.heal_threshold = int(self.values["heal_percent"].get())/100
        self.heal_members = int(self.values["heal_members"].get())
        numbers = {}
        bounds = {"duration": (10, 7200), "battle": (10, 600), "stride": (0.2, 3),
                  "confirm_interval": (0.1, 5), "threshold": (1, 35)}
        for key, (low, high) in bounds.items():
            try:
                number = float(self.values[key].get())
            except ValueError:
                raise ValueError(f"{key} は数値で指定してください") from None
            if not low <= number <= high:
                raise ValueError(f"{key} は {low}〜{high} の範囲で指定してください")
            numbers[key] = number
        self.threshold = numbers.pop("threshold")
        self.run_keys = {key: self.values[key].get() for key in ("left", "right", "confirm", "dash", "boost", "menu", "cancel")}
        self.run_keys.update(up="up", down="down")
        return Limits(**numbers)

    def start(self, immediate=False):
        if self.loop or self.armed:
            return
        self.manual_health_check = False
        try:
            limits = self.settings()
            required = ("field",) if self.simple.get() else ("field", "battle", "victory")
            if any(not self.templates.get(s) for s in required):
                raise ValueError("フィールド・戦闘・勝利結果の見本を先に登録してください")
            self.save()
            self.run_dry = self.dry.get()
            self.run_background = self.background.get()
            self.run_bp = self.bp_mode.get()
            self.run_simple = self.simple.get()
            self.run_heal = self.heal_mode.get()
        except (ValueError, OSError) as error:
            messagebox.showerror("開始できません", str(error))
            return

        if immediate:
            try:
                self.select_game()
                if not self.input_available():
                    self.status.set("ゲームを最小化から戻してください" if self.run_background else "F8で開始するときは、ゲームを前面にしてください")
                    return
            except RuntimeError as error:
                self.status.set(str(error))
                return

        def begin(image):
            scene, _ = self.recognize(image)
            if self.manual_health_check and scene != "field":
                raise RuntimeError("HP確認・回復テストはフィールドから開始してください")
            if self.run_bp and self.bp_reader.read(image).ready and scene != "danger":
                scene = "battle"
            if scene == "unknown" and self.run_simple and sum(ImageStat.Stat(image.resize((64, 36))).stddev) > 6:
                scene = "battle"
            if scene not in ("field", "battle", "victory", "levelup"):
                raise RuntimeError("フィールド・戦闘・結果画面と判定できません。見本を確認してください")
            self.keyboard.release()
            self.keyboard = WindowKeyboard(self.hwnd) if self.run_background else Keyboard()
            if self.run_background or self.topmost.get():
                self.frame_source = BackgroundFrames(self.hwnd)
                self.frame_sequence = None
            self.loop = Loop(time.monotonic(), limits)
            self.bp_policy = BPPolicy()
            self.heal_policy = HealPolicy(self.heal_threshold, self.heal_members)
            self.last_heal_report = None
            if self.manual_health_check:
                self.run_heal = True
                self.heal_policy.begin(time.monotonic())
            self.last_bp_report = None
            self.last_runtime_scene = None
            LOG.info("started background=%s dry=%s foreground=%s bp=%s strategy=all_in simple=%s", self.run_background, self.run_dry, foreground(self.hwnd), self.run_bp, self.run_simple)
            self.status.set("判定のみ実行中" if self.run_dry else "自動操作を開始しました。F9で緊急停止")
        self.later_capture(begin, delay_ms=0 if immediate else 5000)

    def test_healing(self):
        if self.loop or self.armed:
            self.stop("HP確認・回復テストへ切り替え")
        self.start()
        if self.armed:
            self.manual_health_check = True

    def stop(self, reason):
        wins = self.loop.wins if self.loop else 0
        self.loop = None
        self.armed = False
        self.capture_generation += 1
        self.tap_until = None
        self.heal_policy.reset()
        self.manual_health_check = False
        if self.frame_source:
            self.frame_source.close()
            self.frame_source = None
        try:
            self.keyboard.release()
        except RuntimeError as error:
            reason += f" / キー解放エラー：{error}"
        self.status.set(f"停止：{reason} / 検出した勝利 {wins}回")
        LOG.info("stopped reason=%s wins=%s", reason, wins)

    def input_available(self):
        return background_available(self.hwnd) if self.run_background else foreground(self.hwnd)

    def process_frame(self, now, image):
        scene, scores = self.recognize(image)
        if self.run_heal and self.heal_policy.active:
            if scene == "danger":
                self.stop("回復中に停止画面を検出")
            elif now-self.loop.started >= self.loop.limits.duration:
                self.stop("実行時間の上限")
            else:
                self.process_healing(now, image, scene)
            return
        reading = Reading(False)
        if self.run_bp and scene not in ("field", "victory", "levelup", "danger"):
            reading = self.bp_reader.read(image)
            if reading.ready:
                scene = "battle"
        if scene == "unknown" and self.run_simple:
            # Do not mash Enter on a completely black loading/transition frame.
            if sum(ImageStat.Stat(image.resize((64, 36))).stddev) > 6:
                scene = "battle"
        was_in_encounter = self.loop.encounter_started is not None
        action, detail = self.loop.step(scene, now)
        if self.run_heal and scene == "field" and action == "hold" and was_in_encounter:
            self.keyboard.release()
            self.tap_until = None
            self.bp_policy.reset()
            self.heal_policy.begin(now)
            self.process_healing(now, image, scene)
            return
        if action != "stop" and scene == "battle" and self.run_bp:
            override = self.bp_policy.step(reading, now)
            if override:
                action, detail = override
            report = (reading.ready, reading.actor, reading.bp, self.bp_policy.note)
            if report != self.last_bp_report:
                LOG.info("bp ready=%s confidence=%.3f actor=%s remaining=%s action=%s note=%s", reading.ready, reading.confidence, reading.actor, reading.bp, detail, self.bp_policy.note)
                self.last_bp_report = report
            self.bp_status.set(f"BP全投入：{self.bp_policy.note}（BP数の確認待ちなし）")
        elif scene != "battle":
            self.bp_policy.reset()
        if scene != self.last_runtime_scene:
            LOG.info("scene=%s foreground=%s wins=%s", scene, foreground(self.hwnd), self.loop.wins)
            self.last_runtime_scene = scene
        mode = "判定のみ" if self.run_dry else "背景で操作中" if self.run_background else "操作中"
        self.status.set(f"{mode}：{SCENES.get(scene, '不明')} / {action}: {detail} / 勝利 {self.loop.wins}回 / {int(now-self.loop.started)}秒")
        self.apply_action(action, detail)

    def process_healing(self, now, image, scene):
        view = self.health_reader.read(image, self.heal_policy.members)
        action, detail = self.heal_policy.step(view, scene == "field", now)
        report = (self.heal_policy.phase, detail)
        if report != self.last_heal_report:
            LOG.info("healing phase=%s action=%s detail=%s hp=%s casts=%s", self.heal_policy.phase, action, detail, view.hp, self.heal_policy.casts)
            self.last_heal_report = report
        self.heal_status.set(f"戦闘後回復：{self.heal_policy.note} / 使用{self.heal_policy.casts}回")
        self.status.set(f"回復中：{self.heal_policy.phase} / {detail}")
        if action == "done":
            self.keyboard.release()
            self.tap_until = None
            self.heal_policy.reset()
            self.bp_policy.reset()
            if self.manual_health_check:
                self.stop("HP確認・回復テスト完了")
            else:
                self.loop.phase = "field"
                self.loop.pending = "field"
                self.loop.frames = 0
                self.loop.entered = now
                self.loop.last_known = now
                self.status.set("回復確認完了：周回を再開します")
            return
        self.apply_action(action, detail)

    def apply_action(self, action, detail):
        if action == "stop":
            self.stop(detail)
        elif self.run_dry:
            pass
        elif not self.input_available() or pressed(0x78):
            self.stop("入力直前の停止条件を検出")
        elif action == "hold":
            movement = [self.run_keys[detail]]
            if self.run_keys["dash"] != "none":
                movement.insert(0, self.run_keys["dash"])
            self.keyboard.hold(movement)
        elif action == "tap":
            self.keyboard.release()
            self.keyboard.hold(self.run_keys[detail])
            self.tap_until = time.monotonic() + TAP_SECONDS
        else:
            self.keyboard.release()
            self.tap_until = None

    def tick(self):
        try:
            now = time.monotonic()
            for vk in self.hotkeys:
                down = pressed(vk)
                if down and not self.hotkeys[vk]:
                    if vk == 0x78 or self.loop or self.armed:
                        self.stop("F9 緊急停止" if vk == 0x78 else "F8 停止")
                    elif self.root.grab_current() is None:
                        self.start(immediate=True)
                self.hotkeys[vk] = down
            if self.loop:
                if not self.input_available():
                    raise RuntimeError("ゲームが閉じられたか最小化されました" if self.run_background else "ゲームが前面ではなくなりました")
                if self.tap_until is not None and now >= self.tap_until:
                    self.keyboard.release()
                    self.tap_until = None
                if now - self.last_scan >= SCAN_INTERVAL:
                    self.last_scan = now
                    if self.frame_source is not None:
                        snapshot = self.frame_source.poll()
                        if snapshot and snapshot[0] != self.frame_sequence:
                            self.frame_sequence = snapshot[0]
                            self.process_frame(now, snapshot[1])
                    else:
                        self.process_frame(now, capture(self.hwnd))
        except Exception as error:
            self.stop(str(error))
        self.root.after(POLL_MS, self.tick)

    def close(self):
        self.stop("終了")
        self.root.destroy()


if __name__ == "__main__":
    handler = RotatingFileHandler(DATA / "runtime.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    LOG.addHandler(handler)
    LOG.setLevel(logging.INFO)
    root = tk.Tk()
    App(root)
    root.mainloop()
