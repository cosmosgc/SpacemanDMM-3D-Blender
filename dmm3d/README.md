# DMM3D — SS13 DMM/TGM to 3D

A **standalone Rust CLI prototype** that converts BYOND Space Station 13 `.dmm` / TGM-style maps into an OBJ mesh and JSON scene metadata. **No external crates required.**

## Quick start

```bash
cargo test
cargo run --release -- examples/sample.dmm output --rules examples/rules.txt
```

Open `output/station.obj` in Blender, MeshLab, or another OBJ viewer. The `.mtl` file provides basic colors. `output/scene.json` preserves original atom paths, coordinate positions, and raw variable overrides for later Bevy ECS import.

For your own maps:

```bash
cargo run --release -- path/to/station.dmm output/station --tile-size 1 --wall-height 2.8
```

## What works

- Standard DMM dictionary entries with atom path lists and basic `{...}` variable overrides.
- Quoted grid blocks with coordinate origins, multiple coordinate blocks and Z-levels.
- One-character or multi-character ASCII dictionary keys.
- Floors, exposed-face-culled walls, placeholder doors, windows, tables, machines.
- Custom path-prefix classification rules (`path=kind`) in a text file.
- Blender-compatible OBJ/MTL and JSON scene export.
- Basic parser unit tests and a small example map.

## Important limitations

- **Prototype, not a complete BYOND parser.** Complex DM syntax, escaped grid sequences, unusual key encodings, and some TGM variants may need additional parser work. Test on your chosen SS13 codebase before production use.
- Does not parse `.dm` inheritance, `.dmi` icons, `dir` orientation, pixel offsets, overlays, or prefab definitions. Raw atom variable strings are retained for future processing.
- Does not reconstruct full SS13 gameplay, atmospherics, wires, or machinery logic.
- Doors/windows use placeholder geometry; no 3D asset matching or automatic collision generation yet.
- No greedy meshing yet; adjacent wall faces are omitted, but each tile is still an individual box.
- OBJ does not contain interactive entities. Use `scene.json` for ECS spawning.
- No native Bevy viewer in this version; import the OBJ into Blender or use the JSON in a Bevy runtime.

## Suggested Bevy integration

1. Parse `scene.json` into `serde` structs with `cells: Vec<Cell>`.
2. Load your own glTF prefabs based on each atom's `path` or `kind`.
3. Attach ECS components (doors, machines, area IDs) to spawned entities.
4. Interpret DMM coordinates as `Vec3(x * tile_size, (z - 1) * deck_height, y * tile_size)`.
5. Preserve original atom path/vars for reimport and future map editing.

**Coordinate note:** BYOND's 2D `y` becomes the exported OBJ's horizontal `z` axis; BYOND's `z` becomes vertical `y`.

## Future improvements

Use an established BYOND parser such as SpacemanDMM if compatibility with diverse SS13 repositories is required. Add sprite fallback, direction-aware doors/windows, actual asset mappings, chunked greedy meshing, a Bevy 3D viewer, and live reimport.
