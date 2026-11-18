"""Static SS13 placement rules, independent of Blender.

Coordinates and offsets are in tiles, with BYOND north = +Y and height = +Z.
DM runtime initialization is not executed; uncertain wall mounts are reported.
"""

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re


DIRECTIONS = {1: (0, 1), 2: (0, -1), 4: (1, 0), 8: (-1, 0),
              5: (1, 1), 9: (-1, 1), 6: (1, -1), 10: (-1, -1)}
NAMED_DIRECTIONS = dict(zip(
    ("north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest"),
    DIRECTIONS,
))
OPPOSITE = {1: 2, 2: 1, 4: 8, 8: 4}
MODES = {"upright", "wall", "floor", "underfloor", "skip"}
COLLECTIONS = {"wall": "Wall Fixtures",
               "floor": "Floor Fixtures", "underfloor": "Underfloor"}


def number(value, default=0.0):
    try:
        result = float(value)
        return result if math.isfinite(result) else default
    except (ValueError, TypeError):
        return default


def direction_value(value):
    direction = NAMED_DIRECTIONS.get(str(value).lower(), int(number(value)))
    return direction if direction in DIRECTIONS else None


def entity_direction(path, properties, mapped=None):
    return (direction_value(mapped)
            or NAMED_DIRECTIONS.get(path.rsplit("/", 1)[-1].lower())
            or direction_value(properties.get("dir")) or 2)


def is_type(path, prefix):
    return path == prefix or path.startswith(prefix + "/")


def load_rules(path):
    """User overrides: longest matching type prefix wins."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Placement rules must be an object keyed by DM type path")
    for prefix, rule in data.items():
        if not prefix.startswith("/obj/") or not isinstance(rule, dict):
            raise ValueError(f"Invalid placement rule: {prefix}")
        if set(rule) - {"mode", "height", "scale", "label"}:
            raise ValueError(f"Unknown placement option for {prefix}")
        if rule.get("mode") not in MODES:
            raise ValueError(f"Invalid placement mode for {prefix}")
        for key in ("height", "scale"):
            if key in rule and (not isinstance(rule[key], (int, float))
                                or not math.isfinite(rule[key])
                                or (key == "scale" and rule[key] <= 0)):
                raise ValueError(f"Invalid {key} for {prefix}")
        if "label" in rule and not isinstance(rule["label"], str):
            raise ValueError(f"Invalid label for {prefix}")
    return data


@dataclass(frozen=True)
class PlacementRule:
    mode: str
    reason: str
    height: float | None = None
    scale: float = 1.0
    label: str | None = None


def classify(path, properties=None, overrides=None):
    properties = properties or {}
    paths = [path.lower(), *properties.get("_type_chain", "").lower().split("|")]
    parts = set(path.lower().split("/"))
    def family(*prefixes):
        return any(is_type(p, prefix) for p in paths for prefix in prefixes)
    def result(mode, reason):
        return PlacementRule(mode, reason)

    matches = [prefix for prefix in (overrides or {}) if is_type(path, prefix)]
    if matches:
        prefix = max(matches, key=len)
        rule = overrides[prefix]
        return PlacementRule(rule["mode"], f"override: {prefix}", rule.get("height"),
                             rule.get("scale", 1.0), rule.get("label"))

    # Utilities are flat whether buried or exposed. A layer2 suffix denotes a
    # pipe network, not a free-standing object or a generic BYOND render layer.
    if family("/obj/structure/disposalpipe", "/obj/structure/cable", "/obj/machinery/power/cable",
              "/obj/machinery/duct", "/obj/machinery/power/terminal", "/obj/machinery/navbeacon"):
        return result("underfloor", "buried disposal/cable network")
    if family("/obj/machinery/atmospherics/pipe"):
        exposed = "visible" in parts or str(properties.get("hide")).upper() in ("0", "FALSE")
        return result("floor" if exposed else "underfloor", "atmospheric pipe network")
    if family("/obj/machinery/atmospherics/components",
              "/obj/machinery/atmospherics/binary", "/obj/machinery/atmospherics/trinary",
              "/obj/machinery/atmospherics/unary"):
        return result("floor", "surface atmos device (pump/filter/vent/scrubber)")
    if family("/obj/effect/mapping_helpers", "/obj/effect/landmark", "/obj/effect/spawner",
              "/obj/effect/abstract") or parts & {"invisible", "abstract"}:
        return result("skip", "non-rendering mapping marker")
    invisibility = properties.get("invisibility", "0")
    if number(invisibility) > 0 or str(invisibility).startswith("INVISIBILITY_"):
        return result("skip", "invisible source object")
    if family("/obj/structure/lattice", "/obj/structure/catwalk", "/obj/structure/grating"):
        return result("floor", "walkable floor surface")
    if family("/obj/structure/table", "/obj/structure/tray", "/obj/machinery/holopad",
              "/obj/machinery/light/floor", "/obj/structure/shuttle/engine",
              "/obj/machinery/shuttle/engine", "/obj/effect/turf_decal", "/obj/effect/decal",
              "/obj/machinery/conveyor", "/obj/machinery/meter", "/obj/machinery/air_sensor",
              "/obj/machinery/mechpad", "/obj/machinery/piratepad", "/obj/machinery/mass_driver",
              "/obj/machinery/power/solar"):
        return result("floor", "floor surface or fixture")
    if family("/obj/structure/fans/tiny"):
        return result("floor", "floor air barrier grille")
    if family("/obj/machinery/flasher/portable", "/obj/machinery/defibrillator_mount/mobile"):
        return result("upright", "mobile variant of a wall fixture")
    if family("/obj/item/radio/intercom", "/obj/machinery/airalarm", "/obj/machinery/firealarm",
              "/obj/machinery/power/apc", "/obj/machinery/status_display",
              "/obj/machinery/newscaster", "/obj/machinery/requests_console",
              "/obj/machinery/computer/telescreen", "/obj/machinery/computer/security/telescreen",
              "/obj/machinery/barsign",
              "/obj/machinery/lightswitch", "/obj/machinery/digital_clock",
              "/obj/machinery/defibrillator_mount", "/obj/machinery/keycard_auth",
              "/obj/machinery/turretid", "/obj/machinery/flasher", "/obj/machinery/wall_healer",
              "/obj/machinery/door_buttons", "/obj/machinery/airlock_controller",
              "/obj/machinery/embedded_controller", "/obj/machinery/button",
              "/obj/machinery/camera", "/obj/machinery/light", "/obj/structure/sign",
              "/obj/structure/poster", "/obj/structure/wallpaper", "/obj/structure/mirror",
              "/obj/structure/extinguisher_cabinet", "/obj/structure/fireaxecabinet",
              "/obj/structure/noticeboard", "/obj/structure/detectiveboard",
              "/obj/structure/plaque", "/obj/structure/reagent_dispensers/wall") or parts & {
                  "wallmount", "wallmounted", "wall_mount", "wall_mounted", "wallpaper",
                  "wall_screen", "wallscreen",
              } or properties.get("mount_direction") or properties.get("layer") == "SIGN_LAYER":
        return result("wall", "wall fixture or directional wall helper")
    # Plane/layer names are useful fallbacks for fork-specific floor effects.
    if properties.get("layer") in ("TURF_DECAL_LAYER", "FLOOR_DECAL_LAYER") or (
        properties.get("plane") == "FLOOR_PLANE" and family("/obj/effect")
    ):
        return result("floor", "source floor decal layer")
    if family("/obj/effect"):
        return result("skip", "non-physical map effect")
    return result("upright", "default standing sprite")


@dataclass(frozen=True)
class Placement:
    x: float
    y: float
    z: float
    direction: int
    wall_found: bool = True


def place(rule, cell, walls, direction, properties, layer=0):
    """Return tile-relative sprite origin and outward facing direction."""
    px, py = number(properties.get("pixel_x")) / 32, number(properties.get("pixel_y")) / 32
    pz = number(properties.get("pixel_z")) / 32
    # Separate surfaces along their normal; moving Z alone does not separate
    # vertical planes. Pipe networks also get deterministic distinct depths.
    epsilon = 0.003 + layer * 0.002
    if rule.mode in ("floor", "underfloor"):
        match = re.search(r"/layer([1-5])(?:/|$)", properties.get("_path", ""))
        network = number(properties.get("piping_layer"), int(match[1]) if match else 3)
        network = min(5, max(1, network))
        z = (-0.08 - (5 - network) * 0.012 - layer * 0.002
             if rule.mode == "underfloor" else epsilon + (network - 1) * 0.002)
        if rule.mode == "underfloor":
            for prefix, depth in (
                ("/obj/structure/disposalpipe", -0.18), ("/obj/machinery/duct", -0.16),
                ("/obj/structure/cable", -0.04), ("/obj/machinery/power/cable", -0.04),
                ("/obj/machinery/power/terminal", -0.035), ("/obj/machinery/navbeacon", -0.03),
            ):
                if is_type(properties.get("_path", ""), prefix):
                    z = depth - layer * 0.002
                    break
        return Placement(px, py, (rule.height if rule.height is not None else z) + pz, direction)
    if rule.mode != "wall":
        nx, ny = DIRECTIONS[direction]
        length = math.hypot(nx, ny)
        return Placement(px + nx / length * epsilon, py + ny / length * epsilon,
                         (rule.height or 0) + pz + 0.003, direction)

    # Directional helpers point TOWARDS the supporting wall. A fixture on an
    # open tile touches the near face; one mapped inside a wall uses its exposed
    # outer face instead. Offsets help disambiguate legacy maps.
    preferred = direction if direction in OPPOSITE else 2
    if max(abs(px), abs(py)) >= 0.25:
        preferred = (4 if px > 0 else 8) if abs(px) > abs(py) else (1 if py > 0 else 2)
    inside = (cell.x, cell.y, cell.z) in walls
    candidates = []
    for side in (preferred, *[d for d in OPPOSITE if d != preferred]):
        dx, dy = DIRECTIONS[side]
        adjacent = (cell.x + dx, cell.y + dy, cell.z) in walls
        if adjacent != inside:
            candidates.append(side)
    side = candidates[0] if candidates else preferred
    dx, dy = DIRECTIONS[side]
    normal = side if inside else OPPOSITE[side]
    nx, ny = DIRECTIONS[normal]
    # Tangential pixel shifts remain meaningful, but the normal pixel shift is
    # replaced with contact at the actual wall face, not an arbitrary 32px jump.
    tangent = max(-0.4, min(0.4, px if dx == 0 else py))
    return Placement(dx * 0.5 + nx * epsilon + (tangent if dx == 0 else 0),
                     dy * 0.5 + ny * epsilon + (tangent if dy == 0 else 0),
                     (rule.height or 0) + pz, normal, bool(candidates))


def entity_label(path, properties=None):
    properties = properties or {}
    name = re.sub(r"\\(?:improper|proper)\s*", "", properties.get("name", "")).strip()
    parts = path.strip("/").split("/")
    meaningful = [part for part in parts[2:] if part not in {
        "directional", "north", "south", "east", "west", "hidden", "visible",
        "layer1", "layer2", "layer3", "layer4", "layer5",
    }]
    fallback = " ".join(meaningful).replace("_", " ")
    if not name or name in ("object", "machinery", "structure", "item"):
        name = fallback
    variant = " / ".join(parts[-2:]).replace("_", " ")
    # The meaningful display name comes first so narrow Outliner columns and
    # Blender's name length limit don't erase the identity.
    return f"{name} ({variant})" if variant and variant not in name else name
