# SpacemanDMM Blender 3D Maps

https://cosmosgc.github.io/SpacemanDMM-3D-Blender/

Turn Space Station 13 `.dmm` maps into textured, editable 3D blockouts in Blender,
and publish the exported GLBs with a static browser viewer (for example on GitHub
Pages). It reads the map and the game codebase directly; it does not depend on
Statbus or Renderbus.

## Requirements

- Python 3.10+ (for parsing and tests)
- Blender 3.6+ (for generating `.blend` and `.glb` files)

## Generate a map

### Desktop map picker

On Windows, launch the UI with:

```powershell
python launcher.py
```

Or double-click `run_launcher.bat`.

It scans `<codebase>\_maps` for `.dmm` files, supports filtering, lets you choose
Blender and output-root paths, and streams the exporter log. Blender is
auto-detected from `PATH` or `C:\Program Files\Blender Foundation`; set
`SS13_CODEBASE` to pre-fill the codebase field. Every path and dropdown choice is
remembered between runs, so the defaults are only used on the first launch.
Choose **Performance only (fast)** under **Blender files** to build the
batched map directly without regenerating existing high-fidelity files. Choose
**Both versions** if you need both sets of files.
For high-fidelity exports, **Organize by** keeps each z-level and type
collection and optionally splits its terrain and entities into subcollections
by **Area** (the DMM area path) or **Chunk** (32 × 32 tiles by default).
The map tree shows source size, source modification time, and available exports
with their latest modification time. **GLB files** independently selects
high fidelity, performance, both, or none. The default matches **Blender files**.
Any unselected files are left in place. The progress bar shows export stages
and elapsed time, not an estimated time remaining.
Use **Cancel generation** to stop Blender during a run. Files already saved
remain in the output folder.

### Command line

From the repository root, pass a `.dmm` file, its codebase, and an output root:

```powershell
blender --background --factory-startup --python-exit-code 1 --python generate_blender.py -- `
  --dmm "C:\ss13\codebase\_maps\loopstation\loopstation.dmm" `
  --codebase "C:\ss13\codebase" `
  --output "output"
```

`--dmm` and `--codebase` are required. Files are placed under
`<output-root>/<map-name>/files/`, e.g. `output\loopstation\files\`.
That folder contains the Blender project, GLB export, and texture-resolution report.
`--tile-size` sets the width and depth of each game tile (default: 1 Blender unit).
The resolver defaults to the second (`map`) argument of `MAP_SWITCH`, matching
map-preview behavior; use `--map-switch compile` to select the first argument.
Use `--performance-mode` to also create separate `<map>.performance.blend` and
`<map>.performance.glb` copies. These build entity batches by collection to reduce
object and draw-call overhead; the standard high-fidelity files remain unchanged.
Use `--performance-only` instead to build just the optimized copies, with no
intermediate individual entity objects. Existing standard exports are not touched.
Pass `--glb high`, `--glb performance`, or `--glb both` to select GLBs independently
of the Blender files, or `--glb none` (`--no-glb`) to skip them.
Use `--organize-by area` or `--organize-by chunk` to subdivide the high-fidelity
scene, and `--chunk-size N` to change the chunk dimensions. The performance
version is still batched by type and z-level.
The exporter prints separate timings for asset indexing, scene building, and saving.

## Browser map viewer

Serve this folder over HTTP and open `index.html`, e.g.
`python -m http.server 8000` then `http://localhost:8000/`. The viewer reads
`output/maps.json` and loads the selected map's GLB. The exporter refreshes
that map index after each run. All paths are relative, so the same folder works
from any subpath of a static host. Orbit/zoom/pan are available by default. **Walk
mode** starts on station flooring: WASD moves, Shift sprints, and Space jumps.
**Fly mode** uses WASD and mouse look with no gravity or collision; hold Shift
to boost, Space to rise, or Q to descend. Esc releases the mouse in either mode.
Walk mode lazily indexes floor and wall geometry with three-mesh-bvh; the viewer
releases the previous map's resources when changing map or quality.
The **Performance mode** checkbox loads a separate optimized GLB when available;
it does not replace the high-fidelity file.
Serve the page over HTTP (rather than opening it as a `file://` URL) so the
browser can fetch the map index and GLB files. Three.js is loaded from jsDelivr.

## Publish on GitHub Pages

The viewer and `output/maps.json` use relative URLs, so the repository can be
served directly by GitHub Pages:

1. Export the maps you want to publish with **GLB files** set to **Performance
   only** (smaller downloads) or **Both versions**.
2. Commit `index.html`, `viewer_resources.js`, and `output/` — the map index, each
   map's `*.glb`, and its `.blend` project. The viewer only downloads the GLB;
   the Blender file is there so visitors can inspect or edit the scene.
3. In the repository settings, set Pages to deploy from the branch root.

Each tracked map adds its Blender project (about 10–30 MB) and GLB (about
15–45 MB) to the repository and every clone, so remove unneeded exports from
`output/` before committing. Keep individual files under GitHub's 100 MB limit.
Git LFS can move the `.blend` files out of the main history, but GitHub Pages
does not serve LFS objects, so keep the GLBs as regular files if you publish
them. Blender's `.blend1`/`.blend2` autosaves stay ignored.

To find candidate maps:

```powershell
Get-ChildItem "C:\ss13\codebase\_maps" -Filter *.dmm -Recurse
```

## What it generates

- One floor surface per open turf, UV-mapped to its real DMI icon/state.
- Raised, DMI-textured blocks for closed turfs/walls.
- Walls use type-specific DMI sprites, honor mapped `icon` and `icon_state`
  overrides, and select connected junction frames when available.
- A selectable collection hierarchy per z-level: `Space`, `Floors`, `Plating`,
  `Asteroid`, `Walls`, and `Entities` (`Doors`, `Windows`, `Tables`, `Machines`,
  `Objects`), plus `Underfloor` and `Proxy Geometry`.
- Each mapped entity is an individual, named Blender object with its DMM path
  and coordinates stored as custom properties. Doors are upright slabs (with DMI
  textures where available); windows and glass doors use solid frames with
  translucent panes. These are static models, oriented from mapped directions
  where available. Other resolved sprites are transparent planes, and unresolved
  sprites use labeled proxy geometry. Identical sprites
  share mesh data; make the mesh single-user before editing one instance's vertices.
- Optional performance copies join entities by collection to reduce object count.
  They are separate from the default high-fidelity project with individually
  selectable entities and metadata.
- `Proxy Geometry` starts hidden in the viewport; enable it in the Outliner if
  you want to inspect fallback boxes.
- Pipes, cables, and disposal pipes are placed slightly below floor level in
  `Underfloor`; hide the `Floors` collection to inspect them.
- A sun, one area light per z-level, point lights for mapped light fixtures, and
  an orthographic overview camera.

The icon/state resolver reads `tgstation.dme` includes, indexes direct appearance
fields on `/turf` and `/obj` type declarations, inherits icon settings along the
DM type path, then reads DMI's embedded PNG metadata to locate the sprite in its
atlas. This follows the same asset source used by Renderbus/SpacemanDMM: the
codebase's `.dmi` files, rather than a remote texture service.

This is still a blockout, not a full BYOND appearance renderer. Dynamic icon
states, full BYOND smoothing rules, overlays, pixel offsets, and accurate 3D object
models are not reconstructed. Missing turf icons use fallback colors; check
`<map>.textures.json` for missing types. The Rust prototype in `dmm3d/` informed
the object proxies and wall-face culling, while this app keeps Blender as the
native scene builder and textured GLB exporter.

## Parser tests

The parser has no third-party Python dependencies:

```powershell
python -m unittest discover -s tests
node --test tests/test_viewer_resources.mjs
```
