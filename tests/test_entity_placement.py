import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from entity_placement import classify, entity_direction, entity_label, place


class ClassificationTests(unittest.TestCase):
    def test_floor_and_buried_utilities_are_distinct(self):
        cases = {
            "/obj/machinery/atmospherics/pipe/smart/simple/supply/hidden/layer2": "underfloor",
            "/obj/machinery/atmospherics/pipe/smart/simple/supply/visible/layer2": "floor",
            "/obj/structure/disposalpipe/segment": "underfloor",
            "/obj/structure/cable": "underfloor",
            "/obj/machinery/duct": "underfloor",
            "/obj/machinery/atmospherics/components/trinary/filter": "floor",
            "/obj/machinery/atmospherics/components/unary/vent_scrubber": "floor",
            "/obj/machinery/atmospherics/components/binary/pump": "floor",
        }
        for path, mode in cases.items():
            with self.subTest(path=path):
                self.assertEqual(classify(path).mode, mode)

    def test_floor_surfaces_include_lattice_and_catwalks(self):
        for path in (
            "/obj/structure/lattice", "/obj/structure/lattice/catwalk",
            "/obj/structure/catwalk/iron", "/obj/structure/grating",
            "/obj/structure/table/reinforced", "/obj/machinery/holopad",
            "/obj/effect/turf_decal/tile/neutral/fourcorners",
            "/obj/effect/turf_decal/stripes", "/obj/structure/shuttle/engine",
            "/obj/structure/fans/tiny",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify(path).mode, "floor")

    def test_wall_families_and_mobile_exceptions(self):
        for path in (
            "/obj/machinery/airalarm", "/obj/item/radio/intercom/directional/west",
            "/obj/structure/sign/poster/official", "/obj/structure/wallpaper",
            "/obj/machinery/status_display", "/obj/machinery/computer/telescreen",
            "/obj/machinery/computer/security/telescreen/entertainment",
            "/obj/machinery/power/apc", "/obj/machinery/light",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify(path).mode, "wall")
        self.assertEqual(classify("/obj/machinery/flasher/portable").mode, "upright")
        self.assertEqual(classify("/obj/machinery/defibrillator_mount/mobile").mode, "upright")

    def test_broad_keywords_do_not_flatten_unrelated_objects(self):
        for path in (
            "/obj/machinery/computer/shuttle", "/obj/machinery/computer/engine",
            "/obj/item/circuitboard/machine/holopad", "/obj/item/stack/tile",
            "/obj/structure/closet/engineering", "/obj/machinery/portable_atmospherics/canister",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify(path).mode, "upright")

    def test_explicit_parent_family_and_most_specific_override(self):
        path = "/obj/custom/control"
        properties = {"_type_chain": f"{path}|/obj/machinery/airalarm"}
        self.assertEqual(classify(path, properties).mode, "wall")
        overrides = {
            "/obj/custom": {"mode": "floor"},
            path: {"mode": "wall", "height": 0.2, "scale": 0.5, "label": "Control panel"},
        }
        rule = classify(path, properties, overrides)
        self.assertEqual((rule.mode, rule.height, rule.scale), ("wall", 0.2, 0.5))
        self.assertEqual(classify("/obj/customized/control", {}, overrides).mode, "upright")

    def test_invisible_markers_are_skipped_but_hidden_pipes_are_kept(self):
        self.assertEqual(classify("/obj/effect/tiny/invisible").mode, "skip")
        self.assertEqual(classify("/obj/marker", {"invisibility": "101"}).mode, "skip")
        self.assertEqual(classify("/obj/machinery/atmospherics/pipe/hidden",
                                  {"invisibility": "101"}).mode, "underfloor")


class GeometryPlacementTests(unittest.TestCase):
    cell = SimpleNamespace(x=3, y=3, z=1)

    def test_open_tile_mount_touches_near_wall_face(self):
        rule = classify("/obj/machinery/airalarm")
        for direction, wall, axis, expected in (
            (1, (3, 4, 1), "y", 0.497), (2, (3, 2, 1), "y", -0.497),
            (4, (4, 3, 1), "x", 0.497), (8, (2, 3, 1), "x", -0.497),
        ):
            with self.subTest(direction=direction):
                placed = place(rule, self.cell, {wall}, direction, {})
                self.assertAlmostEqual(getattr(placed, axis), expected)
                self.assertTrue(placed.wall_found)
                self.assertNotEqual(placed.direction, direction)

    def test_wall_tile_mount_is_outside_solid_geometry(self):
        rule = classify("/obj/structure/sign/poster")
        placed = place(rule, self.cell, {(3, 3, 1)}, 2, {})
        self.assertAlmostEqual(placed.y, -0.503)
        self.assertEqual(placed.direction, 2)

    def test_wall_neighbor_fallback_and_pixel_offsets(self):
        rule = classify("/obj/item/radio/intercom")
        placed = place(rule, self.cell, {(2, 3, 1)}, 2, {"pixel_x": "-32", "pixel_y": "4"})
        self.assertAlmostEqual(placed.x, -0.497)
        self.assertAlmostEqual(placed.y, 0.125)
        self.assertEqual(placed.direction, 4)
        missing = place(rule, self.cell, set(), 2, {})
        self.assertFalse(missing.wall_found)

    def test_overlap_separation_is_along_surface_normal(self):
        for path, axis in (("/obj/machinery/airalarm", "y"),
                           ("/obj/machinery/computer", "y"),
                           ("/obj/effect/turf_decal/stripe", "z")):
            rule = classify(path)
            first = place(rule, self.cell, {(3, 2, 1)}, 2, {}, 0)
            second = place(rule, self.cell, {(3, 2, 1)}, 2, {}, 1)
            self.assertNotEqual(getattr(first, axis), getattr(second, axis))

    def test_hidden_pipe_networks_have_distinct_negative_heights(self):
        positions = []
        for network in (1, 2, 3, 4, 5):
            path = f"/obj/machinery/atmospherics/pipe/hidden/layer{network}"
            positions.append(place(classify(path), self.cell, set(), 4,
                                   {"_path": path, "piping_layer": "PIPING_LAYER_DEFAULT"}).z)
        self.assertEqual(len(set(positions)), 5)
        self.assertTrue(all(z < 0 for z in positions))
        depths = []
        for path in ("/obj/structure/disposalpipe/segment",
                     "/obj/machinery/atmospherics/pipe/hidden/layer1", "/obj/structure/cable"):
            depths.append(place(classify(path), self.cell, set(), 2, {"_path": path}).z)
        self.assertLess(depths[0], depths[1])
        self.assertLess(depths[1], depths[2])

    def test_names_and_directions_preserve_identity(self):
        path = "/obj/machinery/airalarm/directional/north"
        self.assertTrue(entity_label(path, {"name": "air alarm"}).startswith("air alarm"))
        self.assertTrue(entity_label("/obj/structure/disposalpipe/hidden/layer2").startswith("disposalpipe"))
        self.assertEqual(entity_direction(path, {"dir": "SOUTH"}), 1)
        self.assertEqual(entity_direction(path, {"dir": "SOUTH"}, 8), 8)
        self.assertEqual(entity_direction("/obj/test", {"dir": "NORTHEAST"}), 5)


if __name__ == "__main__":
    unittest.main()
