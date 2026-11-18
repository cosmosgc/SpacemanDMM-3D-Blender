// glTF nodes can share geometries, materials, textures and decoded images.
export function disposeMapResources(scenes) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  const skeletons = new Set();
  for (const scene of scenes) {
    scene.removeFromParent();
    scene.traverse(object => {
      if (object.geometry) geometries.add(object.geometry);
      if (object.skeleton) skeletons.add(object.skeleton);
      for (const material of Array.isArray(object.material) ? object.material : [object.material]) {
        if (material) materials.add(material);
      }
    });
  }

  for (const geometry of geometries) {
    if (geometry.boundsTree) geometry.boundsTree = null;
    geometry.dispose();
  }
  for (const material of materials) {
    for (const value of Object.values(material)) {
      if (value?.isTexture) textures.add(value);
    }
    material.dispose();
  }
  for (const skeleton of skeletons) skeleton.dispose();

  const bitmaps = new Set();
  for (const texture of textures) {
    const image = texture.source?.data;
    if (typeof ImageBitmap !== "undefined" && image instanceof ImageBitmap) bitmaps.add(image);
    texture.dispose();
  }
  for (const bitmap of bitmaps) bitmap.close();
}

export function indexTerrain(meshes, MeshBVH, acceleratedRaycast) {
  for (const mesh of meshes) {
    const geometry = mesh.geometry;
    // Indirect mode leaves the GLB's render indices and material groups intact.
    if (!geometry.boundsTree) geometry.boundsTree = new MeshBVH(geometry, { indirect: true });
    mesh.raycast = acceleratedRaycast;
  }
}
