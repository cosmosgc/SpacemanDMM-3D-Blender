"""Run with Blender --background --factory-startup --python-exit-code 1 --python <this file>."""

from collections import Counter, defaultdict
from pathlib import Path
import sys
import tempfile

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dmm import Cell
from generate_blender import MeshBuilder, build_level
from source_assets import DmiInfo, DmiState


def stats():
    return defaultdict(int, dmi_files=set(), light_fixtures=set(),
                       fallback_types=Counter(), fallback_object_types=Counter(),
                       placement_counts=Counter(), skipped_types=Counter(),
                       unmounted_types=Counter())


def points(vertices):
    return Counter(tuple(round(float(v), 5) for v in point) for point in vertices)


with tempfile.TemporaryDirectory() as folder:
    image = bpy.data.images.new("Placement test sprite", width=32, height=128)
    image.filepath_raw = str(Path(folder) / "test.png")
    image.file_format = "PNG"
    image.save()
    info = DmiInfo(Path(image.filepath_raw), 32, 128, 32, 32,
                   {"test": DmiState("test", 4, 1, 0)})

    class Assets:
        def properties(self, path):
            return {"name": "air alarm" if "airalarm" in path else path.split("/")[-1]}

        def turf_texture(self, path, icon, state):
            return None if path == "/obj/custom/missing_panel" else (info, "test")

    paths = (
        "/obj/machinery/airalarm/directional/north",
        "/obj/item/radio/intercom/directional/north",
        "/obj/structure/sign/poster",
        "/obj/machinery/atmospherics/pipe/hidden/layer2",
        "/obj/machinery/atmospherics/pipe/hidden/layer4",
        "/obj/structure/disposalpipe/segment",
        "/obj/machinery/atmospherics/components/trinary/filter",
        "/obj/effect/turf_decal/tile/neutral/fourcorners",
        "/obj/structure/lattice/catwalk",
        "/obj/structure/table",
        "/obj/machinery/computer/shuttle",
        "/obj/custom/missing_panel",
        "/obj/effect/tiny/invisible",
    )
    cells = [
        Cell(0, 0, 1, "/turf/open/floor", paths,
             object_directions=(1,) * len(paths)),
        Cell(0, 1, 1, "/turf/closed/wall", ()),
    ]
    rules = {"/obj/custom/missing_panel": {"mode": "wall", "height": 0.1, "scale": 0.5}}
    root = bpy.data.collections.new("Placement regression")
    bpy.context.scene.collection.children.link(root)
    batches = defaultdict(MeshBuilder)
    result = stats()
    build_level(cells, 2, 4, 0, 0, root, Assets(), result, {}, batches,
                organize_by="chunk", chunk_size=1, placement_rules=rules)
    bpy.context.view_layer.update()
    objects = {obj["DMM type"]: obj for obj in root.all_objects if "DMM type" in obj}
    assert len(objects) == len(paths) - 1
    assert result["objects_skipped"] == 1
    assert result["underfloor_objects"] == 3
    assert result["fallback_objects"] == 1
    for path, obj in objects.items():
        verts = [obj.matrix_world @ vertex.co for vertex in obj.data.vertices]
        zs = [vertex.z for vertex in verts]
        if obj["Placement"] in ("floor", "underfloor"):
            assert max(zs) - min(zs) < 0.00001, path
            if obj["Placement"] == "underfloor":
                assert max(zs) < 4, path
            else:
                assert min(zs) > 4, path
        elif obj["Placement"] == "wall":
            assert all(0.9 < vertex.y < 1 for vertex in verts), path
            assert max(zs) > min(zs), path
    assert objects[paths[0]].name.startswith("air alarm")
    assert objects["/obj/structure/lattice/catwalk"]["Walkable surface"]
    assert objects[paths[3]].location.z != objects[paths[4]].location.z
    assert objects[paths[0]].location.y != objects[paths[1]].location.y
    # A performance batch must contain exactly the high-fidelity geometry,
    # including normals/UV orientation, scale, layer offsets, and proxy mounts.
    for collection, batch in batches.items():
        high_points = [
            obj.matrix_world @ vertex.co
            for obj in collection.all_objects for vertex in obj.data.vertices
        ]
        assert points(high_points) == points(batch.vertices), collection.name
    root_fast = bpy.data.collections.new("Performance-only regression")
    bpy.context.scene.collection.children.link(root_fast)
    fast_batches = defaultdict(MeshBuilder)
    build_level(cells, 2, 4, 0, 0, root_fast, Assets(), stats(), {}, fast_batches,
                performance_only=True, placement_rules=rules)
    assert points([v for b in batches.values() for v in b.vertices]) == points(
        [v for b in fast_batches.values() for v in b.vertices])
    for direction in (1, 2, 4, 8, 5, 9, 6, 10):
        builder = MeshBuilder()
        builder.vertical_plane(0, 0, 0, 1, 1, 0, (0, 0, 1, 1), direction)
        from mathutils import Vector
        a, b, c, _ = map(Vector, builder.vertices)
        normal = (b - a).cross(c - a)
        from entity_placement import DIRECTIONS
        dx, dy = DIRECTIONS[direction]
        assert normal.dot(Vector((dx, dy, 0))) > 0
    print("PASS: Blender placements, wall contact, readable names, floor surfaces, "
          "network depths, proxy mounts, facing normals, high/batched/fast parity")
