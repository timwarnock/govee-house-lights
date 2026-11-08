import unittest
from io import BytesIO

from kaitaistruct import KaitaiStream

from govee_ble_local._generated.govee_upload import GoveeUpload

from house_lights.still import still_scene_value

RED = (255, 0, 0)
WHITE = (255, 255, 255)
BLUE = (0, 0, 255)
CHRISTMAS = (RED, (0, 255, 0), BLUE, (255, 165, 0))


RWB = bytes.fromhex(
    "0120000000010001ffff0100320101003203ff0000ffffff0000ff00000000000000"
)


def _colors(value: bytes) -> list[tuple[int, int, int]]:
    scene = GoveeUpload.RgbicSceneValue(KaitaiStream(BytesIO(value)))
    scene._read()
    record = scene.effects[0].record
    return [(color.r, color.g, color.b) for color in record.colors]


class StillSceneTests(unittest.TestCase):
    def test_red_white_blue_matches_the_scene_the_house_showed(self) -> None:
        self.assertEqual(still_scene_value((RED, WHITE, BLUE)), RWB)

    def test_christmas_is_one_light_per_color(self) -> None:
        value = still_scene_value(CHRISTMAS)
        scene = GoveeUpload.RgbicSceneValue(KaitaiStream(BytesIO(value)))
        scene._read()
        record = scene.effects[0].record
        self.assertEqual(scene.num_effects, 1)
        self.assertEqual(record.style, 0)
        self.assertEqual(record.mode, 0)
        self.assertEqual(record.color_ic, 1)
        self.assertEqual(record.speed, 0)
        self.assertEqual(len(record.slack), 0)
        self.assertEqual(_colors(value), list(CHRISTMAS))

    def test_rejects_an_empty_palette(self) -> None:
        with self.assertRaises(ValueError):
            still_scene_value(())


if __name__ == "__main__":
    unittest.main()
