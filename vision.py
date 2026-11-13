from PIL import Image, ImageChops, ImageStat
import cv2
import numpy as np

SCENES = {"field": "フィールド", "battle": "戦闘", "victory": "勝利結果", "levelup": "レベルアップ", "danger": "停止画面"}


def signature(image):
    return image.convert("RGB").resize((96, 48), Image.Resampling.BILINEAR)


def distance(a, b):
    return sum(ImageStat.Stat(ImageChops.difference(signature(a), signature(b))).mean) / 3


def field_distance(image, box, template):
    """Find the HUD icon while suppressing scenery visible through the minimap."""
    target = cv2.cvtColor(np.asarray(template.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    if target.std() < 8:
        return 256.0
    margin = max(16, round(16 * image.height / 720))
    x0, y0, x1, y1 = box
    area = image.crop((max(0, x0-margin), max(0, y0-margin),
                       min(image.width, x1+margin), min(image.height, y1+margin)))
    search = cv2.cvtColor(np.asarray(area.convert("RGB")), cv2.COLOR_RGB2GRAY).astype(np.float32)
    if search.shape[0] < target.shape[0] or search.shape[1] < target.shape[1]:
        return 256.0
    # Subtract low spatial frequencies: a translucent map carries scenery gradients,
    # so removing only the mean brightness is insufficient. Keep the icon's fine detail.
    target -= cv2.GaussianBlur(target, (0, 0), 1)
    search -= cv2.GaussianBlur(search, (0, 0), 1)
    # Cropped reference borders have artificial blur boundaries; exclude that rim.
    trim = 2 if min(target.shape) >= 12 else 0
    if trim:
        target = target[trim:-trim, trim:-trim]
        search = search[trim:-trim, trim:-trim]
    if target.std() < 2:
        return 256.0
    match = cv2.matchTemplate(search, target, cv2.TM_CCOEFF_NORMED)
    # Constant or invalid candidates must never become positive identifications.
    finite = match[np.isfinite(match)]
    if not finite.size:
        return 256.0
    return 100 * (1 - float(np.clip(finite.max(), 0, 1)))


def classify(image, templates, threshold):
    scores = {}
    for scene, entries in templates.items():
        if not entries:
            continue
        if scene == "field":
            scores[scene] = min(field_distance(image, box, template) for box, template in entries)
        else:
            scores[scene] = min(distance(image.crop(box), template) for box, template in entries)
    if scores.get("danger", 256) <= threshold:
        return "danger", scores
    # Result-page variants all require the same action, so they cannot conflict.
    families = {}
    for scene, score in scores.items():
        if scene == "danger":
            continue
        family = "victory" if scene == "levelup" else scene
        if family not in families or score < families[family][0]:
            families[family] = (score, scene)
    ordered = sorted(families.values())
    if not ordered or ordered[0][0] > threshold:
        return "unknown", scores
    if len(ordered) > 1 and ordered[1][0] - ordered[0][0] < 4:
        return "unknown", scores
    return ordered[0][1], scores
