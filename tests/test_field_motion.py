import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from vision import classify


def frame(x=100, y=100, background=70, icon=True):
    image = Image.new("RGB", (240, 180), (background, background, background))
    draw = ImageDraw.Draw(image)
    if icon:
        draw.ellipse((x-6, y-6, x+6, y+6), fill=(25, 25, 25), outline=(210, 210, 210), width=2)
        draw.ellipse((x-2, y-2, x+2, y+2), fill=(150, 150, 150))
    return image


class FieldMotionTests(unittest.TestCase):
    def test_real_transparent_minimap_over_changed_scenery(self):
        fixtures = Path(__file__).parent / "fixtures"
        with Image.open(fixtures / "field_reference.png") as source:
            template = source.convert("RGB")
        refs = {"field": [((16, 16, 28, 35), template)]}
        with Image.open(fixtures / "field_changed_background.png") as source:
            self.assertEqual(classify(source.convert("RGB"), refs, 12)[0], "field")
        with Image.open(fixtures / "field_icon_absent.png") as source:
            self.assertEqual(classify(source.convert("RGB"), refs, 12)[0], "unknown")

    def test_field_icon_moves_while_background_changes(self):
        reference = frame()
        box = (92, 92, 109, 109)
        templates = {"field": [(box, reference.crop(box))]}
        moved = frame(x=109, y=94, background=105)
        self.assertEqual(classify(moved, templates, 12)[0], "field")

    def test_missing_minimap_icon_is_unknown(self):
        reference = frame()
        box = (92, 92, 109, 109)
        templates = {"field": [(box, reference.crop(box))]}
        self.assertEqual(classify(frame(icon=False), templates, 12)[0], "unknown")


if __name__ == "__main__":
    unittest.main()
