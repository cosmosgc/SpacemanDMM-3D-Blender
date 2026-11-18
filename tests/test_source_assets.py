import sys
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from source_assets import CodebaseAssets, _map_value, wall_state


class MapSwitchTests(unittest.TestCase):
    def test_selects_map_render_branch(self):
        self.assertEqual(
            _map_value('MAP_SWITCH("space", "space_basic_map")', "map"),
            '"space_basic_map"',
        )

    def test_selects_compile_branch(self):
        self.assertEqual(
            _map_value(
                "MAP_SWITCH('icons/turf/wall.dmi', 'icons/turf/map_wall.dmi')",
                "compile",
            ),
            "'icons/turf/wall.dmi'",
        )

    def test_nested_arguments(self):
        self.assertEqual(
            _map_value('MAP_SWITCH("first", "second,with-comma")', "map"),
            '"second,with-comma"',
        )


class TextureCacheTests(unittest.TestCase):
    def test_caches_resolved_and_missing_types(self):
        with patch.object(CodebaseAssets, "_index_codebase"):
            assets = CodebaseAssets(".")
        texture = (object(), "sprite")
        with patch.object(assets, "_resolve_texture", side_effect=[texture, None]) as resolve:
            for _ in range(2):
                self.assertIs(assets.texture("/obj/test"), texture)
                self.assertIsNone(assets.texture("/obj/missing"))
        self.assertEqual(resolve.call_count, 2)

    def test_turf_texture_prefers_mapped_override(self):
        with patch.object(CodebaseAssets, "_index_codebase"):
            assets = CodebaseAssets(".")
        with patch.object(assets, "appearance", return_value=(Path("old.dmi"), "wall-0")), \
             patch.object(assets, "_load_texture") as load:
            assets.turf_texture("/turf/closed/wall", "icons/new.dmi", "")
            load.assert_called_once_with(assets.root / "icons/new.dmi", "")


class SourceDefaultsTests(unittest.TestCase):
    def test_parent_type_helpers_and_procedure_boundaries(self):
        source = '''/obj/machinery/airalarm
\tname = "air alarm"
\ticon = 'icons/wall.dmi'
\ticon_state = "alarm"
/obj/machinery/airalarm/update_name()
\tname = "temporary runtime name"
/obj/custom_panel
\tparent_type = /obj/machinery/airalarm
\tpixel_y = 4
/obj/custom_panel/Initialize(mapload)
\tpixel_y = 99
MAPPING_DIRECTIONAL_HELPERS(/obj/custom_panel, 27)
'''
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "tgstation.dme").write_text('#include "test.dm"')
            (root / "test.dm").write_text(source)
            assets = CodebaseAssets(root)
            values = assets.properties("/obj/custom_panel/directional/north")
            self.assertEqual(values["name"], "air alarm")
            self.assertEqual(values["icon_state"], "alarm")
            self.assertEqual(values["pixel_y"], "27")
            self.assertEqual(values["dir"], "1")
            self.assertIn("/obj/machinery/airalarm", values["_type_chain"])
            self.assertEqual(assets.properties("/obj/custom_panel")["pixel_y"], "4")


class WallStateTests(unittest.TestCase):
    def test_connects_regular_and_reinforced_walls_with_supported_diagonal(self):
        wall = "/turf/closed/wall"
        info = SimpleNamespace(states={"wall-0", "wall-5", "wall-21"})
        walls = {(0, 0, 1): wall, (1, 0, 1): f"{wall}/r_wall", (0, 1, 1): wall}
        self.assertEqual(wall_state(info, "wall-0", 0, 0, 1, walls), "wall-5")
        walls[1, 1, 1] = wall
        self.assertEqual(wall_state(info, "wall-0", 0, 0, 1, walls), "wall-21")
        self.assertEqual(wall_state(info, "special", 0, 0, 1, walls), "special")


if __name__ == "__main__":
    unittest.main()
