import unittest
from datetime import date

from house_lights.holidays import (
    BLUE,
    CHRISTMAS,
    DEFAULT_NIGHT,
    GOLD,
    GREEN,
    HALLOWEEN,
    INDEPENDENCE,
    NEW_YEAR,
    ORANGE_YELLOW,
    RED,
    VALENTINES,
    WHITE,
    pattern_for,
    segment_groups,
)


class HolidayTests(unittest.TestCase):
    def test_christmas_window_is_december_1_through_26(self) -> None:
        self.assertEqual(pattern_for(date(2026, 11, 30)), DEFAULT_NIGHT)
        self.assertEqual(pattern_for(date(2026, 12, 1)), CHRISTMAS)
        self.assertEqual(pattern_for(date(2026, 12, 25)), CHRISTMAS)
        self.assertEqual(pattern_for(date(2026, 12, 26)), CHRISTMAS)
        self.assertEqual(pattern_for(date(2026, 12, 27)), DEFAULT_NIGHT)
        self.assertEqual(pattern_for(date(2026, 12, 30)), DEFAULT_NIGHT)

    def test_christmas_is_red_green_blue_and_orange_yellow(self) -> None:
        self.assertEqual(CHRISTMAS.colors, (RED, GREEN, BLUE, ORANGE_YELLOW))
        self.assertEqual(CHRISTMAS.color_names, ("red", "green", "blue", "orange/yellow"))
        self.assertGreater(len(CHRISTMAS.colors), 2)

    def test_independence_day(self) -> None:
        self.assertEqual(pattern_for(date(2026, 7, 3)), DEFAULT_NIGHT)
        self.assertEqual(pattern_for(date(2026, 7, 4)), INDEPENDENCE)
        self.assertEqual(pattern_for(date(2026, 7, 5)), DEFAULT_NIGHT)
        self.assertEqual(INDEPENDENCE.colors, (RED, WHITE, BLUE))

    def test_new_year_is_gold_and_white(self) -> None:
        self.assertEqual(pattern_for(date(2026, 12, 31)), NEW_YEAR)
        self.assertEqual(pattern_for(date(2027, 1, 1)), NEW_YEAR)
        self.assertEqual(pattern_for(date(2027, 1, 2)), DEFAULT_NIGHT)
        self.assertEqual(NEW_YEAR.colors, (GOLD, WHITE))

    def test_other_table_rows(self) -> None:
        self.assertEqual(pattern_for(date(2026, 10, 31)), HALLOWEEN)
        self.assertEqual(pattern_for(date(2026, 2, 14)), VALENTINES)
        self.assertEqual(HALLOWEEN.color_names, ("orange", "purple"))
        self.assertEqual(VALENTINES.color_names, ("red", "pink"))

    def test_segment_repeat(self) -> None:
        groups = segment_groups(CHRISTMAS.colors, 8)
        by_color = dict(groups)
        self.assertEqual(by_color[RED], [0, 4])
        self.assertEqual(by_color[GREEN], [1, 5])
        self.assertEqual(by_color[BLUE], [2, 6])
        self.assertEqual(by_color[ORANGE_YELLOW], [3, 7])


if __name__ == "__main__":
    unittest.main()
