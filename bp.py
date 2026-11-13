"""Optional HUD diagnostics plus a count-independent all-in input cycle."""
from dataclasses import dataclass
import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class Reading:
    ready: bool
    actor: int | None = None
    bp: int | None = None
    confidence: float = 0


def detail(gray):
    gray = gray.astype(np.float32)
    return gray - cv2.GaussianBlur(gray, (0, 0), 1)


class BPReader:
    def __init__(self, command_template):
        self.template = detail(cv2.cvtColor(np.asarray(command_template.convert("RGB")), cv2.COLOR_RGB2GRAY))[2:-2, 2:-2]

    def read(self, image):
        # Normalize game resolution; command and status UI use the same reference layout.
        rgb = np.asarray(image.convert("RGB").resize((1280, 720), Image.Resampling.BILINEAR))
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        search = detail(gray[220:650, 420:1260])
        matches = cv2.matchTemplate(search, self.template, cv2.TM_CCOEFF_NORMED)
        # Normalized matching is unreliable on almost-flat patches. Ignore those
        # positions as well as NaN/Inf rather than treating them as perfect matches.
        th, tw = self.template.shape
        mean = cv2.boxFilter(search, -1, (tw, th), anchor=(0, 0), normalize=True)
        square_mean = cv2.boxFilter(search*search, -1, (tw, th), anchor=(0, 0), normalize=True)
        variance = (square_mean-mean*mean)[:matches.shape[0], :matches.shape[1]]
        valid = np.isfinite(matches) & (variance >= 9)
        confidence = float(np.clip(matches[valid].max(), -1, 1)) if np.any(valid) else 0
        ready = confidence >= .80
        hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
        mask = cv2.inRange(hsv[40:450, 1020:1270], np.array((35, 30, 80)), np.array((80, 200, 230)))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        bars = []
        for x, y, width, height, area in stats[1:count]:
            x, y = int(x)+1020, int(y)+40
            actor = round((y-78)/102)
            if (0 <= actor < 4 and abs(y-(78+102*actor)) <= 8
                    and 30 <= width <= 160 and 3 <= height <= 9 and area >= width*2):
                bars.append((actor, x, y, int(width)))
        # The current actor's panel slides left. Do not use a stationary party member.
        active = [bar for bar in bars if 1025 <= bar[1] <= 1090]
        if not active:
            return Reading(ready, confidence=confidence)
        actor, x, y, _ = max(active, key=lambda bar: bar[3])
        if any(bar[0] != actor for bar in active):
            return Reading(ready, confidence=confidence)
        lit = []
        for slot in range(5):
            cx, cy = x+6+10*slot, y-30
            patch = hsv[cy-5:cy+6, cx-4:cx+5]
            gold = cv2.inRange(patch, np.array((5, 60, 140)), np.array((40, 255, 255)))
            lit.append(int(np.count_nonzero(gold)) >= 4)
        # BP occupies a contiguous prefix; holes indicate an unreliable reading.
        bp = sum(lit)
        if lit != [True]*bp + [False]*(5-bp):
            return Reading(ready, actor, confidence=confidence)
        return Reading(ready, actor, bp, confidence)


class BPPolicy:
    """Best-effort all-in: O x3, Enter x2; no BP-count or acknowledgement waits."""
    def __init__(self, interval=.1):
        self.interval = interval
        self.reset()

    def reset(self):
        self.index = 0
        self.next_input = 0
        self.note = "3回ブースト→決定2回"

    def step(self, reading, now):
        # Perception must never restart the sequence or postpone Enter indefinitely.
        # The game itself ignores unavailable BP and inputs during non-input phases.
        if now < self.next_input:
            return "idle", "入力間隔待ち"
        key = "boost" if self.index < 3 else "confirm"
        self.note = f"ブースト{self.index+1}/3" if key == "boost" else f"決定{self.index-2}/2"
        self.index = (self.index+1) % 5
        self.next_input = now+self.interval
        return "tap", key
