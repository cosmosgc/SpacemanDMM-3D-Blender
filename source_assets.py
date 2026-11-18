"""Resolve DMI icon/state data for DMM turf paths using a DM codebase."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import struct
import zlib


_INCLUDE = re.compile(r'^\s*#include\s+"([^"]+)"', re.IGNORECASE)
_TYPE = re.compile(r"^(/(?:turf|obj)(?:/[A-Za-z0-9_]+)*)\s*(?://.*)?$")
_FIELD = re.compile(r"^(icon|icon_state|base_icon_state|parent_type)\s*=\s*(.*?)\s*$")
_STRING = re.compile(r'^"((?:\\.|[^"\\])*)"$')
_DMI_PATH = re.compile(r"""['"]([^'"]+\.dmi)['"]""", re.IGNORECASE)
_FIELD_VALUE = re.compile(r'^\s*(?:state|width|height|dirs|frames)\s*=\s*(.*?)\s*$')
_MAP_SWITCH = re.compile(r"^MAP_SWITCH\s*\((.*)\)\s*$", re.DOTALL)
_DIRECTION_ORDER = (2, 1, 4, 8, 6, 10, 5, 9)


def wall_state(info, state, x, y, z, walls):
    """Pick a connected DMI frame for walls with numbered junction states."""
    if not state.endswith("-0") or state not in info.states:
        return state
    kind = walls[x, y, z]
    station_walls = ("/turf/closed/wall", "/turf/closed/wall/r_wall")

    def connects(dx, dy):
        other = walls.get((x + dx, y + dy, z))
        return other == kind or (kind in station_walls and other in station_walls)

    mask = sum(bit for dx, dy, bit in ((0, 1, 1), (0, -1, 2), (1, 0, 4), (-1, 0, 8))
               if connects(dx, dy))
    cardinal = mask
    for dx, dy, adjacent, bit in ((1, 1, 5, 16), (1, -1, 6, 32), (-1, -1, 10, 64), (-1, 1, 9, 128)):
        if cardinal & adjacent == adjacent and connects(dx, dy):
            mask |= bit
    for variant in (mask, cardinal):
        candidate = f"{state[:-1]}{variant}"
        if candidate in info.states:
            return candidate
    return state


@dataclass(frozen=True)
class DmiState:
    name: str
    dirs: int
    frames: int
    first_frame: int


@dataclass(frozen=True)
class DmiInfo:
    path: Path
    image_width: int
    image_height: int
    frame_width: int
    frame_height: int
    states: dict[str, DmiState]

    def uv_rect(self, state_name: str, direction: int = 2) -> tuple[float, float, float, float] | None:
        state = self.states.get(state_name)
        if state is None:
            state = self.states.get("")
        if state is None:
            return None
        direction_slot = _DIRECTION_ORDER.index(direction) if direction in _DIRECTION_ORDER else 0
        if direction_slot >= state.dirs:
            direction_slot = 0
        frame_index = state.first_frame + direction_slot
        columns = self.image_width // self.frame_width
        if columns < 1:
            return None
        pixel_x = (frame_index % columns) * self.frame_width
        pixel_y = (frame_index // columns) * self.frame_height
        u0 = pixel_x / self.image_width
        u1 = (pixel_x + self.frame_width) / self.image_width
        v0 = 1.0 - (pixel_y + self.frame_height) / self.image_height
        v1 = 1.0 - pixel_y / self.image_height
        return u0, v0, u1, v1


def _png_chunks(path: Path):
    with path.open("rb") as stream:
        if stream.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"Not a PNG/DMI file: {path}")
        while True:
            header = stream.read(8)
            if len(header) != 8:
                break
            length, kind = struct.unpack(">I4s", header)
            data = stream.read(length)
            stream.read(4)  # CRC
            yield kind, data
            if kind == b"IEND":
                break


def _description(data: bytes, kind: bytes) -> str | None:
    if kind == b"tEXt":
        _, separator, text = data.partition(b"\0")
        return text.decode("latin-1") if separator else None
    if kind == b"zTXt":
        _, separator, rest = data.partition(b"\0")
        if not separator or len(rest) < 2:
            return None
        return zlib.decompress(rest[1:]).decode("utf-8", errors="replace")
    if kind == b"iTXt":
        fields = data.split(b"\0", 5)
        if len(fields) != 6 or fields[0] != b"Description":
            return None
        compressed = fields[1] == b"\x01"
        content = zlib.decompress(fields[5]) if compressed else fields[5]
        return content.decode("utf-8", errors="replace")
    return None


def read_dmi_info(path: str | Path) -> DmiInfo:
    path = Path(path)
    image_width = image_height = 0
    description = None
    for kind, data in _png_chunks(path):
        if kind == b"IHDR":
            image_width, image_height = struct.unpack(">II", data[:8])
        elif kind in (b"tEXt", b"zTXt", b"iTXt"):
            value = _description(data, kind)
            if value is not None and (kind != b"tEXt" or data.startswith(b"Description\0")):
                description = value

    frame_width, frame_height = 32, 32
    state_data: list[tuple[str, int, int]] = []
    current_name: str | None = None
    current_dirs, current_frames = 1, 1
    for raw_line in (description or "").splitlines():
        line = raw_line.strip()
        if line.startswith("state = "):
            if current_name is not None:
                state_data.append((current_name, current_dirs, current_frames))
            match = _STRING.match(line[len("state = "):])
            current_name = match.group(1).replace(r"\"", '"').replace(r"\\", "\\") if match else ""
            current_dirs, current_frames = 1, 1
            continue
        match = _FIELD_VALUE.match(line)
        if not match:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if key == "width":
            frame_width = int(value)
        elif key == "height":
            frame_height = int(value)
        elif key == "dirs":
            current_dirs = int(value)
        elif key == "frames":
            current_frames = int(value)
    if current_name is not None:
        state_data.append((current_name, current_dirs, current_frames))
    states: dict[str, DmiState] = {}
    first_frame = 0
    for name, dirs, frames in state_data:
        states[name] = DmiState(name, dirs, frames, first_frame)
        first_frame += dirs * frames
    if not states:
        states[""] = DmiState("", 1, 1, 0)
        frame_width, frame_height = image_width, image_height
    if not image_width or not image_height or not frame_width or not frame_height:
        raise ValueError(f"Invalid DMI dimensions in {path}")
    return DmiInfo(path, image_width, image_height, frame_width, frame_height, states)


def _literal(value: str) -> str | None:
    match = _STRING.match(value.strip())
    if not match:
        return None
    return match.group(1).replace(r"\"", '"').replace(r"\\", "\\")


def _arguments(value: str) -> list[str]:
    parts: list[str] = []
    start = depth = 0
    in_string = escaped = False
    for index, char in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(value[start:index].strip())
            start = index + 1
    parts.append(value[start:].strip())
    return parts


def _map_value(value: str, mode: str) -> str:
    match = _MAP_SWITCH.match(value.strip())
    if not match:
        return value.strip()
    args = _arguments(match.group(1))
    if len(args) < 2:
        return value.strip()
    return args[0 if mode == "compile" else 1]


class CodebaseAssets:
    """Index DM type appearance fields and resolve each turf to a DMI state."""

    def __init__(self, codebase: str | Path, map_switch: str = "map"):
        self.root = Path(codebase).resolve()
        self.map_switch = map_switch
        self.types: dict[str, dict[str, str]] = {}
        self.dmi_cache: dict[Path, DmiInfo] = {}
        self.texture_cache: dict[str, tuple[DmiInfo, str] | None] = {}
        self.turf_texture_cache = {}
        self._index_codebase()

    def _included_files(self) -> list[Path]:
        main_dme = self.root / "tgstation.dme"
        if not main_dme.is_file():
            candidates = list(self.root.glob("*.dme"))
            if not candidates:
                raise FileNotFoundError(f"No .dme project file found in {self.root}")
            main_dme = candidates[0]
        queue = [main_dme]
        visited: set[Path] = set()
        dm_files: list[Path] = []
        while queue:
            current = queue.pop()
            current = current.resolve()
            if current in visited or not current.is_file():
                continue
            visited.add(current)
            try:
                content = current.read_text(encoding="utf-8-sig", errors="replace")
            except OSError:
                continue
            for line in content.splitlines():
                match = _INCLUDE.match(line)
                if not match:
                    continue
                included = (self.root / match.group(1).replace("\\", "/")).resolve()
                suffix = included.suffix.lower()
                if suffix == ".dme":
                    queue.append(included)
                elif suffix == ".dm":
                    dm_files.append(included)
        return list(dict.fromkeys(dm_files))

    def _index_codebase(self) -> None:
        for path in self._included_files():
            try:
                lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            except OSError:
                continue
            current_type = None
            for line in lines:
                declaration = _TYPE.match(line)
                if declaration:
                    current_type = declaration.group(1)
                    self.types.setdefault(current_type, {})
                    continue
                if current_type is None or not line.startswith("\t") or line.startswith("\t\t"):
                    continue
                field = _FIELD.match(line.lstrip("\t").strip())
                if not field:
                    continue
                name, raw_value = field.groups()
                value = _map_value(raw_value, self.map_switch)
                if name == "icon":
                    icon_match = _DMI_PATH.search(value)
                    if icon_match:
                        self.types[current_type]["icon"] = icon_match.group(1)
                else:
                    literal = _literal(value)
                    if literal is not None:
                        self.types[current_type][name] = literal

    def appearance(self, type_path: str) -> tuple[Path, str] | None:
        chain: list[str] = []
        current = type_path
        seen: set[str] = set()
        while current and current not in seen:
            seen.add(current)
            chain.append(current)
            values = self.types.get(current, {})
            parent = values.get("parent_type")
            current = parent if parent else current.rpartition("/")[0]
        effective: dict[str, str] = {}
        for type_name in reversed(chain):
            effective.update(self.types.get(type_name, {}))
        icon = effective.get("icon")
        state = effective.get("icon_state") or effective.get("base_icon_state") or ""
        if not icon:
            return None
        icon_path = (self.root / icon.replace("\\", "/")).resolve()
        if not icon_path.is_file():
            return None
        return icon_path, state

    def texture(self, type_path: str) -> tuple[DmiInfo, str] | None:
        if type_path not in self.texture_cache:
            self.texture_cache[type_path] = self._resolve_texture(type_path)
        return self.texture_cache[type_path]

    def _resolve_texture(self, type_path: str) -> tuple[DmiInfo, str] | None:
        appearance = self.appearance(type_path)
        if appearance is None:
            return None
        return self._load_texture(*appearance)

    def turf_texture(self, type_path, icon, state):
        if icon is None and state is None:
            return self.texture(type_path)
        key = (type_path, icon, state)
        if key not in self.turf_texture_cache:
            appearance = self.appearance(type_path)
            icon_path, default_state = appearance or (None, "")
            if icon is not None:
                icon_path = self.root / icon.replace("\\", "/")
            self.turf_texture_cache[key] = (
                self._load_texture(icon_path, default_state if state is None else state)
                if icon_path is not None else None
            )
        return self.turf_texture_cache[key]

    def _load_texture(self, icon_path, state):
        if icon_path not in self.dmi_cache:
            try:
                self.dmi_cache[icon_path] = read_dmi_info(icon_path)
            except (OSError, ValueError, zlib.error):
                return None
        info = self.dmi_cache[icon_path]
        if info.uv_rect(state) is None:
            return None
        return info, state
