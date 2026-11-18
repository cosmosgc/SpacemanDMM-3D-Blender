"""Small, dependency-free parser for the layout portions of BYOND DMM files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class Cell:
    x: int
    y: int
    z: int
    turf: str
    objects: tuple[str, ...]
    turf_icon: str | None = None
    turf_icon_state: str | None = None
    area: str | None = None
    object_directions: tuple[int | None, ...] = ()


@dataclass(frozen=True)
class DmmMap:
    cells: tuple[Cell, ...]
    symbol_width: int


def _matching_paren(text: str, start: int) -> int:
    """Find the closing paren for text[start], respecting strings and nesting."""
    depth = 0
    quote = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return index
    raise ValueError("Unclosed parenthesis in DMM symbol definition")


def _split_top_level(text: str, separator: str = ",") -> list[str]:
    """Split a DMM list at commas outside braces, parentheses, and strings."""
    parts: list[str] = []
    start = 0
    braces = parens = 0
    quote = None
    escaped = False
    for index, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in "\"'":
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char == "(":
            parens += 1
        elif char == ")":
            parens -= 1
        elif char == separator and braces == 0 and parens == 0:
            parts.append(text[start:index].strip())
            start = index + 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _overrides(entry: str) -> dict[str, str]:
    _, brace, body = entry.partition("{")
    if not brace:
        return {}
    return {
        field.strip(): value.strip()
        for assignment in _split_top_level(body.rsplit("}", 1)[0], ";")
        for field, equals, value in [assignment.partition("=")]
        if equals
    }


def _literal_override(value: str) -> str | None:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1].replace(r'\"', '"')
    return None


def _parse_symbols(text: str):
    symbols = {}
    definition = re.compile(r'(?m)^\s*"([A-Za-z]+)"\s*=\s*\(')
    for match in definition.finditer(text):
        opening = match.end() - 1
        closing = _matching_paren(text, opening)
        entries = _split_top_level(text[opening + 1 : closing])
        paths = tuple(
            re.sub(r"\{.*\}\s*$", "", entry, flags=re.DOTALL).strip()
            for entry in entries
            if entry
        )
        turf_index = next((i for i, path in enumerate(paths) if path.startswith("/turf/")), None)
        if turf_index is None:
            raise ValueError(f"Symbol {match.group(1)!r} has no turf entry")
        objects = []
        directions = []
        for path, entry in zip(paths, entries):
            if not path.startswith("/obj/"):
                continue
            objects.append(path)
            direction = _overrides(entry).get("dir")
            directions.append(int(direction) if direction in ("1", "2", "4", "8") else None)
        overrides = _overrides(entries[turf_index])
        area = next((path for path in paths if path.startswith("/area/") or path == "/area"), None)
        symbols[match.group(1)] = (
            paths[turf_index], tuple(objects), _literal_override(overrides.get("icon", "")),
            _literal_override(overrides.get("icon_state", "")), area, tuple(directions),
        )
    if not symbols:
        raise ValueError("No DMM symbol definitions found")
    widths = {len(key) for key in symbols}
    if len(widths) != 1:
        raise ValueError("DMM symbol keys are not a consistent width")
    return symbols


def parse_dmm_text(text: str) -> DmmMap:
    symbols = _parse_symbols(text)
    symbol_width = len(next(iter(symbols)))
    cells: list[Cell] = []
    map_block = re.compile(
        r'\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)\s*=\s*\{\s*"([\s\S]*?)"\s*\}'
    )
    found_blocks = 0
    for match in map_block.finditer(text):
        found_blocks += 1
        origin_x, origin_y, z = (int(match.group(i)) for i in (1, 2, 3))
        rows = [row.strip() for row in match.group(4).splitlines() if row.strip()]
        for row_index, row in enumerate(rows):
            if len(row) % symbol_width:
                raise ValueError(
                    f"Map row at ({origin_x},{origin_y},{z}) has "
                    f"{len(row)} characters, not divisible by symbol width "
                    f"{symbol_width}"
                )
            # DMM writes rows top-to-bottom; BYOND Y coordinates increase upward.
            y = origin_y + len(rows) - row_index - 1
            for column in range(0, len(row), symbol_width):
                key = row[column : column + symbol_width]
                if key not in symbols:
                    raise ValueError(
                        f"Map at ({origin_x},{origin_y},{z}) uses unknown symbol {key!r}"
                    )
                turf, objects, turf_icon, turf_icon_state, area, directions = symbols[key]
                cells.append(
                    Cell(
                        x=origin_x + column // symbol_width,
                        y=y,
                        z=z,
                        turf=turf,
                        objects=objects,
                        turf_icon=turf_icon,
                        turf_icon_state=turf_icon_state,
                        area=area,
                        object_directions=directions,
                    )
                )
    if not found_blocks:
        raise ValueError("No DMM map coordinate blocks found")
    return DmmMap(tuple(cells), symbol_width)


def parse_dmm(path: str | Path) -> DmmMap:
    return parse_dmm_text(Path(path).read_text(encoding="utf-8-sig"))
