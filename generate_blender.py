"""Generate a textured Blender blockout from a BYOND DMM file.

Run with:
blender --background --python generate_blender.py -- --dmm map.dmm --codebase codebase --output output
"""

from __future__ import annotations

import argparse
from array import array
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys
from time import perf_counter

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dmm import parse_dmm
from source_assets import CodebaseAssets, wall_state


WALL_HEIGHT = 2.8
LEVEL_GAP = 4.0
OBJECT_HEIGHT = 0.75

COLORS = {
    "space": (0.035, 0.045, 0.07, 1.0),
    "asteroid": (0.30, 0.25, 0.17, 1.0),
    "wall": (0.36, 0.39, 0.44, 1.0),
    "plating": (0.30, 0.33, 0.36, 1.0),
    "floor": (0.56, 0.58, 0.60, 1.0),
    "door": (0.80, 0.55, 0.20, 1.0),
    "window": (0.25, 0.70, 0.85, 1.0),
    "table": (0.40, 0.45, 0.50, 1.0),
    "machine": (0.30, 0.65, 0.40, 1.0),
    "object": (0.68, 0.54, 0.72, 1.0),
}


def turf_kind(path: str) -> str:
    lowered = path.lower()
    if "/turf/closed/" in lowered:
        return "wall"
    if "asteroid" in lowered or "icemoon" in lowered:
        return "asteroid"
    if "/space" in lowered:
        return "space"
    if "plating" in lowered:
        return "plating"
    return "floor"


def object_kind(path: str) -> str | None:
    lowered = path.lower()
    if not lowered.startswith("/obj/"):
        return None
    if any(part in lowered for part in (
        "/mapping_helpers/", "/landmark/", "/spawner/", "/abstract/",
    )):
        return None
    if lowered.startswith("/obj/effect/") and not any(
        part in lowered for part in ("/turf_decal/", "/effect/decal/")
    ):
        return None
    if "/door" in lowered or "/airlock" in lowered:
        return "door"
    if "/window" in lowered:
        return "window"
    if "/table" in lowered:
        return "table"
    if lowered.startswith("/obj/machinery/"):
        return "machine"
    return "object"


def is_underfloor(path: str) -> bool:
    lowered = path.lower()
    return (
        "/machinery/atmospherics/" in lowered
        or lowered.startswith("/obj/structure/cable")
        or "/structure/disposalpipe" in lowered
        or "/machinery/power/cable" in lowered
    )


def entity_name(kind: str, path: str, cell) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    label = " ".join(parts[-2:]).replace("_", " ")
    return f"{kind.title()} - {label} [{cell.x},{cell.y},{cell.z}]"


def set_entity_metadata(obj, path: str, cell, placement: str, info=None, state=None):
    obj["DMM type"] = path
    obj["DMM coordinates"] = [cell.x, cell.y, cell.z]
    obj["Placement"] = placement
    if cell.area:
        obj["DMM area"] = cell.area
    if info:
        obj["DMI file"] = str(info.path)
    if state is not None:
        obj["DMI state"] = state


def material_for_kind(kind: str) -> bpy.types.Material:
    name = f"DMM - {kind}"
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    color = COLORS[kind]
    material.diffuse_color = color
    material.use_nodes = True
    material.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = color
    return material


def textured_material(info, opaque=False) -> bpy.types.Material:
    suffix = " - opaque" if opaque else ""
    material_name = (
        f"DMI - {info.path.stem} - {abs(hash(str(info.path))) & 0xFFFFFF:06x}{suffix}"
    )
    material = bpy.data.materials.get(material_name)
    if material:
        return material

    image = bpy.data.images.load(str(info.path), check_existing=True)
    image.pack()
    material = bpy.data.materials.new(material_name)
    material.use_nodes = True
    nodes = material.node_tree.nodes
    shader = nodes.get("Principled BSDF")
    texture = nodes.new("ShaderNodeTexImage")
    texture.image = image
    texture.interpolation = "Closest"
    texture.extension = "CLIP"
    material.node_tree.links.new(texture.outputs["Color"], shader.inputs["Base Color"])
    if not opaque:
        material.node_tree.links.new(texture.outputs["Alpha"], shader.inputs["Alpha"])
        try:
            material.surface_render_method = "DITHERED"
        except (AttributeError, TypeError):
            pass
    return material


class MeshBuilder:
    def __init__(self):
        self.vertices = []
        self.faces = []
        self.material_ids = []
        self.uv_faces = []
        self.materials = []
        self.material_slot_ids = {}

    def material_id(self, key, material):
        if key not in self.material_slot_ids:
            self.material_slot_ids[key] = len(self.materials)
            self.materials.append(material)
        return self.material_slot_ids[key]

    def quad(self, points, material_id, uv_rect=None):
        base = len(self.vertices)
        self.vertices.extend(points)
        self.faces.append(tuple(range(base, base + 4)))
        self.material_ids.append(material_id)
        if uv_rect:
            u0, v0, u1, v1 = uv_rect
            self.uv_faces.append(((u0, v0), (u1, v0), (u1, v1), (u0, v1)))
        else:
            self.uv_faces.append(((0.0, 0.0),) * 4)

    def box(self, x, y, z, width, depth, height, material_id, front=None, transform=None):
        x2, y2, z2 = x + width, y + depth, z + height
        corners = [
            (x, y, z), (x2, y, z), (x2, y2, z), (x, y2, z),
            (x, y, z2), (x2, y, z2), (x2, y2, z2), (x, y2, z2),
        ]
        if transform:
            corners = [transform(*point) for point in corners]
        for index, face in enumerate((
            (3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4),
            (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
        )):
            slot, uv = front if front and index in (2, 4) else (material_id, None)
            self.quad([corners[i] for i in face], slot, uv)

    def plane(self, x, y, z, width, depth, material_id, uv_rect):
        self.quad(
            [(x-width/2, y-depth/2, z), (x+width/2, y-depth/2, z),
             (x+width/2, y+depth/2, z), (x-width/2, y+depth/2, z)],
            material_id,
            uv_rect,
        )

    def append(self, other):
        base = len(self.vertices)
        slots = [self.material_id(material, material) for material in other.materials]
        self.vertices.extend(other.vertices)
        self.faces.extend(tuple(base + index for index in face) for face in other.faces)
        self.material_ids.extend(slots[slot] for slot in other.material_ids)
        self.uv_faces.extend(other.uv_faces)

    def create_mesh(self, name):
        mesh = bpy.data.meshes.new(name)
        mesh.from_pydata(self.vertices, [], self.faces)
        mesh.update()
        for material in self.materials:
            mesh.materials.append(material)
        uv_layer = mesh.uv_layers.new(name="DMI atlas UV")
        mesh.polygons.foreach_set("material_index", self.material_ids)
        coords = array("f", (v for face in self.uv_faces for uv in face for v in uv))
        uv_layer.data.foreach_set("uv", coords)
        return mesh

    def create_object(self, name, collection):
        if not self.faces:
            return None
        obj = bpy.data.objects.new(name, self.create_mesh(f"{name} mesh"))
        collection.objects.link(obj)
        return obj


def new_collection(parent, name):
    collection = bpy.data.collections.new(name)
    parent.children.link(collection)
    return collection


def glazing_material():
    name = "DMM Glazing"
    material = bpy.data.materials.get(name)
    if material:
        return material
    material = bpy.data.materials.new(name)
    material.diffuse_color = (0.28, 0.67, 0.82, 0.26)
    material.use_nodes = True
    shader = material.node_tree.nodes["Principled BSDF"]
    shader.inputs["Base Color"].default_value = material.diffuse_color
    shader.inputs["Alpha"].default_value = 0.26
    shader.inputs["Roughness"].default_value = 0.28
    if hasattr(material, "surface_render_method"):
        material.surface_render_method = "BLENDED"
    else:
        material.blend_method = "BLEND"
    return material


def opening_direction(cell, path, mapped_dir, walls, kind):
    if mapped_dir:
        return mapped_dir
    named = {"north": 1, "south": 2, "east": 4, "west": 8}.get(path.rsplit("/", 1)[-1])
    if named:
        return named
    if kind == "door":
        def wall(dx, dy):
            return (cell.x + dx, cell.y + dy, cell.z) in walls

        if wall(0, 1) + wall(0, -1) > wall(1, 0) + wall(-1, 0):
            return 4
    return 2


def add_opening(builder, x, y, z, tile_size, kind, path, direction, texture, fallback):
    lowered = path.lower()
    glass = kind == "window" or "glass" in lowered or "windoor" in lowered
    full = kind == "window" and ("fulltile" in lowered or "full_tile" in lowered)
    frame = builder.material_id(fallback.name, fallback)
    front = None
    if texture and not glass:
        info, state = texture
        material = textured_material(info, opaque=True)
        front = (builder.material_id(material.name, material), info.uv_rect(state, direction))
    half = tile_size * (0.46 if full else 0.49)
    depth = tile_size * (0.06 if glass else 0.09)
    height = WALL_HEIGHT * 0.91
    sill = WALL_HEIGHT * 0.21 if kind == "window" and not full else 0.0
    for side in ((1, 2, 4, 8) if full else (direction,)):
        edge = (tile_size / 2 - depth) if kind == "window" else 0
        # Rotate the cross-section into the selected BYOND direction.
        def transform(u, v, h):
            dx, dy = {1: (-u, edge - v), 2: (u, v - edge),
                      4: (edge - v, u), 8: (v - edge, -u)}[side]
            return x + dx, y + dy, z + h

        def part(left, right, base, top, half_depth, slot, face=None):
            builder.box(left, -half_depth, base, right - left, 2 * half_depth,
                        top - base, slot, front=face, transform=transform)

        if not glass:
            part(-half, half, 0, height, depth, frame, front)
            continue
        glass_material = glazing_material()
        pane = builder.material_id(glass_material.name, glass_material)
        rail = min(0.09, tile_size * 0.12)
        part(-half, half, sill, sill + rail, depth, frame)
        part(-half, half, height - rail, height, depth, frame)
        part(-half, -half + rail, sill + rail, height - rail, depth, frame)
        part(half - rail, half, sill + rail, height - rail, depth, frame)
        part(-half + rail, half - rail, sill + rail, height - rail, depth * 0.11, pane)
    return front is not None


def build_level(cells, tile_size, level_height, origin_x, origin_y, level_collection,
                assets, stats, sprite_meshes, performance_batches, performance_only=False,
                organize_by="type", chunk_size=32, terrain_parts=None):
    terrain_collections = {
        "space": new_collection(level_collection, "Space"),
        "floor": new_collection(level_collection, "Floors"),
        "plating": new_collection(level_collection, "Plating"),
        "asteroid": new_collection(level_collection, "Asteroid"),
        "wall": new_collection(level_collection, "Walls"),
    }
    entities_collection = new_collection(level_collection, "Entities")
    entity_collections = {
        kind: new_collection(entities_collection, name)
        for kind, name in (
            ("door", "Doors"),
            ("window", "Windows"),
            ("table", "Tables"),
            ("machine", "Machines"),
            ("object", "Objects"),
        )
    }
    underfloor_collection = new_collection(level_collection, "Underfloor")
    proxy_collection = new_collection(level_collection, "Proxy Geometry")
    proxy_collection.hide_viewport = True
    terrain_builders = defaultdict(MeshBuilder)
    subcollections = {}

    def subgroup(collection, label):
        if not label:
            return collection
        key = (collection, label)
        if key not in subcollections:
            subcollections[key] = new_collection(collection, label)
        return subcollections[key]
    fallback_materials = {
        kind: material_for_kind(kind)
        for kind in COLORS
    }
    wall_cells = {
        (cell.x, cell.y, cell.z): cell.turf
        for cell in cells if turf_kind(cell.turf) == "wall"
    }
    half = tile_size / 2
    object_stack = Counter()

    for cell in cells:
        kind = turf_kind(cell.turf)
        label = ""
        if organize_by == "area":
            label = cell.area or "Unassigned area"
        elif organize_by == "chunk":
            cx, cy = (cell.x - origin_x) // chunk_size, (cell.y - origin_y) // chunk_size
            label = f"Chunk {cx:02d}, {cy:02d}"
        builder = terrain_builders[kind, label]
        x = (cell.x - origin_x) * tile_size
        y = (cell.y - origin_y) * tile_size
        bottom = level_height
        texture = assets.turf_texture(cell.turf, cell.turf_icon, cell.turf_icon_state)
        if texture:
            info, state = texture
            face_material = builder.material_id(
                f"dmi:{info.path}:{'opaque' if kind == 'wall' else 'alpha'}",
                textured_material(info, opaque=kind == "wall"),
            )
            if kind == "wall" and cell.turf_icon_state is None:
                state = wall_state(info, state, cell.x, cell.y, cell.z, wall_cells)
            uv_rect = info.uv_rect(state)
            stats["textured_turfs"] += 1
            stats["dmi_files"].add(str(info.path))
        else:
            face_material = builder.material_id(
                f"kind:{kind}", fallback_materials[kind]
            )
            uv_rect = None
            stats["fallback_turfs"] += 1
            stats["fallback_types"][cell.turf] += 1

        if kind != "wall":
            builder.quad(
                [(x-half, y-half, bottom), (x+half, y-half, bottom),
                 (x+half, y+half, bottom), (x-half, y+half, bottom)],
                face_material,
                uv_rect,
            )
        else:
            top = bottom + WALL_HEIGHT
            builder.quad(
                [(x-half, y-half, top), (x+half, y-half, top),
                 (x+half, y+half, top), (x-half, y+half, top)],
                face_material,
                uv_rect,
            )
            sides = (
                ((0, -1), [(x-half, y-half, bottom), (x+half, y-half, bottom),
                           (x+half, y-half, top), (x-half, y-half, top)]),
                ((1, 0), [(x+half, y-half, bottom), (x+half, y+half, bottom),
                          (x+half, y+half, top), (x+half, y-half, top)]),
                ((0, 1), [(x+half, y+half, bottom), (x-half, y+half, bottom),
                          (x-half, y+half, top), (x+half, y+half, top)]),
                ((-1, 0), [(x-half, y+half, bottom), (x-half, y-half, bottom),
                           (x-half, y-half, top), (x-half, y+half, top)]),
            )
            for (dx, dy), points in sides:
                if (cell.x + dx, cell.y + dy, cell.z) not in wall_cells:
                    builder.quad(points, face_material, uv_rect)

        # Object sprites are separate, transparent top-down planes, which are
        # easy to select and preserve the source game's 2D icon appearance.
        for index, path in enumerate(cell.objects):
            obj_kind = object_kind(path)
            if not obj_kind:
                stats["objects_skipped"] += 1
                continue
            below_floor = is_underfloor(path)
            if below_floor:
                stats["underfloor_objects"] += 1
            if "/machinery/light/" in path.lower():
                fixture_height = 0.3 if "/light/floor" in path.lower() else WALL_HEIGHT * 0.82
                stats["light_fixtures"].add(
                    (round(x, 4), round(y, 4), round(bottom + fixture_height, 4),
                     25.0 if "/light/floor" in path.lower() else 90.0)
                )
            entity_collection = underfloor_collection if below_floor else entity_collections[obj_kind]
            obj_texture = assets.texture(path)
            if obj_kind in ("door", "window"):
                mapped_dir = cell.object_directions[index] if cell.object_directions else None
                direction = opening_direction(cell, path, mapped_dir, wall_cells, obj_kind)
                fallback = fallback_materials[obj_kind]
                geometry_texture = obj_kind == "door" and not any(
                    part in path.lower() for part in ("glass", "windoor")
                )
                texture = obj_texture if geometry_texture else None
                if performance_batches is not None:
                    add_opening(performance_batches[entity_collection], x, y, bottom,
                                tile_size, obj_kind, path, direction, texture, fallback)
                if not performance_only:
                    key = ("opening", path, direction)
                    if key not in sprite_meshes:
                        opening = MeshBuilder()
                        add_opening(opening, 0, 0, 0, tile_size, obj_kind, path,
                                    direction, texture, fallback)
                        sprite_meshes[key] = opening.create_mesh(f"{obj_kind.title()} geometry")
                    obj = bpy.data.objects.new(entity_name(obj_kind, path, cell), sprite_meshes[key])
                    obj.location = (x, y, bottom)
                    subgroup(entity_collection, label).objects.link(obj)
                    set_entity_metadata(obj, path, cell, "upright geometry", *(texture or ()))
                    obj["DMM direction"] = direction
                stats["geometry_objects"] += 1
                if texture:
                    stats["textured_objects"] += 1
                    stats["dmi_files"].add(str(texture[0].path))
                continue
            if obj_texture:
                info, state = obj_texture
                ratio = max(info.frame_width, info.frame_height) / 32
                size = tile_size * min(max(ratio, 0.65), 2.0)
                stack_key = (cell.x, cell.y, cell.z)
                layer = object_stack[stack_key]
                object_stack[stack_key] += 1
                sprite_z = bottom - 0.04 - layer * 0.002 if below_floor else bottom + 0.015 + layer * 0.002
                if performance_batches is not None:
                    batch = performance_batches[entity_collection]
                    slot = batch.material_id(info.path, textured_material(info))
                    batch.plane(x, y, sprite_z, size, size, slot, info.uv_rect(state))
                if not performance_only:
                    key = (info.path, state)
                    if key not in sprite_meshes:
                        sprite = MeshBuilder()
                        slot = sprite.material_id(info.path, textured_material(info))
                        sprite.plane(0, 0, 0, size, size, slot, info.uv_rect(state))
                        sprite_meshes[key] = sprite.create_mesh(f"{info.path.stem} - {state}")
                    obj = bpy.data.objects.new(
                        entity_name(obj_kind, path, cell), sprite_meshes[key]
                    )
                    # Keep each placement independently editable. The linked
                    # mesh is shared until explicitly made single-user.
                    obj.location = (x, y, sprite_z)
                    subgroup(entity_collection, label).objects.link(obj)
                    set_entity_metadata(
                        obj, path, cell, "below floor" if below_floor else "on floor",
                        info, state,
                    )
                stats["textured_objects"] += 1
                stats["dmi_files"].add(str(info.path))
            else:
                targets = []
                if not performance_only:
                    sprite_builder = MeshBuilder()
                    targets.append(sprite_builder)
                if performance_batches is not None:
                    targets.append(performance_batches[proxy_collection])
                box = (
                    x - tile_size * 0.3, y - tile_size * 0.3, bottom,
                    tile_size * 0.6, tile_size * 0.6, OBJECT_HEIGHT,
                )
                for target in targets:
                    slot = target.material_id(obj_kind, fallback_materials[obj_kind])
                    target.box(*box, slot)
                if not performance_only:
                    obj = sprite_builder.create_object(
                        f"Proxy - {entity_name(obj_kind, path, cell)}", subgroup(proxy_collection, label)
                    )
                    set_entity_metadata(obj, path, cell, "proxy box")
                stats["fallback_objects"] += 1
                stats["fallback_object_types"][path] += 1

    for (kind, label), builder in terrain_builders.items():
        name = f"{kind.title()} tiles" + (f" - {label}" if label else "")
        builder.create_object(name, subgroup(terrain_collections[kind], label))
        if terrain_parts is not None:
            terrain_parts[terrain_collections[kind], kind].append(builder)


def add_scene_lighting(root, map_width, map_height, tile_size, level_heights, fixtures):
    lighting = new_collection(root, "Lighting")
    center_x = (map_width - tile_size) / 2
    center_y = (map_height - tile_size) / 2

    world = bpy.context.scene.world
    if world is None:
        world = bpy.data.worlds.new("DMM World")
        bpy.context.scene.world = world
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.22, 0.24, 0.28, 1)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.45

    sun_data = bpy.data.lights.new("DMM Sun", type="SUN")
    sun_data.energy = 1.5
    sun_data.angle = math.radians(18)
    sun = bpy.data.objects.new("DMM Sun", sun_data)
    lighting.objects.link(sun)
    sun.rotation_euler = (math.radians(22), math.radians(-18), math.radians(-28))

    for index, height in enumerate(level_heights, start=1):
        data = bpy.data.lights.new(f"Z{index} Area", type="AREA")
        data.energy = 3500
        data.shape = "DISK"
        data.size = max(12, min(map_width, map_height) * 0.35)
        light = bpy.data.objects.new(f"Z{index} Area", data)
        lighting.objects.link(light)
        light.location = (
            center_x,
            center_y,
            height + max(12, min(map_width, map_height) * 0.2),
        )

    fixtures_collection = new_collection(lighting, "Fixtures")
    for index, (x, y, z, energy) in enumerate(sorted(fixtures), start=1):
        data = bpy.data.lights.new(f"Fixture {index:03}", type="POINT")
        data.energy = energy
        data.shadow_soft_size = 1.1
        light = bpy.data.objects.new(f"Fixture {index:03}", data)
        fixtures_collection.objects.link(light)
        light.location = (x, y, z)

    camera_collection = new_collection(root, "Cameras")
    camera_data = bpy.data.cameras.new("Map Overview")
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = max(map_width, map_height) * 1.35
    camera = bpy.data.objects.new("Map Overview", camera_data)
    camera_collection.objects.link(camera)
    max_height = max(level_heights, default=0) + WALL_HEIGHT
    distance = max(map_width, map_height) * 0.85
    target = Vector((center_x, center_y, max_height / 2))
    camera.location = (
        center_x - distance * 0.65,
        center_y - distance * 0.8,
        max_height + distance * 0.8,
    )
    camera.rotation_euler = (target - camera.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.camera = camera


def install_entity_batches(batches, terrain_parts=None):
    """Replace individual placements in memory, after their files have been saved."""
    replaces = list(batches)
    if terrain_parts is not None:
        replaces.extend(collection for collection, _ in terrain_parts)
    individual = {obj for collection in replaces for obj in collection.all_objects}
    if individual:
        bpy.data.batch_remove(tuple(individual))
    empty_groups = {group for collection in replaces for group in collection.children}
    if empty_groups:
        bpy.data.batch_remove(tuple(empty_groups))
    for collection, builder in batches.items():
        builder.create_object(f"{collection.name} - merged", collection)
    for (collection, kind), builders in (terrain_parts or {}).items():
        merged = MeshBuilder()
        for builder in builders:
            merged.append(builder)
        merged.create_object(f"{kind.title()} tiles", collection)


def arguments():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description="Create a textured Blender blockout from DMM.")
    parser.add_argument("--dmm", required=True, help="Path to a .dmm map")
    parser.add_argument("--codebase", required=True,
                        help="SS13 codebase root containing tgstation.dme and icons/")
    parser.add_argument("--map-switch", choices=("map", "compile"), default="map",
                        help="MAP_SWITCH branch to use; Renderbus map renders use 'map'")
    parser.add_argument(
        "--output",
        default="output",
        help="Output root; files are written to <root>/<map-name>/files",
    )
    parser.add_argument("--tile-size", type=float, default=1.0, help="Tile width/depth")
    variants = parser.add_mutually_exclusive_group()
    variants.add_argument(
        "--performance-mode",
        action="store_true",
        help="Write both high-fidelity and performance Blender files",
    )
    variants.add_argument(
        "--performance-only", action="store_true",
        help="Write only the performance Blender file",
    )
    glb = parser.add_mutually_exclusive_group()
    glb.add_argument("--glb", choices=("match", "high", "performance", "both", "none"),
                     default="match", help="Which GLB variants to write (default: match Blender files)")
    glb.add_argument("--no-glb", action="store_true", help="Alias for --glb none")
    parser.add_argument("--organize-by", choices=("type", "area", "chunk"), default="type",
                        help="Optional area or chunk subcollections in high-fidelity exports")
    parser.add_argument("--chunk-size", type=int, default=32, help="Chunk width/depth in map tiles")
    return parser.parse_args(argv)


def main():
    started = perf_counter()
    args = arguments()
    high_blend = not args.performance_only
    perf_blend = args.performance_mode or args.performance_only
    glb_mode = "none" if args.no_glb else args.glb
    high_glb = high_blend if glb_mode == "match" else glb_mode in ("high", "both")
    perf_glb = perf_blend if glb_mode == "match" else glb_mode in ("performance", "both")
    build_high = high_blend or high_glb
    build_perf = perf_blend or perf_glb
    step = 0
    total = 3 + sum((high_blend, perf_blend, high_glb, perf_glb, build_high and build_perf))

    def progress(label):
        nonlocal step
        print(f"PROGRESS {step}/{total} {label}", flush=True)
        step += 1

    source = Path(args.dmm).resolve()
    output_root = Path(args.output).resolve()
    if not source.is_file():
        raise SystemExit(f"DMM file not found: {source}")
    if args.tile_size <= 0:
        raise SystemExit("--tile-size must be positive")
    if args.chunk_size <= 0:
        raise SystemExit("--chunk-size must be positive")
    output = output_root / source.stem / "files"
    output.mkdir(parents=True, exist_ok=True)

    progress("Reading the map and indexing sprites")
    dmm = parse_dmm(source)
    assets = CodebaseAssets(args.codebase, map_switch=args.map_switch)
    print(f"Parsed map and indexed assets in {perf_counter() - started:.1f}s", flush=True)
    build_started = perf_counter()
    progress("Building the Blender scene")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    root = bpy.data.collections.new(source.stem)
    bpy.context.scene.collection.children.link(root)
    grouped = defaultdict(list)
    for cell in dmm.cells:
        grouped[cell.z].append(cell)
    origin_x = min(cell.x for cell in dmm.cells)
    origin_y = min(cell.y for cell in dmm.cells)
    max_x = max(cell.x for cell in dmm.cells)
    max_y = max(cell.y for cell in dmm.cells)
    map_width = (max_x - origin_x + 1) * args.tile_size
    map_height = (max_y - origin_y + 1) * args.tile_size
    stats = {
        "textured_turfs": 0,
        "fallback_turfs": 0,
        "textured_objects": 0,
        "geometry_objects": 0,
        "fallback_objects": 0,
        "objects_skipped": 0,
        "underfloor_objects": 0,
        "dmi_files": set(),
        "fallback_types": Counter(),
        "fallback_object_types": Counter(),
        "light_fixtures": set(),
    }
    level_heights = []
    sprite_meshes = {}
    batches = defaultdict(MeshBuilder) if build_perf else None
    layout = args.organize_by if build_high else "type"
    terrain_parts = defaultdict(list) if build_perf and layout != "type" else None
    for level_index, (z, cells) in enumerate(sorted(grouped.items())):
        level_height = level_index * LEVEL_GAP
        level_heights.append(level_height)
        collection = new_collection(root, f"Z-level {z}")
        build_level(
            cells,
            args.tile_size,
            level_height,
            origin_x,
            origin_y,
            collection,
            assets,
            stats,
            sprite_meshes,
            batches,
            performance_only=not build_high,
            organize_by=layout,
            chunk_size=args.chunk_size,
            terrain_parts=terrain_parts,
        )
    if not build_high:
        install_entity_batches(batches)
    add_scene_lighting(
        root, map_width, map_height, args.tile_size, level_heights,
        stats["light_fixtures"],
    )
    print(f"Built scene in {perf_counter() - build_started:.1f}s", flush=True)

    report = {
        "source_dmm": str(source),
        "codebase": str(Path(args.codebase).resolve()),
        "map_switch": args.map_switch,
        "cells": len(dmm.cells),
        "z_levels": sorted(grouped),
        "textured_turfs": stats["textured_turfs"],
        "fallback_turfs": stats["fallback_turfs"],
        "textured_objects": stats["textured_objects"],
        "door_and_window_geometry": stats["geometry_objects"],
        "organize_by": layout,
        "fallback_objects": stats["fallback_objects"],
        "objects_skipped": stats["objects_skipped"],
        "underfloor_objects": stats["underfloor_objects"],
        "dmi_files": sorted(stats["dmi_files"]),
        "fallback_types": dict(stats["fallback_types"]),
        "fallback_object_types": dict(stats["fallback_object_types"]),
        "scene_lighting": {
            "sun": True,
            "area_lights": len(level_heights),
            "game_fixtures": len(stats["light_fixtures"]),
            "overview_camera": True,
        },
        "proxy_geometry_hidden_by_default": True,
    }
    suffix = "" if build_high else ".performance"
    (output / f"{source.stem}{suffix}.textures.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    def save_variant(suffix, blend, glb):
        started = perf_counter()
        name = f"{source.stem}{suffix}"
        if blend:
            progress(f"Saving {name}.blend")
            result = bpy.ops.wm.save_as_mainfile(filepath=str(output / f"{name}.blend"))
            if 'FINISHED' not in result:
                raise RuntimeError(f"Blender save failed for {name}")
        if glb:
            progress(f"Exporting {name}.glb")
            result = bpy.ops.export_scene.gltf(
                filepath=str(output / f"{name}.glb"),
                export_format="GLB",
                use_selection=False,
            )
            if 'FINISHED' not in result:
                raise RuntimeError(f"GLB export failed for {name}")
        print(f"Saved {name} in {perf_counter() - started:.1f}s", flush=True)

    if build_high:
        save_variant("", high_blend, high_glb)
    if build_perf:
        if build_high:
            progress("Installing batched meshes for the performance version")
            batch_started = perf_counter()
            install_entity_batches(batches, terrain_parts)
            print(f"Installed {len(batches):,} entity batches in {perf_counter() - batch_started:.1f}s", flush=True)
        save_variant(".performance", perf_blend, perf_glb)
    progress("Updating the browser map index")
    maps = []
    for map_dir in sorted(output_root.glob("*/files")):
        map_name = map_dir.parent.name
        model = map_dir / f"{map_name}.glb"
        performance_model = map_dir / f"{map_name}.performance.glb"
        if not model.is_file() and not performance_model.is_file():
            continue
        entry = {
            "name": map_name,
            "url": (model if model.is_file() else performance_model).relative_to(output_root).as_posix(),
        }
        performance_model = map_dir / f"{map_name}.performance.glb"
        if performance_model.is_file():
            entry["performance_url"] = performance_model.relative_to(output_root).as_posix()
        maps.append(entry)
    (output_root / "maps.json").write_text(
        json.dumps({"maps": maps}, indent=2), encoding="utf-8"
    )
    print(
        f"Parsed {len(dmm.cells):,} tiles across {len(grouped)} z-level(s); "
        f"textured {stats['textured_turfs']:,} terrain tiles and "
        f"{stats['textured_objects']:,} objects; "
        f"{stats['fallback_objects']:,} objects use proxy geometry."
    )
    print(f"Built {stats['geometry_objects']:,} doors and windows as geometry.")
    print(f"Used {len(stats['dmi_files'])} DMI files.")
    print(f"Saved exports in: {output} ({perf_counter() - started:.1f}s total)")
    progress("Export complete")


if __name__ == "__main__":
    main()
