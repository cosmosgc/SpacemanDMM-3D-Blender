import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dmm import parse_dmm_text


FIXTURE = '''// minimal map
"aa" = (
/turf/open/floor/plating,
/area/test)
"ab" = (
/obj/structure/door{dir = 4},
/turf/closed/wall,
/area/test)
(1,1,1) = {"
aaab
abaa
"}
(1,1,2) = {"
aaaa
"}
'''


class DmmParserTests(unittest.TestCase):
    def test_parses_symbols_rows_and_z_levels(self):
        parsed = parse_dmm_text(FIXTURE)
        self.assertEqual(parsed.symbol_width, 2)
        self.assertEqual(len(parsed.cells), 6)
        self.assertEqual(parsed.cells[0].z, 1)
        self.assertEqual(parsed.cells[0].y, 2)
        self.assertEqual(parsed.cells[0].turf, "/turf/open/floor/plating")
        wall = next(cell for cell in parsed.cells if cell.turf == "/turf/closed/wall")
        self.assertEqual(wall.objects, ("/obj/structure/door",))
        self.assertEqual(wall.object_directions, (4,))
        self.assertEqual(wall.area, "/area/test")
        self.assertEqual(sum(cell.z == 2 for cell in parsed.cells), 2)

    def test_preserves_mapped_wall_icon_and_state(self):
        text = FIXTURE.replace(
            "/turf/closed/wall,",
            """/turf/closed/wall{icon = 'icons/wall.dmi'; icon_state = "stripe;yellow"},""",
        )
        wall = next(cell for cell in parse_dmm_text(text).cells if cell.turf == "/turf/closed/wall")
        self.assertEqual(wall.turf_icon, "icons/wall.dmi")
        self.assertEqual(wall.turf_icon_state, "stripe;yellow")


if __name__ == "__main__":
    unittest.main()
