import assert from "node:assert/strict";
import test from "node:test";
import { disposeMapResources, indexTerrain } from "../viewer_resources.js";

test("indexes shared terrain geometry only once without reordering indices", () => {
  const geometry = {};
  const meshes = [{ geometry }, { geometry }];
  let builds = 0;
  class TestBVH {
    constructor(input, options) {
      assert.equal(input, geometry);
      assert.equal(options.indirect, true);
      builds++;
    }
  }
  const raycast = () => {};
  indexTerrain(meshes, TestBVH, raycast);
  assert.equal(builds, 1);
  assert.ok(meshes.every(mesh => mesh.raycast === raycast));
});

test("releases resources shared across nodes and scenes exactly once", () => {
  const disposed = [];
  const texture = { isTexture: true, dispose: () => disposed.push("texture") };
  const material = { map: texture, emissiveMap: texture, dispose: () => disposed.push("material") };
  const geometry = { boundsTree: {}, dispose: () => disposed.push("geometry") };
  const mesh = { geometry, material: [material, material] };
  const scene = () => ({
    removeFromParent: () => disposed.push("scene"),
    traverse: visit => { visit(mesh); visit(mesh); },
  });
  disposeMapResources([scene(), scene()]);
  assert.deepEqual(disposed, ["scene", "scene", "geometry", "material", "texture"]);
  assert.equal(geometry.boundsTree, null);
});
