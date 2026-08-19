import * as THREE from 'three';
import { widthM, heightM } from './geo.js';

const EXAG = 1.8; // vertical exaggeration relative to lake level

function colorForHeight(h, lakeLevel) {
  // h in real meters above sea level
  if (h < lakeLevel - 0.2) return [0.16, 0.30, 0.36]; // lake bed (mostly hidden)
  if (h < lakeLevel + 1.2) return [0.74, 0.68, 0.50]; // shoreline sand
  if (h < 42) return [0.33, 0.53, 0.29];              // meadow
  if (h < 60) return [0.21, 0.43, 0.23];              // forest
  if (h < 85) return [0.17, 0.36, 0.21];              // dense forest
  return [0.46, 0.39, 0.31];                          // ridge tops
}

export async function loadTerrain(scene, meta) {
  const [geoInfo, terrBuf] = await Promise.all([
    fetch('/data/geo.json').then((r) => r.json()),
    fetch('/data/terrain.bin').then((r) => r.arrayBuffer()),
  ]);
  const N = geoInfo.grid; // 256
  const heights = new Float32Array(terrBuf); // row 0 = north
  const lakeLevel = meta.lakeLevel;

  const W = widthM();
  const H = heightM();

  const geo = new THREE.PlaneGeometry(W, H, N - 1, N - 1);
  geo.rotateX(-Math.PI / 2); // row 0 ends up at z = -H/2 (north)

  const pos = geo.attributes.position;
  const colors = new Float32Array(pos.count * 3);
  for (let i = 0; i < pos.count; i++) {
    const h = heights[i];
    pos.setY(i, (h - lakeLevel) * EXAG);
    const c = colorForHeight(h, lakeLevel);
    const j = (Math.sin(i * 12.9898) * 43758.5453) % 1; // deterministic jitter
    colors[i * 3 + 0] = Math.min(1, Math.max(0, c[0] + j * 0.05));
    colors[i * 3 + 1] = Math.min(1, Math.max(0, c[1] + j * 0.05));
    colors[i * 3 + 2] = Math.min(1, Math.max(0, c[2] + j * 0.05));
  }
  geo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
  geo.computeVertexNormals();

  const mat = new THREE.MeshStandardMaterial({
    vertexColors: true,
    flatShading: true,
    roughness: 0.95,
    metalness: 0.0,
  });
  const mesh = new THREE.Mesh(geo, mat);
  scene.add(mesh);

  // water plane at y = 0 (lake level); terrain above lake level occludes it
  const waterGeo = new THREE.PlaneGeometry(W, H, 1, 1);
  waterGeo.rotateX(-Math.PI / 2);
  const waterMat = new THREE.MeshStandardMaterial({
    color: 0x2e6f9e,
    transparent: true,
    opacity: 0.93,
    roughness: 0.12,
    metalness: 0.35,
  });
  const water = new THREE.Mesh(waterGeo, waterMat);
  water.position.y = 0;
  scene.add(water);

  // dark base far below so scene edges don't show void
  const baseGeo = new THREE.PlaneGeometry(W * 4, H * 4, 1, 1);
  baseGeo.rotateX(-Math.PI / 2);
  const base = new THREE.Mesh(
    baseGeo,
    new THREE.MeshBasicMaterial({ color: 0x24401f })
  );
  base.position.y = -80;
  scene.add(base);

  // bilinear ground-height sampler in world (exaggerated) meters
  const cellW = W / (N - 1);
  const cellH = H / (N - 1);
  function sampleGround(x, z) {
    const fx = Math.min(Math.max((x + W / 2) / cellW, 0), N - 1.001);
    const fz = Math.min(Math.max((z + H / 2) / cellH, 0), N - 1.001);
    const x0 = Math.floor(fx), z0 = Math.floor(fz);
    const tx = fx - x0, tz = fz - z0;
    const i00 = z0 * N + x0, i10 = i00 + 1, i01 = i00 + N, i11 = i01 + 1;
    const h =
      heights[i00] * (1 - tx) * (1 - tz) +
      heights[i10] * tx * (1 - tz) +
      heights[i01] * (1 - tx) * tz +
      heights[i11] * tx * tz;
    return (h - lakeLevel) * EXAG;
  }

  return { mesh, water, sampleGround, lakeLevel, exag: EXAG };
}
