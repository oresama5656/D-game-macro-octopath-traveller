"""Post-battle menu-only HP checks and visually gated Ophilia healing."""
from dataclasses import dataclass
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from bp import detail


@dataclass(frozen=True)
class HealthView:
    menu: bool = False
    stage: str = "unknown"
    hp: tuple | None = None
    pointer_y: float | None = None
    ophilia: bool = False
    spell: bool = False


class HealthReader:
    def __init__(self, assets):
        self.templates = {}
        for name in ("menu", "pointer", "ophilia", "spell", "target"):
            with Image.open(Path(assets) / f"{name}.png") as source:
                gray = cv2.cvtColor(np.asarray(source.convert("RGB")), cv2.COLOR_RGB2GRAY)
                self.templates[name] = detail(gray)[2:-2, 2:-2]

    def match(self, gray, name, box):
        x0, y0, x1, y1 = box
        search = detail(gray[y0:y1, x0:x1])
        template = self.templates[name]
        th, tw = template.shape
        matches = cv2.matchTemplate(search, template, cv2.TM_CCOEFF_NORMED)
        mean = cv2.boxFilter(search, -1, (tw, th), anchor=(0, 0), normalize=True)
        square = cv2.boxFilter(search*search, -1, (tw, th), anchor=(0, 0), normalize=True)
        variance = (square-mean*mean)[:matches.shape[0], :matches.shape[1]]
        matches[~np.isfinite(matches) | (variance < 9)] = -1
        _, score, _, location = cv2.minMaxLoc(matches)
        return score, (x0+location[0]+tw/2, y0+location[1]+th/2)

    def read(self, image, members=4):
        rgb = np.asarray(image.convert("RGB").resize((1280, 720), Image.Resampling.BILINEAR))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        if self.match(gray, "menu", (25, 15, 180, 75))[0] < .82:
            return HealthView()
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        hp = []
        for row in range(members):
            y = 157+121*row
            strip = hsv[y-1:y+2, 1072:1233]
            green = cv2.inRange(strip, np.array((35, 90, 70)), np.array((85, 255, 255)))
            filled = (green > 0).mean(axis=0) > .5
            filled = cv2.morphologyEx(filled.astype(np.uint8).reshape(1, -1), cv2.MORPH_CLOSE, np.ones((1, 3), np.uint8))[0]
            length = next((i for i, value in enumerate(filled) if not value), len(filled))
            blue = cv2.inRange(hsv[y+25:y+31, 1072:1233], np.array((85, 50, 45)), np.array((125, 255, 255)))
            if length < 3 and np.count_nonzero(blue) < 10:
                hp = None
                break
            hp.append(length/len(filled))
        stage, pointer_y = "unknown", None
        if self.match(gray, "target", (25, 665, 540, 720))[0] >= .85:
            stage = "target"
        else:
            choices = []
            for name, box in (("main", (20, 75, 80, 600)), ("healer", (240, 100, 286, 600)), ("ability", (290, 100, 342, 420))):
                score, location = self.match(gray, "pointer", box)
                if score >= .80:
                    choices.append((score, name, location[1]))
            if choices:
                _, stage, pointer_y = max(choices)
        return HealthView(True, stage, tuple(hp) if hp is not None else None, pointer_y,
                          self.match(gray, "ophilia", (325, 52, 660, 105))[0] >= .82,
                          self.match(gray, "spell", (350, 115, 550, 157))[0] >= .82)


class HealPolicy:
    def __init__(self, threshold=.6, members=4):
        self.threshold = threshold
        self.members = members
        self.reset()

    def reset(self):
        self.phase = "idle"
        self.started = 0
        self.deadline = 0
        self.next_key = 0
        self.casts = 0
        self.navigation = 0
        self.healer_attempts = 0
        self.exits = 0
        self.baseline = None
        self.candidate = None
        self.stable = 0
        self.field_frames = 0
        self.note = ""
        self.waiting_stage = None

    @property
    def active(self):
        return self.phase != "idle"

    def begin(self, now):
        self.reset()
        self.phase = "open"
        self.started = now
        self.deadline = now+5
        self.note = "戦闘後HP確認"

    def tap(self, key, now, phase=None, from_stage=None):
        self.next_key = now+.35
        if phase:
            self.phase = phase
            self.deadline = now+4
            self.waiting_stage = from_stage
        return "tap", key

    def step(self, view, field, now):
        if now-self.started > 35:
            return "stop", "回復処理の時間上限"
        if now < self.next_key:
            return "idle", "回復操作の反映待ち"
        if self.phase == "open":
            return self.tap("menu", now, "check")
        if self.phase == "exit":
            self.field_frames = self.field_frames+1 if field and not view.menu else 0
            if self.field_frames >= 2:
                return "done", "HP確認完了・フィールド復帰"
            if view.menu:
                if self.exits >= 8:
                    return "stop", "回復メニューを閉じられません"
                self.exits += 1
                self.deadline = now+4
                return self.tap("cancel", now)
        if view.menu and view.hp is not None:
            candidate = tuple(round(value, 2) for value in view.hp)
            self.stable = self.stable+1 if candidate == self.candidate else 1
            self.candidate = candidate
            if any(value <= .015 for value in view.hp):
                return "stop", "HP0を検出：通常回復では周回を再開しません"
            self.note = "HP " + " / ".join(f"{round(value*100)}%" for value in view.hp)
            if self.phase == "check" and self.stable >= 2:
                self.phase = "exit" if min(view.hp) >= self.threshold else "navigate"
                self.deadline = now+4
                return "idle", self.note
            if self.phase == "verify" and self.stable >= 2:
                increased = sum(view.hp)-sum(self.baseline) > .025
                if increased:
                    self.phase = "exit" if min(view.hp) >= self.threshold else "target"
                    self.deadline = now+4
                    if self.phase == "target" and self.casts >= 3:
                        return "stop", "3回回復してもHPが基準未満です"
                    return "idle", "回復後のHP増加を確認"
        if self.phase in ("navigate", "healer", "ability", "target") and view.menu:
            if self.waiting_stage and view.stage == self.waiting_stage:
                if now > self.deadline:
                    return "stop", "回復メニューが進みません：SP不足や操作設定を確認してください"
                return "idle", "回復画面の切り替え待ち"
            if view.stage != "unknown":
                self.waiting_stage = None
            if view.stage == "main":
                self.navigation += 1
                if self.navigation > 12:
                    return "stop", "回復アビリティへ移動できません"
                if abs(view.pointer_y-256) <= 12:
                    return self.tap("confirm", now, "healer", "main")
                return self.tap("up" if view.pointer_y > 256 else "down", now)
            if view.stage == "healer":
                if view.ophilia and view.spell:
                    return self.tap("confirm", now, "ability", "healer")
                self.healer_attempts += 1
                if self.healer_attempts > self.members:
                    return "stop", "オフィーリアの回復魔法を確認できません"
                return self.tap("down", now)
            if view.stage == "ability":
                if not view.ophilia or not view.spell:
                    return self.tap("cancel", now, "healer", "ability")
                if abs(view.pointer_y-134) <= 12:
                    return self.tap("confirm", now, "target", "ability")
                self.navigation += 1
                if self.navigation > 16:
                    return "stop", "回復魔法を選択できません"
                return self.tap("up" if view.pointer_y > 134 else "down", now)
            if view.stage == "target" and view.ophilia and view.spell:
                if view.hp is None:
                    return "idle", "回復対象のHP確認待ち"
                self.baseline = view.hp
                self.casts += 1
                self.candidate, self.stable = None, 0
                return self.tap("confirm", now, "verify")
        if now > self.deadline:
            if self.phase == "verify":
                return "stop", "回復後のHP増加なし：SP不足や回復対象を確認してください"
            return "stop", f"回復画面を確認できません（{self.phase}）"
        return "idle", self.note or "回復画面の確認待ち"
