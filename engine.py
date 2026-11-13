"""Side-effect free decisions for the farming loop."""
from dataclasses import dataclass


@dataclass
class Limits:
    duration: float = 600
    battle: float = 180
    unknown: float = 20
    field: float = 120
    result: float = 30
    stride: float = 0.8
    confirm_interval: float = 0.15


class Loop:
    def __init__(self, now, limits):
        self.limits = limits
        self.started = now
        self.last_known = now
        self.entered = now
        self.phase = None
        self.pending = None
        self.frames = 0
        self.next_confirm = now
        self.encounter_started = None
        self.wins = 0
        self.counted = False

    def step(self, scene, now):
        if scene == "levelup":
            scene = "victory"
        if now - self.started >= self.limits.duration:
            return "stop", "実行時間の上限"
        if scene == "danger":
            return "stop", "停止用の画面を検出"
        if scene != self.pending:
            self.pending, self.frames = scene, 1
        else:
            self.frames += 1
        if scene == "unknown":
            if now - self.last_known >= self.limits.unknown:
                return "stop", "画面を判定できない状態が継続"
            return "idle", "判定待ち"
        self.last_known = now
        if self.encounter_started is not None and now - self.encounter_started >= self.limits.battle:
            return "stop", "戦闘時間の上限"
        if self.frames < 2:
            return "idle", "画面の安定待ち"
        if scene != self.phase:
            self.phase, self.entered = scene, now
            if scene == "battle" and self.encounter_started is None:
                self.encounter_started = now
                self.counted = False
            if scene == "victory" and self.encounter_started is not None and not self.counted:
                self.wins += 1
                self.counted = True
            if scene == "field":
                self.encounter_started = None
        elapsed = now - self.entered
        if scene == "field":
            if elapsed >= self.limits.field:
                return "stop", "長時間遭遇なし：場所と移動を確認"
            return "hold", "left" if int(elapsed / self.limits.stride) % 2 == 0 else "right"
        if scene == "victory" and elapsed >= self.limits.result:
            return "stop", "結果画面から進まない"
        if now >= self.next_confirm:
            self.next_confirm = now + self.limits.confirm_interval
            return "tap", "confirm"
        return "idle", "次の入力待ち"
